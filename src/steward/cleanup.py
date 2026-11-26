"""Project storage cleanup (0.13.0; DESIGN_BRIEF_storage_cleanup; SC1 - SC5): scan, plan, check, ask, delete, record.

- `scan` is read-only. It lists this project's temporary storage, wherever it is (the startup disk or an external
  one), with its volume, its size and who else uses it: other steward projects on this machine (the registry),
  running processes with files open there, and active steward runs.
- `plan` writes the chosen candidates with their identity (device, inode, modification time) to `.steward/cleanup/`.
- `apply` checks every condition again, asks for each location in a terminal, deletes through held directory
  descriptors without following links, and records each deletion in a committed ledger.

Shared user-wide caches (pip, conda, Hugging Face, torch, the DVC cache) are listed, never deleted. A link's target
is listed, and is cleaned (its contents only) only when chosen by class.
"""

from __future__ import annotations

import datetime as _dt
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .fsutil import git_run

CLASSES = ("toolkit", "python", "docs", "declared", "linked", "shared")
DEFAULT_CLASSES = ("toolkit", "python", "docs", "declared")  # linked and shared are never chosen by default (SC3)
PY_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".ipynb_checkpoints", ".tox", ".nox",
           ".hypothesis"}
TOP_DIRS = {"build": "python", "site": "docs", "htmlcov": "python", ".coverage_html": "python"}
LATEX_EXT = (".aux", ".fls", ".fdb_latexmk", ".synctex.gz", ".toc", ".out", ".bbl", ".blg", ".nav", ".snm", ".vrb",
             ".bcf", ".run.xml", ".lof", ".lot")
LEDGER = "development/storage-cleanup.jsonl"
SKIP_WALK = {".git", "node_modules", ".venv", "venv", ".steward"}


@dataclass
class Candidate:
    cls: str
    path: str                 # as shown: repository-relative, or with ~ for the home folder
    real: str                 # the resolved path (kept local; never published)
    kind: str                 # dir | file
    size: int
    volume: str               # mount point, shown with ~ where it applies
    external: bool
    users: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    ident: tuple[int, int, int] = (0, 0, 0)  # st_dev, st_ino, st_mtime_ns
    entries: int = 0                          # files and folders under it (V7: a partial deletion is visible)

    @property
    def cleanable(self) -> bool:
        return self.cls != "shared" and not self.refusals


def tilde(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p


# ---------------------------------------------------------------- volumes and sizes
def mount_point(p: Path) -> Path:
    p = p.resolve()
    dev = p.stat().st_dev
    while p.parent != p and p.parent.stat().st_dev == dev:
        p = p.parent
    return p


def is_external(mount: Path) -> bool:
    s = str(mount)
    return s.startswith(("/Volumes/", "/media/", "/mnt/", "/run/media/"))


def size_of(p: Path, limit: int = 2_000_000) -> int:
    """Bytes under `p`, without following links (at most `limit` entries are visited)."""
    try:
        st = p.lstat()
    except OSError:
        return 0
    if not stat.S_ISDIR(st.st_mode):
        return st.st_size if stat.S_ISREG(st.st_mode) else 0
    total, seen = 0, 0
    for dirpath, dirnames, filenames in os.walk(p, followlinks=False):
        for n in filenames:
            seen += 1
            if seen > limit:
                return total
            try:
                s = os.lstat(os.path.join(dirpath, n))
                if stat.S_ISREG(s.st_mode):
                    total += s.st_size
            except OSError:
                pass
    return total


def entries_under(p: Path, limit: int = 2_000_000) -> int:
    if not os.path.lexists(p):
        return 0
    if not p.is_dir() or p.is_symlink():
        return 1
    n = 0
    for _, dirnames, filenames in os.walk(p, followlinks=False):
        n += len(dirnames) + len(filenames)
        if n > limit:
            break
    return n


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n} B"


# ---------------------------------------------------------------- the machine registry (SC2)
def registry_file() -> Path:
    from .talk import config_home

    return config_home() / "projects.toml"


def registry_readable() -> bool:
    """False when a registry exists but is not a list of strings (AA8: unknown shared use is never "none")."""
    import tomllib

    f = registry_file()
    if not f.is_file():
        return True
    try:
        doc = tomllib.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    projects = doc.get("projects", []) if isinstance(doc, dict) else None
    return isinstance(projects, list) and all(isinstance(p, str) for p in projects)


def registered() -> list[Path]:
    import tomllib

    f = registry_file()
    try:
        doc = tomllib.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except (OSError, ValueError):
        return []
    return _projects(doc)


def _projects(doc: Any) -> list[Path]:
    """V5 (0.17.0): a registry is a list of strings; any other shape, or any other entry, is an empty registry."""
    projects = doc.get("projects", []) if isinstance(doc, dict) else None
    if not isinstance(projects, list) or not all(isinstance(p, str) for p in projects):
        return []
    return [Path(p) for p in projects]


def register(root: Path, cfg: Any) -> None:
    """Add this checkout to the machine registry, unless opted out (`[storage.clean] registry = false` or
    STEWARD_NO_REGISTRY). Never raises: a registry that cannot be written is only a less informed scan."""
    if os.environ.get("STEWARD_NO_REGISTRY"):
        return
    cl = getattr(getattr(cfg, "storage", None), "clean", None)
    if cl is not None and not cl.registry:
        return
    import fcntl
    import json

    from .fsutil import LinkRefused, open_at, open_dir_beneath
    from .release import write_in_dir

    try:
        f = registry_file()
        home = Path(os.path.realpath(f.parent))
        # W9: the config folder is resolved once, then walked from / without links and created there (0.17.0: no
        # mkdir by path); the lock, the read, the temporary file and the replacement all happen inside the held folder
        dfd = open_dir_beneath(Path("/"), home.parts[1:], create=True)
        try:
            lk = open_at(f.name + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dfd)
            try:
                fcntl.flock(lk, fcntl.LOCK_EX)  # V5 (0.14.0): registrations are serialised, so none overwrites another
                import tomllib

                try:  # X5 (0.17.0): read through the held folder, never by path
                    rfd = os.open(f.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
                    with os.fdopen(rfd, "rb") as fh:
                        cur = [str(p) for p in _projects(tomllib.loads(fh.read().decode("utf-8")))]
                except FileNotFoundError:
                    cur = []
                except (OSError, ValueError):
                    cur = []
                me = str(root.resolve())
                if me in cur:
                    return
                lines = "".join(f"  {json.dumps(p)},\n" for p in sorted(set(cur + [me])))
                write_in_dir(dfd, f.name, ("# steward projects on this machine (for the storage cleanup's shared-use "
                                           f"check)\nprojects = [\n{lines}]\n").encode("utf-8"))
            finally:
                os.close(lk)
        finally:
            os.close(dfd)
    except (OSError, LinkRefused):
        pass


def _project_storage(proj: Path) -> set[str]:
    """Real paths another project relies on: its declared clean paths, its DVC cache, links leaving it, and its
    environment-file cache settings."""
    import tomllib

    out: set[str] = set()
    try:
        doc = tomllib.loads((proj / "steward.toml").read_text(encoding="utf-8"))
        for p in ((doc.get("storage") or {}).get("clean") or {}).get("paths") or []:
            if isinstance(p, str):
                q = Path(p).expanduser()
                out.add(str((q if q.is_absolute() else proj / q).resolve()))
    except (OSError, ValueError):
        pass
    dvc = proj / ".dvc" / "config"
    if dvc.is_file():
        for line in dvc.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("dir") and "=" in line:
                q = Path(line.split("=", 1)[1].strip()).expanduser()
                out.add(str((q if q.is_absolute() else proj / ".dvc" / q).resolve()))
    for envf in (proj / ".env", proj / ".envrc"):
        if envf.is_file():
            for line in envf.read_text(encoding="utf-8", errors="replace").splitlines():
                k, sep, v = line.removeprefix("export ").partition("=")
                if sep and k.strip() in ("HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME", "PIP_CACHE_DIR", "DVC_CACHE_DIR"):
                    q = Path(v.strip().strip('"\'')).expanduser()
                    out.add(str((q if q.is_absolute() else proj / q).resolve()))  # V5: relative to that project
    for top in proj.iterdir() if proj.is_dir() else []:
        try:
            kids = [top] + (list(top.iterdir()) if top.is_dir() and not top.is_symlink() and top.name != ".git" else [])
        except OSError:
            kids = [top]
        for q in kids:  # V5: links one level down count too
            try:
                if q.is_symlink():
                    out.add(str(q.resolve()))
            except OSError:
                pass
    return out


def _peers(root: Path) -> list[Path]:
    """The [exchange] peers of this project: projects it already works with, registered or not (V5)."""
    import tomllib

    from .exchange import local_peer_path
    from .models import ExchangePeer

    try:
        doc = tomllib.loads((root / "steward.toml").read_text(encoding="utf-8"))
        peers = ((doc.get("exchange") or {}).get("peers") or {})
        if not isinstance(peers, dict):
            return []
    except Exception:  # noqa: BLE001 - V5 (0.15.0): a malformed table is no peers, never a stopped scan
        return []
    out = []
    for v in peers.values():  # X7 (0.15.0): one peer that cannot be resolved never hides the others
        try:
            path = local_peer_path(root, v if isinstance(v, str) else ExchangePeer.model_validate(v))
            if path is not None:
                out.append(path)
        except Exception:  # noqa: BLE001
            continue
    return out


def _overlaps(a: str, b: str) -> bool:
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep) or b.startswith(a.rstrip(os.sep) + os.sep)


# ---------------------------------------------------------------- discovery
def _untracked(root: Path, rels: list[str]) -> set[str]:
    if not rels:
        return set()
    out = git_run(root, "ls-files", "-z", "--", *rels)
    if out.returncode != 0:
        return set(rels) if not (root / ".git").exists() else set()  # git failed: nothing is assumed untracked
    tracked = {p.decode("utf-8", "surrogateescape") for p in out.stdout.split(b"\0") if p}
    return {r for r in rels if not any(t == r or t.startswith(r.rstrip("/") + "/") for t in tracked)}


def _walk(root: Path) -> tuple[list[tuple[str, str]], list[str], list[Path]]:
    """(dir candidates (rel, class), LaTeX by-product files, links leaving the project)."""
    dirs, files, links = [], [], []
    rr = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        d = Path(dirpath)
        rel_d = d.relative_to(root).as_posix()
        for n in list(dirnames):
            p = d / n
            rel = (Path(rel_d) / n).as_posix() if rel_d != "." else n
            if p.is_symlink():
                try:
                    t = p.resolve()
                    if not (t == rr or rr in t.parents):
                        links.append(p)
                except OSError:
                    pass
                dirnames.remove(n)
                continue
            if n in SKIP_WALK:
                dirnames.remove(n)
                continue
            if n in PY_DIRS or n.endswith(".egg-info"):
                dirs.append((rel, "python"))
                dirnames.remove(n)
            elif rel_d == "." and n in TOP_DIRS:
                dirs.append((rel, TOP_DIRS[n]))
                dirnames.remove(n)
        for n in filenames:
            p = d / n
            if p.is_symlink():
                try:
                    t = p.resolve()
                    if not (t == rr or rr in t.parents):
                        links.append(p)
                except OSError:
                    pass
                continue
            if n.endswith(LATEX_EXT):
                files.append((Path(rel_d) / n).as_posix() if rel_d != "." else n)
    return dirs, files, links


SHARED_ENV = ("HF_HOME", "TORCH_HOME", "PIP_CACHE_DIR", "CONDA_PKGS_DIRS", "XDG_CACHE_HOME")
SHARED_DEFAULTS = ("~/.cache/huggingface", "~/.cache/torch", "~/.cache/pip", "~/Library/Caches/pip", "~/.conda/pkgs",
                   "~/.cache/dvc")
SHARED_DEFAULTS_ALL = SHARED_DEFAULTS  # the shared-overlap check always uses every known cache


def scan(root: Path, cfg: Any, *, check_users: bool = True) -> list[Candidate]:
    """Every cleanup candidate of this project, read-only."""
    root = root.resolve()
    out: list[Candidate] = []

    def add(cls: str, p: Path, shown: str) -> None:
        try:
            st = p.lstat()
            real = p.resolve()
            rst = real.stat()
            mount = mount_point(real)
        except OSError:
            return
        c = Candidate(cls, shown, str(real), "dir" if stat.S_ISDIR(rst.st_mode) else "file", size_of(real),
                      tilde(str(mount)), is_external(mount), ident=(rst.st_dev, rst.st_ino, rst.st_mtime_ns),
                      entries=entries_under(real))
        if stat.S_ISLNK(st.st_mode) and cls != "linked":
            c.refusals.append("reached through a link: listed as linked instead")
        if cls in ("toolkit", "python", "docs") and not real.is_relative_to(root):  # V1 (0.13.0): a linked ancestor
            c.refusals.append("it resolves outside the project (a linked folder above it)")
        out.append(c)

    cache = root / ".steward" / "cache"
    if cache.is_dir() and not cache.is_symlink():
        add("toolkit", cache, ".steward/cache")
    dirs, files, links = _walk(root)
    rels = [r for r, _ in dirs] + files
    free = _untracked(root, rels)
    for rel, cls in dirs:
        if rel in free:
            add(cls, root / rel, rel)
    for rel in files:
        if rel in free:
            add("docs", root / rel, rel)
    cl = getattr(getattr(cfg, "storage", None), "clean", None)
    for p in (cl.paths if cl is not None else []):
        q = Path(p).expanduser()
        q = q if q.is_absolute() else root / q
        if q.exists():
            add("declared", q, tilde(str(q)) if q.is_absolute() and not str(q).startswith(str(root)) else p)
    for ln in links:
        add("linked", ln, f"{ln.relative_to(root).as_posix()} -> {tilde(str(ln.resolve()))}")
    seen_shared: set[str] = set()
    for env in SHARED_ENV:
        v = os.environ.get(env)
        if v:
            for part in v.split(os.pathsep):
                q = Path(part).expanduser()
                if q.is_dir() and str(q.resolve()) not in seen_shared:
                    seen_shared.add(str(q.resolve()))
                    add("shared", q, f"{tilde(str(q))} (${env})")
    for d in SHARED_DEFAULTS:
        q = Path(d).expanduser()
        if q.is_dir() and str(q.resolve()) not in seen_shared:
            seen_shared.add(str(q.resolve()))
            add("shared", q, d)
    for c in out:
        c.refusals += checks(root, cfg, c)
    if check_users:
        users(root, out)
    return out


# ---------------------------------------------------------------- who else uses it (§4 of the brief)
def users(root: Path, cands: list[Candidate]) -> None:
    import psutil

    others = [p for p in dict.fromkeys([*registered(), *_peers(root)]) if p.resolve() != root and (p / "steward.toml").is_file()]
    if not registry_readable():  # AA8 (0.17.0): the stronger confirmation stays when shared use cannot be read
        for c in cands:
            c.users.append("project use: the machine registry could not be read")
    used = {str(p): _project_storage(p) for p in others}
    for c in cands:
        for proj, paths in used.items():
            if str(Path(proj).resolve()) == c.real or any(_overlaps(c.real, q) for q in paths) or \
                    _overlaps(c.real, str(Path(proj).resolve())):
                c.users.append(f"project {Path(proj).name}")
    try:
        procs = list(psutil.process_iter(["pid", "name", "uids"]))
    except (psutil.Error, OSError):
        for c in cands:
            c.users.append("running processes: could not be checked")
        return
    blind = False
    me = os.getuid()
    for pr in procs:
        uids = pr.info.get("uids")
        if uids is not None and me not in (uids.real, uids.effective) and me != 0:
            continue  # another account's process cannot write this user's files without privileges
        try:
            files = pr.open_files()
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.Error, OSError):  # V6 (0.13.0): an own process not inspected is unknown use
            if pr.pid != os.getpid():
                blind = True
            continue
        for f in files:
            for c in cands:
                if _overlaps(f.path, c.real) and f.path.startswith(c.real):
                    label = f"process {pr.info.get('name') or pr.pid} (pid {pr.pid}) has a file open there"
                    if label not in c.users:
                        c.users.append(label)
    if blind:
        for c in cands:
            c.users.append(BLIND)


# ---------------------------------------------------------------- checks before deletion (§5 of the brief)
HOMES = ("/Users", "/home", "/root", "/var/root")


def _shared_reals() -> list[str]:
    out = []
    for env in SHARED_ENV:
        for part in (os.environ.get(env) or "").split(os.pathsep):
            if part:
                out.append(str(Path(part).expanduser().resolve()))
    out += [str(Path(d).expanduser().resolve()) for d in SHARED_DEFAULTS_ALL]
    return out


def checks(root: Path, cfg: Any, c: Candidate) -> list[str]:
    """Why this candidate must not be deleted (empty when it may be)."""
    why: list[str] = []
    real = Path(c.real)
    root = root.resolve()
    home = Path.home().resolve()
    forbidden = {root, home, Path("/"), mount_point(real)} | set(root.parents) | set(home.parents)
    # V4 (0.13.0): any home folder (/Users/<name>, /home/<name>), not only this user's
    if real in forbidden or root.is_relative_to(real) or (len(real.parts) <= 3 and str(real.parent) in HOMES):
        why.append("it is the repository, a home folder, a disk root or one of their parents")
        return why
    if c.cls != "shared" and any(_overlaps(c.real, s) for s in _shared_reals()):
        why.append("it overlaps a shared user cache (pip, conda, Hugging Face, torch, DVC); use that tool's own cleanup")
    if real.is_relative_to(root):
        rel = real.relative_to(root).as_posix()
        if rel in ("", ".git") or rel.startswith(".git/"):
            why.append("it is part of git")
        tracked = git_run(root, "ls-files", "-z", "--", rel)  # lists tracked descendants too
        if tracked.returncode != 0 and (root / ".git").exists():
            why.append("git could not say whether files under it are tracked")
        elif tracked.stdout.strip(b"\0"):
            why.append("git tracks files under it")
        if rel.split("/")[0] in ("development", "exchange"):  # V3: the folders themselves, too
            why.append("it is under the project's records")
    why += _protected_descendants(root, cfg, real)  # V3: inside the project or on another disk
    for run in _active_runs(root, cfg):
        if run == "unknown" or _overlaps(run, c.real):
            why.append("an active steward run works or writes there" if run != "unknown"
                       else "the run ledger is not intact, so active runs cannot be ruled out")
            break
    return why


def _protected_descendants(root: Path, cfg: Any, real: Path, limit: int = 20000) -> list[str]:
    """V3 (0.13.0): what anything beneath the candidate is: a ledger, a registered artifact, sealed data, a frozen
    file or a recorded run output. Too many files to check is a refusal, never a pass."""
    from .fsutil import glob_match

    files = []
    for dirpath, dirnames, filenames in os.walk(real, followlinks=False):
        for n in filenames:
            files.append(Path(dirpath, n))
            if len(files) > limit:
                return [f"more than {limit} files: too many to check one by one"]
    if real.is_file():
        files = [real]
    rels = [f.relative_to(root).as_posix() for f in files if f.is_relative_to(root)]
    why: list[str] = []
    if any(f.name.endswith(".jsonl") for f in files):
        why.append("it holds a ledger (.jsonl)")
    st = getattr(cfg, "storage", None)
    if st is not None and (root / st.artifacts).is_file():
        try:
            from . import storage as stg

            reg = stg.load((root / st.artifacts).read_text(encoding="utf-8"))
            arts = {str((root / a.path).resolve()) for a in reg.artifacts}
            if any(_overlaps(x, str(real)) for x in arts):
                why.append("the artifact registry records something under it")
        except Exception:  # noqa: BLE001 - an unreadable registry never permits deletion
            why.append("the artifact registry could not be read")
    if getattr(cfg, "integrity", None) is not None:
        from . import integrity as ig

        try:
            if any(ig.sealed_owner(root, cfg, r) for r in rels):
                why.append("it holds sealed data")
        except Exception:  # noqa: BLE001
            why.append("the sealed datasets could not be checked")
    for fs in getattr(cfg, "frozen", []) or []:
        if any(glob_match(r, g) for r in rels for g in fs.files):
            why.append(f"it holds files of the frozen set {fs.name}")
            break
    outs = _run_outputs(root, cfg)
    if any(_overlaps(str((root / o).resolve()), str(real)) for o in outs):
        why.append("it holds an output a recorded run produced")
    return why


def _run_outputs(root: Path, cfg: Any) -> set[str]:
    from .ledger import verify
    from .models import RunSection

    rc = getattr(cfg, "run", None) or RunSection()
    p = root / rc.ledger
    if not p.is_file():
        return set()
    return {o for e in verify(p).entries if e.get("kind") == "outcome" for o in (e.get("outputs") or {})}


def _active_runs(root: Path, cfg: Any) -> list[str]:
    from .ledger import verify
    from .models import RunSection

    rc = getattr(cfg, "run", None) or RunSection()
    p = root / rc.ledger
    if not p.is_file():
        return []
    v = verify(p)
    if v.errors or v.torn_tail:  # V6 (0.13.0): an unreadable ledger cannot rule an active run out
        return ["unknown"]
    done = {e.get("run") for e in v.entries if e.get("kind") == "outcome"}
    out = []
    for e in v.entries:
        if e.get("kind") == "started" and e.get("run") not in done:
            out.append(str((root / e.get("cwd", ".")).resolve()))
            out += [str((root / o).resolve()) for o in (e.get("outputs_before") or {})]
    return out


# ---------------------------------------------------------------- plan and apply
def write_plan(root: Path, chosen: list[Candidate]) -> Path:
    import json

    from .fsutil import open_dir_beneath
    from .release import write_in_dir

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dfd = open_dir_beneath(root, (".steward", "cleanup"), create=True)  # V7 (0.14.0): never through a link
    try:
        write_in_dir(dfd, f"{stamp}.json", (json.dumps({"schema": "steward.cleanup_plan/0.1", "root": str(root.resolve()),
                                                        "entries": [asdict(c) for c in chosen]}, indent=2) + "\n").encode())
    finally:
        os.close(dfd)
    return root / ".steward" / "cleanup" / f"{stamp}.json"


BLIND = "running processes: not every process could be checked"


def recheck(root: Path, cfg: Any, e: dict[str, Any], current: list[Candidate] | None = None) -> list[str]:
    """Every condition again, at deletion time: the entry is still a candidate of this project as planned (V1), its
    identity, disk and size are unchanged (V2), the checks hold, and who else uses it is read afresh (V4, V6). Sets
    e["users_now"] for the confirmation."""
    real = Path(e["real"])
    try:
        st = real.lstat()
    except OSError:
        return ["it is gone"]
    if stat.S_ISLNK(st.st_mode):
        return ["it is a link now"]
    if (st.st_dev, st.st_ino, st.st_mtime_ns) != tuple(e["ident"]) and e["kind"] == "file":
        return ["it changed since the plan"]
    if (st.st_dev, st.st_ino) != tuple(e["ident"][:2]):
        return ["it is not the folder that was planned (another one, or another disk, is there now)"]
    if e["cls"] == "shared":
        return ["shared caches are never cleaned by this command"]
    if "entries" not in e:  # X3 (0.15.0): a plan from an older version cannot show a partial deletion; write a new one
        return ["the plan was written by an older version: write a new plan (steward storage clean --plan)"]
    current = current if current is not None else scan(root, cfg, check_users=False)
    match = next((c for c in current if c.real == e["real"] and c.cls == e["cls"] and c.path == e["path"]), None)
    if match is None:  # V1 (0.13.0): what is shown is what is deleted, and it is still this project's
        return ["it is no longer a cleanup candidate of this project as planned"]
    if match.refusals:
        return list(match.refusals)
    if match.size != e["size"]:  # V2: its contents changed since the plan
        return ["its contents changed since the plan"]
    c = Candidate(e["cls"], e["path"], e["real"], e["kind"], e["size"], e["volume"], e["external"], ident=tuple(e["ident"]))
    users(root, [c])
    e["users_now"] = [u for u in c.users if u != BLIND]
    e["blind"] = BLIND in c.users
    return [u for u in c.users if u.startswith(("process", "running processes: could not"))]


def delete(e: dict[str, Any]) -> int:
    """Delete one planned entry through its parent's descriptor; never follows a link. For a `linked` entry only the
    target's contents go. Returns the bytes freed (as measured before)."""
    import shutil

    from .fsutil import open_dir_beneath

    real = Path(e["real"])
    # V2 (0.13.0): the parent is walked from / one component at a time without following links, and held
    parent_fd = open_dir_beneath(Path("/"), real.parent.parts[1:])
    try:
        st = os.stat(real.name, dir_fd=parent_fd, follow_symlinks=False)
        if (st.st_dev, st.st_ino) != tuple(e["ident"][:2]):
            raise OSError("it was replaced while being deleted")
        if stat.S_ISLNK(st.st_mode):
            raise OSError("it is a link")
        if stat.S_ISDIR(st.st_mode):
            for dirpath, dirnames, _ in os.walk(real, followlinks=False):  # V2: never across a nested mount
                for n in dirnames:
                    try:
                        if os.lstat(os.path.join(dirpath, n)).st_dev != st.st_dev:
                            raise OSError(f"another disk is mounted inside it ({n}); nothing was deleted")
                    except FileNotFoundError:
                        pass
        if stat.S_ISDIR(st.st_mode):
            if e["cls"] == "linked":
                dfd = os.open(real.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                try:
                    for n in os.listdir(dfd):
                        s = os.stat(n, dir_fd=dfd, follow_symlinks=False)
                        if stat.S_ISDIR(s.st_mode):
                            shutil.rmtree(n, dir_fd=dfd)
                        else:
                            os.unlink(n, dir_fd=dfd)
                finally:
                    os.close(dfd)
            else:
                shutil.rmtree(real.name, dir_fd=parent_fd)
        else:
            os.unlink(real.name, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    return int(e["size"])
