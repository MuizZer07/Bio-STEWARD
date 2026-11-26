"""v0.6.1 release integrity: manifest, distribution audit, CITATION.cff, R-42; the toolkit's own distributions
(red-team A4)."""

import io
import json
import shutil
import subprocess
import tarfile
import zipfile

import pytest

from conftest import REPO, codes, one

CFF = 'cff-version: 1.2.0\nmessage: "cite"\ntitle: "x"\nauthors:\n  - name: "A"\n'


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[release]\nlocks = ["uv.lock"]\n')
    for name, text in (("CITATION.cff", CFF), ("LICENSE", "MIT\n"), ("README.md", "# x\n"), ("uv.lock", "v1\n")):
        (tmp_path / name).write_text(text)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def build(repo, extra=None):
    d = repo / "dist"
    d.mkdir(exist_ok=True)
    with zipfile.ZipFile(d / "pkg-1.0-py3-none-any.whl", "w") as z:
        z.writestr("pkg/__init__.py", "x = 1\n")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    buf = io.BytesIO(b"source")
    with tarfile.open(d / "pkg-1.0.tar.gz", "w:gz") as t:
        info = tarfile.TarInfo("pkg-1.0/pkg/__init__.py")
        info.size = 6
        t.addfile(info, buf)


def test_clean_release_passes(cli, repo):
    build(repo)
    _, rep = cli.check(repo)
    assert one(rep, "R-42")["status"] == "INCOMPLETE"  # built, not yet recorded
    code, out, _ = cli("release", "manifest", "--version", "1.0")
    assert code == 0 and "2 artifact(s)" in out
    _, rep = cli.check(repo)
    assert one(rep, "R-42")["status"] == "PASS"
    man = json.loads((repo / "release-manifest.json").read_text())
    assert man["version"] == "1.0" and man["locks"]["uv.lock"] and man["citation_sha256"]


def test_tampered_artifact_and_changed_lock_fail(cli, repo):
    build(repo)
    cli("release", "manifest")
    with open(repo / "dist/pkg-1.0.tar.gz", "ab") as f:
        f.write(b"x")
    (repo / "uv.lock").write_text("v2\n")
    _, rep = cli.check(repo)
    assert {"R-42.artifact_mismatch", "R-42.lock_changed"} <= codes(one(rep, "R-42"))


def test_development_and_secrets_refused(cli, repo):
    build(repo, {"development/DECISIONS.md": "plans", ".env": "KEY=1", "pkg/id_rsa": "k"})
    code, out, _ = cli("release", "audit")
    assert code == 1 and out.count("REFUSED") == 3
    cli("release", "manifest")
    _, rep = cli.check(repo)
    assert "R-42.excluded" in codes(one(rep, "R-42"))


def test_private_terms_in_members(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[privacy]\ndenylist_file = ".steward/private/terms.txt"\n')
    (repo / ".steward/private").mkdir(parents=True)
    (repo / ".steward/private/terms.txt").write_text("projectnightjar\n")
    build(repo, {"pkg/notes.txt": "internal projectnightjar notes"})
    code, out, _ = cli("release", "audit")
    assert code == 1 and "private_term" in out and "nightjar" not in out


def test_required_files_and_citation(cli, repo):
    (repo / "LICENSE").unlink()
    (repo / "CITATION.cff").write_text('cff-version: 1.2.0\ntitle: "x"\n')
    _, rep = cli.check(repo)
    res = one(rep, "R-42")
    # 0.9.0 (REQ-001): with nothing built, they are reported, not failed; a final check (or a build) fails them
    assert res["status"] == "NOT_APPLICABLE" and {"R-42.missing_required", "R-42.citation"} <= codes(res)
    _, out, _ = cli("check", "--repo", repo, "--format", "json", "--final")
    res = one(json.loads(out), "R-42")
    assert res["status"] == "FAIL" and {"R-42.missing_required", "R-42.citation"} <= codes(res)


def test_not_configured(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, rep = cli.check(tmp_path)
    assert one(rep, "R-42")["status"] == "NOT_APPLICABLE"


@pytest.mark.skipif(not shutil.which("uv") or not (REPO / ".git").exists(), reason="needs uv and a git checkout")
def test_A4_toolkit_distributions_are_audited_and_installable(cli, tmp_path):
    """Red-team A4: build the toolkit's own wheel and sdist from a clean export, audit them, install the wheel in a
    fresh environment, and use its bundled skills and templates."""
    export = tmp_path / "export"
    export.mkdir()
    archive = subprocess.run(["git", "archive", "HEAD"], cwd=REPO, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(archive)).extractall(export)
    for rel in ("pyproject.toml", "src", "skills", "templates", "CITATION.cff"):  # the working-tree state under test
        src, dst = REPO / rel, export / rel
        if src.is_dir():
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy(src, dst)
    dist = tmp_path / "dist"
    subprocess.run(["uv", "build", "-q", "-o", str(dist)], cwd=export, check=True)
    from steward import release as rl
    aud = rl.audit(dist, rl.DEFAULT_EXCLUDE, [])
    assert aud["findings"] == [] and len(aud["artifacts"]) == 2
    sdist = next(dist.glob("*.tar.gz"))
    names = tarfile.open(sdist).getnames()
    top = names[0].split("/")[0]
    assert f"{top}/CITATION.cff" in names
    assert not [n for n in names if n.startswith(f"{top}/development/")]
    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", "-q", str(venv)], check=True)
    wheel = next(dist.glob("*.whl"))
    subprocess.run(["uv", "pip", "install", "-q", "--python", str(venv / "bin/python"), str(wheel)], check=True)
    proj = tmp_path / "proj"
    proj.mkdir()
    r = subprocess.run([str(venv / "bin/steward"), "init", "--skills", ".agents/skills", "--paper"], cwd=proj,
                       capture_output=True, text=True)
    assert r.returncode == 0 and (proj / ".agents/skills/using-steward/SKILL.md").is_file()
    assert (proj / "paper/main.tex").is_file()
    # S10 (0.13.0): the core quick start, from the installed artifact, in a fresh folder, to the gate it documents
    import re as _re
    qs = (REPO / "docs/quickstart.md").read_text()
    block = _re.search(r"```bash\n(.*?)```", qs, _re.S).group(1)
    expected = _re.search(r"Expected gate: `(Gate default: [A-Z ]+)`", qs).group(1)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    gate = ""
    for line in [l for l in block.splitlines() if l.startswith("steward ")]:
        r = subprocess.run([str(venv / "bin/steward"), *line.split()[1:]], cwd=fresh, capture_output=True, text=True)
        assert r.returncode in (0, 1, 2, 3), (line, r.stderr)
        gate = next((l for l in r.stdout.splitlines() if l.startswith("Gate default:")), gate)
    assert gate.startswith(expected), gate


# ---------------------------------------------------------------- red-team B5
def test_B5_failing_claim_map_blocks_the_release(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write("\n[evidence]\n")
    (repo / "development/claims.toml").write_text("this is [not valid toml\n")
    build(repo)
    cli("release", "manifest")
    man = json.loads((repo / "release-manifest.json").read_text())
    assert man["claims"] == "FAIL" and man["claims_sha256"]
    code, rep = cli.check(repo, "release")
    res = one(rep, "R-42")
    assert res["status"] == "FAIL" and "R-42.claims_not_passing" in codes(res) and code == 1


def test_B5_cffconvert_is_run_when_installed(cli, repo, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "cffconvert"
    fake.write_text("#!/bin/sh\necho 'invalid: authors' >&2\nexit 1\n")
    fake.chmod(0o755)
    import os
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    _, rep = cli.check(repo)
    assert "R-42.citation_invalid" in codes(one(rep, "R-42"))


# ---------------------------------------------------------------- red-team round 3: D4
def _evidence(repo, claims='schema = "steward.claims/0.1"\n'):
    with open(repo / "steward.toml", "a") as f:
        f.write("\n[evidence]\n")
    if claims is not None:
        (repo / "development/claims.toml").write_text(claims)


@pytest.fixture
def released(cli, repo):
    _evidence(repo)
    build(repo)
    assert cli("release", "manifest")[0] == 0
    _, rep = cli.check(repo, "release")
    assert one(rep, "R-42")["status"] == "PASS"
    return repo


def _add_comment(path):
    with open(path, "a") as f:
        f.write("# a harmless comment\n")


@pytest.mark.parametrize("change,code", [
    (lambda r: _add_comment(r / "development/claims.toml"), "R-42.claims_changed"),
    (lambda r: _add_comment(r / "CITATION.cff"), "R-42.citation_changed"),
    (lambda r: (r / "development/claims.toml").unlink(), "R-42.claims_changed"),
])
def test_D4_manifest_evidence_must_be_current(cli, released, change, code):
    change(released)
    code_, rep = cli.check(released, "release")
    res = one(rep, "R-42")
    assert res["status"] == "FAIL" and code in codes(res) and code_ == 1


def test_D4_configured_claim_map_must_exist(cli, repo):
    _evidence(repo, claims=None)
    _, rep = cli.check(repo, "release")
    res = one(rep, "R-42")
    assert res["status"] == "INCOMPLETE" and "R-42.no_claim_map" in codes(res)


def test_D4_malformed_claim_map_is_checked_without_distributions(cli, repo):
    _evidence(repo, claims="this is [not valid toml\n")
    _, rep = cli.check(repo, "release")
    res = one(rep, "R-42")
    assert res["status"] == "FAIL" and "R-42.claims_not_passing" in codes(res) and "R-42.no_dist" in codes(res)


# ---------------------------------------------------------------- red-team round 3: D6
def test_D6_coverage_credits_r42_only_when_distributions_were_audited(cli, repo):
    _, rep = cli.check(repo, "release")
    # AR-16 / SR-007 (0.8.1): nothing built is not applicable in a draft check, never a PASS
    assert one(rep, "R-42")["status"] == "NOT_APPLICABLE" and "R-42.no_dist" in codes(one(rep, "R-42"))
    assert "R-42" not in rep["verdict"]["coverage"]["statement"]
    build(repo)
    cli("release", "manifest")
    _, rep = cli.check(repo, "release")
    assert "checked by R-42" in rep["verdict"]["coverage"]["statement"]
