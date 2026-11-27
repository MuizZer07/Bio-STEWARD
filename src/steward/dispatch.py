"""Dispatching a task to another agent (0.20.4, STW-046): the brief, run the way each agent's headless mode needs.

`steward task brief` writes a prompt; `steward task dispatch TASK --to AGENT` also runs it, so no project has to
rediscover how each agent behaves without a human at the keyboard:

- **Codex** (`codex exec`): a read-only sandbox for a review (`-s read-only`), a writable one for an implementation
  (`-s workspace-write`), `--skip-git-repo-check` so it starts in any folder, stdin closed so it never waits.
- **Antigravity** (`agy -p`): headless mode cannot ask for permission, so it silently denies every shell command
  that is not allowed beforehand and may print nothing at all. A dispatch passes `--sandbox` and a session-only
  allow-list of read-only commands (`--settings`), never `--dangerously-skip-permissions`; when the agent still
  produces nothing, the dispatch says so and points to `--inline`.
- **`--inline`** (any agent): the documents the task names (its `git diff A..B` range and the files in its Scope)
  are put in the prompt itself, and the agent is asked to answer in text only. It needs no tool at all, so it works
  where commands are refused.

A review runs in a clean, detached checkout of the current commit (never the working tree), and the checkout is
checked afterwards: a reviewer that changed a file is reported. Nothing is committed, pushed or merged here.

W12b: a review's checkout is a local clone whose `.git` folder is inside it (a linked worktree's `.git` points to the
source repository, outside an agent's sandbox, so git could not run there). The clone has every branch and tag, no
remote and no hard links into the source repository, so `git log`, `git diff` and the tests run in it while the
source repository stays out of the reviewer's reach. A review gets its own read-only command list (`REVIEW`);
`READ_ONLY` is the wider list an implementation, and an Antigravity edit-and-run sprint task, builds on.
W12c: both take from `READ_ONLY` only what a sprint allow entry may name (no wrapper, shell or interpreter).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DIR = ".steward/dispatch"
READ_ONLY = ["git", "grep", "rg", "ls", "cat", "sed", "awk", "head", "tail", "wc", "find", "sort", "uniq", "cut", "tr",
             "diff", "stat", "file", "shasum", "python3", "python", "pytest", "uv", "mkdir", "mktemp", "cp", "touch",
             "echo", "printf", "cd", "pwd", "env", "gzcat", "zcat", "tar"]
# W12b (F8): what a read-only reviewer may run. No wrapper (env, xargs), no interpreter alone (python), no command
# that writes (cp, mkdir, touch, tar, sed -i) and no git subcommand that changes the repository.
REVIEW = ["git status", "git diff", "git log", "git show", "git rev-parse", "git ls-files", "git blame", "git grep",
          "git branch --list", "git describe", "git cat-file", "grep", "rg", "ls", "cat", "head",
          "tail", "wc", "sort", "uniq", "cut", "diff", "stat", "file", "shasum", "pwd", "echo", "pytest",
          "python -m pytest", "python3 -m pytest", "uv run pytest", "uv run --extra dev python -m pytest"]
# W12c (N1): an implementation gets READ_ONLY less what a sprint allow entry may not name (git as a whole, env,
# python, uv, awk), plus git's reading and committing subcommands and the test runners in exact form.
IMPLEMENT_EXTRA = ["git status", "git diff", "git log", "git show", "git add", "git commit", "python -m pytest",
                   "python3 -m pytest", "uv run pytest"]


def implement_list() -> list[str]:
    """The command list of an implementation dispatch (W12c, N1): every entry passes the sprint allow rule."""
    from .sprint import allow_refusal

    keep = [c for c in READ_ONLY if allow_refusal(c) is None]
    return keep + [c for c in IMPLEMENT_EXTRA if c not in keep]
AGY_DENIED = re.compile(r"no output produced|auto-denied|cannot prompt", re.I)
INLINE_BUDGET = 200_000  # characters of documents put in an inline prompt


@dataclass
class Run:
    cmd: list[str]
    cwd: Path
    report: Path
    errors: Path


def agy_path() -> str | None:
    """Antigravity's CLI: on PATH, or where its installer puts it."""
    found = shutil.which("agy")
    if found:
        return found
    home = Path(os.path.expanduser("~/.gemini/bin/agy"))
    return str(home) if home.is_file() and os.access(home, os.X_OK) else None


def agy_settings(root: Path, implement: bool = False) -> Path:
    """A session-only allow-list: for a review, the read-only commands a reviewer needs (`REVIEW`); for an
    implementation, `implement_list()`. Both with the sprint's default deny list."""
    from .fsutil import safe_write
    from .sprint import DEFAULT_DENY

    rel = f"{DIR}/agy-settings.json"
    doc = {"permissions": {"allow": [f"command({c})" for c in (implement_list() if implement else REVIEW)],
                           "deny": [f"command({c})" for c in DEFAULT_DENY]}}
    safe_write(root, rel, (json.dumps(doc, indent=1) + "\n").encode())
    return root / rel


def scope_documents(root: Path, task_text: str, budget: int = INLINE_BUDGET) -> tuple[str, list[str]]:
    """The documents a task names, for an inline prompt: its `git diff A..B` ranges and the repository files in
    backticks. ([text], [what was left out because of the budget])."""
    from .fsutil import escapes_root, git_run

    parts, left = [], []
    used = 0
    for m in re.finditer(r"git diff ([\w./^~-]+\.\.[\w./^~-]+)(?: -- ([^`\n]+))?", task_text):
        args = ["diff", m.group(1)] + (["--"] + m.group(2).split() if m.group(2) else [])
        r = git_run(root, *args, text=True, timeout=60)
        if r.returncode == 0 and r.stdout:
            block = f"### `git diff {m.group(1)}`\n```diff\n{r.stdout}\n```\n"
            if used + len(block) > budget:
                left.append(f"git diff {m.group(1)} ({len(block)} characters)")
                continue
            parts.append(block)
            used += len(block)
    seen = set()
    for m in re.finditer(r"`([A-Za-z0-9_./-]+\.(?:py|md|toml|json|txt|yml|yaml|cfg|sh|tex))`", task_text):
        rel = m.group(1)
        if rel in seen or escapes_root(rel) or not (root / rel).is_file():
            continue
        seen.add(rel)
        try:
            body = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        block = f"### `{rel}`\n```\n{body}\n```\n"
        if used + len(block) > budget:
            left.append(f"{rel} ({len(block)} characters)")
            continue
        parts.append(block)
        used += len(block)
    return "".join(parts), left


def inline_prompt(brief_text: str, documents: str, left: list[str]) -> str:
    note = ("\n## How to answer\nYou have no tools in this session: do not run commands or open files. Everything you "
            "need is below. Answer in text only; say plainly what you could not check from these documents.\n")
    if left:
        note += "Left out for size (say what you could not check because of it): " + "; ".join(left) + "\n"
    return brief_text.rstrip() + "\n" + note + "\n## Documents\n" + (documents or "(the task names no document)\n")


def command(agent: str, prompt: str, cwd: Path, root: Path, implement: bool, model: str | None, inline: bool) -> list[str]:
    if agent == "codex":
        exe = shutil.which("codex")
        if exe is None:
            raise FileNotFoundError("codex is not installed (npm install -g @openai/codex)")
        return [exe, "exec", "-s", "workspace-write" if implement else "read-only", "--skip-git-repo-check", "-C",
                str(cwd)] + (["-m", model] if model else []) + [prompt]
    if agent == "antigravity":
        exe = agy_path()
        if exe is None:
            raise FileNotFoundError("Antigravity's CLI (agy) is not installed or not on PATH")
        cmd = [exe, "-p", prompt, "--model", model or "gemini-4-neon-high", "--sandbox"]
        if not inline:
            cmd += ["--settings", str(agy_settings(root, implement))]
        return cmd
    raise ValueError(f"no headless dispatch for {agent}; use steward task brief --for {agent} and paste it")


def checkout(root: Path, name: str) -> Path:
    """A clean, detached checkout of HEAD for a review, under .steward/dispatch/."""
    from .fsutil import git_run

    dest = root / DIR / f"wt-{name}"
    if dest.exists():
        git_run(root, "worktree", "remove", "--force", str(dest), text=True, timeout=60)
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = git_run(root, "worktree", "add", "-q", "--detach", str(dest), "HEAD", text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"a clean checkout could not be made: {(r.stderr or '').strip()[:200]}")
    return dest


def review_clone(root: Path, name: str) -> Path:
    """W12b: a read-only reviewer's checkout, a local clone under .steward/dispatch/ whose .git is inside it: every
    branch and tag of the source repository, HEAD's commit checked out detached, no remote, objects copied (never hard
    linked), no hooks. git log, git diff and the tests work in it; the source repository is not written."""
    from .fsutil import SAFE_GIT_CONFIG, git_env, git_run, open_dir_beneath

    head = git_run(root, "rev-parse", "--verify", "HEAD^{commit}", text=True, timeout=30)
    if head.returncode != 0:
        raise RuntimeError("the repository has no commit to review")
    sha = head.stdout.strip()
    try:
        os.close(open_dir_beneath(root, tuple(Path(DIR).parts), create=True))  # never through a link
    except OSError as e:  # W12c (N3b): LinkRefused among them; a refusal for the user to fix, not an internal error
        raise RuntimeError(f"{DIR} cannot be used for a review clone: {e}") from None
    dest = root / DIR / f"review-{name}"
    if dest.is_symlink():
        raise RuntimeError(f"{DIR}/review-{name} is a link; remove it")
    if dest.exists():
        shutil.rmtree(dest)
    cfg: list[str] = []
    for c in SAFE_GIT_CONFIG:
        cfg += ["-c", c]
    cfg += ["-c", "protocol.file.allow=always"]  # the local copy only; every other transport stays denied
    env = {**git_env(), "GIT_ALLOW_PROTOCOL": "file"}
    steps = [(["init", "-q", str(dest)], root),
             (["fetch", "-q", "--no-tags", "--update-head-ok", str(root.resolve()), "+refs/heads/*:refs/heads/*",
               "+refs/tags/*:refs/tags/*"], dest),
             (["-c", "advice.detachedHead=false", "checkout", "-q", "--detach", sha], dest)]
    for args, cwd in steps:
        r = subprocess.run(["git", *cfg, *args], cwd=cwd, capture_output=True, text=True, timeout=600, env=env)
        if r.returncode != 0:
            shutil.rmtree(dest, ignore_errors=True)
            raise RuntimeError(f"a review clone could not be made: {(r.stderr or '').strip()[:200]}")
    return dest


def changed(cwd: Path) -> list[str]:
    from .fsutil import git_run

    r = git_run(cwd, "status", "--short", text=True, timeout=60)
    return [ln for ln in (r.stdout or "").splitlines() if ln.strip()]


def remove_checkout(root: Path, cwd: Path) -> None:
    from .fsutil import git_run

    if (cwd / ".git").is_dir() and not (cwd / ".git").is_symlink():  # a review clone: only its own folder goes
        shutil.rmtree(cwd, ignore_errors=True)
        return
    git_run(root, "worktree", "remove", "--force", str(cwd), text=True, timeout=60)
