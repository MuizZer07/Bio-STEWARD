"""v0.8 optional MCP server (RELEASE_v0.8_SPEC §3): protocol round trip, read-only tool surface, CLI parity."""

import json
import subprocess
import sys

import pytest

from conftest import CONTRACT

FORBIDDEN = ("sign", "prepare", "authorize_verify", "consume", "pin", "approve", "freeze", "amend", "seal", "unseal",
             "waive", "spend_check", "spend_record", "reserve", "run_", "submit", "execute", "write", "record", "init",
             "hooks", "install", "delete", "recover", "anchor", "manifest", "export", "set", "merge", "go")
EXPECTED = {"check", "report_rule", "diff_run", "diff_impact", "benchmark_splits", "benchmark_results", "storage_verify",
            "storage_audit", "integrity_status", "spend_status", "runs"}


def session(root, *messages):
    """Run `steward mcp` over pipes; return the decoded replies."""
    text = "".join(json.dumps(m) + "\n" if not isinstance(m, str) else m + "\n" for m in messages)
    p = subprocess.run([sys.executable, "-m", "steward.cli", "mcp", "--repo", str(root)], input=text,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return [json.loads(line) for line in p.stdout.splitlines()]


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def call(i, name, **arguments):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


def test_round_trip_and_read_only_surface(example):
    replies = session(example, INIT, INITIALIZED, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                      {"jsonrpc": "2.0", "id": 3, "method": "ping"})
    assert [r["id"] for r in replies] == [1, 2, 3]  # the notification is not answered
    init = replies[0]["result"]
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"]
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert names == EXPECTED
    for n in names:
        assert not any(f in n for f in FORBIDDEN if f != "run_") or n in ("diff_run",), n
        assert not n.startswith("run_") and n != "run"
    for t in replies[1]["result"]["tools"]:
        assert t["inputSchema"]["type"] == "object" and t["description"]


def test_check_matches_the_cli(cli, example):
    replies = session(example, INIT, call(2, "check"))
    via_mcp = json.loads(replies[1]["result"]["structuredContent"]["stdout"])
    _, rep = cli.check(example)
    assert via_mcp["verdict"] == rep["verdict"]
    assert replies[1]["result"]["isError"] is False


def test_report_rule_and_benchmark_tools(example):
    replies = session(example, INIT, call(2, "report_rule", rule="R-45"), call(3, "benchmark_splits", contract=CONTRACT))
    rs = json.loads(replies[1]["result"]["structuredContent"]["stdout"])
    assert rs and all(r["rule"] == "R-45" for r in rs)
    splits = json.loads(replies[2]["result"]["structuredContent"]["stdout"])
    assert splits["counts"]["test"] == 24


@pytest.mark.parametrize("arguments", [{"contract": "../outside.toml"}, {"contract": "/etc/passwd"}, {"contract": "--json"}])
def test_paths_outside_the_repository_are_refused(example, arguments):
    r = session(example, INIT, call(2, "benchmark_splits", **arguments))[1]["result"]
    assert r["isError"] is True and "repository" in r["content"][0]["text"]


def test_arguments_are_validated(example):
    replies = session(example, INIT, call(2, "check", areas=["nope"]), call(3, "check", extra=1),
                      call(4, "diff_run", a="x; rm -rf /", b="y"), call(5, "unknown_tool"))
    assert all(r["result"]["isError"] for r in replies[1:])


def test_protocol_errors_never_crash_the_server(example):
    replies = session(example, "{not json", {"jsonrpc": "2.0", "id": 7, "method": "resources/list"}, INIT)
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["error"]["code"] == -32601 and replies[1]["id"] == 7
    assert replies[2]["result"]["serverInfo"]["name"] == "bio-steward"


def test_no_cli_path_through_the_server_writes_files(example):
    from conftest import EXAMPLE  # noqa: F401
    before = sorted((p.relative_to(example).as_posix(), p.stat().st_mtime_ns) for p in example.rglob("*") if p.is_file())
    session(example, INIT, *[call(i, n) for i, n in enumerate(["check", "diff_impact", "storage_verify", "storage_audit",
                                                               "integrity_status", "spend_status", "runs"], 2)])
    after = sorted((p.relative_to(example).as_posix(), p.stat().st_mtime_ns) for p in example.rglob("*") if p.is_file())
    assert before == after


# ---------------------------------------------------------------- v0.8 review: K1, K6, K11
@pytest.fixture
def gitrepo(example):
    import shutil
    if not shutil.which("git"):
        pytest.skip("needs git")
    run = lambda *a: subprocess.run(a, cwd=example, check=True, capture_output=True)  # noqa: E731
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.name", "T")
    run("git", "config", "user.email", "t@example.org")
    run("git", "add", "-A", "-f")
    run("git", "commit", "-qm", "x")
    return example


def test_K1_check_runs_no_repository_selected_program_and_writes_no_index(gitrepo, tmp_path):
    import os
    import time
    marker = tmp_path / "fsmonitor-ran"
    hook = tmp_path / "fsmonitor.sh"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    hook.chmod(0o755)
    subprocess.run(["git", "config", "core.fsmonitor", str(hook)], cwd=gitrepo, check=True)
    tracked = gitrepo / "steward.toml"
    t = time.time() + 5
    os.utime(tracked, (t, t))  # a stat change git would refresh into the index
    index = (gitrepo / ".git/index").read_bytes()
    replies = session(gitrepo, INIT, call(2, "check", areas=["config"]), call(3, "report_rule", rule="R-01"))
    assert all(not r["result"]["isError"] for r in replies[1:])
    assert not marker.exists(), "a repository-configured program ran"
    assert (gitrepo / ".git/index").read_bytes() == index, "the git index was written"


def test_K1_the_server_offers_no_signature_tooling():
    from steward.mcp import Server
    from conftest import EXAMPLE
    assert "authorize_list" not in Server(EXAMPLE).tools


def test_K6_oversized_and_undecodable_frames_are_refused_and_the_session_continues(example):
    from steward.mcp import MAX_FRAME
    big = json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {"x": "a" * (MAX_FRAME + 10)}})
    deep = "[" * 100000 + "]" * 100000
    payload = (big + "\n").encode() + b"\xff\xfe not utf-8\n" + (deep + "\n").encode() + (json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}) + "\n").encode()
    p = subprocess.run([sys.executable, "-m", "steward.cli", "mcp", "--repo", str(example)], input=payload,
                       capture_output=True, timeout=120)
    lines = [json.loads(l) for l in p.stdout.decode().splitlines()]
    assert p.returncode == 0 and [l.get("error", {}).get("code") for l in lines[:3]] == [-32600, -32700, -32700]
    assert lines[3] == {"jsonrpc": "2.0", "id": 3, "result": {}}


def test_K11_arguments_and_ids_follow_the_schemas(example):
    replies = session(example, INIT, call(2, "runs", limit=True), call(3, "check", final="yes"),
                      {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "check", "arguments": []}},
                      {"jsonrpc": "2.0", "id": {"x": 1}, "method": "ping"}, call(6, "report_rule", rule="R-99"))
    assert all(r["result"]["isError"] for r in replies[1:4])
    assert replies[4]["error"]["code"] == -32600
    assert replies[5]["result"]["isError"] is True and "unknown rule" in replies[5]["result"]["content"][0]["text"]


def test_K11_tolerances_accept_what_the_cli_accepts():
    from steward.mcp import TOL
    assert TOL.fullmatch("/a=b=abs:1") and TOL.fullmatch("=rel:0.1") and not TOL.fullmatch("--x=abs:1")


# ---------------------------------------------------------------- re-verification of 74e9cba: L1 - L3
def test_L1_no_check_route_runs_a_repository_clean_filter(cli, gitrepo, tmp_path):
    import os
    import time
    marker = tmp_path / "filter-ran"
    filt = tmp_path / "clean.sh"
    filt.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    filt.chmod(0o755)
    (gitrepo / ".gitattributes").write_text("* filter=evil\n")
    subprocess.run(["git", "config", "filter.evil.clean", str(filt)], cwd=gitrepo, check=True)
    t = time.time() + 5
    for p in gitrepo.rglob("*.toml"):
        os.utime(p, (t, t))
    index = (gitrepo / ".git/index").read_bytes()
    session(gitrepo, INIT, call(2, "check", areas=["config"]), call(3, "report_rule", rule="R-01"))
    _, out, _ = cli("check", "--repo", gitrepo, "--format", "json", "config")
    assert not marker.exists(), "a repository-configured clean filter ran"
    assert (gitrepo / ".git/index").read_bytes() == index
    assert json.loads(out)["envelope"]["git"]["dirty"] == "not checked"


def test_L2_the_server_never_verifies_signatures(example, monkeypatch):
    import tempfile
    from steward import authorize as az
    from steward.mcp import Server
    Server(example)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", lambda *a, **k: (_ for _ in ()).throw(AssertionError("temp files")))
    with pytest.raises(az.AuthError) as e:
        az.verify_ssh_tag(example, "steward/auth/x", b"")
    assert "MCP" in e.value.message
    monkeypatch.setattr(az, "READ_ONLY", False)


def test_L3_transport_is_denied_whatever_the_git_version_or_repository_config():
    from steward import fsutil
    env = fsutil.git_env()
    assert env["GIT_ALLOW_PROTOCOL"] == ""  # M3: an empty allow-list permits no protocol, not even a custom helper
    cfg = " ".join(fsutil.SAFE_GIT_CONFIG)
    for proto in ("file", "git", "ssh", "http", "https", "ext"):
        assert f"protocol.{proto}.allow=never" in cfg, proto
