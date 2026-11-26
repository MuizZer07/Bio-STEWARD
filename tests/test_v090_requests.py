"""0.9.0, section B: the requests deferred from 0.8.1 (RELEASE_v0.9.0_SPEC §2). Each test is named after its task
and request ID."""

import tarfile
import io
import zipfile

import pytest

from conftest import codes, gate, one

CFF = "cff-version: 1.2.0\nmessage: m\ntitle: t\nauthors:\n  - name: n\n"


@pytest.fixture
def release(cli, tmp_path, monkeypatch):
    cli("init", "--repo", tmp_path)
    for name, text in (("CITATION.cff", CFF), ("LICENSE", "MIT\n"), ("README.md", "# x\n")):
        (tmp_path / name).write_text(text)
    (tmp_path / "dist").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _wheel(root, name, members):
    with zipfile.ZipFile(root / "dist" / name, "w") as z:
        for m in members:
            z.writestr(m, "x = 1\n")


def _sdist(root, name, members):
    top = name[: -len(".tar.gz")]
    with tarfile.open(root / "dist" / name, "w:gz") as t:
        for m in members:
            data = b"x = 1\n"
            info = tarfile.TarInfo(f"{top}/{m}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


ARTIFACT_RULES = '''
[release]
[[release.artifact]]
match = "mylib-*.whl"
forbid = ["mylib/server/**"]
require = ["mylib/__init__.py"]

[[release.artifact]]
match = "myapp-*.whl"
require = ["myapp/static/**"]

[release.checks]
expect = ["mylib-*.whl", "mylib-*.tar.gz", "myapp-*.whl"]
same_version = true
'''


def _configure(root, text=ARTIFACT_RULES):
    with open(root / "steward.toml", "a") as f:
        f.write(text)


# ---------------------------------------------------------------- B1 / REQ-002
def test_B1_REQ_002_each_artifact_rule_gives_one_finding(cli, release):
    _configure(release)
    _wheel(release, "mylib-1.0-py3-none-any.whl", ["mylib/__init__.py", "mylib/server/app.py"])   # forbidden member
    _wheel(release, "myapp-1.1-py3-none-any.whl", ["myapp/__init__.py"])                         # missing member, version
    # the sdist mylib-*.tar.gz is absent
    code, out, _ = cli("release", "audit")
    assert code == 1
    for c in ("forbidden_member", "missing_member", "missing_artifact", "version_mismatch"):
        assert c in out, (c, out)
    cli("release", "manifest")
    _, rep = cli.check(release, "release")
    res = one(rep, "R-42")
    assert res["status"] == "FAIL"
    assert {"R-42.forbidden_member", "R-42.missing_member", "R-42.missing_artifact", "R-42.version_mismatch"} <= codes(res)


def test_B1_REQ_002_a_clean_dist_passes(cli, release):
    _configure(release)
    _wheel(release, "mylib-1.0-py3-none-any.whl", ["mylib/__init__.py", "mylib/core.py"])
    _sdist(release, "mylib-1.0.tar.gz", ["mylib/__init__.py", "PKG-INFO"])
    _wheel(release, "myapp-1.0-py3-none-any.whl", ["myapp/__init__.py", "myapp/static/index.html"])
    code, out, _ = cli("release", "audit")
    assert code == 0, out
    cli("release", "manifest")
    _, rep = cli.check(release, "release")
    assert one(rep, "R-42")["status"] == "PASS", one(rep, "R-42")


def test_B1_REQ_002_an_artifact_without_a_rule_uses_the_global_lists_only(cli, release):
    _configure(release, '\n[release]\n[[release.artifact]]\nmatch = "other-*.whl"\nrequire = ["other/x.py"]\n')
    _wheel(release, "mylib-1.0-py3-none-any.whl", ["mylib/__init__.py"])
    code, out, _ = cli("release", "audit")
    assert code == 0, out


def test_B1_REQ_002_same_version_reads_wheel_and_sdist_names(cli, release):
    from steward import release as rl
    assert rl.artifact_version("my_lib-1.2.3-py3-none-any.whl") == "1.2.3"
    assert rl.artifact_version("my-lib-1.2.3.tar.gz") == "1.2.3"
    assert rl.artifact_version("bundle-2.0.zip") == "2.0"
    assert rl.artifact_version("noversion.zip") is None


# ---------------------------------------------------------------- shared
import shutil
import subprocess

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def proj(cli, tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)  # hermetic: no user-level ignore rules or settings
    r = tmp_path / "proj"
    r.mkdir()
    cli("init", "--repo", r)
    monkeypatch.chdir(r)
    return r


def _add(root, text):
    with open(root / "steward.toml", "a") as f:
        f.write(text)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


# ---------------------------------------------------------------- B3 / REQ-005: R-56 boundary.imports
BOUNDARY = '''
[boundary]
packages = ["src/lib"]
forbidden_imports = ["requests", "anthropic"]
forbidden_distributions = ["requests", "bio-steward"]
allow_groups = ["dev"]
'''


@pytest.mark.parametrize("source, status, code", [
    ("import requests.adapters\n", "FAIL", "R-56.forbidden_import"),
    ("from anthropic import Client\n", "FAIL", "R-56.forbidden_import"),
    ("import importlib\nm = importlib.import_module('requests')\n", "FAIL", "R-56.forbidden_import"),
    ("m = __import__('anthropic.types')\n", "FAIL", "R-56.forbidden_import"),
    ("import importlib\nm = importlib.import_module(name)\n", "UNKNOWN", "R-56.computed_import"),
    ("from . import sibling\nfrom .sub import x\n", "PASS", None),
    ("import requests_toolbelt\nimport json\n", "PASS", None),
])
def test_B3_REQ_005_imports(cli, proj, source, status, code):
    _add(proj, BOUNDARY)
    _write(proj, "pyproject.toml", '[project]\nname = "x"\n')  # declared distributions need a file to check (Q16)
    _write(proj, "src/lib/a.py", source)
    _, rep = cli.check(proj, "boundary")
    res = one(rep, "R-56")
    assert res["status"] == status, res
    if code:
        assert code in codes(res)


@pytest.mark.parametrize("pyproject, status", [
    ('[project]\nname = "x"\ndependencies = ["Requests>=2"]\n', "FAIL"),
    ('[project]\nname = "x"\n[project.optional-dependencies]\nweb = ["requests[socks]"]\n', "FAIL"),
    ('[project]\nname = "x"\n[dependency-groups]\ntest = ["bio_steward"]\n', "FAIL"),
    ('[project]\nname = "x"\ndependencies = ["numpy"]\n[dependency-groups]\ndev = ["bio-steward>=0.8"]\n', "PASS"),
])
def test_B3_REQ_005_distributions(cli, proj, pyproject, status):
    _add(proj, BOUNDARY)
    _write(proj, "src/lib/a.py", "import json\n")
    _write(proj, "pyproject.toml", pyproject)
    _, rep = cli.check(proj, "boundary")
    res = one(rep, "R-56")
    assert res["status"] == status, res
    if status == "FAIL":
        assert "R-56.forbidden_distribution" in codes(res)


def test_B3_not_configured_is_not_applicable(cli, proj):
    _, rep = cli.check(proj, "boundary")
    assert one(rep, "R-56")["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- B4 / REQ-007: R-57 tasks.board
TASKS = '''
[tasks]
specs = ["development/tasks/*.md"]
archive = ["development/tasks/archive/*.md"]
board = "development/BOARD.md"
id_pattern = "TSK-\\\\d{3}"
'''


def _task(root, rel, tid, status):
    _write(root, rel, f"# Task: t\n\n- **ID:** `{tid}`\n- **Status:** {status}\n")


@pytest.fixture
def board(cli, proj):
    _add(proj, TASKS)
    _task(proj, "development/tasks/one.md", "TSK-001", "in progress")
    _task(proj, "development/tasks/three.md", "TSK-003", "done")
    _task(proj, "development/tasks/archive/two.md", "TSK-002", "done")
    _write(proj, "development/BOARD.md", "# Board\n\n- TSK-001 one\n\nNext unused ID: TSK-004\n")
    return proj


def test_B4_REQ_007_a_consistent_board_passes(cli, board):
    _, rep = cli.check(board, "tasks")
    assert one(rep, "R-57")["status"] == "PASS", one(rep, "R-57")


@pytest.mark.parametrize("mutate, code", [
    (lambda r: _task(r, "development/tasks/dup.md", "TSK-002", "proposed"), "R-57.duplicate_id"),
    (lambda r: _task(r, "development/tasks/four.md", "TSK-004", "proposed"), "R-57.not_on_board"),
    (lambda r: _write(r, "development/BOARD.md", "- TSK-001\n\nNext unused ID: TSK-003\n"), "R-57.next_id_stale"),
    (lambda r: _task(r, "development/tasks/one.md", "TSK-001", "wip"), "R-57.unknown_status"),
    (lambda r: _write(r, "development/tasks/noid.md", "# Task: x\n- **Status:** proposed\n"), "R-57.no_id"),
])
def test_B4_REQ_007_each_defect_fails(cli, board, mutate, code):
    mutate(board)
    _, rep = cli.check(board, "tasks")
    res = one(rep, "R-57")
    assert res["status"] == "FAIL" and code in codes(res), res


# ---------------------------------------------------------------- B5 / REQ-008: R-58 changelog.unreleased
@pytest.fixture
def chlog(cli, proj):
    sh(proj, "git", "init", "-q", "-b", "main")
    sh(proj, "git", "config", "user.name", "T")
    sh(proj, "git", "config", "user.email", "t@example.org")
    _add(proj, '\n[changelog]\nfile = "CHANGELOG.md"\nexclude = ["docs/**"]\n')
    _write(proj, "CHANGELOG.md", "# Changelog\n\n## Unreleased\n\n## 1.0\n- first\n")
    _write(proj, "src/x.py", "x = 1\n")
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "1.0")
    return proj


@git_needed
def test_B5_REQ_008_no_release_tag_is_unknown(cli, chlog):
    _, rep = cli.check(chlog, "changelog")
    assert one(rep, "R-58")["status"] == "UNKNOWN"


@git_needed
def test_B5_REQ_008_code_changed_without_an_entry_fails_but_is_advisory(cli, chlog):
    sh(chlog, "git", "tag", "v1.0")
    _write(chlog, "src/x.py", "x = 2\n")
    sh(chlog, "git", "commit", "-qam", "change")
    _, rep = cli.check(chlog)
    res = one(rep, "R-58")
    assert res["status"] == "FAIL" and "R-58.no_entry" in codes(res), res
    assert "R-58" not in gate(rep)["required"] if "required" in gate(rep) else True
    assert gate(rep)["eligible"], gate(rep)  # advisory: the default gate does not require it


@git_needed
def test_B5_REQ_008_an_entry_in_the_range_passes(cli, chlog):
    sh(chlog, "git", "tag", "v1.0")
    _write(chlog, "src/x.py", "x = 2\n")
    _write(chlog, "CHANGELOG.md", "# Changelog\n\n## Unreleased\n- changed x\n\n## 1.0\n- first\n")
    sh(chlog, "git", "commit", "-qam", "change")
    _, rep = cli.check(chlog, "changelog")
    assert one(rep, "R-58")["status"] == "PASS", one(rep, "R-58")


@git_needed
def test_B5_REQ_008_only_excluded_files_changed_passes(cli, chlog):
    sh(chlog, "git", "tag", "v1.0")
    _write(chlog, "docs/guide.md", "text\n")
    sh(chlog, "git", "add", "-A")
    sh(chlog, "git", "commit", "-qm", "docs")
    _, rep = cli.check(chlog, "changelog")
    assert one(rep, "R-58")["status"] == "PASS", one(rep, "R-58")


@git_needed
def test_B5_a_gate_can_require_the_changelog_rule(cli, chlog):
    sh(chlog, "git", "tag", "v1.0")
    _write(chlog, "src/x.py", "x = 2\n")
    sh(chlog, "git", "commit", "-qam", "change")
    _add(chlog, '\n[gates.release]\nrequire = ["R-58"]\n')
    _, rep = cli.check(chlog, gate="release")
    assert not gate(rep, "release")["eligible"]


# ---------------------------------------------------------------- B6 / REQ-009: R-59 branches.model
@pytest.fixture
def branches(cli, proj):
    sh(proj, "git", "init", "-q", "-b", "main")
    sh(proj, "git", "config", "user.name", "T")
    sh(proj, "git", "config", "user.email", "t@example.org")
    _add(proj, '\n[branches]\nrelease = "release"\nintegration = "main"\nmerge = "no-ff"\ntask_patterns = ["task/*", "fix/*"]\n')
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "init")
    sh(proj, "git", "tag", "v0.1")
    sh(proj, "git", "branch", "release")
    sh(proj, "git", "checkout", "-q", "-b", "task/a")
    _write(proj, "a.txt", "a\n")
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "a")
    sh(proj, "git", "checkout", "-q", "main")
    sh(proj, "git", "merge", "-q", "--no-ff", "-m", "merge task/a", "task/a")
    return proj


@git_needed
def test_B6_REQ_009_the_declared_model_passes(cli, branches):
    _, rep = cli.check(branches, "branches")
    assert one(rep, "R-59")["status"] == "PASS", one(rep, "R-59")


@git_needed
def test_B6_REQ_009_a_fast_forward_into_integration_fails(cli, branches):
    sh(branches, "git", "checkout", "-q", "-b", "task/b")
    _write(branches, "b.txt", "b\n")
    sh(branches, "git", "add", "-A")
    sh(branches, "git", "commit", "-qm", "b")
    sh(branches, "git", "checkout", "-q", "main")
    sh(branches, "git", "merge", "-q", "--ff-only", "task/b")
    _, rep = cli.check(branches, "branches")
    res = one(rep, "R-59")
    assert res["status"] == "FAIL" and "R-59.not_no_ff" in codes(res), res


@git_needed
def test_B6_REQ_009_an_untagged_release_commit_fails(cli, branches):
    sh(branches, "git", "checkout", "-q", "release")
    sh(branches, "git", "merge", "-q", "--no-ff", "-m", "release", "main")
    sh(branches, "git", "checkout", "-q", "main")
    _, rep = cli.check(branches, "branches")
    res = one(rep, "R-59")
    assert res["status"] == "FAIL" and "R-59.untagged_release_commit" in codes(res), res


@git_needed
def test_B6_REQ_009_a_branch_name_outside_the_patterns_fails(cli, branches):
    sh(branches, "git", "branch", "wip")
    _, rep = cli.check(branches, "branches")
    res = one(rep, "R-59")
    assert res["status"] == "FAIL" and "R-59.branch_name" in codes(res), res


@git_needed
def test_B6_REQ_009_pre_push_refuses_an_untagged_release_tip(cli, branches, capsys):
    from steward import hooks as hk
    sh(branches, "git", "checkout", "-q", "release")
    sh(branches, "git", "merge", "-q", "--no-ff", "-m", "release", "main")
    tip = sh(branches, "git", "rev-parse", "HEAD")
    sh(branches, "git", "checkout", "-q", "main")
    line = [f"refs/heads/release {tip} refs/heads/release {'0' * 40}"]
    assert hk.run_pre_push(branches, "default", [], "skip", line) == 1
    assert "not tagged" in capsys.readouterr().err
    sh(branches, "git", "tag", "v0.2", tip)
    assert hk.run_pre_push(branches, "default", [], "skip", line) == 0


# ---------------------------------------------------------------- B7 / REQ-014: one canonical skills directory, R-60
def test_B7_REQ_014_two_directories_give_one_copy_and_a_link(cli, tmp_path):
    r = tmp_path / "s"
    r.mkdir()
    code, out, err = cli("init", "--repo", r, "--skills", ".agents/skills", "--skills", ".claude/skills")
    assert code == 0, err
    assert (r / ".agents/skills").is_dir() and not (r / ".agents/skills").is_symlink()
    link = r / ".claude/skills"
    assert link.is_symlink() and not str(link.readlink()).startswith("/")
    assert link.resolve() == (r / ".agents/skills").resolve()
    assert ".agents/skills" in (r / "AGENTS.md").read_text()
    _, rep = cli.check(r, "skills")
    assert one(rep, "R-60")["status"] == "PASS", one(rep, "R-60")


def test_B7_REQ_014_drift_between_copies_fails(cli, tmp_path):
    r = tmp_path / "s"
    r.mkdir()
    cli("init", "--repo", r, "--skills", ".agents/skills", "--skills", ".claude/skills")
    (r / ".claude/skills").unlink()
    shutil.copytree(r / ".agents/skills", r / ".claude/skills")
    _, rep = cli.check(r, "skills")
    assert one(rep, "R-60")["status"] == "PASS"  # an identical copy is allowed
    md = next((r / ".claude/skills").glob("*/SKILL.md"))
    md.write_text(md.read_text() + "\nedited\n")
    _, rep = cli.check(r, "skills")
    res = one(rep, "R-60")
    assert res["status"] == "FAIL" and "R-60.drift" in codes(res), res


def test_B7_REQ_014_a_dangling_link_fails(cli, tmp_path):
    r = tmp_path / "s"
    r.mkdir()
    cli("init", "--repo", r, "--skills", ".agents/skills", "--skills", ".claude/skills")
    shutil.rmtree(r / ".agents/skills")
    _, rep = cli.check(r, "skills")
    res = one(rep, "R-60")
    assert res["status"] == "FAIL", res


def test_B7_one_directory_is_unchanged(cli, tmp_path):
    r = tmp_path / "s"
    r.mkdir()
    code, _, _ = cli("init", "--repo", r, "--skills", ".agents/skills")
    assert code == 0 and (r / ".agents/skills").is_dir()
    assert "[skills]" not in (r / "steward.toml").read_text()


# ---------------------------------------------------------------- B8 / REQ-015: deterministic release bundles
def _assets(root, order, mode=0o644):
    import os
    import time
    for i, name in enumerate(order):
        _write(root, f"golden/{name}", f"{name}\n")
        os.chmod(root / f"golden/{name}", mode)
        os.utime(root / f"golden/{name}", (time.time() - i * 1000, time.time() - i * 1000))


def test_B8_REQ_015_bundles_are_byte_identical_across_runs(cli, release, tmp_path):
    import os
    _assets(release, ["b.txt", "a.txt", "sub/c.txt"])
    code, out, err = cli("release", "bundle", "golden", "--paths", "golden")
    assert code == 0, err
    first = (release / "dist/bundles/golden.zip").read_bytes()
    shutil.rmtree(release / "golden")
    old = os.umask(0o077)
    try:
        _assets(release, ["sub/c.txt", "a.txt", "b.txt"], mode=0o600)
    finally:
        os.umask(old)
    (release / "dist/bundles/golden.zip").unlink()
    cli("release", "bundle", "golden", "--paths", "golden")
    assert (release / "dist/bundles/golden.zip").read_bytes() == first
    with zipfile.ZipFile(release / "dist/bundles/golden.zip") as z:
        assert [i.filename for i in z.infolist()] == ["golden/a.txt", "golden/b.txt", "golden/sub/c.txt"]
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_B8_REQ_015_the_manifest_lists_bundles_and_r42_checks_them(cli, release):
    _configure(release, "\n[release]\n")
    _wheel(release, "p-1.0-py3-none-any.whl", ["p/__init__.py"])
    _assets(release, ["a.txt"])
    cli("release", "bundle", "golden", "--paths", "golden")
    cli("release", "manifest")
    import json
    man = json.loads((release / "release-manifest.json").read_text())
    assert "golden" in man["bundles"] and len(man["bundles"]["golden"]["sha256"]) == 64
    _, rep = cli.check(release, "release")
    assert one(rep, "R-42")["status"] == "PASS", one(rep, "R-42")
    _write(release, "golden/a.txt", "changed\n")
    cli("release", "bundle", "golden", "--paths", "golden", "--force")
    _, rep = cli.check(release, "release")
    res = one(rep, "R-42")
    assert res["status"] == "FAIL" and "R-42.bundle_mismatch" in codes(res), res


def test_B8_REQ_015_a_test_report_is_recorded(cli, release):
    import json
    import sys
    _assets(release, ["a.txt"])
    code, _, err = cli("release", "bundle", "golden", "--paths", "golden", "--test-report",
                       f"{sys.executable} -c \"raise SystemExit(3)\"")
    assert code == 0, err
    rec = json.loads((release / "dist/bundles/golden.bundle.json").read_text())
    assert rec["test_report"]["exit_code"] == 3 and rec["test_report"]["python"]
    assert rec["members"] == ["golden/a.txt"]


def test_B8_REQ_015_paths_outside_the_repository_and_overwrites_are_refused(cli, release, tmp_path):
    (tmp_path / "outside.txt").write_text("x\n")
    code, _, _ = cli("release", "bundle", "x", "--paths", "../outside.txt")
    assert code == 64
    _assets(release, ["a.txt"])
    assert cli("release", "bundle", "golden", "--paths", "golden")[0] == 0
    assert cli("release", "bundle", "golden", "--paths", "golden")[0] == 64  # exists: --force to replace


# ---------------------------------------------------------------- B2 / REQ-008: reproduction gate, R-52
REPRO = '''schema = "steward.repro/0.1"
id = "published-v1"
manifest = "benchmarks/golden/MANIFEST.json"
reference = "benchmarks/golden/ref"
canonical = "json-sorted"
volatile = ["/created_at"]
[compare]
default = "{default}"
'''


@pytest.fixture
def repro(cli, proj):
    import json
    sh(proj, "git", "init", "-q", "-b", "main")
    sh(proj, "git", "config", "user.name", "T")
    sh(proj, "git", "config", "user.email", "t@example.org")
    _add(proj, '\n[repro]\ncontracts = ["benchmarks/*.repro.toml"]\n')
    _write(proj, "benchmarks/published.repro.toml", REPRO.format(default="exact"))
    ref = {"auc": 0.9123, "n": 10, "created_at": "2026-01-01"}
    _write(proj, "benchmarks/golden/ref/out/metrics.json", json.dumps(ref))
    _write(proj, "benchmarks/golden/ref/out/table.csv", "a,b\n1,2\n")
    code, _, err = cli("repro", "manifest", "published-v1", "--from", "benchmarks/golden/ref")
    assert code == 0, err
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "repro")
    return proj


def _work(root, auc=0.9123, created="2026-11-23", table="a,b\n1,2\n"):
    import json
    w = root.parent / "work"
    shutil.rmtree(w, ignore_errors=True)
    _write(w, "out/metrics.json", json.dumps({"created_at": created, "n": 10, "auc": auc}))
    _write(w, "out/table.csv", table)
    return w


@git_needed
def test_B2_REQ_008_a_matching_work_folder_passes_and_is_recorded(cli, repro):
    code, out, err = cli("repro", "check", "published-v1", "--work", _work(repro))
    assert code == 0, out + err
    _, rep = cli.check(repro, "repro")
    assert one(rep, "R-52")["status"] == "PASS", one(rep, "R-52")


@git_needed
def test_B2_REQ_008_a_changed_float_fails_exact_and_passes_within_a_tolerance(cli, repro):
    code, out, _ = cli("repro", "check", "published-v1", "--work", _work(repro, auc=0.91230004))
    assert code == 1 and "/auc" in out
    _, rep = cli.check(repro, "repro")
    assert one(rep, "R-52")["status"] == "FAIL"
    _write(repro, "benchmarks/published.repro.toml", REPRO.format(default="abs:0.000001"))
    sh(repro, "git", "commit", "-qam", "tolerance")
    code, out, _ = cli("repro", "check", "published-v1", "--work", _work(repro, auc=0.91230004))
    assert code == 0, out


@git_needed
def test_B2_REQ_008_a_volatile_field_difference_passes_and_a_csv_change_fails(cli, repro):
    assert cli("repro", "check", "published-v1", "--work", _work(repro, created="2030-01-01"))[0] == 0
    code, out, _ = cli("repro", "check", "published-v1", "--work", _work(repro, table="a,b\n1,3\n"))
    assert code == 1 and "out/table.csv" in out


@git_needed
def test_B2_REQ_008_no_record_on_the_current_commit_is_incomplete(cli, repro):
    _, rep = cli.check(repro, "repro")
    assert one(rep, "R-52")["status"] == "INCOMPLETE"
    cli("repro", "check", "published-v1", "--work", _work(repro))
    _write(repro, "src/new.py", "x = 1\n")
    sh(repro, "git", "add", "-A")
    sh(repro, "git", "commit", "-qm", "later change")
    _, rep = cli.check(repro, "repro")
    res = one(rep, "R-52")
    assert res["status"] == "INCOMPLETE" and "R-52.not_current" in codes(res), res


@git_needed
def test_B2_a_missing_work_file_fails(cli, repro):
    w = _work(repro)
    (w / "out/table.csv").unlink()
    code, out, _ = cli("repro", "check", "published-v1", "--work", w)
    assert code == 1 and "missing" in out
