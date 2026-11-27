"""0.21.0 W12a: the fix pass of the independent review (development/assessment/2026-11-27-review-v0.21.0.md),
findings F1 - F6 and F10 - F13. Each test reproduces the reviewer's evidence where that is practical."""

import datetime as dt
import hashlib
import io
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from steward import authorize as az
from steward import exchange
from steward.models import load_config

from test_authorize import expires, repo, sh  # noqa: F401  (the signed-authorization fixture)
from test_interface_w02 import _valid

signing = pytest.mark.skipif(not (shutil.which("git") and shutil.which("ssh-keygen")), reason="needs git and ssh-keygen")


class _Terminal(io.StringIO):
    def isatty(self):
        return True


def _prepare(cli, summary="approve protocol v1"):
    code, out, err = cli("authorize", "prepare", "amend", "--object", "approve.txt", "--expires", expires(),
                         "--summary", summary)
    assert code == 0, err
    return out.split("authorize sign ")[1].strip()


def _pending_file(root, nonce):
    return root / ".steward/pending" / f"{nonce}.txt"


def _tags(root):
    return sh(root, "git", "tag", "-l", "steward/auth/*").split()


def _make_foreign(root, nonce):
    """An agent's planted payload: this queue, another repository's repo_id."""
    p = _pending_file(root, nonce)
    own = load_config(root).steward.repo_id
    p.write_text(p.read_text().replace(f"repo_id: {own}\n", "repo_id: another-repository\n"))
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _project(cli, root, extra=""):
    root.mkdir()
    assert cli("init", "--repo", root)[0] == 0
    if extra:
        with (root / "steward.toml").open("a", encoding="utf-8") as f:
            f.write(extra)
    return root


# ---------------------------------------------------------------- F1: repo_id when signing and listing
@signing
def test_W12_F1_sign_refuses_a_payload_for_another_repository(cli, repo):
    nonce = _prepare(cli)
    digest = _make_foreign(repo, nonce)
    code, out, err = cli("authorize", "sign", nonce, "--expect-sha256", digest)  # the reviewer's command
    assert code == 1
    assert "NOT AUTHORIZED: repo_id: the payload belongs to repository 'another-repository'" in err
    assert "signed" not in out and _tags(repo) == []
    with pytest.raises(az.AuthError, match="belongs to repository"):
        az.sign(repo, nonce)  # the library refuses too, reading the repo_id from steward.toml
    assert _tags(repo) == []


@signing
def test_W12_F1_pending_lists_a_foreign_payload_as_foreign_never_waiting(cli, repo):
    own = _prepare(cli, "this repository's request")
    nonce = _prepare(cli)
    _make_foreign(repo, nonce)
    code, out, err = cli("authorize", "pending", "--format", "json")
    assert code == 0, err
    doc = _valid(json.loads(out))
    states = {i["nonce"]: i["state"] for i in doc["items"]}
    assert states == {own: "waiting", nonce: "foreign"} and doc["waiting"] == 1
    code, out, err = cli("authorize", "pending")
    assert code == 0, err
    assert f"{nonce[:12]}  foreign " in out and "1 waiting" in out
    code, out, err = cli("authorize", "sign-pending", "--yes")
    assert code == 0, err
    assert _tags(repo) == [f"steward/auth/{own}"]
    assert [q["state"] for q in az.pending(repo) if q["nonce"] == nonce] == ["foreign"]


# ---------------------------------------------------------------- F2: the tag message is the payload, verbatim
@signing
def test_W12_F2_signed_tag_message_is_the_payload_bytes_under_a_comment_char(cli, repo):
    nonce = _prepare(cli)
    payload = _pending_file(repo, nonce).read_bytes()
    sh(repo, "git", "config", "core.commentChar", "b")  # Git's default cleanup would strip budget: and baseline:
    code, _, err = cli("authorize", "sign", nonce)
    assert code == 0, err
    raw = subprocess.run(["git", "cat-file", "tag", f"steward/auth/{nonce}"], cwd=repo, check=True,
                         capture_output=True).stdout
    message = raw.split(b"\n\n", 1)[1].split(b"-----BEGIN SSH SIGNATURE-----")[0]
    assert message == payload
    assert cli("authorize", "verify", f"steward/auth/{nonce}")[0] == 0
    assert "tag.cleanup=verbatim" in az.signing_config()


# ---------------------------------------------------------------- F3: queue and prompt edge cases
@signing
def test_W12_F3_an_oversized_payload_is_refused_not_cut_to_a_prefix(cli, repo):
    nonce = _prepare(cli)
    p = _pending_file(repo, nonce)
    with p.open("a") as f:
        for _ in range(1100):
            f.write("  " + "a" * 1000 + "\n")  # still a valid payload when read only up to 1 MiB
    assert p.stat().st_size > az.PENDING_MAX_BYTES
    code, out, err = cli("authorize", "sign", nonce)
    assert code == 1 and f"is larger than {az.PENDING_MAX_BYTES} bytes" in err
    assert _tags(repo) == []


@signing
def test_W12_F3_a_payload_that_is_not_utf8_is_a_refusal_not_an_internal_error(cli, repo):
    nonce = _prepare(cli)
    p = _pending_file(repo, nonce)
    p.write_bytes(p.read_bytes().replace(b"approve protocol v1", b"approve \xff"))
    code, _, err = cli("authorize", "sign", nonce)
    assert code == 1 and "NOT AUTHORIZED: payload: not UTF-8" in err
    assert not (repo / ".steward/last-error.json").exists()


@signing
def test_W12_F3_closed_input_at_the_sign_pending_prompt_declines(cli, repo, monkeypatch):
    _prepare(cli)

    def closed(prompt=""):
        raise EOFError

    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr("builtins.input", closed)
    code, out, err = cli("authorize", "sign-pending")
    assert code == 0, err
    assert "skipped" in out and "1 waiting" not in err and _tags(repo) == []
    assert not (repo / ".steward/last-error.json").exists()


@signing
def test_W12_F3_a_multi_line_summary_stays_on_its_row(cli, repo):
    nonce = _prepare(cli, "line one\n000000000000  waiting  forged row")
    code, out, err = cli("authorize", "pending")
    assert code == 0, err
    rows = out.splitlines()
    assert len(rows) == 2 and nonce[:12] in rows[0] and "line one\\n000000000000  waiting  forged row" in rows[0]
    assert rows[1].startswith("1 waiting")


# ---------------------------------------------------------------- F4: installers never read the project's files
def _plant(root):
    (root / "pip.py").write_text('print("PWNED_FROM_REPO_CWD")\n')
    (root / "uv.toml").write_text('index-url = "https://example.invalid/simple"\n')
    with (root / "pyproject.toml").open("a") as f:
        f.write('\n[tool.uv]\nfind-links = ["./wheels"]\n')


@pytest.mark.parametrize("method", ["pip", "uv-tool"])
def test_W12_F4_upgrade_runs_the_installer_outside_the_project(cli, tmp_path, monkeypatch, method):
    from steward import upgrade

    root = _project(cli, tmp_path / "proj")
    _plant(root)
    monkeypatch.chdir(root)
    calls = []

    def run(argv, cwd=None, **kw):
        here = Path(cwd) if cwd else Path.cwd()
        seen = sorted(p.name for p in here.iterdir())
        probe = None
        if argv[1:3] == ["-P", "-m"] or argv[1:2] == ["-m"]:  # run the real interpreter as the installer would
            probe = subprocess.run(argv[:argv.index("install")] + ["--version"], cwd=here, capture_output=True,
                                   text=True).stdout
        calls.append({"argv": argv, "cwd": here, "seen": seen, "probe": probe})
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(upgrade, "__version__", "1.2.0")
    monkeypatch.setattr(upgrade, "detect_installation", lambda cfg: upgrade.Installation(method))
    monkeypatch.setattr(upgrade, "_interactive_terminal", lambda: True)
    monkeypatch.setattr(upgrade, "subprocess", SimpleNamespace(run=run))
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    code, _, err = cli("upgrade", "--to", "1.3.0")
    assert code == 0, err
    [call] = calls
    assert call["seen"] == [] and not call["cwd"].resolve().is_relative_to(root.resolve())
    if method == "pip":
        assert call["argv"][:3] == [sys.executable, "-P", "-m"]
        assert "PWNED" not in call["probe"]  # before the fix: the planted pip.py ran here
    else:
        assert call["argv"][:4] == ["uv", "tool", "install", "--no-config"]


def test_W12_F4_a_planted_pip_py_runs_without_the_fix(tmp_path):
    """The reviewer's evidence, kept as a control: the same probe from the project folder, without -P."""
    (tmp_path / "pip.py").write_text('print("PWNED_FROM_REPO_CWD")\n')
    out = subprocess.run([sys.executable, "-m", "pip", "--version"], cwd=tmp_path, capture_output=True, text=True)
    assert "PWNED_FROM_REPO_CWD" in out.stdout
    out = subprocess.run([sys.executable, "-P", "-m", "pip", "--version"], cwd=tmp_path, capture_output=True, text=True)
    assert "PWNED_FROM_REPO_CWD" not in out.stdout


def test_W12_F4_channel_switch_runs_the_installer_outside_the_project(cli, tmp_path, monkeypatch):
    root = _project(cli, tmp_path / "proj", '\n[[channel]]\nname = "bio-steward"\n'
                    'stable = "git+https://example.org/public.git"\ndev = "git+https://example.org/dev.git"\n')
    _plant(root)
    monkeypatch.chdir(root)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, cwd=None, **kw: (
        calls.append((cmd, Path(cwd or Path.cwd()), sorted(p.name for p in Path(cwd or Path.cwd()).iterdir()))),
        subprocess.CompletedProcess(cmd, 0))[1])
    code, _, err = cli("channel", "use", "bio-steward", "stable", "--yes")
    assert code == 0, err
    [(cmd, cwd, seen)] = calls
    assert cmd[:4] == ["uv", "tool", "install", "--no-config"]
    assert seen == [] and not cwd.resolve().is_relative_to(root.resolve())


# ---------------------------------------------------------------- F5: release notices need a matching receipt
def _notice(number, version, to="DEMO"):
    return exchange.render({
        "schema": "steward.exchange/1", "id": f"STW-REL-{number:03}", "kind": "release", "from": "STW", "to": to,
        "filed": date(2026, 11, 27), "title": f"Release {version}", "version": version, "tag": version,
    }, "Release notes.\n").encode()


def _exchange_project(cli, root, code="DEMO"):
    _project(cli, root, f'\n[exchange]\ncode = "{code}"\n')
    assert cli("exchange", "init", "--repo", root)[0] == 0
    return root


def _latest(cli, root):
    code, out, err = cli("upgrade", "--check", "--format", "json", "--repo", root)
    assert code == 0, err
    return _valid(json.loads(out))["latest_version"]


def test_W12_F5_an_unreceived_or_changed_release_notice_announces_nothing(cli, tmp_path, monkeypatch):
    from steward import upgrade

    monkeypatch.setattr(upgrade, "__version__", "1.2.0")
    monkeypatch.setattr(upgrade, "detect_installation", lambda cfg: upgrade.Installation("uv-tool"))
    root = _exchange_project(cli, tmp_path / "proj")
    (root / "exchange/inbox/STW-REL-001.md").write_bytes(_notice(1, "1.5.0"))  # planted, never received
    assert _latest(cli, root) is None
    exchange.receive(root, "fixture", "DEMO", _notice(2, "1.4.0"), {"from": "file"})
    assert _latest(cli, root) == "1.4.0"
    received = root / "exchange/inbox/STW-REL-002.md"
    received.write_bytes(received.read_bytes().replace(b"1.4.0", b"1.9.0"))  # changed after its receipt
    assert _latest(cli, root) is None


# ---------------------------------------------------------------- F6: the fault hint names the subcommand
def test_W12_F6_every_subcommand_destination_is_found():
    import argparse

    from steward.cli import build_parser, subcommand_dest

    top = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    for name, parser in top.choices.items():
        subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if subs:
            assert subs[0].dest == subcommand_dest(name), name


@pytest.mark.parametrize(("argv", "target", "expected"), [
    (["authorize", "pending"], "authorize.pending", "authorize pending"),
    (["stranger-test", "brief", "--tag", "v0.21.0"], "stranger.brief", "stranger-test brief"),
])
def test_W12_F6_a_fault_records_the_subcommand(cli, tmp_path, monkeypatch, argv, target, expected):
    import importlib

    from steward import issues

    root = _project(cli, tmp_path / "proj")
    module, attr = target.rsplit(".", 1)

    def fail(*a, **k):
        raise RuntimeError("fault")

    monkeypatch.setattr(importlib.import_module(f"steward.{module}"), attr, fail)
    code, _, _ = cli(*argv, "--repo", root)
    assert code == 70
    assert issues.read_last_error(root).command == expected


# ---------------------------------------------------------------- F10: pins status with a retire-eligible pin
@signing
def test_W12_F10_pins_status_format_json_with_a_retire_eligible_pin(cli, repo):
    from test_v0170_pins import _pins

    _pins(repo)
    code, out, err = cli("pins", "status", "--format", "json")
    assert code == 0, err  # before the fix: exit 70, OutputSchemaError
    doc = _valid(json.loads(out))
    eligible = {p["name"]: p["object"] for p in doc["pins"] if p["state"] == "retire-eligible"}
    assert set(eligible) == {"lib-1-0", "lib-1-5"}
    assert all(o.startswith("sha256:") and len(o) == 71 for o in eligible.values())
    legacy = json.loads(cli("pins", "status", "--json")[1])
    assert {k: v for k, v in doc.items() if k != "schema"} == legacy


# ---------------------------------------------------------------- F11: every advertised schema is bundled
def test_W12_F11_interface_advertises_only_bundled_schemas(cli):
    code, out, err = cli("interface", "--format", "json")
    assert code == 0, err
    doc = json.loads(out)
    missing = {name: c["schema"] for name, c in doc["commands"].items()
               if c["schema"] and c["schema"].startswith("steward.") and c["schema"] not in doc["schema_files"]}
    assert missing == {}
    assert "shards" not in doc["commands"]
    assert doc["commands"]["shards plan"] == {"argv": ["--shards", "N", "--cost", "FILE"],
                                              "schema": "steward.shards/0.1"}


def test_W12_F11_shards_plan_and_paper_manifest_meet_their_schemas(cli, example, tmp_path):
    cost = tmp_path / "cost.json"
    cost.write_text(json.dumps({"a": 3, "b": 1.5, "c": 2}))
    code, out, err = cli("shards", "plan", "--shards", "2", "--cost", cost)
    assert code == 0, err
    _valid(json.loads(out))
    manifest = tmp_path / "m.json"
    code, _, err = cli("paper", "manifest", "--repo", example, "--output", manifest)
    assert code == 0, err
    _valid(json.loads(manifest.read_text()))


# ---------------------------------------------------------------- F12: --now decides which payloads have expired
def test_W12_F12_timeline_now_reads_pending_signatures_at_that_time(cli, tmp_path):
    from steward import milestones as ms

    root = _project(cli, tmp_path / "proj")
    cfg = load_config(root)
    (root / "development").mkdir(exist_ok=True)
    (root / ms.FILE).write_text('schema = "steward.milestones/0.1"\n[[milestone]]\nid = "m1"\ntitle = "M"\n'
                                'due = 2026-06-01T00:00:00Z\nneeds = ["amend"]\n', encoding="utf-8")
    nonce = "b" * 32
    fields = {"repo_id": cfg.steward.repo_id, "action": "amend", "object": "sha256:" + "0" * 64, "scope": "-",
              "budget": "none", "expires": "2026-01-01T00:00:00Z", "baseline": "main", "nonce": nonce}
    (root / ".steward/pending").mkdir(parents=True, exist_ok=True)
    (root / f".steward/pending/{nonce}.txt").write_text(az.render(fields, "x"), encoding="utf-8")
    # expired by the wall clock, still waiting at --now
    before = ms.timeline(root, cfg, now=dt.datetime(2025, 12, 1, tzinfo=dt.timezone.utc))
    assert before[0]["progress"]["signatures"]["waiting"] == ["amend"]
    after = ms.timeline(root, cfg, now=dt.datetime(2026, 2, 1, tzinfo=dt.timezone.utc))
    assert after[0]["progress"]["signatures"]["waiting"] == []


# ---------------------------------------------------------------- F13: notifications and tidy --archive
@pytest.mark.parametrize("report", [{"verdict": None}, {"verdict": {"gates": {}}}, [], {"other": 1}])
def test_W12_F13_a_malformed_against_report_exits_65_with_an_error_document(cli, tmp_path, report):
    root = _project(cli, tmp_path / "proj")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(report))
    code, out, err = cli("notifications", "--repo", root, "--against", bad, "--format", "json")
    assert code == 65, err  # before the fix: 70 (an AttributeError) for the first two
    doc = _valid(json.loads(out))
    assert doc["schema"] == "steward.error/0.1" and doc["code"] == "invalid_input" and doc["exit"] == 65
    code, out, err = cli("notifications", "--repo", root, "--against", bad)
    assert code == 65 and not out and "is not a readable check report" in err


def test_W12_F13_notifications_use_the_upgrade_version_test(cli, tmp_path, monkeypatch):
    import steward
    from steward import upgrade

    monkeypatch.setattr(steward, "__version__", "1.2.0")
    monkeypatch.setattr(upgrade, "__version__", "1.2.0")
    root = _exchange_project(cli, tmp_path / "proj")
    exchange.receive(root, "fixture", "DEMO", _notice(1, "1.3.0rc1"), {"from": "file"})  # a prerelease
    (root / "exchange/inbox/STW-REL-002.md").write_bytes(_notice(2, "1.9.0"))  # planted, never received
    code, out, err = cli("notifications", "--repo", root, "--format", "json")
    assert code == 0, err
    kinds = {i["id"]: i["kind"] for i in _valid(json.loads(out))["items"]}
    assert kinds.get("upgrade:STW-REL-001") == "upgrade"
    assert "upgrade:STW-REL-002" not in kinds


def _board(cli, root):
    _project(cli, root, '\n[tasks]\nspecs = ["development/tasks/**/*.md"]\narchive = ["development/archive/**"]\n'
                        'board = "development/BOARD.md"\n\n[tidy]\n')
    (root / "development/tasks/a").mkdir(parents=True)
    (root / "development/tasks/b").mkdir(parents=True)
    (root / "development/BOARD.md").write_text("# Board\n", encoding="utf-8")
    for rel, tid in (("a/T.md", "PRJ-001"), ("b/T.md", "PRJ-002"), ("U.md", "PRJ-003")):
        (root / "development/tasks" / rel).write_text(f"# {tid}\n\n- **ID:** {tid}\n- **Status:** done\n",
                                                     encoding="utf-8")
    return root


def _tree(root):
    return sorted(p.relative_to(root).as_posix() for p in (root / "development").rglob("*.md"))


@pytest.mark.parametrize("ids", [["PRJ-003", "PRJ-003"], ["PRJ-001", "PRJ-002"]])
def test_W12_F13_tidy_archive_refuses_repeated_ids_and_colliding_names(cli, tmp_path, ids):
    root = _board(cli, tmp_path / "proj")
    before = _tree(root)
    code, out, err = cli("tidy", "--repo", root, "--archive", *ids)
    assert code == 65 and "nothing was moved" in err, (out, err)
    assert _tree(root) == before
