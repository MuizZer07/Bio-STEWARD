"""Check for toolkit versions and run an explicitly confirmed upgrade."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from argparse import Namespace
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Literal, NamedTuple
from urllib.parse import urlsplit
from urllib.request import urlopen

from . import __version__
from .cockpit import TOOLKIT_CODE, _inbox
from .fsutil import find_root
from .interface import OTHER_SCHEMAS, write_document
from .models import StewardConfig, load_config
from .publish import installer_command, run_installer
from .status import EXIT_DATAERR, EXIT_FAIL, EXIT_OK, EXIT_USAGE, NotConfigured

PACKAGE = "bio-steward"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
Installer = Literal["uv-tool", "pipx", "pip"]
VERSION = re.compile(r"v?((?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2})(?:(\.dev|a|b|rc|\.post)(0|[1-9][0-9]*))?")
STAGES = (".dev", "a", "b", "rc", None, ".post")


class Version(NamedTuple):
    key: tuple[tuple[int, ...], int, int]
    text: str

    def __str__(self) -> str:
        return self.text


def parse_version(text: str) -> Version:
    """Compare toolkit release versions, including Python prerelease and development suffixes."""
    match = VERSION.fullmatch(text)
    if match is None:
        raise ValueError("invalid toolkit version")
    release, stage, sequence = match.groups()
    return Version((tuple(map(int, release.split("."))), STAGES.index(stage), int(sequence or 0)),
                   text.removeprefix("v"))


@dataclass(frozen=True)
class Installation:
    installer: Installer | None = None
    git_source: str | None = None
    channel: Literal["stable", "dev"] | None = None

    @property
    def method(self) -> str:
        return "channel" if self.channel else self.installer or "unknown"

    def argv(self, version: Version, tag: str | None) -> list[str] | None:
        if self.installer is None:
            return None
        spec = (f"{PACKAGE} @ {self.git_source}@{tag or f'v{version}'}" if self.git_source
                else f"{PACKAGE}=={version}")
        return installer_command(self.installer, spec, python=sys.executable)


def _git_source(direct: dict) -> str | None:
    vcs = direct.get("vcs_info")
    url = direct.get("url")
    if not isinstance(vcs, dict) or vcs.get("vcs") != "git" or not isinstance(url, str):
        return None
    if direct.get("subdirectory") or any(not c.isprintable() or c.isspace() for c in url):
        return None
    parsed = urlsplit(url)
    if (parsed.scheme not in ("https", "ssh", "file") or parsed.password is not None
            or (parsed.scheme != "ssh" and parsed.username is not None) or parsed.query or parsed.fragment):
        return None
    return f"git+{url}"


def detect_installation(cfg: StewardConfig | None) -> Installation:
    """Use the active distribution and its environment, without running a tool manager."""
    try:
        dist = distribution(PACKAGE)
        if parse_version(dist.version) != parse_version(__version__):
            return Installation()
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        if not isinstance(direct, dict) or (direct.get("dir_info") or {}).get("editable"):
            return Installation()
        source = _git_source(direct)
        if direct.get("vcs_info") and not source:
            return Installation()
        prefix = Path(sys.prefix)
        if (prefix / "uv-receipt.toml").is_file():
            installer: Installer = "uv-tool"
        elif (prefix / "pipx_metadata.json").is_file():
            installer = "pipx"
        elif (dist.read_text("INSTALLER") or "").strip() == "pip":
            installer = "pip"
        else:
            return Installation()
    except (PackageNotFoundError, OSError, ValueError, TypeError, AttributeError):
        return Installation()
    if source and cfg:
        for ch in cfg.channel:
            if re.sub(r"[-_.]+", "-", ch.name).lower() == PACKAGE and ch.installer == installer:
                if ch.stable == source:
                    return Installation(installer, source, "stable")
                if ch.dev == source:
                    return Installation(installer, source, "dev")
    return Installation(installer, source)


def release_version(root: Path, cfg: StewardConfig, rel: str, item, entries: list[dict]) -> Version | None:
    """The version a toolkit release notice in the inbox announces, or None. The notice is addressed to this project,
    read without following links, and its bytes match the hash recorded when it was received (W12 F5): a file placed
    in exchange/inbox/ without `steward exchange receive` announces nothing. Its tag is the version, optionally
    prefixed with v. `upgrade --check` and `notifications` both use this test (W12 F13)."""
    from . import exchange as xc
    from .fsutil import sha256_bytes
    from .issues import _read_regular

    if cfg.exchange is None or item.kind != "release" or item.from_ != TOOLKIT_CODE or item.to != cfg.exchange.code:
        return None
    try:
        version = parse_version(item.version or "")
        raw = _read_regular(root, Path(rel), 1 << 20)
    except (OSError, ValueError):
        return None
    if xc.receipt_sha(entries) != sha256_bytes(raw):
        return None
    return version if item.tag in (str(version), f"v{version}") else None


def release_notices(root: Path, cfg: StewardConfig) -> dict[Version, str]:
    if cfg.exchange is None:
        return {}
    notices = {}
    for rel, item, entries in _inbox(root, cfg)[0]:
        version = release_version(root, cfg, rel, item, entries)
        if version is not None:
            notices[version] = item.tag
    return notices


def pypi_version() -> Version:
    with urlopen(PYPI_URL, timeout=5) as response:
        body = json.load(response)
    return parse_version(body["info"]["version"])


def _check(args: Namespace, installed: Version, install: Installation, notices: dict[Version, str]) -> int:
    latest = max(notices, default=None)
    source = "exchange" if latest is not None else None
    note = None
    if args.online:
        try:
            latest = pypi_version()
            source = "pypi"
        except (OSError, ValueError, TypeError, KeyError):
            note = "PyPI lookup failed. Only local release notices were checked."
    newer = latest is not None and latest > installed
    argv = install.argv(latest, notices.get(latest)) if newer else None
    if args.format == "json":
        write_document({
            "schema": OTHER_SCHEMAS["upgrade --check"], "installed_version": __version__,
            "latest_version": str(latest) if latest is not None else None, "source": source,
            "install_method": install.method, "channel": install.channel, "upgrade_available": newer,
            "command": argv, "note": note,
        })
    else:
        print(f"Installed version {__version__} ({install.method})")
        print(f"Newest known version {latest} ({source})" if latest is not None else "Newest version unknown")
        if argv:
            print(f"Install command {shlex.join(argv)}")
        elif newer:
            print("Upgrade available. Installer could not be detected.")
        if note:
            print(note)
    return EXIT_OK


def command(args: Namespace) -> int:
    if args.check and args.allow_downgrade:
        return _error("--allow-downgrade requires --to", EXIT_USAGE)
    if not args.check and (args.online or args.format == "json"):
        return _error("--online and --format json require --check", EXIT_USAGE)
    installed = parse_version(__version__)
    target = None
    if not args.check:
        try:
            target = parse_version(args.to)
        except ValueError:
            return _error("--to expects an exact version", EXIT_USAGE)
        if target < installed and not args.allow_downgrade:
            return _error(f"{target} is older than {installed}. Use --allow-downgrade to continue.", EXIT_DATAERR)

    root = args.repo.resolve() if args.repo else find_root(Path.cwd())
    if root is not None and not (root / "steward.toml").is_file():
        raise NotConfigured("not a steward repository (no steward.toml)")
    try:
        cfg = load_config(root) if root is not None else None
    except (OSError, ValueError):
        return _error("steward.toml is not valid. Run steward check config.", EXIT_USAGE)
    install = detect_installation(cfg)
    notices = release_notices(root, cfg) if root is not None and cfg is not None else {}
    if target is None:
        return _check(args, installed, install, notices)
    argv = install.argv(target, notices.get(target))
    if argv is None:
        return _error("could not detect the installer for this installation", EXIT_DATAERR)
    if not _interactive_terminal():
        return _error("an upgrade requires confirmation in an interactive terminal", EXIT_USAGE)

    print(f"Install command {shlex.join(argv)}")
    try:
        answer = input(f"Install Bio-STEWARD {target}? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        return _error("upgrade cancelled", EXIT_FAIL)
    try:
        result = run_installer(argv, subprocess.run)  # W12 F4: from an empty temporary directory, not the project
    except OSError:
        return _error("could not start the installer", EXIT_DATAERR)
    if result.returncode:
        return _error(f"installer exited with status {result.returncode}", EXIT_DATAERR)
    return EXIT_OK


def _interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _error(message: str, code: int) -> int:
    print(f"steward: {message}", file=sys.stderr)
    return code
