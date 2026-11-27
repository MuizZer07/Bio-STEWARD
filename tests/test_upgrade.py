"""W07 release discovery and terminal confirmation, using local fixtures and mocked installers."""

import io
import json
import socket
from datetime import date
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from steward import exchange, upgrade
from steward.fsutil import canonical_json
from steward.models import Channel
from steward.status import EXIT_DATAERR, EXIT_FAIL, EXIT_USAGE

from test_interface import machine_example  # noqa: F401
from test_interface_w02 import _check_golden, _valid


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def unexpected(*args, **kwargs):
        pytest.fail("unexpected installer or network access")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(socket, "create_connection", unexpected)
    monkeypatch.setattr(upgrade, "urlopen", unexpected)
    # Use a module-local substitute to leave other uses of subprocess alone.
    monkeypatch.setattr(upgrade, "subprocess", SimpleNamespace(run=unexpected))
    monkeypatch.setattr(upgrade, "__version__", "1.2.0")


def mock_install(monkeypatch, prefix, kind, direct=None):
    if kind == "uv-tool":
        (prefix / "uv-receipt.toml").touch()
    if kind == "pipx":
        (prefix / "pipx_metadata.json").touch()
    metadata = {"INSTALLER": "pip" if kind == "pip" else "uv", "direct_url.json": json.dumps(direct or {})}
    dist = SimpleNamespace(version="1.2.0", read_text=metadata.get)
    monkeypatch.setattr(upgrade, "distribution", lambda name: dist)
    monkeypatch.setattr(upgrade, "sys", SimpleNamespace(prefix=str(prefix), executable="fixture-python"))


@pytest.mark.parametrize(("method", "command"), [
    ("uv-tool", ["uv", "tool", "install", "--no-config", "--force"]),  # W12 F4: no project uv.toml or pyproject.toml
    ("pipx", ["pipx", "install", "--force"]),
    ("pip", ["fixture-python", "-P", "-m", "pip", "install", "--force-reinstall"]),  # W12 F4: no cwd on sys.path
])
def test_detect_installers(monkeypatch, tmp_path, method, command):
    mock_install(monkeypatch, tmp_path, method)
    install = upgrade.detect_installation(None)
    assert install.method == method
    assert install.argv(upgrade.parse_version("1.3.0"), None) == command + ["bio-steward==1.3.0"]


@pytest.mark.parametrize("which", ["stable", "dev"])
def test_detect_matching_channel(monkeypatch, tmp_path, which):
    channel = Channel(name="Bio_Steward", stable="git+https://example.invalid/stable.git",
                      dev="git+ssh://git@example.invalid/dev.git", installer="pip")
    source = getattr(channel, which)
    mock_install(monkeypatch, tmp_path, "pip", {"url": source.removeprefix("git+"), "vcs_info": {"vcs": "git"}})
    other = channel.model_copy(update={"installer": "pipx"})
    assert upgrade.detect_installation(SimpleNamespace(channel=[other])).method == "pip"
    install = upgrade.detect_installation(SimpleNamespace(channel=[channel]))
    assert (install.method, install.channel) == ("channel", which)
    assert install.argv(upgrade.parse_version("1.3.0"), "1.3.0")[-1] == f"bio-steward @ {source}@1.3.0"


def test_editable_install_is_unknown(monkeypatch, tmp_path):
    mock_install(monkeypatch, tmp_path, "pip", {"dir_info": {"editable": True}})
    assert upgrade.detect_installation(None).method == "unknown"


def notice(root, number, version, sender="STW"):
    (root / "exchange/inbox").mkdir(parents=True, exist_ok=True)
    data = exchange.render({
        "schema": "steward.exchange/1", "id": f"{sender}-REL-{number:03}", "kind": "release", "from": sender,
        "to": "DEMO", "filed": date(2026, 11, 27), "title": f"Release {version}", "version": version, "tag": version,
    }, "Release notes.\n").encode()
    exchange.receive(root, "fixture", "DEMO", data, {"from": "file"})


def check(cli, *args):
    code, out, err = cli("upgrade", "--check", "--format", "json", *args)
    assert code == 0, err
    doc = _valid(json.loads(out))
    assert out == canonical_json(doc)
    return doc


def test_offline_json_goldens(cli, machine_example, monkeypatch):
    name, root = machine_example
    monkeypatch.setattr(upgrade, "detect_installation", lambda cfg: upgrade.Installation("uv-tool"))
    assert check(cli, "--repo", root)["latest_version"] is None
    notice(root, 1, "1.10.0")
    notice(root, 2, "1.10.0rc1")
    notice(root, 3, "1.9.0")
    notice(root, 4, "99.0", sender="PEER")
    notice(root, 5, "invalid")
    doc = check(cli, "--repo", root)
    assert doc["latest_version"] == "1.10.0"
    _check_golden(f"{name}.w07.json", doc)


@pytest.mark.parametrize("failure", [False, True])
def test_online_pypi(cli, monkeypatch, machine_example, failure):
    _, root = machine_example
    notice(root, 1, "1.3.0")
    monkeypatch.setattr(upgrade, "detect_installation", lambda cfg: upgrade.Installation("pipx"))
    calls = []

    def request(url, timeout):
        calls.append((url, timeout))
        if failure:
            raise URLError("unreachable")
        return io.BytesIO(b'{"info":{"version":"2.0.0"}}')

    monkeypatch.setattr(upgrade, "urlopen", request)
    doc = check(cli, "--online", "--repo", root)
    assert calls == [(upgrade.PYPI_URL, 5)]
    assert doc["latest_version"] == ("1.3.0" if failure else "2.0.0")
    assert doc["source"] == ("exchange" if failure else "pypi")
    assert bool(doc["note"]) == failure


def test_check_outside_project(cli, monkeypatch):
    monkeypatch.setattr(upgrade, "detect_installation", lambda cfg: upgrade.Installation())
    doc = check(cli)
    assert doc["installed_version"] == "1.2.0"
    assert doc["install_method"] == "unknown"
    assert doc["latest_version"] is doc["source"] is doc["command"] is None
    assert doc["upgrade_available"] is False


def test_channel_check_and_confirm_use_the_same_notice_tag(cli, machine_example, monkeypatch, capsys):
    _, root = machine_example
    notice(root, 1, "1.3.0")
    source = "git+https://example.invalid/stable.git"
    monkeypatch.setattr(upgrade, "detect_installation", lambda cfg: upgrade.Installation("uv-tool", source, "stable"))
    doc = check(cli, "--repo", root)
    assert doc["install_method"] == "channel" and doc["channel"] == "stable"
    assert doc["command"][-1] == f"bio-steward @ {source}@1.3.0"

    monkeypatch.setattr(upgrade, "_interactive_terminal", lambda: True)

    def confirm(prompt):
        assert f"{source}@1.3.0" in capsys.readouterr().out
        return "y"

    def install(argv, cwd=None):  # W12 F4: run from an empty temporary folder
        assert argv == doc["command"] and cwd is not None
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("builtins.input", confirm)
    monkeypatch.setattr(upgrade.subprocess, "run", install)
    code, _, err = cli("upgrade", "--to", doc["latest_version"], "--repo", root)
    assert code == 0, err


@pytest.fixture
def install_prompt(monkeypatch):
    monkeypatch.setattr(upgrade, "detect_installation", lambda cfg: upgrade.Installation("pipx"))


def test_to_requires_interactive_terminal(cli, install_prompt, monkeypatch):
    monkeypatch.setattr(upgrade.sys.stdin, "isatty", lambda: False)
    code, out, err = cli("upgrade", "--to", "1.3.0")
    assert code == EXIT_USAGE and not out and "interactive terminal" in err


@pytest.mark.parametrize("answer", ["", "n", None])
def test_to_decline_or_eof(cli, install_prompt, monkeypatch, answer):
    monkeypatch.setattr(upgrade, "_interactive_terminal", lambda: True)
    def confirm(prompt):
        assert "1.3.0" in prompt
        if answer is None:
            raise EOFError
        return answer

    monkeypatch.setattr("builtins.input", confirm)
    code, out, err = cli("upgrade", "--to", "1.3.0")
    assert code == EXIT_FAIL and "bio-steward==1.3.0" in out and "cancelled" in err


@pytest.mark.parametrize(("version", "extra", "exit_code"), [
    ("1.3.0", [], 0), ("1.1.0", ["--allow-downgrade"], 0), ("1.1.0", [], EXIT_DATAERR),
    ("latest", [], EXIT_USAGE), ("1.3.0", ["--online"], EXIT_USAGE),
])
def test_to_validates_version_and_runs_only_after_yes(cli, install_prompt, monkeypatch, capsys,
                                                       version, extra, exit_code):
    monkeypatch.setattr(upgrade, "_interactive_terminal", lambda: True)
    events = []
    argv = ["pipx", "install", "--force", f"bio-steward=={version}"]

    def confirm(prompt):
        assert " ".join(argv) in capsys.readouterr().out
        events.append("confirmed")
        return "YES"

    def install(command, cwd=None):
        events.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("builtins.input", confirm)
    monkeypatch.setattr(upgrade.subprocess, "run", install)
    code, _, _ = cli("upgrade", "--to", version, *extra)
    assert code == exit_code
    assert events == ([] if exit_code else ["confirmed", argv])


def test_installer_failure(cli, install_prompt, monkeypatch):
    monkeypatch.setattr(upgrade, "_interactive_terminal", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    monkeypatch.setattr(upgrade.subprocess, "run", lambda argv, cwd=None: SimpleNamespace(returncode=12))
    code, _, err = cli("upgrade", "--to", "1.3.0")
    assert code == EXIT_DATAERR and "status 12" in err
