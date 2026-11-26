"""Git hooks (0.6.2, C6.5; 0.8.1: AR-01, AR-17, AR-20, SR-009, review N1, N2): `steward hooks install` and
`steward hooks run`.

The installed hook scripts do nothing but exec `steward hooks run …` with validated arguments, so no configured
value is ever interpreted by a shell (N2). The work happens in Python:

- **pre-commit** checks the current checkout and blocks only when its gate is NOT ELIGIBLE because of a FAIL. It is
  quiet otherwise (AR-17, AR-20), and skips a checkout without `steward.toml` with a notice.
- **pre-push** refuses force-pushes and deletions of protected branches. It then checks each pushed ref's tip
  commit, staged without running anything the repository configures (N1): the tree is materialized from raw blobs
  (`git cat-file --batch`, no filters), in a worktree added with `--no-checkout` (no checkout hook), through the
  safe git helper. Intermediate commits of a push are not checked; the tip is. A pushed commit without
  `steward.toml` is skipped with a notice, or refused with `--unconfigured refuse`.

Hook files are written only inside the hooks directory and never through a symbolic link (N2). Hooks can be skipped
(`--no-verify`); CI is the enforcement point.
"""

from __future__ import annotations

import os
import posixpath
import re
import shlex
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

MARK = "# installed by steward hooks"
GATE = re.compile(r"^[a-z0-9_-]{1,64}$")
BRANCH = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}(?<!/)(?<!\.lock)$")
ZERO = "0" * 40


def render(kind: str, gate: str, protected: list[str], unconfigured: str = "skip", python: str | None = None) -> str:
    if not GATE.match(gate):
        raise ValueError(f"gate name {gate!r} is not valid")
    bad = [p for p in protected if not BRANCH.match(p)]
    if bad:
        raise ValueError(f"protected branch name(s) {bad!r} are not valid branch names")
    if unconfigured not in ("skip", "refuse"):
        raise ValueError("unconfigured must be skip or refuse")
    # -I: isolated mode. Neither the checkout (the hook's working directory) nor PYTHON* variables choose the module
    # that runs (review O1)
    head = [python or sys.executable, "-I", "-m", "steward.cli", "hooks", "run", kind]
    opts = ["--gate", gate]
    if kind == "pre-push":
        opts += ["--unconfigured", unconfigured] + [a for p in protected for a in ("--protect", p)]
    remote = ' "$@" ' if kind == "pre-push" else " "  # git's remote name and URL, before the options
    return ("#!/bin/sh\n" + MARK + "\nexec " + " ".join(shlex.quote(a) for a in head) + remote
            + " ".join(shlex.quote(a) for a in opts) + "\n")


def _linked_component(path: Path, anchors: list[Path]) -> Path | None:
    """The first component of `path` that is a symbolic link, checked from the deepest anchor that contains it (the
    repository or its main worktree, which may themselves be reached by a link) or from the filesystem root, down to
    the leaf (0.9.0 A4). Components that do not exist yet are created as real directories."""
    path = Path(os.path.abspath(path))
    inside = [a for a in anchors if a == path or a in path.parents]
    base = max(inside, key=lambda a: len(a.parts)) if inside else Path(path.anchor)
    cur = base
    for part in path.relative_to(base).parts:
        cur = cur / part
        if cur.is_symlink():
            return cur
        if not cur.exists():
            break
    return None


CHAINED = "# chained: the hook kept at NAME.local runs first; its refusal and exit code are kept (REQ-002)"


def render_chained(kind: str, gate: str, protected: list[str], unconfigured: str = "skip",
                   python: str | None = None) -> str:
    """Run the adopter's own hook (kept beside it as `<kind>.local`), then steward's. Only fixed text and the
    validated arguments of `render` appear; pre-push stdin (the pushed refs) is given to both."""
    plain = render(kind, gate, protected, unconfigured, python)
    steward_cmd = plain.splitlines()[2][len("exec "):]
    head = "#!/bin/sh\n" + MARK + "\n" + CHAINED.replace("NAME", kind) + "\nhere=$(dirname \"$0\")\n"
    if kind == "pre-commit":
        return head + f'"$here/{kind}.local" "$@" || exit $?\nexec {steward_cmd}\n'
    return head + ('tmp=$(mktemp) || exit 1\ncat > "$tmp" || { rm -f "$tmp"; exit 1; }\n'
                   f'"$here/{kind}.local" "$@" < "$tmp"; rc=$?\n'
                   'if [ "$rc" -ne 0 ]; then rm -f "$tmp"; exit "$rc"; fi\n'
                   f'{steward_cmd} < "$tmp"; rc=$?\nrm -f "$tmp"\nexit "$rc"\n')


def hooks_dir(root: Path) -> Path:
    """The common hooks directory, also from a linked worktree (AR-01). The repository's own core.hooksPath is
    respected: this is where git will run the hooks. No component below the repository (or, for a path outside
    it, below the filesystem root) may be a link (review O3; 0.9.0 A4)."""
    from .fsutil import git_run

    out = git_run(root, "rev-parse", "--path-format=absolute", "--git-path", "hooks", text=True, safe_config=False)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError("not a git repository (git rev-parse failed)")
    hooks = Path(out.stdout.strip())
    conf = git_run(root, "config", "--get", "core.hooksPath", text=True, safe_config=False)
    configured = Path(conf.stdout.strip()).expanduser() if conf.returncode == 0 and conf.stdout.strip() else None
    if configured is not None and not configured.is_absolute():
        configured = root / configured
    common = git_run(root, "rev-parse", "--path-format=absolute", "--git-common-dir", text=True, safe_config=False)
    anchors = [Path(os.path.abspath(root)), root.resolve()]
    if common.returncode == 0 and common.stdout.strip():
        main = Path(common.stdout.strip()).parent
        anchors += [Path(os.path.abspath(main)), main.resolve()]
    for candidate in (hooks, configured):
        if candidate is None:
            continue
        link = _linked_component(candidate, anchors)
        if link is not None:
            raise RuntimeError(f"the hooks directory {candidate} is reached through a symlink ({link}); "
                               "point core.hooksPath at the real directory")
    return hooks


MANIFEST = ".steward-hooks.json"  # K3 (R5): what steward wrote, by hash; ownership is never read from a hook's text


class _HooksDir:
    """The checked hooks directory, held open: every read, write, rename and unlink goes through its descriptor, so
    a directory replaced after the check cannot redirect them (K6, the Q7 limit)."""

    def __init__(self, root: Path, create: bool):
        from .fsutil import LinkRefused, open_dir_beneath

        self.path = hooks_dir(root)
        base, parts = _anchor_parts(root, self.path)
        try:
            self.fd = open_dir_beneath(base, parts, create=create)
        except LinkRefused as e:
            raise RuntimeError(f"the hooks directory {self.path} cannot be opened without links: {e.strerror or e}") from None

    def close(self) -> None:
        os.close(self.fd)

    def kind(self, name: str) -> str | None:
        import stat as st

        try:
            m = os.stat(name, dir_fd=self.fd, follow_symlinks=False).st_mode
        except FileNotFoundError:
            return None
        return "link" if st.S_ISLNK(m) else "file" if st.S_ISREG(m) else "other"

    def read(self, name: str) -> bytes:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            from .ledger import _read_all

            return _read_all(fd)
        finally:
            os.close(fd)

    def write(self, name: str, data: bytes, mode: int) -> None:
        import secrets

        from .fsutil import open_at, write_all

        tmp = f".{name}.{secrets.token_hex(6)}.tmp"
        fd = open_at(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, self.fd)
        try:
            try:
                write_all(fd, data)
                os.fchmod(fd, mode)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=self.fd)
            except OSError:
                pass
            raise

    def rename(self, a: str, b: str) -> None:
        os.rename(a, b, src_dir_fd=self.fd, dst_dir_fd=self.fd)

    def unlink(self, name: str) -> None:
        os.unlink(name, dir_fd=self.fd)

    def manifest(self) -> dict[str, Any]:
        """The recorded installation. A manifest that exists but cannot be read is never treated as empty: that
        would let an install replace, or a removal delete, what it records (S4)."""
        import json

        k = self.kind(MANIFEST)
        if k is None:
            return {}
        bad = RuntimeError(f"{self.path / MANIFEST} is not a valid steward hooks manifest; it is left as it is. "
                           "Inspect it, then move it aside and run `steward hooks install --force`")
        if k != "file":
            raise bad
        try:
            doc = json.loads(self.read(MANIFEST).decode("utf-8"))
        except (ValueError, OSError, RecursionError):
            raise bad from None
        hexd = re.compile(r"^[0-9a-f]{64}$")

        def ok(rec: Any) -> bool:  # U6 (0.13.0): every field of a record has its type
            return isinstance(rec, dict) and set(rec) <= {"sha256", "chained", "previous", "local_sha256"} \
                and isinstance(rec.get("sha256"), str) and hexd.match(rec["sha256"]) is not None \
                and isinstance(rec.get("chained", False), bool) \
                and all(rec.get(k) is None or (isinstance(rec[k], str) and (hexd.match(rec[k]) or rec[k].startswith("link:")))
                        for k in ("previous", "local_sha256"))
        if not isinstance(doc, dict) or not all(k in ("pre-commit", "pre-push") and ok(v) for k, v in doc.items()):
            raise bad
        return doc

    def save_manifest(self, doc: dict[str, Any]) -> None:
        import json

        self.write(MANIFEST, (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode(), 0o644)

    def ours(self, name: str, man: dict[str, Any]) -> bool:
        """Installed by steward: its bytes are the ones the manifest recorded. A hook from before the manifest counts
        only as a plain (never a chained) wrapper (K3)."""
        import hashlib

        if self.kind(name) != "file":
            return False
        data = self.read(name)
        rec = man.get(name)
        if isinstance(rec, dict):
            h = hashlib.sha256(data).hexdigest()
            # S4: during an install the manifest is written first and also accepts the bytes being replaced, so a
            # failure part way leaves every hook recorded
            return h == rec.get("sha256") or (h is not None and h == rec.get("previous"))
        return legacy(name, data) == "plain"  # an unrecorded chain is adopted only by `install --chain` (K3, S4)


def legacy(name: str, data: bytes) -> str | None:
    """A wrapper written before the manifest (0.9.0 or earlier): "plain" or "chained" only when its bytes are
    exactly what steward renders for the arguments in its exec line. A marker string alone is never enough (R5, S4:
    the 0.9.0 chained wrapper can be removed or upgraded)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    line = next((l for l in text.splitlines() if " steward.cli hooks run " + name in l), None)
    if line is None:
        return None
    cmd = line[len("exec "):] if line.startswith("exec ") else line.split(' < "$tmp"')[0]
    try:
        args = shlex.split(cmd)
    except ValueError:
        return None
    if len(args) < 7 or args[1:7] != ["-I", "-m", "steward.cli", "hooks", "run", name]:
        return None
    python, rest = args[0], [a for a in args[7:] if a != "$@"]
    gate, unconfigured, protected = None, "skip", []
    it = iter(rest)
    for a in it:
        v = next(it, None)
        if v is None:
            return None
        if a == "--gate":
            gate = v
        elif a == "--unconfigured":
            unconfigured = v
        elif a == "--protect":
            protected.append(v)
        else:
            return None
    if gate is None:
        return None
    for kind, fn in (("plain", render), ("chained", render_chained)):
        try:
            if fn(name, gate, protected, unconfigured, python).encode() == data:
                return kind
        except ValueError:
            return None
    return None


def _anchor_parts(root: Path, hooks: Path) -> tuple[Path, tuple[str, ...]]:
    common = git_common(root)
    anchors = [Path(os.path.abspath(root)), root.resolve()]
    if common is not None:
        anchors += [Path(os.path.abspath(common.parent)), common.parent.resolve()]
    hp = Path(os.path.abspath(hooks))
    inside = [a for a in anchors if a == hp or a in hp.parents]
    base = max(inside, key=lambda a: len(a.parts)) if inside else Path(hp.anchor)
    return base, hp.relative_to(base).parts


def git_common(root: Path) -> Path | None:
    from .fsutil import git_run

    c = git_run(root, "rev-parse", "--path-format=absolute", "--git-common-dir", text=True, safe_config=False)
    return Path(c.stdout.strip()) if c.returncode == 0 and c.stdout.strip() else None


def install(root: Path, protected: list[str], gate: str, force: bool, dry_run: bool = False,
            unconfigured: str = "skip", chain: bool = False) -> list[tuple[str, str]]:
    """Install the two hooks as one recorded transaction (S4): every change is planned first, the manifest is
    written next (recording the new bytes and accepting the ones they replace), then the hooks change, then the
    manifest is written again without the replaced bytes. A failure at any step leaves each hook recorded, so
    `steward hooks remove` or a new install recovers it."""
    import hashlib

    def sha(b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    hd = _HooksDir(root, create=not dry_run)
    out: list[tuple[str, str]] = []
    plan: list[tuple[str, bytes, bool, bool]] = []  # name, new bytes, chained, rename to .local first
    try:
        man = hd.manifest()
        for name in ("pre-commit", "pre-push"):
            local = f"{name}.local"
            present = hd.kind(name) is not None
            foreign = present and not hd.ours(name, man)
            move = False
            adopt = bool(chain and foreign and name not in man and hd.kind(name) == "file" and hd.kind(local) is not None
                         and legacy(name, hd.read(name)) == "chained")  # S4: a 0.9.0 chain, upgraded in place
            if adopt:
                foreign = False
            if chain and foreign:  # REQ-002: keep the adopter's hook (the link itself, never its target)
                if hd.kind(local) is not None:
                    out.append((name, f"refused: {local} exists; run `steward hooks remove` first"))
                    continue
                if dry_run:
                    out.append((name, f"would keep {name} as {local} and chain it before steward"))
                    continue
                move, foreign = True, False
            rec = man.get(name) if isinstance(man.get(name), dict) else {}
            was_chained = adopt or bool(present and not move and hd.ours(name, man) and rec.get("chained"))
            chained = move or ((chain or was_chained) and hd.kind(local) is not None)
            if hd.kind(local) is not None and not chained:
                out.append((name, f"refused: {local} exists and was not chained by steward; inspect it, then use "
                                  "--chain or remove it"))
                continue
            text = (render_chained if chained else render)(name, gate, protected, unconfigured)
            if hd.kind(name) == "link" and not move:  # N2: never write through a link
                out.append((name, f"refused: {hd.path / name} is a symlink; use --chain to keep it, or replace it by hand"))
                continue
            if foreign and not force:
                out.append((name, f"kept existing hook at {hd.path / name} (use --chain to run both, or --force to replace)"))
                continue
            if dry_run:
                out.append((name, f"would install at {hd.path / name} (gate {gate}; protected: {' '.join(protected) or 'none'})"))
                continue
            plan.append((name, text.encode("utf-8"), chained, move))
        if dry_run or not plan:
            return out
        final = dict(man)
        for name, data, chained, move in plan:
            local = f"{name}.local"
            rec = {"sha256": sha(data), "chained": chained}
            if chained:  # R5: the original that is chained is bound by hash, so removal restores only that file
                if move:
                    rec["local_sha256"] = sha(hd.read(name)) if hd.kind(name) == "file" else \
                        "link:" + sha(os.readlink(name, dir_fd=hd.fd).encode()) if hd.kind(name) == "link" else None
                else:
                    old = man.get(name) if isinstance(man.get(name), dict) else {}
                    rec["local_sha256"] = old.get("local_sha256", sha(hd.read(local)) if hd.kind(local) == "file" else None)
            final[name] = rec
        pending = {k: dict(v) for k, v in final.items()}
        for name, _, _, move in plan:
            # the bytes about to be replaced stay recognised until step 3, but only when they are steward's own: a
            # foreign hook replaced with --force is never recorded as steward's (U6, 0.13.0)
            if hd.kind(name) == "file" and not move and hd.ours(name, man):
                pending[name]["previous"] = sha(hd.read(name))
        hd.save_manifest(pending)  # step 1: the intent, before any hook changes
        for name, data, chained, move in plan:
            local = f"{name}.local"
            if move:
                hd.rename(name, local)
            hd.write(name, data, 0o755)
            out.append((name, f"installed at {hd.path / name}" + (f" (chained after {local})" if chained else "")))
        hd.save_manifest(final)  # step 3: the result
    finally:
        hd.close()
    return out


def remove(root: Path) -> list[tuple[str, str]]:
    """Remove steward's hooks; a chained hook's original goes back in place, byte for byte (it was only renamed),
    and only while it is the file that was chained (R5)."""
    import hashlib

    hd = _HooksDir(root, create=False)
    out = []
    try:
        man = hd.manifest()
        for name in ("pre-commit", "pre-push"):
            local = f"{name}.local"
            rec = man.get(name) if isinstance(man.get(name), dict) else {}
            if hd.kind(name) is not None and not hd.ours(name, man):
                out.append((name, "not installed by steward; left as it is"))
                continue
            was_chained = bool(rec.get("chained"))
            if hd.kind(name) is None:
                if rec.get("chained") and hd.kind(local) is not None and _local_matches(hd, local, rec):
                    hd.rename(local, name)  # S4: an install interrupted after keeping the original, before the wrapper
                    man.pop(name, None)
                    out.append((name, f"{local} restored as {name} (the install had not finished)"))
                    continue
                man.pop(name, None)
                out.append((name, "nothing to remove" + (f"; {local} left in place (steward did not chain it)"
                                                         if hd.kind(local) is not None else "")))
                continue
            if was_chained and hd.kind(local) is not None and _local_matches(hd, local, rec):
                # U6 (0.13.0): one atomic rename puts the original back over the wrapper; a failure leaves both active
                hd.rename(local, name)
                man.pop(name, None)
                out.append((name, f"removed; {local} restored as {name}"))
                continue
            hd.unlink(name)
            man.pop(name, None)
            if was_chained and hd.kind(local) is not None:  # Q7, K3: restored only behind steward's recorded wrapper
                out.append((name, f"removed; {local} changed since it was chained, so it is left in place: "
                                  f"inspect it, then rename it to {name} yourself"))
            else:
                out.append((name, "removed"))
        if man:
            hd.save_manifest(man)
        elif hd.kind(MANIFEST) == "file":
            hd.unlink(MANIFEST)
    finally:
        hd.close()
    return out


def _local_matches(hd: _HooksDir, local: str, rec: dict[str, Any]) -> bool:
    """The kept original is the one recorded (a link is compared as a link, never followed). A record from before
    0.12.0 has no hash and is trusted as before."""
    import hashlib

    if "local_sha256" not in rec:
        return True
    want = rec.get("local_sha256")
    k = hd.kind(local)
    if k == "link":  # U6: a link is the same link only while it points at the same target text
        if want is None:  # a chain recorded by 0.12.0 bound a linked original as null: restored as then (U6, 0.14.0)
            return True
        return want == "link:" + hashlib.sha256(os.readlink(local, dir_fd=hd.fd).encode()).hexdigest()
    return k == "file" and want == hashlib.sha256(hd.read(local)).hexdigest()


# ---------------------------------------------------------------- run time
def _quiet(report_text: str, gate: str) -> str:
    keep = [l for l in report_text.splitlines()
            if l.startswith(("FAIL ", "INCOMPLETE ", "UNKNOWN ", "Summary:")) or l.startswith(f"Gate {gate}")]
    return "\n".join(keep)


def _check(root: Path, gate: str) -> tuple[int, str]:
    from .engine import UnknownGate, run_check
    from .report import render_summary
    from .status import gate_exit_code

    try:
        rep = run_check(root, gate=gate)
    except UnknownGate:
        return 64, f"steward: unknown gate {gate!r}"
    g = next(x for x in rep["verdict"]["gates"] if x["name"] == rep["_gate"])
    return gate_exit_code(g), render_summary(rep)


def run_pre_commit(cwd: Path, gate: str) -> int:
    from .fsutil import git_run

    top = git_run(cwd, "rev-parse", "--show-toplevel", text=True)
    root = Path(top.stdout.strip()) if top.returncode == 0 else cwd
    if not (root / "steward.toml").is_file():
        print("steward: no steward.toml in this checkout; pre-commit check skipped", file=sys.stderr)
        return 0
    code, text = _check(root, gate)
    if code == 1:
        print(text)
        print(f"steward: commit blocked: gate '{gate}' has a FAIL (see above). Fix it, or skip consciously with --no-verify.",
              file=sys.stderr)
        return 1
    if code == 64:
        print(text, file=sys.stderr)
        return 1
    quiet = _quiet(text, gate)
    if quiet:
        print(quiet)
    return 0


BATCH_COUNT = 256                # blobs per `cat-file --batch` read (review O2)
BATCH_BYTES = 64 << 20           # and bytes per read (0.9.0 A5)
MAX_BLOB_BYTES = 256 << 20       # a larger blob refuses the push


def _fold(rel: str) -> str:
    """The form under which two names are one entry on a case-insensitive or normalising volume (0.9.0 A5)."""
    return unicodedata.normalize("NFC", rel).casefold()


def _tip_contexts(root: Path, sha: str) -> list[str]:
    """The container build contexts the pushed tip's own steward.toml declares (read as data, never run)."""
    import tomllib

    from . import fsutil

    cfg = fsutil.git_run(root, "show", f"{sha}:steward.toml")
    try:
        c = tomllib.loads(cfg.stdout.decode("utf-8")).get("containers", {}) if cfg.returncode == 0 else {}
    except (ValueError, RecursionError, UnicodeDecodeError):
        return []
    ctxs = c.get("contexts", []) if isinstance(c, dict) else []
    out = []
    for x in ctxs:  # R15: compared in git's own spelling: ./svc and svc/ are svc; "." is the whole tree
        if isinstance(x, str):
            n = posixpath.normpath(x.replace("\\", "/")).lstrip("/")
            out.append("" if n in (".", "") else n)
    return out


def materialize(root: Path, sha: str, dest: Path) -> None:
    """Write the commit's tree into `dest` from raw blobs: no filters, textconv, hooks or checkout (N1). Every path
    is checked before the first write: components, links under `exchange/` (in any case), and names that would
    collapse into one entry on a case-insensitive or normalising volume. Blob reads are bounded by count and bytes."""
    from . import fsutil

    out = fsutil.git_run(root, "ls-tree", "-r", "-z", "--full-tree", sha)
    if out.returncode != 0:
        raise RuntimeError(f"cannot list the tree of {sha}")
    entries, seen = [], {}
    contexts = _tip_contexts(root, sha)
    for rec in out.stdout.split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, kind, obj = meta.split()
        rel = path.decode("utf-8", errors="surrogateescape")
        parts = Path(rel).parts
        if not parts or Path(rel).is_absolute() or ".." in parts or any(_fold(p) == ".git" for p in parts):
            raise RuntimeError(f"{sha[:12]} names an unsafe path")
        for i in range(1, len(parts) + 1):  # every prefix: a file `a` and a directory `A/` collide too
            name = "/".join(parts[:i])
            other = seen.setdefault(_fold(name), name)
            if other != name:
                raise RuntimeError(f"{sha[:12]}: paths {other!r} and {name!r} collide on a case-insensitive or "
                                   "normalising volume")
        if kind == b"blob" and mode in (b"100644", b"100755"):
            entries.append((rel, obj.decode(), mode == b"100755"))
        elif mode == b"120000":  # links are not materialized; the exchange folder holds none (review O2, A5)
            if _fold(parts[0]) == "exchange":
                raise RuntimeError(f"{sha[:12]} has a symbolic link under exchange/: {rel}")
            inside = next((c or "." for c in contexts if c == "" or rel == c or rel.startswith(c + "/")), None)
            if inside is not None:  # Q25: links are not staged, so R-64 could not see this one
                raise RuntimeError(f"{sha[:12]} has a symbolic link inside the build context {inside}: {rel}")
            print(f"steward: note: {rel} is a symbolic link in {sha[:12]}; not materialized for the check", file=sys.stderr)
    sizes = {}
    if entries:
        check = fsutil.git_run(root, "cat-file", "--batch-check", input=b"".join(o.encode() + b"\n" for _, o, _ in entries),
                               timeout=600)
        if check.returncode != 0:
            raise RuntimeError(f"cannot read the blob sizes of {sha}")
        for line in check.stdout.splitlines():
            f = line.split()
            if len(f) != 3:
                raise RuntimeError(f"cannot read the blob sizes of {sha}")
            sizes[f[0].decode()] = int(f[2])
    for rel, obj, _ in entries:
        if sizes.get(obj, MAX_BLOB_BYTES + 1) > MAX_BLOB_BYTES:
            raise RuntimeError(f"{sha[:12]}: {rel} is larger than {MAX_BLOB_BYTES >> 20} MiB; not staged")
    batches, cur, cur_bytes = [], [], 0
    for e in entries:
        if cur and (len(cur) >= BATCH_COUNT or cur_bytes + sizes[e[1]] > BATCH_BYTES):
            batches.append(cur)
            cur, cur_bytes = [], 0
        cur.append(e)
        cur_bytes += sizes[e[1]]
    if cur:
        batches.append(cur)
    for chunk in batches:
        batch = fsutil.git_run(root, "cat-file", "--batch", input=b"".join(o.encode() + b"\n" for _, o, _ in chunk), timeout=600)
        if batch.returncode != 0:
            raise RuntimeError(f"cannot read the blobs of {sha}")
        data, pos = batch.stdout, 0
        for rel, obj, executable in chunk:
            nl = data.index(b"\n", pos)
            size = int(data[pos:nl].split()[2])
            blob = data[nl + 1: nl + 1 + size]
            pos = nl + 1 + size + 1
            target = dest.joinpath(*Path(rel).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            if executable:
                target.chmod(0o755)


def _release_branch(root: Path) -> tuple[str, str, str] | None:
    """The invoking checkout's `[branches] release` and its tag pattern, or None (read without validating the rest)."""
    import tomllib

    try:
        b = tomllib.loads((root / "steward.toml").read_text(encoding="utf-8")).get("branches", {})
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    rel, pat, on = b.get("release"), b.get("tag_pattern", "v*"), b.get("release_tag_on", "commit")
    return (rel, pat, on if on in ("commit", "merged-parent") else "commit") \
        if isinstance(rel, str) and rel and isinstance(pat, str) else None


def checkout_pinned(root: Path) -> str | None:
    """Where a trust root for the invoking checkout is pinned ("env", "user", "user-checkout"), or None: an env
    trust root, a per-user pin recorded for this checkout, or a pin for the repo_id of its own steward.toml
    (0.9.0 A1). A steward.toml that cannot be read is read as pinned only through the other two."""
    import tomllib
    from types import SimpleNamespace

    from .authorize import pinned_trust_exists

    rid = None
    try:
        rid = tomllib.loads((root / "steward.toml").read_text(encoding="utf-8")).get("steward", {}).get("repo_id")
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        pass
    cfg = SimpleNamespace(steward=SimpleNamespace(repo_id=rid if isinstance(rid, str) and rid else "\0none"))
    return pinned_trust_exists(cfg, root)


def _remove_worktree(root: Path, wt: Path) -> bool:
    """Remove the staged worktree and its registration; True when it is gone."""
    from . import fsutil

    if fsutil.git_run(root, "worktree", "remove", "--force", str(wt)).returncode == 0:
        fsutil.git_run(root, "worktree", "prune")
        return True
    fsutil.git_run(root, "worktree", "prune")
    listed = fsutil.git_run(root, "worktree", "list", "--porcelain", text=True)
    names = {Path(l[len("worktree "):]).resolve() for l in listed.stdout.splitlines() if l.startswith("worktree ")}
    return listed.returncode == 0 and wt.resolve() not in names


def _authorization_push(root: Path, local_ref: str, remote_ref: str, local_sha: str) -> str | None:
    """Why a pushed `steward/auth/*` or `steward/anchor/*` tag is refused, or None. The object pushed must be the local
    tag of that same name, and that tag a signed record of this repository under the pinned trust root (U2)."""
    from . import authorize as az
    from .fsutil import git_run
    from .models import load_config

    if local_ref != remote_ref:
        return f"pushed as {remote_ref}; an authorization tag is pushed under its own name"
    tag = local_ref[len("refs/tags/"):]
    obj = git_run(root, "rev-parse", "--verify", "--quiet", local_ref, text=True)
    if obj.returncode != 0 or obj.stdout.strip() != local_sha:
        return "the object pushed is not the local tag of that name"
    try:
        cfg = load_config(root)
    except Exception:  # noqa: BLE001 - any configuration error is a refusal, never a skipped check
        return "steward.toml cannot be read, so the signature cannot be checked"
    if cfg.policy is None:
        return "no [policy] table: there is no signer list to verify it against"
    try:
        az.verify_record(root, cfg, tag)
    except az.AuthError as e:
        return f"not a verified authorization ({e.step}: {e.message})"
    return None


def run_pre_push(cwd: Path, gate: str, protected: list[str], unconfigured: str, lines: list[str]) -> int:
    from .fsutil import git_run

    top = git_run(cwd, "rev-parse", "--show-toplevel", text=True)
    root = Path(top.stdout.strip()) if top.returncode == 0 else cwd
    status = 0
    for line in lines:
        parts = line.split()
        if len(parts) != 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts
        branch = remote_ref[len("refs/heads/"):] if remote_ref.startswith("refs/heads/") else remote_ref
        if set(local_sha) == {"0"}:
            if branch in protected:
                print(f"steward: push refused: deleting protected branch '{branch}'", file=sys.stderr)
                return 1
            continue
        if branch in protected and set(remote_sha) != {"0"}:
            if git_run(root, "merge-base", "--is-ancestor", remote_sha, local_sha).returncode != 0:
                print(f"steward: push refused: force-push to protected branch '{branch}'", file=sys.stderr)
                return 1
        reserved = ("refs/tags/steward/auth/", "refs/tags/steward/anchor/")
        if local_ref.startswith(reserved) or remote_ref.startswith(reserved):
            # DEF-013, U2: a signed record is verified as one (the object pushed, under its own name); the gate is
            # never run on the commit it was signed on
            why = _authorization_push(root, local_ref, remote_ref, local_sha)
            if why:
                print(f"steward: push refused: {local_ref}: {why}", file=sys.stderr)
                status = 1
            continue
        release = _release_branch(root)
        if release and branch == release[0]:  # 0.9.0 B6 (REQ-009): the release branch carries only tagged commits
            from .process import release_tip_tagged

            if not release_tip_tagged(root, local_sha, release[1], release[2]):
                print(f"steward: push refused: the tip of release branch '{branch}' ({local_sha[:12]}) is not tagged "
                      f"(a tag matching {release[1]!r})", file=sys.stderr)
                return 1
        if git_run(root, "cat-file", "-e", f"{local_sha}:steward.toml").returncode != 0:
            pinned = checkout_pinned(root)
            if pinned:  # 0.9.0 A1 (P1): signed policy applies to every gate, so a pinned checkout never skips
                print(f"steward: push refused: {local_ref} has no steward.toml, and this checkout's policy is pinned "
                      f"({pinned})", file=sys.stderr)
                status = 1
            elif unconfigured == "refuse":
                print(f"steward: push refused: {local_ref} has no steward.toml", file=sys.stderr)
                status = 1
            else:
                print(f"steward: {local_ref} has no steward.toml; gate not checked", file=sys.stderr)
            continue
        with tempfile.TemporaryDirectory(prefix="steward-push-") as tmp:
            import json as _json

            # R4 (0.12.0): who owns this staged worktree, so `session close --end` removes only its own, ended ones
            (Path(tmp) / "owner.json").write_text(_json.dumps({"root": str(root.resolve()), "pid": os.getpid()}))
            wt = Path(tmp) / "wt"
            added = git_run(root, "worktree", "add", "--no-checkout", "--detach", str(wt), local_sha)
            try:
                if added.returncode != 0:
                    print(f"steward: push refused: cannot stage {local_ref} for checking", file=sys.stderr)
                    status = 1
                    continue
                if git_run(wt, "read-tree", local_sha).returncode != 0:  # the index only; review O2: a failure refuses
                    raise RuntimeError("cannot load the index of the pushed commit")
                materialize(root, local_sha, wt)
                from .authorize import checkout_hint

                with checkout_hint(root):  # review O4: the staged copy is judged against this checkout's pin
                    code, _ = _check(wt, gate)
            except (RuntimeError, OSError) as e:
                print(f"steward: push refused: {local_ref}: {e}", file=sys.stderr)
                status = 1
                continue
            finally:
                if not _remove_worktree(root, wt):  # DEF-003: a failed cleanup is not a silent pass
                    print(f"steward: push refused: could not remove the temporary worktree {wt} "
                          "(run: git worktree prune)", file=sys.stderr)
                    status = 1
            if code != 0:
                print(f"steward: push refused: gate '{gate}' is not eligible for {local_ref} ({local_sha[:12]})", file=sys.stderr)
                status = 1
    return status
