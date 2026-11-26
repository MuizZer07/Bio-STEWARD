"""0.8.1: named term lists, local paths, exemptions (SR-004, AR-04, SR-005, FB-2, FB-3, FB-11)."""

import json
import zipfile

import pytest

from conftest import append, codes, one

POLICY = '\n[[terms]]\nname = "policy"\nfile = "development/policy_terms.txt"\npublic = true\n'


def r07(cli, root):
    _, rep = cli.check(root)
    return one(rep, "R-07")


def test_SR004_a_committed_public_list_works_without_the_private_one(cli, example):
    append(example, "steward.toml", POLICY + '\n[privacy]\ndenylist_file = ".steward/private/denylist.txt"\n')
    (example / "development/policy_terms.txt").write_text("# names the software never mentions\nAcmeHost\n")
    res = r07(cli, example)
    assert res["status"] == "PASS" and "R-07.list_missing" in codes(res)      # the private list is absent: a detail
    append(example, "README.md", "\nRuns on AcmeHost.\n")
    res = r07(cli, example)
    hit = next(d for d in res["details"] if d["code"] == "R-07.policy_hit")
    assert res["status"] == "FAIL" and hit["term"] == "policy:2" and hit["value"] == "AcmeHost"


def test_SR004_substring_terms_match_inside_identifiers_plain_terms_do_not(cli, example):
    append(example, "steward.toml", POLICY)
    (example / "development/policy_terms.txt").write_text("substr:acmehost\nzeta\n")
    append(example, "analysis/metrics.py", "\nclass AcmeHostClient: pass\nzeta_value = 1\n")
    res = r07(cli, example)
    terms = {d["term"] for d in res["details"] if d["code"] == "R-07.policy_hit"}
    assert terms == {"policy:1"}  # substring matched inside the identifier; the plain term did not


def test_AR04_scope_case_and_patterns(cli, example):
    append(example, "steward.toml", POLICY + 'include = ["analysis/**"]\ncase_sensitive = true\npatterns = true\n')
    (example / "development/policy_terms.txt").write_text(r"ACME\b" + "\n" + r"ID-\d+" + "\n")
    append(example, "analysis/metrics.py", "\n# acme is fine in lower case; ID-42 is not\n")
    append(example, "README.md", "\nACME and ID-7 outside the scope\n")
    res = r07(cli, example)
    hits = [d for d in res["details"] if d["code"] == "R-07.policy_hit"]
    assert [(h["path"], h["term"]) for h in hits] == [("analysis/metrics.py", "policy:2")]


def test_AR04_an_invalid_pattern_fails(cli, example):
    append(example, "steward.toml", POLICY + "patterns = true\n")
    (example / "development/policy_terms.txt").write_text("[unclosed\n")
    res = r07(cli, example)
    assert res["status"] == "FAIL" and "R-07.bad_pattern" in codes(res)


def test_AR04_allow_globs_exempt_a_file(cli, example):
    append(example, "steward.toml", POLICY + 'allow = ["tests/**"]\n')
    (example / "development/policy_terms.txt").write_text("AcmeHost\n")
    (example / "tests").mkdir(exist_ok=True)
    (example / "tests/test_names.py").write_text("FORBIDDEN = ['AcmeHost']\n")
    assert r07(cli, example)["status"] == "PASS"


def test_FB11_a_marked_line_is_exempt_and_counted(cli, example):
    append(example, "steward.toml", POLICY)
    (example / "development/policy_terms.txt").write_text("AcmeHost\n")
    append(example, "README.md", "\nWe never name AcmeHost here.  <!-- steward: allow R-07 -->\n")
    res = r07(cli, example)
    assert res["status"] == "PASS" and next(d for d in res["details"] if d["code"] == "R-07.allowed_lines")["value"] == 1


@pytest.mark.parametrize("text,hit", [
    ("cd /" "home/someone/project", True), ("open /" "Users/alice/data.csv", True), ("C:\\" r"Users\bob\file.txt", True),  # steward: allow R-07 (examples)
    ("see /" "home/<user>/project", False), ("/" "Users/you/repo", False), ("export HOME=/" "home/$USER/", False),
])
def test_SR005_local_home_paths_are_found_without_showing_them(cli, example, text, hit):
    append(example, "steward.toml", "\n[privacy]\n")
    append(example, "analysis/metrics.py", f"\n# {text}\n")
    res = r07(cli, example)
    found = [d for d in res["details"] if d["code"] == "R-07.local_path"]
    assert bool(found) is hit, res
    if hit:
        assert "someone" not in json.dumps(res) and "alice" not in json.dumps(res)


def test_SR005_the_audit_refuses_a_member_with_a_local_path(cli, tmp_path, monkeypatch):
    cli("init", "--repo", tmp_path)
    append(tmp_path, "steward.toml", "\n[release]\nrequired = []\n[privacy]\n")
    (tmp_path / "dist").mkdir()
    with zipfile.ZipFile(tmp_path / "dist/p-1.0-py3-none-any.whl", "w") as z:
        z.writestr("p/fixture.py", "ROOT = '/" "home/someone/project'\n")  # steward: allow R-07 (example)
    monkeypatch.chdir(tmp_path)
    code, out, _ = cli("release", "audit")
    assert code == 1 and "local_path" in out and "someone" not in out


def test_FB3_binary_assets_are_excluded_and_not_listed(cli, example):
    append(example, "steward.toml", "\n[privacy]\n")
    (example / "assets").mkdir()
    for i in range(5):
        (example / f"assets/f{i}.woff2").write_bytes(b"\x00\x01")
    (example / "data/blob.bin").write_bytes(b"\x00\x01binary")
    _, rep = cli.check(example)
    listed = {n["path"] for n in rep["verdict"]["coverage"]["not_evaluated"]}
    assert not any(p.endswith(".woff2") for p in listed) and "data/blob.bin" in listed
    _, out, _ = cli("check", "--repo", example, "--summary")
    line = next(l for l in out.splitlines() if l.startswith("Not evaluated:"))
    assert ".bin: 1" in line


def test_SR004_the_audit_honours_each_lists_allow_globs(cli, tmp_path, monkeypatch):
    cli("init", "--repo", tmp_path)
    append(tmp_path, "steward.toml", '\n[release]\nrequired = []\n' + POLICY + 'allow = ["p/names.py"]\n')
    (tmp_path / "development/policy_terms.txt").write_text("AcmeHost\n")
    (tmp_path / "dist").mkdir()
    with zipfile.ZipFile(tmp_path / "dist/p-1.0-py3-none-any.whl", "w") as z:
        z.writestr("p/names.py", "FORBIDDEN = ['AcmeHost']\n")
        z.writestr("p/core.py", "x = 1\n")
    monkeypatch.chdir(tmp_path)
    assert cli("release", "audit")[0] == 0
    with zipfile.ZipFile(tmp_path / "dist/p-1.0-py3-none-any.whl", "a") as z:
        z.writestr("p/client.py", "# talks to AcmeHost\n")
    code, out, _ = cli("release", "audit")
    assert code == 1 and "policy_term" in out and "client.py" in out
