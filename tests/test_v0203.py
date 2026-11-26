"""0.20.3: going public with a release mirror (STW-044) and a public-ready export (STW-043)."""

import os
import subprocess
from pathlib import Path

import pytest

from test_v0120_features import gsh, xproj  # noqa: F401
from test_v0190_publish import _dev

REPO = Path(__file__).parents[1]


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    log = tmp_path / "gh.log"
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "gh").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\ncase "$2" in view) echo "not found" >&2; exit 1;; esac\n')
    (bin_ / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    return log


def test_go_public_lays_out_the_plan_and_changes_nothing(cli, xproj, tmp_path, fake_gh):
    _dev(xproj, tmp_path)
    gsh(xproj, "git", "remote", "add", "origin", "https://github.com/acme/widget.git")
    code, out, err = cli("release", "go-public", "--owner", "acme", "--name", "widget")
    assert code == 0, out + err
    assert "nothing to fix" in out and "gh repo rename widget-dev --repo acme/widget" in out
    assert out.index("rename") < out.index("point origin") < out.index("create the release repository") < out.index("publish v1.0.0")
    assert not fake_gh.exists()  # nothing was run
    assert "widget.git" in subprocess.run(["git", "remote", "get-url", "origin"], cwd=xproj, capture_output=True,
                                          text=True).stdout


def test_go_public_applies_in_order_and_publishes(cli, xproj, tmp_path, fake_gh):
    pub = _dev(xproj, tmp_path)
    gsh(xproj, "git", "remote", "add", "origin", "https://github.com/acme/widget.git")
    code, out, err = cli("release", "go-public", "--owner", "acme", "--name", "widget", "--apply")
    assert code == 0, out + err
    calls = [c for c in fake_gh.read_text().splitlines() if not c.startswith(("auth status", "repo view"))]  # checks
    assert calls[0].startswith("repo rename widget-dev --repo acme/widget") and calls[1].startswith("repo create acme/widget --private")
    assert "gh repo edit acme/widget --visibility public" in out  # private first: the owner looks, then publishes
    assert "widget-dev.git" in subprocess.run(["git", "remote", "get-url", "origin"], cwd=xproj, capture_output=True,
                                              text=True).stdout
    assert "v1.0.0" in subprocess.run(["git", "tag", "--list"], cwd=pub, capture_output=True, text=True).stdout


def test_go_public_refuses_to_apply_while_anything_would_leak(cli, xproj, tmp_path, fake_gh):
    _dev(xproj, tmp_path, 'private_codes = ["BBB"]\n')
    (xproj / "src/notes.py").write_text("# from BBB-REQ-007\n")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "x")
    gsh(xproj, "git", "tag", "-f", "-a", "v1.0.0", "-m", "v1.0.0")
    gsh(xproj, "git", "remote", "add", "origin", "https://github.com/acme/widget.git")
    code, out, err = cli("release", "go-public", "--owner", "acme", "--name", "widget", "--apply")
    assert code == 65 and "private item IDs (1)" in out and "not applied" in err and not fake_gh.exists()


@pytest.mark.parametrize("args", [["--owner", "acme", "--name", "w;rm"], ["--owner", "acme", "--name", "w", "--dev-name", "w"]])
def test_go_public_refuses_odd_names(cli, xproj, args):
    assert cli("release", "go-public", *args)[0] == 64


def test_the_public_export_names_no_adopter(tmp_path):
    """AR1: every file the public export holds, against this project's own exchange codes and adopter names (read at
    run time from its private records, so this test names none of them)."""
    import re
    import tomllib

    from steward import publish as pb
    from steward.models import load_config
    cfg = load_config(REPO)
    if cfg.exchange is None or cfg.publish is None:
        pytest.skip("not this repository's own configuration")
    codes = sorted(set(cfg.exchange.consumers) | set(cfg.exchange.peers))
    adoption = REPO / "development/ADOPTION.md"
    names = re.findall(r"^- \*\*([^*(]+?)\s*\(", adoption.read_text()) if adoption.is_file() else []
    files = pb.export(REPO, "HEAD", pb.settings(cfg), pb.private_paths(cfg))
    code_rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(map(re.escape, codes)) + r")(?![A-Za-z0-9])") if codes else None
    name_rxs = [re.compile(r"[\W_]*".join(map(re.escape, re.sub(r"[^A-Za-z0-9]", "", n))), re.I) for n in names]
    hits = []
    for rel, data in files.items():
        if rel.endswith((".gz", ".pdf", ".png", ".svg")) or rel == "CHANGELOG.md":  # the changelog is redacted on export
            continue
        text = data.decode("utf-8", "replace")
        if (code_rx and code_rx.search(text)) or any(r.search(text) for r in name_rxs):
            hits.append(rel)
    assert hits == [], hits
    _ = tomllib


def test_go_public_can_create_it_public_at_once(cli, xproj, tmp_path, fake_gh):
    _dev(xproj, tmp_path)
    gsh(xproj, "git", "remote", "add", "origin", "https://github.com/acme/widget.git")
    code, out, err = cli("release", "go-public", "--owner", "acme", "--name", "widget", "--apply", "--public")
    assert code == 0, out + err
    assert "repo create acme/widget --public" in fake_gh.read_text() and "is public with v1.0.0" in out


# ---------------------------------------------------------------- STW-045 (Gemini re-verification of 0.20.3): AR1 – AR4
def _ready(xproj, tmp_path, publish_extra="", origin="https://github.com/acme/widget.git"):
    pub = _dev(xproj, tmp_path, publish_extra)
    gsh(xproj, "git", "remote", "add", "origin", origin)
    return pub


def test_AR2_a_publish_table_without_remote_gets_it_first(cli, xproj, tmp_path, fake_gh):
    _ready(xproj, tmp_path)
    t = (xproj / "steward.toml").read_text()
    import re as _re
    (xproj / "steward.toml").write_text(_re.sub(r'^remote = ".*"\n', "", t, flags=_re.M))
    code, out, err = cli("release", "go-public", "--owner", "acme", "--name", "widget")
    assert out.index("record [publish] remote") < out.index("rename the development")
    import tomllib
    assert "remote" not in tomllib.loads((xproj / "steward.toml").read_text())["publish"]  # nothing written yet
    from steward import golive as gl
    gl.record_remote(xproj, "https://github.com/acme/widget.git")
    assert tomllib.loads((xproj / "steward.toml").read_text())["publish"]["remote"] == "https://github.com/acme/widget.git"


@pytest.mark.parametrize("case", ["mismatch", "semver", "nogh"])
def test_AR3_refused_before_anything_changes(cli, xproj, tmp_path, fake_gh, monkeypatch, case):
    _ready(xproj, tmp_path)
    tag = "v1.0.0"
    if case == "mismatch":
        t = (xproj / "steward.toml").read_text()
        import re as _re
        (xproj / "steward.toml").write_text(_re.sub(r'^remote = ".*"$', 'remote = "https://github.com/acme/other.git"',
                                                    t, flags=_re.M))
    elif case == "semver":
        gsh(xproj, "git", "tag", "-a", "v-not-semver", "-m", "x")
        tag = "v-not-semver"
    else:
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
    code, out, err = cli("release", "go-public", "--owner", "acme", "--name", "widget", "--tag", tag, "--apply")
    assert code == 65 and "not applied" in err, (out, err)
    assert not fake_gh.exists()
    assert "acme/widget.git" in subprocess.run(["git", "remote", "get-url", "origin"], cwd=xproj, capture_output=True,
                                               text=True).stdout


def test_AR3_an_ssh_origin_stays_ssh(cli, xproj, tmp_path, fake_gh):
    _ready(xproj, tmp_path, origin="git@github.com:acme/widget.git")  # scrub: allow (an SSH URL, not an address)
    code, out, err = cli("release", "go-public", "--owner", "acme", "--name", "widget")
    assert "git remote set-url origin git@github.com:acme/widget-dev.git" in out  # scrub: allow (an SSH URL, not an address)


def test_AR4_the_plan_is_quoted_and_a_missing_author_is_not_ready(cli, xproj, tmp_path, fake_gh):
    _ready(xproj, tmp_path)
    _, out, _ = cli("release", "go-public", "--owner", "acme", "--name", "widget")
    assert "--description 'widget: released versions" in out or "--description '" in out
    t = (xproj / "steward.toml").read_text()
    import re as _re
    (xproj / "steward.toml").write_text(_re.sub(r'^author = ".*"\n', "", t, flags=_re.M))
    code, out, _ = cli("release", "go-public", "--owner", "acme", "--name", "widget")
    assert code == 65 and "[publish] author" in out
