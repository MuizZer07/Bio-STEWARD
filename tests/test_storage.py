"""v0.8 storage (RELEASE_v0.8_SPEC): large artifacts by hash (R-50), DVC and git-annex aware; resource audit."""

import hashlib
import json
import shutil
import subprocess

import pytest

from conftest import codes, one

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    r = tmp_path / "r"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.name", "T")
    sh(r, "git", "config", "user.email", "t@example.org")
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write("\n[storage]\nlarge_mb = 1\n")
    (r / "models").mkdir()
    (r / "models/w.bin").write_bytes(b"weights" * 1000)
    monkeypatch.chdir(r)
    return r


def r50(cli, root, final=False):
    args = ["check", "--repo", root, "--format", "json", "storage"] + (["--final"] if final else [])
    _, out, err = cli(*args)
    assert out, err
    return one(json.loads(out), "R-50")


def record(cli, path="models/w.bin", retrieval="dvc pull models/w.bin", *extra):
    code, out, err = cli("storage", "record", path, "--retrieval", retrieval, *extra)
    assert code == 0, err
    return out


def test_not_configured_is_not_applicable(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, out, _ = cli("check", "--repo", tmp_path, "--format", "json", "storage")
    assert one(json.loads(out), "R-50")["status"] == "NOT_APPLICABLE"


def test_record_then_verify_passes(cli, repo):
    record(cli)
    doc = (repo / "development/artifacts.toml").read_text()
    assert hashlib.sha256((repo / "models/w.bin").read_bytes()).hexdigest() in doc and "dvc pull" in doc
    assert r50(cli, repo)["status"] == "PASS"


def test_record_updates_an_entry_rather_than_duplicating_it(cli, repo):
    record(cli)
    (repo / "models/w.bin").write_bytes(b"new")
    record(cli)
    assert (repo / "development/artifacts.toml").read_text().count('path      = "models/w.bin"') == 1
    assert r50(cli, repo)["status"] == "PASS"


def test_a_changed_byte_fails(cli, repo):
    record(cli)
    (repo / "models/w.bin").write_bytes(b"weights" * 999 + b"weightz")
    res = r50(cli, repo)
    assert res["status"] == "FAIL" and "R-50.hash_mismatch" in codes(res)


def test_an_absent_artifact_is_named_with_its_retrieval_and_incomplete_when_final(cli, repo):
    record(cli)
    (repo / "models/w.bin").unlink()
    res = r50(cli, repo)
    assert res["status"] == "PASS"
    d = next(d for d in res["details"] if d["code"] == "R-50.not_present")
    assert "dvc pull" in d["message"]
    assert r50(cli, repo, final=True)["status"] == "INCOMPLETE"


def test_an_entry_without_retrieval_is_incomplete(cli, repo):
    record(cli)
    p = repo / "development/artifacts.toml"
    p.write_text(p.read_text().replace('retrieval = "dvc pull models/w.bin"\n', ""))
    res = r50(cli, repo)
    assert res["status"] == "INCOMPLETE" and "R-50.no_retrieval" in codes(res)


def _dvc(repo, md5):
    (repo / "models/w.bin.dvc").write_text(f"outs:\n- md5: {md5}\n  size: 7000\n  path: w.bin\n")


def test_a_dvc_pointer_is_cross_checked(cli, repo):
    record(cli, "models/w.bin", "dvc pull models/w.bin", "--tool", "dvc")
    _dvc(repo, hashlib.md5((repo / "models/w.bin").read_bytes()).hexdigest())
    assert r50(cli, repo)["status"] == "PASS"
    _dvc(repo, "0" * 32)
    res = r50(cli, repo)
    assert res["status"] == "FAIL" and "R-50.dvc_mismatch" in codes(res)


def _annex(repo, content, name="a.bin"):
    h = hashlib.sha256(content).hexdigest()
    key = f"SHA256E-s{len(content)}--{h}.bin"
    obj = repo / ".git/annex/objects/Xy/Zw" / key
    obj.mkdir(parents=True)
    (obj / key).write_bytes(content)
    (repo / "models" / name).symlink_to(obj / key)
    return h


def test_an_annex_key_is_read_from_the_symlink(cli, repo):
    h = _annex(repo, b"annexed content")
    record(cli, "models/a.bin", "datalad get models/a.bin", "--tool", "datalad")
    assert h in (repo / "development/artifacts.toml").read_text()
    assert r50(cli, repo)["status"] == "PASS"
    p = repo / "development/artifacts.toml"
    p.write_text(p.read_text().replace(h, "0" * 64))
    res = r50(cli, repo)
    assert res["status"] == "FAIL" and "R-50.annex_mismatch" in codes(res)


def test_an_annex_key_is_used_when_the_content_is_absent(cli, repo):
    _annex(repo, b"annexed content")
    record(cli, "models/a.bin", "datalad get models/a.bin", "--tool", "datalad")
    for f in (repo / ".git/annex/objects").rglob("*.bin"):
        if f.is_file():
            f.unlink()  # the content was dropped; the symlink and its key remain
    res = r50(cli, repo)
    assert res["status"] == "PASS" and "R-50.annex_key_only" in codes(res)


def test_a_large_tracked_file_is_reported_until_registered(cli, repo):
    (repo / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))
    sh(repo, "git", "add", "-f", "big.bin")  # -f: a global gitignore may cover *.bin
    res = r50(cli, repo)
    assert res["status"] == "INCOMPLETE" and "R-50.large_tracked" in codes(res)
    record(cli, "big.bin", "regenerate: python make_big.py")
    assert "R-50.large_tracked" not in codes(r50(cli, repo))


def test_paths_outside_the_repository_are_refused(cli, repo, tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x")
    (repo / "models/link.bin").symlink_to(outside)
    code, _, err = cli("storage", "record", "models/link.bin", "--retrieval", "x")
    assert code == 64 and "outside" in err
    with open(repo / "development/artifacts.toml", "w") as f:
        f.write(f'schema = "steward.artifacts/0.1"\n[[artifacts]]\npath = "models/link.bin"\nsha256 = "{"0" * 64}"\nsize = 1\nretrieval = "x"\n')
    res = r50(cli, repo)
    assert res["status"] == "FAIL" and "R-50.path_outside" in codes(res)


def test_verify_command_lists_states(cli, repo):
    record(cli)
    record(cli, "models/w.bin", "dvc pull models/w.bin")
    (repo / "models/other.bin").write_bytes(b"o")
    record(cli, "models/other.bin", "regenerate")
    (repo / "models/other.bin").unlink()
    code, out, _ = cli("storage", "verify", "--json")
    doc = json.loads(out)
    assert code == 0 and {a["path"]: a["state"] for a in doc["artifacts"]} == {"models/w.bin": "present", "models/other.bin": "absent"}


# ---------------------------------------------------------------- slice 2: resource audit (advisory)
def _tree(root):
    return sorted((p.relative_to(root).as_posix(), p.read_bytes() if p.is_file() else None)
                  for p in root.rglob("*") if ".git" not in p.relative_to(root).parts)


def test_audit_reports_sizes_against_caps_and_deletes_nothing(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[storage.caps]\n"cache" = 1\n"outputs/tmp" = 10\n"absent-dir" = 5\n')
    (repo / "cache").mkdir()
    (repo / "cache/blob").write_bytes(b"x" * (2 * 1024 * 1024))
    (repo / "outputs/tmp").mkdir(parents=True)
    (repo / "outputs/tmp/small").write_bytes(b"y" * 1000)
    before = _tree(repo)
    code, out, _ = cli("storage", "audit", "--json")
    assert _tree(repo) == before  # never deletes or changes anything
    doc = json.loads(out)
    dirs = {d["path"]: d for d in doc["directories"]}
    assert code == 0 and dirs["cache"]["over"] is True and dirs["outputs/tmp"]["over"] is False
    assert dirs["absent-dir"]["state"] == "absent"
    assert doc["largest_untracked"][0]["path"] == "cache/blob"


def test_audit_refuses_a_directory_outside_the_repository(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[storage.caps]\n"../elsewhere" = 1\n')
    code, out, _ = cli("storage", "audit", "--json")
    assert json.loads(out)["directories"][0]["state"] == "outside"


def test_audit_is_not_a_rule(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[storage.caps]\n"cache" = 1\n')
    (repo / "cache").mkdir()
    (repo / "cache/blob").write_bytes(b"x" * (2 * 1024 * 1024))
    assert r50(cli, repo)["status"] in ("NOT_APPLICABLE", "PASS")  # over a cap never changes a verdict


# ---------------------------------------------------------------- v0.8 review: K2, K4, K5, K8, K12
def test_K2_a_registry_outside_the_repository_is_refused(cli, repo, tmp_path):
    outside = tmp_path / "reg.toml"
    outside.write_text('schema = "steward.artifacts/0.1"\n')
    (repo / "development/reg.toml").symlink_to(outside)
    with open(repo / "steward.toml") as f:
        text = f.read()
    (repo / "steward.toml").write_text(text.replace("[storage]\n", '[storage]\nartifacts = "development/reg.toml"\n'))
    code, _, err = cli("storage", "record", "models/w.bin", "--retrieval", "x")
    assert code == 64 and "outside" in err and outside.read_text() == 'schema = "steward.artifacts/0.1"\n'
    res = r50(cli, repo)
    assert res["status"] == "FAIL" and "R-50.registry_outside" in codes(res)


def test_K2_a_dvc_pointer_outside_the_repository_is_not_read(cli, repo, tmp_path):
    record(cli, "models/w.bin", "dvc pull", "--tool", "dvc")
    ext = tmp_path / "w.bin.dvc"
    ext.write_text("outs:\n- md5: " + "0" * 32 + "\n  path: w.bin\n")
    (repo / "models/w.bin.dvc").symlink_to(ext)
    res = r50(cli, repo)
    assert "R-50.dvc_mismatch" not in codes(res) and "R-50.path_outside" in codes(res)


@pytest.mark.parametrize("pointer", [
    "outs:\n- md5: {bad}\n  size: 7000\n  path: w.bin  # the weights\n",
    "deps:\n- md5: {good}\n  path: w.bin\nouts:\n- md5: {bad}\n  path: w.bin\n",
])
def test_K4_dvc_pointer_syntax_cannot_hide_a_mismatch(cli, repo, pointer):
    record(cli, "models/w.bin", "dvc pull", "--tool", "dvc")
    good = hashlib.md5((repo / "models/w.bin").read_bytes()).hexdigest()
    (repo / "models/w.bin.dvc").write_text(pointer.format(good=good, bad="0" * 32))
    res = r50(cli, repo)
    assert res["status"] == "FAIL" and "R-50.dvc_mismatch" in codes(res)


def test_K4_the_pointer_is_part_of_the_verdict_digest(cli, repo):
    record(cli, "models/w.bin", "dvc pull", "--tool", "dvc")
    good = hashlib.md5((repo / "models/w.bin").read_bytes()).hexdigest()
    (repo / "models/w.bin.dvc").write_text(f"outs:\n- md5: {good}\n  path: w.bin\n")
    _, a, _ = cli("check", "--repo", repo, "--format", "json", "storage")
    (repo / "models/w.bin.dvc").write_text(f"outs:\n- md5: {'0' * 32}\n  path: w.bin\n")
    _, b, _ = cli("check", "--repo", repo, "--format", "json", "storage")
    assert json.loads(a)["verdict"]["inputs_digest"] != json.loads(b)["verdict"]["inputs_digest"]


def test_K4_sha_size_and_md5_come_from_one_observation(repo):
    from steward import storage as stg
    st = stg.measure(repo, "models/w.bin")
    data = (repo / "models/w.bin").read_bytes()
    assert st["sha256"] == hashlib.sha256(data).hexdigest() and st["size"] == len(data) and st["md5"] == hashlib.md5(data).hexdigest()


@pytest.mark.parametrize("note", ["line one\nline two", 'say "pull" \\ then go', "tab\there", "bell\x07"])
def test_K5_record_round_trips_any_retrieval_note(cli, repo, note):
    record(cli)
    record(cli, "models/w.bin", note)
    code, out, _ = cli("storage", "verify", "--json")
    assert code == 0
    import tomllib
    reg = tomllib.loads((repo / "development/artifacts.toml").read_text())
    assert reg["artifacts"][0]["retrieval"] == note


def test_K8_a_dropped_annex_object_is_incomplete_when_final(cli, repo):
    _annex(repo, b"annexed content")
    record(cli, "models/a.bin", "datalad get models/a.bin", "--tool", "datalad")
    for f in (repo / ".git/annex/objects").rglob("*.bin"):
        if f.is_file():
            f.unlink()
    assert r50(cli, repo)["status"] == "PASS"
    res = r50(cli, repo, final=True)
    assert res["status"] == "INCOMPLETE"
    assert "datalad get" in next(d for d in res["details"] if d["code"] == "R-50.annex_key_only")["message"]


def test_K12_the_audit_does_not_depend_on_the_registry(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[storage.caps]\n"models" = 1\n')
    (repo / "development/artifacts.toml").write_text("schema = [\n")
    code, out, _ = cli("storage", "audit", "--json")
    assert code == 0 and json.loads(out)["directories"][0]["path"] == "models"
