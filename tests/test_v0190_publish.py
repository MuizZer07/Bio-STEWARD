"""0.19.0: release publishing to a public mirror (STW-007), the setup for model A or B (STW-020), install channels
(STW-019)."""

import subprocess

import pytest

from test_v0120_features import gsh, xproj  # noqa: F401

AUTHOR = "Public Name <12345+public@users.noreply.github.com>"  # scrub: allow (a synthetic no-reply address)


def _dev(x, tmp_path, extra=""):
    pub = tmp_path / "public.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(pub)], check=True)
    (x / "src").mkdir(exist_ok=True)
    (x / "src/tool.py").write_text("print('hello')\n")
    (x / "README.md").write_text("# Tool\n")
    (x / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0.0\n- Superseded items (ABC-FB-018, ABC-FB-019) and a fix (XYZ-REQ-020).\n")
    (x / "development").mkdir(exist_ok=True)
    (x / "development/DECISIONS.md").write_text("private decisions\n")
    with open(x / "steward.toml", "a") as f:
        f.write(f'\n[publish]\nmode = "mirror"\nremote = "{pub}"\nauthor = "{AUTHOR}"\n{extra}')
    gsh(x, "git", "add", "-A")
    gsh(x, "git", "commit", "-qm", "dev work with private notes")
    gsh(x, "git", "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    return pub


def _files(repo, ref):
    return subprocess.run(["git", "ls-tree", "-r", "--name-only", ref], cwd=repo, capture_output=True, text=True).stdout.split()


def test_a_release_is_published_as_one_clean_commit_and_pushed_only_on_request(cli, xproj, tmp_path):
    pub = _dev(xproj, tmp_path)
    code, out, err = cli("release", "publish", "v1.0.0", "--dry-run")
    assert code == 0 and "3 private ID(s) removed" in out and "nothing was written" in out, err
    code, out, err = cli("release", "publish", "v1.0.0")
    assert code == 0 and "not pushed" in out, err
    stage = xproj / ".steward/publish"
    files = _files(stage, "v1.0.0")
    assert "src/tool.py" in files and "README.md" in files
    assert not [f for f in files if f.startswith(("development/", "exchange/", ".steward/"))]
    log = subprocess.run(["git", "log", "--format=%an <%ae>|%s", "v1.0.0"], cwd=stage, capture_output=True, text=True).stdout
    assert log.strip().splitlines() == [f"{AUTHOR}|Release v1.0.0"]  # one commit, the public identity, no dev history
    ch = subprocess.run(["git", "show", "v1.0.0:CHANGELOG.md"], cwd=stage, capture_output=True, text=True).stdout
    assert "ABC-FB" not in ch and "XYZ-REQ" not in ch and "Superseded items and a fix." in ch
    assert subprocess.run(["git", "tag", "--list"], cwd=pub, capture_output=True, text=True).stdout.strip() == ""
    code, out, err = cli("release", "publish", "v1.0.0", "--push")
    assert code == 0 and "pushed" in out, err
    assert "v1.0.0" in subprocess.run(["git", "tag", "--list"], cwd=pub, capture_output=True, text=True).stdout
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=xproj, capture_output=True, text=True).stdout  # untouched
    remotes = subprocess.run(["git", "remote"], cwd=xproj, capture_output=True, text=True).stdout.split()
    assert remotes == []  # the working checkout's remotes were never changed


def test_a_term_hit_or_a_local_path_refuses_the_publish(cli, xproj, tmp_path):
    (xproj / "development").mkdir(exist_ok=True)
    (xproj / "development/terms.txt").write_text("Zebrafinch\n")
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "products"\nfile = "development/terms.txt"\n')
    _dev(xproj, tmp_path)
    (xproj / "src/leak.py").write_text("# for the Zebrafinch pipeline\n")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "x")
    gsh(xproj, "git", "tag", "-a", "v1.1.0", "-m", "v1.1.0")
    code, out, err = cli("release", "publish", "v1.1.0")
    assert code == 65 and "REFUSED  src/leak.py:1: term list products:1" in out and "Zebrafinch" not in out + err
    assert not (xproj / ".steward/publish").exists()


def test_an_open_licence_finding_refuses_the_publish(cli, xproj, tmp_path):
    _dev(xproj, tmp_path, "")
    (xproj / "LICENSE").write_text("Permission is hereby granted, free of charge\n")
    (xproj / "pyproject.toml").write_text('[project]\nname = "tool"\nlicense = "Apache-2.0"\n')
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[licence]\ndeclared = "MIT"\n')
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "x")
    gsh(xproj, "git", "tag", "-a", "v1.2.0", "-m", "v1.2.0")
    code, out, _ = cli("release", "publish", "v1.2.0")
    assert code == 65 and "licence: R-79: pyproject.toml states Apache-2.0" in out


def test_status_names_the_last_public_release_and_what_is_unpublished(cli, xproj, tmp_path):
    _dev(xproj, tmp_path)
    cli("release", "publish", "v1.0.0")
    gsh(xproj, "git", "tag", "-a", "v1.1.0", "-m", "v1.1.0")
    code, out, _ = cli("release", "status")
    # AG2: a release built but not sent is still unpublished
    assert code == 0 and "last public release: v1.0.0 (not pushed yet)" in out and "not yet published: v1.0.0, v1.1.0" in out


def test_setup_writes_the_table_once_and_open_mode_only_plans(cli, xproj):
    code, out, _ = cli("release", "setup", "--mode", "mirror", "--remote", "https://example.org/x.git", "--author", AUTHOR)
    assert code == 0 and "[publish]" in (xproj / "steward.toml").read_text()
    assert cli("release", "setup", "--mode", "open")[0] == 64  # once
    t = (xproj / "steward.toml").read_text()
    (xproj / "steward.toml").write_text(t[:t.index("\n[publish]")])
    (xproj / "development").mkdir(exist_ok=True)
    (xproj / "development/x.md").write_text("x\n")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "about ABC-REQ-001")
    before = subprocess.run(["git", "log", "--format=%H"], cwd=xproj, capture_output=True, text=True).stdout
    code, out, _ = cli("release", "setup", "--mode", "open")
    assert code == 0 and "development" in out and "commits with private content: 1" in out
    assert subprocess.run(["git", "log", "--format=%H"], cwd=xproj, capture_output=True, text=True).stdout == before


def test_a_channel_switch_prints_then_installs_and_records(cli, xproj, monkeypatch):
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[[channel]]\nname = "bio-steward"\nstable = "git+https://example.org/public.git"\n'
                'dev = "git+ssh://git@example.org/private.git"\n')
    code, out, _ = cli("channel", "use", "bio-steward", "stable", "--tag", "v1.0.0")
    assert code == 0 and "uv tool install --force 'bio-steward @ git+https://example.org/public.git@v1.0.0'" in out
    assert "printed only" in out
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (calls.append(cmd), subprocess.CompletedProcess(cmd, 0))[1])
    code, out, _ = cli("channel", "use", "bio-steward", "dev", "--yes")
    assert code == 0 and calls and "now on dev" in out
    monkeypatch.undo()  # (this also undoes the fixture's chdir: name the repository)
    _, out, _ = cli("channel", "status", "--repo", xproj)
    assert "bio-steward: dev" in out


@pytest.mark.parametrize("text,expected", [
    ("Fixed (ABC-FB-018, ABC-FB-019).", "Fixed."),
    ("Shipped ABC-REQ-020 and more.", "Shipped and more."),
    ("No IDs here.", "No IDs here."),
])
def test_redaction(text, expected):
    from steward.publish import redact
    assert redact(text)[0] == expected
