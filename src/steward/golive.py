"""Going public with a release mirror (0.20.3, STW-044): model A for any project, in one guided command.

`steward release go-public --owner OWNER --name NAME` checks that a release tag can be published (the export scanned
as `release publish` would, and the licence gate at public strictness), then lays out the steps: rename the
development repository (GitHub redirects its old address until another repository takes the name), point `origin` at
its new name, create the public repository under the old name, record `[publish]`, and publish the tag. With `--apply`
and a clean readiness it runs them in order, stopping at the first failure and saying what was done. Without
`--apply`, nothing changes anywhere.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KINDS = (  # (name, how a finding of this kind is recognised, what to do)
    ("private item IDs", re.compile(r"private item ID|private term or item ID"),
     "replace them with neutral references in public files (the development history keeps the originals)"),
    ("local paths", re.compile(r"local path"),
     "build synthetic paths at run time in tests (\"/\" \"Users/x\"), and remove real ones"),
    ("term-list hits", re.compile(r"term list"), "reword, or move the file to a private path ([publish] exclude)"),
    ("binary files", re.compile(r"binary file"),
     "check each by hand, then allow its kind in [publish] binary, or exclude it"),
    ("licence", re.compile(r"^licence:"), "steward check licence --summary; steward licence notices --write"),
)
NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


@dataclass
class Readiness:
    tag: str
    files: int = 0
    groups: dict[str, list[str]] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not any(self.groups.values())


def readiness(root: Path, cfg: Any, tag: str) -> Readiness:
    """The tag's export as `release publish` builds it, every finding grouped by kind."""
    from . import publish as pb

    files, _, findings = pb.build(root, cfg, tag)
    r = Readiness(tag, len(files))
    for f in findings:
        kind = next((k for k, rx, _ in KINDS if rx.search(f)), "other")
        r.groups.setdefault(kind, []).append(f)
    return r


def origin_url(root: Path) -> str:
    from .fsutil import git_run

    r = git_run(root, "remote", "get-url", "origin", text=True, timeout=10)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def origin_repo(root: Path) -> tuple[str, str] | None:
    """(owner, name) of a GitHub `origin`, or None."""
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", origin_url(root))
    return (m.group(1), m.group(2)) if m else None


def github_url(owner: str, name: str, like: str = "") -> str:
    """The repository's URL in the same scheme as `like` (AR3: an SSH origin stays SSH)."""
    return f"git@github.com:{owner}/{name}.git" if like.startswith("git@github.com:") else f"https://github.com/{owner}/{name}.git"  # scrub: allow (an SSH URL, not an address)


def plan(root: Path, cfg: Any, owner: str, name: str, dev: str, tag: str,
         public: bool = False) -> list[tuple[str, list[str]]]:
    """[(what, command)] in order; a step already done is left out. The local, reversible step comes first (AR2)."""
    steps: list[tuple[str, list[str]]] = []
    here, url = origin_repo(root), origin_url(root)
    public_url = f"https://github.com/{owner}/{name}.git"
    if cfg.publish is None or not cfg.publish.remote:
        steps.append((f"record [publish] remote = {public_url}", ["steward-internal", "record-remote", public_url]))
    if here == (owner, name):
        steps.append((f"rename the development repository {owner}/{name} to {dev} (it stays private)",
                      ["gh", "repo", "rename", dev, "--repo", f"{owner}/{name}", "--yes"]))
        steps.append((f"point origin at {owner}/{dev}", ["git", "remote", "set-url", "origin",
                                                         github_url(owner, dev, url)]))
    steps.append((f"create the release repository {owner}/{name} (empty, " + ("public" if public else
                  "private until you have looked at it") + ")",
                  ["gh", "repo", "create", f"{owner}/{name}", "--public" if public else "--private", "--description",
                   f"{cfg.steward.project}: released versions (development is private)"]))
    steps.append((f"publish {tag} to {owner}/{name}", ["steward", "release", "publish", tag, "--push"]))
    return steps


def record_remote(root: Path, url: str) -> None:
    """AR2: `remote = URL` in `[publish]`, written into an existing table (or a new one), never through a link."""
    from .fsutil import safe_write
    from .records import read_rel

    text = read_rel(root, "steward.toml").decode("utf-8")
    m = re.search(r"^\[publish\][^\n]*\n", text, re.M)
    if m:
        new = text[:m.end()] + f'remote = "{url}"\n' + text[m.end():]
    else:
        new = text.rstrip("\n") + f'\n\n[publish]\nmode = "mirror"\nremote = "{url}"\n'
    import tomllib

    tomllib.loads(new)
    safe_write(root, "steward.toml", new.encode("utf-8"))


def preflight(root: Path, cfg: Any, owner: str, name: str, tag: str, steps: list[tuple[str, list[str]]]) -> str | None:
    """AR3: every reason not to start, found before anything changes."""
    from . import publish as pb

    try:
        pb.semver_key(tag)
    except ValueError as e:
        return str(e)
    have = cfg.publish.remote if cfg.publish else None
    public_url = f"https://github.com/{owner}/{name}.git"
    if have and "github.com" in have and have.rstrip("/").removesuffix(".git") != public_url.removesuffix(".git") \
            and have != github_url(owner, name, have):
        return f"[publish] remote is {have}, not {owner}/{name}; change one of them first"
    if any(cmd[0] == "gh" for _, cmd in steps):
        if shutil.which("gh") is None:
            return "the GitHub CLI (gh) is not installed"
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=60)
        if auth.returncode != 0:
            return "gh is not signed in (gh auth login)"
        if origin_repo(root) != (owner, name):
            exists = public_exists(owner, name)
            if exists is None:
                return f"gh cannot tell whether {owner}/{name} exists; nothing was changed"
            if exists:
                return f"{owner}/{name} exists already; publish to it with steward release publish {tag} --push"
    return None


def make_public(owner: str, name: str) -> list[str]:
    """The last step, left to the owner after looking at the published repository (private first, the default)."""
    return ["gh", "repo", "edit", f"{owner}/{name}", "--visibility", "public", "--accept-visibility-change-consequences"]


def check_names(owner: str, name: str, dev: str) -> str | None:
    for v in (owner, name, dev):
        if not NAME.match(v):
            return f"{v!r} is not a plain GitHub owner or repository name"
    if name == dev:
        return "the development and public names must differ"
    return None


def public_exists(owner: str, name: str) -> bool | None:
    """True when OWNER/NAME exists on GitHub, False when it does not, None when `gh` cannot say."""
    if shutil.which("gh") is None:
        return None
    r = subprocess.run(["gh", "repo", "view", f"{owner}/{name}", "--json", "name"], capture_output=True, text=True,
                       timeout=60)
    if r.returncode == 0:
        return True
    return False if "Could not resolve" in (r.stderr or "") or "not found" in (r.stderr or "").lower() else None


def run_step(root: Path, cmd: list[str]) -> subprocess.CompletedProcess:
    """One step; `steward …` steps run this toolkit's own CLI in-process for the same repository."""
    if cmd[0] == "steward-internal" and cmd[1] == "record-remote":
        try:
            record_remote(root, cmd[2])
        except Exception as e:  # noqa: BLE001
            return subprocess.CompletedProcess(cmd, 1, "", str(e))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    if cmd[0] == "steward":
        import contextlib
        import io

        from .cli import main

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(cmd[1:] + ["--repo", str(root)])
        return subprocess.CompletedProcess(cmd, code, out.getvalue(), err.getvalue())
    return subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=300)
