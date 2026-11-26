"""Pinned-dependency retirement (0.17.0; REQ-019; Muiz, 2026-11-24: "deprecated soon").

A project may keep several versions of one library side by side, because frozen records depend on the exact version
that produced them. Each pin is declared (`[[pin]]` in steward.toml) with what it protects and when it may go.

**States.** `active` → `deprecated` (declared with a reason; still installed, reported while anything uses it) →
`retire-eligible` (computed) → `retiring` (the plan is recorded, removal under way or interrupted) → `retired`. A
retired pin can be restored; it counts as restored only once its own check passes.

**Retire = keep the artifact, drop the install.** `steward pins retire NAME` needs a signed, single-use `pin.retire`
approval for exactly this **plan**: the pin, its version, its artifact path and bytes, every install path with every
file under it, and the keep location (review of 0.17.0, Z3). The steps, under one lock (Z4):
1. check the plan's layout (no links, no overlap with git, the keep folder or other pins; Z1) and that the plan
   still equals the approved one;
2. write the kept artifact, its manifest and its checksum inside the held keep folder, and read them back;
3. record the plan as `retiring` in the pins ledger, with the approval's nonce (Z2, Z5), and only then consume it;
4. remove each planned path through its held parent folder, after checking it is the planned file or folder;
5. record `retire`. An interruption leaves `retiring`; `steward pins retire NAME --resume` finishes the same plan.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

from .fsutil import git_run


class PinError(ValueError):
    pass


def settings(cfg: Any) -> Any:
    from .models import PinsSection

    return cfg.pins or PinsSection()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _real_inside(root: Path, rel: str) -> Path:
    """`root/rel`, refused when any component is a link (its real path must be its own)."""
    p = root / rel
    if os.path.realpath(p) != os.path.join(os.path.realpath(root), os.path.normpath(rel)):
        raise PinError(f"{rel} is reached through a link; refused")
    return p


def inventory(root: Path, rel: str) -> list[dict[str, Any]]:
    """Every entry under a planned path (Z10): files with digests, links with targets, folders (empty ones too)."""
    p = _real_inside(root, rel)
    if not os.path.lexists(p):
        return []
    st = p.lstat()
    if stat.S_ISLNK(st.st_mode):
        return [{"path": rel, "link": os.readlink(p)}]
    if not stat.S_ISDIR(st.st_mode):
        return [{"path": rel, "sha256": sha_file(p)}]
    out = [{"path": rel, "dir": True}]

    def boom(err: OSError) -> None:  # AA5 (0.17.0): an unreadable tree is never a smaller inventory
        raise PinError(f"{rel} cannot be read completely ({type(err).__name__}); refused")
    for dirpath, dirnames, filenames in os.walk(p, followlinks=False, onerror=boom):
        dirnames.sort()
        for n in sorted(dirnames) + sorted(filenames):
            q = Path(dirpath) / n
            r = q.relative_to(root).as_posix()
            if q.is_symlink():
                out.append({"path": r, "link": os.readlink(q)})
            elif q.is_dir():
                out.append({"path": r, "dir": True})
            elif q.is_file():
                out.append({"path": r, "sha256": sha_file(q)})
            else:
                out.append({"path": r, "other": True})
    return out


def plan(root: Path, cfg: Any, spec: Any) -> dict[str, Any]:
    """The retirement plan a `pin.retire` approval signs (Z3); refuses an unsafe layout before anything happens (Z1)."""
    keep = f"{settings(cfg).keep_dir.rstrip('/')}/{spec.name}"
    art = _real_inside(root, spec.artifact)
    if not art.is_file() or art.is_symlink():
        raise PinError(f"the artifact {spec.artifact} is not a plain file here")
    if Path(spec.artifact).name in ("manifest.json",) or Path(spec.artifact).name.endswith(".sha256"):
        raise PinError("the artifact's name collides with the kept manifest or checksum")

    def overlaps(a: str, b: str) -> bool:  # AA4 (0.17.0): compared as normalized paths, never as spellings
        a, b = os.path.normpath(a), os.path.normpath(b)
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")
    others = [p for p in cfg.pin if p.name != spec.name]
    for o in others:  # AA4: the keep destination never lands on another pin's files or a protected record
        if any(overlaps(keep, x) for x in [o.artifact, *o.install, *o.protects, f"{settings(cfg).keep_dir}/{o.name}"]):
            raise PinError(f"the keep folder {keep} overlaps the pin {o.name}; refused")
    if any(overlaps(keep, x) for x in spec.protects):
        raise PinError(f"the keep folder {keep} overlaps a record this pin protects; refused")
    for rel in [*spec.install, spec.artifact]:
        if rel.split("/")[0] in (".git", ".steward") or rel in ("steward.toml",) or overlaps(rel, keep) or \
                overlaps(rel, settings(cfg).ledger) or overlaps(rel, settings(cfg).keep_dir):
            raise PinError(f"{rel} overlaps git, the toolkit's records or the keep folder; refused")
        for o in others:
            if any(overlaps(rel, x) for x in [o.artifact, *o.install, *o.protects]):
                raise PinError(f"{rel} overlaps the pin {o.name}; refused")
        if any(overlaps(rel, x) for x in spec.protects):
            raise PinError(f"{rel} overlaps a record this pin protects; refused")
    artifact_sha = sha_file(art)
    if spec.sha256 and spec.sha256 != artifact_sha:
        raise PinError("the artifact's digest is not the declared sha256")
    remove = []
    for rel in sorted(set([*spec.install, spec.artifact])):
        remove += inventory(root, rel)
    if any(e.get("other") for e in remove):  # AA5: only files, links and folders are retired
        raise PinError("an install path holds something other than files, links and folders; refused")
    doc = {"pin": spec.name, "package": spec.package, "version": spec.version, "artifact": spec.artifact,
           "artifact_sha256": artifact_sha, "keep": keep, "roots": sorted(set([*spec.install, spec.artifact])),
           "remove": remove}
    doc["object"] = "sha256:" + sha_bytes(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())
    return doc


def ledger_entries(root: Path, cfg: Any) -> list[dict[str, Any]]:
    from .ledger import verify

    p = root / settings(cfg).ledger
    if not p.is_file():
        return []
    v = verify(p)
    if v.errors or v.torn_tail:
        raise PinError(f"the pins ledger {settings(cfg).ledger} is not intact")
    return v.entries


def last_event(entries: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((e for e in reversed(entries) if e.get("pin") == name
                 and e.get("kind") in ("retiring", "retire", "restore")), None)


class _Unavailable(Exception):
    """Caller evidence cannot be read: the pin is never eligible on it (Z7, AB1)."""


def _tracked(root: Path) -> list[tuple[str, str]] | None:
    """(mode, path) of every tracked entry, from the index (AB1, 0.18.0): its kind comes from git, not from what the
    working tree shows now. None when git fails."""
    out = git_run(root, "ls-files", "-s", "-z")
    if out.returncode != 0:
        return None
    rows = []
    for rec in out.stdout.split(b"\0"):
        if not rec:
            continue
        meta, _, name = rec.partition(b"\t")
        rows.append((meta.split()[0].decode(), name.decode("utf-8", "surrogateescape")))
    return rows


def _entry(root: Path, rel: str) -> tuple[str, bytes]:
    """What the working tree holds at a tracked path, reached through its folders one at a time without following any
    link (AB1): ("file", bytes), ("link", b"") or ("missing", b""). Anything else (a folder, a FIFO, a device) and any
    path reached through a linked folder is unavailable evidence. A regular file is opened non-blocking and checked
    to be the entry just classified, so a FIFO swapped in never stalls the scan (AC2)."""
    import os

    from .fsutil import LinkRefused, open_dir_beneath

    parts = rel.split("/")
    try:
        dfd = open_dir_beneath(root, parts[:-1])
    except LinkRefused:
        raise _Unavailable(rel) from None
    try:
        try:
            st = os.stat(parts[-1], dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            return "missing", b""
        except OSError:
            raise _Unavailable(rel) from None
        if stat.S_ISLNK(st.st_mode):
            return "link", b""
        if not stat.S_ISREG(st.st_mode):
            raise _Unavailable(rel)
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
                         dir_fd=dfd)
        except OSError:
            raise _Unavailable(rel) from None
    finally:
        os.close(dfd)
    try:
        now = os.fstat(fd)
        if not stat.S_ISREG(now.st_mode) or (now.st_dev, now.st_ino) != (st.st_dev, st.st_ino):
            raise _Unavailable(rel)
        chunks = []
        while True:
            b = os.read(fd, 1 << 20)
            if not b:
                break
            chunks.append(b)
        return "file", b"".join(chunks)
    except OSError:
        raise _Unavailable(rel) from None
    finally:
        os.close(fd)


def _scanned(root: Path, skip: list[str], suffix: str | None = None) -> list[tuple[str, bytes]] | None:
    """(path, bytes) of every tracked file outside `skip` whose working-tree entry holds text. A gitlink (a submodule)
    is left out by its index mode. A tracked symbolic link is left out while it is still a link, and scanned when a
    regular file has replaced it (AC1). A tracked regular file must still be one: missing, a folder, a link or
    anything else makes the evidence unavailable (None), never "no callers"."""
    rows = _tracked(root)
    if rows is None:
        return None
    out = []
    try:
        for mode, f in rows:
            if suffix is not None and not f.endswith(suffix):
                continue
            if mode == "160000" or any(f == o or f.startswith(o + "/") for o in skip):
                continue
            kind, data = _entry(root, f)
            if kind == "file":
                out.append((f, data))
            elif mode != "120000":  # a regular file in the index that is now a link or gone
                raise _Unavailable(f)
    except _Unavailable:
        return None
    return out


def _module_callers(root: Path, spec: Any) -> list[str] | None:
    """Tracked Python files (outside the pin's own install paths) that import the pin's module; None when the
    evidence is unavailable (no `module`, git failed, a file unreadable): never "no callers" then (Z7)."""
    if not spec.module:
        return None
    files = _scanned(root, [p.rstrip("/") for p in spec.install], ".py")
    if files is None:
        return None
    mod = re.escape(spec.module)
    rx_from = re.compile(rf"^\s*from\s+{mod}(?:\.\S+)?\s+import\b", re.M)
    rx_import = re.compile(r"^\s*import\s+([^\n#]+)", re.M)
    rx_dyn = re.compile(rf"import_module\(\s*['\"]{mod}(?:\.[\w.]+)?['\"]")
    found = []
    for f, data in files:
        try:  # AC1: universal newlines, as a text read gives (CRLF and CR files import the same)
            text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            return None
        names = [n.strip().split(" as ")[0].strip() for m in rx_import.finditer(text) for n in m.group(1).split(",")]
        if rx_from.search(text) or rx_dyn.search(text) or any(n == spec.module or n.startswith(spec.module + ".")
                                                               for n in names):
            found.append(f)
    return sorted(found)


def _reference_callers(root: Path, cfg: Any, spec: Any) -> list[str] | None:
    """Tracked files that mention one of the pin's `references` (REQ-020): a byte scan, so any text encoding and
    any language counts. Outside the scan: the pin's own install paths and artifact, the records it protects (the
    `protects` condition covers them), and the toolkit's own records (steward.toml, the pins ledger, the keep folder),
    which name the references themselves. None when the evidence is unavailable (git failed, a file unreadable or
    no longer the regular file the index names)."""
    s = settings(cfg)
    skip = [p.rstrip("/") for p in [*spec.install, spec.artifact, *spec.protects, s.ledger, s.keep_dir,
                                     "steward.toml", "steward.local.toml"]]
    files = _scanned(root, skip)
    if files is None:
        return None
    needles = [r.encode("utf-8") for r in spec.references]
    return sorted(f for f, data in files if any(n in data for n in needles))


def caller_detail(root: Path, cfg: Any, spec: Any) -> list[dict[str, Any]] | None:
    """Every caller with the rule that found it (`module`, `reference`) and whether an `ignore_callers` glob makes it
    a listed but not blocking caller (`ignored`). None when any scan the pin's rule needs is unavailable: an ignored
    file must still be readable, so unavailable evidence is never hidden by a glob (REQ-020)."""
    from .fsutil import glob_match

    rule = spec.caller_rule
    via: dict[str, str] = {}
    if rule in ("module", "both"):
        mod = _module_callers(root, spec)
        if mod is None:
            return None
        via.update({f: "module" for f in mod})
    if rule in ("references", "both"):
        ref = _reference_callers(root, cfg, spec)
        if ref is None:
            return None
        for f in ref:
            via[f] = "module+reference" if via.get(f) == "module" else "reference"
    return [{"path": f, "via": v, **({"ignored": True} if any(glob_match(f, g) for g in spec.ignore_callers) else {})}
            for f, v in sorted(via.items())]


def callers(root: Path, cfg: Any, spec: Any) -> list[str] | None:
    """The callers that block retirement: every caller not matched by `ignore_callers`; None when the evidence is
    unavailable (Z7)."""
    detail = caller_detail(root, cfg, spec)
    return None if detail is None else [d["path"] for d in detail if not d.get("ignored")]


def conditions(root: Path, cfg: Any, spec: Any, entries: list[dict[str, Any]]) -> list[tuple[str, bool, str]]:
    """(condition, holds, why): the declared `retire_when` conditions, and the ones that always apply (Z6)."""
    out = []
    pins = {p.name: p for p in cfg.pin}
    who = callers(root, cfg, spec)
    if who is None:  # Z6, Z7: callers always count, and unavailable evidence blocks
        out.append(("callers", False, "who uses it cannot be told (declare `module` or `references`; git and every "
                    "file readable)"))
    else:
        out.append(("callers", not who, "no tracked code uses it" if not who else f"used by {', '.join(who[:5])}"))
    if spec.protects and not any(c.startswith("after:") for c in spec.retire_when):  # Z6: protected records
        out.append(("protects", False, "it protects records: add an after:<record> or after:milestone:<id> condition"))
    for c in spec.retire_when:
        if c == "never":
            out.append((c, False, "declared never to retire"))
        elif c == "no_callers":
            continue  # covered by the callers check above
        elif c.startswith("superseded_by:"):
            v = c.split(":", 1)[1]
            newer = [p for p in pins.values() if p.package == spec.package and p.version == v and p.name != spec.name
                     and state(root, cfg, p, entries)[0] in ("active", "deprecated", "retire-eligible")
                     and (root / p.artifact).is_file()]  # Z6: installed, with its artifact present
            out.append((c, bool(newer), f"{spec.package} {v} is pinned with its artifact present" if newer else
                        f"no pin of {spec.package} {v} with its artifact present"))
        elif c.startswith("after:milestone:"):
            mid = c.split(":", 2)[2]
            from . import milestones as ms

            try:
                mf = ms.load(root)
            except Exception:  # noqa: BLE001
                mf = None
            m = next((x for x in (mf.milestone if mf else []) if x.id == mid), None)
            met = bool(m and m.outcome and m.outcome.state == "met")
            out.append((c, met, f"milestone {mid} is recorded as met" if met else f"milestone {mid} is not recorded as met"))
        elif c.startswith("after:"):
            rel = c.split(":", 1)[1]
            ok = (root / rel).is_file()
            out.append((c, ok, f"{rel} exists" if ok else f"{rel} does not exist yet"))
    return out


def state(root: Path, cfg: Any, spec: Any, entries: list[dict[str, Any]]) -> tuple[str, list[str]]:
    last = last_event(entries, spec.name)
    if last and last["kind"] == "retiring":
        return "retiring", ["a retirement was interrupted: finish it with steward pins retire NAME --resume"]
    if last and last["kind"] == "retire":
        return "retired", [f"retired; artifact kept at {last.get('kept')}"]
    if spec.deprecated is None:
        return "active", ["not deprecated: declare deprecated = { reason = … } first"]
    conds = conditions(root, cfg, spec, entries)
    if conds and all(ok for _, ok, _ in conds):
        return "retire-eligible", [why for _, _, why in conds]
    return "deprecated", [f"waiting: {why}" for _, ok, why in conds if not ok]


def status(root: Path, cfg: Any) -> list[dict[str, Any]]:
    entries = ledger_entries(root, cfg)
    rows = []
    for spec in cfg.pin:
        st, why = state(root, cfg, spec, entries)
        row = {"name": spec.name, "package": spec.package, "version": spec.version, "state": st, "reasons": why,
               "protects": list(spec.protects)}
        if st not in ("retired", "retiring"):
            detail = caller_detail(root, cfg, spec)  # REQ-020: which rule found each caller
            row["callers"] = None if detail is None else [d["path"] for d in detail if not d.get("ignored")]
            row["caller_rule"] = spec.caller_rule
            row["caller_detail"] = detail
        if spec.deprecated is not None:
            row["deprecated"] = spec.deprecated.model_dump()
        if st == "retire-eligible":
            try:
                row["object"] = plan(root, cfg, spec)["object"]
            except PinError as e:
                row["state"], row["reasons"] = "deprecated", [f"its retirement plan is refused: {e}"]
        rows.append(row)
    return rows


# ---------------------------------------------------------------- retirement
def _held_parent(root: Path, rel: str) -> int:
    from .fsutil import LinkRefused, open_dir_beneath

    try:
        return open_dir_beneath(root, tuple(Path(rel).parent.parts))
    except LinkRefused:
        raise PinError(f"the folder of {rel} is reached through a link; refused") from None


def _write_kept(root: Path, keep: str, name: str, data: bytes, doc: dict[str, Any]) -> None:
    """The artifact, its manifest and its checksum, inside the held keep folder, read back (Z1)."""
    from .fsutil import LinkRefused, open_dir_beneath
    from .release import write_in_dir

    try:
        dfd = open_dir_beneath(root, tuple(Path(keep).parts), create=True)
    except LinkRefused:
        raise PinError(f"{keep} is reached through a link; refused") from None
    try:
        files = {name: data,
                 "manifest.json": (json.dumps({"schema": "steward.pin_manifest/0.1", **{k: doc[k] for k in (
                     "pin", "package", "version", "artifact", "artifact_sha256")}, "object": doc["object"]},
                     indent=2) + "\n").encode(),
                 f"{name}.sha256": f"{doc['artifact_sha256']}  {name}\n".encode()}
        for n, b in files.items():
            write_in_dir(dfd, n, b)
        for n, b in files.items():  # every kept file is read back before anything is removed
            fd = os.open(n, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
            with os.fdopen(fd, "rb") as f:
                if f.read() != b:
                    raise PinError(f"the kept {n} does not read back as written; nothing was removed")
    finally:
        os.close(dfd)


def _verify_kept(root: Path, doc: dict[str, Any]) -> None:
    kept = f"{doc['keep']}/{Path(doc['artifact']).name}"
    try:
        p = _real_inside(root, kept)
        ok = p.is_file() and not p.is_symlink() and sha_file(p) == doc["artifact_sha256"]
    except PinError:
        ok = False
    if not ok:
        raise PinError(f"the kept artifact {kept} is missing or changed; nothing more was removed")


def _remove(root: Path, entry: dict[str, Any]) -> None:
    """Remove one planned root, through its held parent, only while it is what the plan recorded."""
    rel = entry["path"]
    pfd = _held_parent(root, rel)
    try:
        name = Path(rel).name
        try:
            st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
        except FileNotFoundError:
            if entry.get("dir"):  # AA3: a folder moved aside and partly removed by an interrupted run
                aside = _aside_name(name, entry)
                try:
                    os.stat(aside, dir_fd=pfd, follow_symlinks=False)
                except FileNotFoundError:
                    return
                _remove_aside(root, rel, aside, entry, pfd, partial=True)
            return  # already removed (a resumed retirement)
        if entry.get("dir"):
            if not stat.S_ISDIR(st.st_mode):
                raise PinError(f"{rel} is no longer the planned folder; stopped")
            aside = _aside_name(name, entry)
            # AA5 (0.17.0): moved aside first (atomic, a name only this plan uses), then checked and removed there
            os.rename(name, aside, src_dir_fd=pfd, dst_dir_fd=pfd)
            _remove_aside(root, rel, aside, entry, pfd)
        elif "link" in entry:
            if not stat.S_ISLNK(st.st_mode) or os.readlink(name, dir_fd=pfd) != entry["link"]:
                raise PinError(f"{rel} is no longer the planned link; stopped")
            os.unlink(name, dir_fd=pfd)
        else:
            if not stat.S_ISREG(st.st_mode):
                raise PinError(f"{rel} is no longer the planned file; stopped")
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=pfd)
            with os.fdopen(fd, "rb") as f:
                if sha_bytes(f.read()) != entry["sha256"]:
                    raise PinError(f"{rel} changed since the plan; stopped")
            os.unlink(name, dir_fd=pfd)
    finally:
        os.close(pfd)


def _aside_name(name: str, entry: dict[str, Any]) -> str:
    return f".{name}.steward-retire-{entry['_plan'][7:23]}"


def _remove_aside(root: Path, rel: str, aside: str, entry: dict[str, Any], pfd: int, partial: bool = False) -> None:
    """The moved folder holds exactly the planned entries (all of them, or for a resumed run a subset with the
    planned bytes); then it goes. Anything else stops the retirement and is left in place."""
    arel = (Path(rel).parent / aside).as_posix() if Path(rel).parent.as_posix() != "." else aside
    now = inventory(root, arel)
    planned = {e["path"][len(rel):]: e for e in entry["_tree"]}
    seen = {e["path"][len(arel):]: e for e in now}
    if any(k not in planned or {x: y for x, y in v.items() if x != "path"} !=
           {x: y for x, y in planned[k].items() if x != "path"} for k, v in seen.items()) or \
            (not partial and set(seen) != set(planned)):
        raise PinError(f"{rel} is not the planned folder (moved aside as {arel}, left in place); stopped")
    shutil.rmtree(aside, dir_fd=pfd)


def _roots(doc: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in doc["roots"]:
        entries = [e for e in doc["remove"] if e["path"] == r or e["path"].startswith(r.rstrip("/") + "/")]
        head = next((e for e in entries if e["path"] == r), None)
        if head is not None:
            out.append({**head, "_tree": entries, "_plan": doc["object"]})
    return out


def retire(root: Path, cfg: Any, name: str, verified: Any, consume, resume: bool = False) -> dict[str, Any]:
    from .fsutil import owner_lock, release_owner_lock
    from .ledger import Ledger

    lock = owner_lock(root, "pins")  # Z4: one retirement or restore at a time
    if lock is None:
        raise PinError("another pins command is running; nothing was done")
    try:
        spec = next((p for p in cfg.pin if p.name == name), None)
        if spec is None:
            raise PinError(f"no [[pin]] named {name!r}")
        entries = ledger_entries(root, cfg)
        led = Ledger(root / settings(cfg).ledger, "pins", cfg.steward.repo_id, base=root)
        last = last_event(entries, spec.name)
        if resume:
            if not last or last["kind"] != "retiring":
                raise PinError(f"{name} has no interrupted retirement to resume")
            doc = last["plan"]
            # AA1 (0.17.0): the recorded plan is believed only with its signed approval, the same nonce
            if verified is None or verified.payload.get("object") != doc["object"] or \
                    verified.payload.get("nonce") != last.get("nonce"):
                raise PinError("resume needs the signed approval of the recorded plan (--authorization TAG)")
            consume()  # a no-op when already recorded; records it when the interrupted run had not
            _verify_kept(root, doc)  # AA2: never remove the original while the kept copy is missing or changed
        else:
            st, why = state(root, cfg, spec, entries)
            if st != "retire-eligible":
                raise PinError(f"{name} is {st}: {'; '.join(why)}")
            doc = plan(root, cfg, spec)
            if verified is None or verified.payload.get("object") != doc["object"]:
                raise PinError("the approval is not for this plan (pin, version, artifact, install paths, keep folder)")
            nonce = verified.payload["nonce"]
            if any(e.get("nonce") == nonce for e in entries):  # Z5: the pins ledger keeps its own record of use
                raise PinError("this approval was already used for a retirement")
            pfd = _held_parent(root, spec.artifact)
            try:
                fd = os.open(Path(spec.artifact).name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=pfd)
                with os.fdopen(fd, "rb") as f:
                    data = f.read()
            finally:
                os.close(pfd)
            if sha_bytes(data) != doc["artifact_sha256"]:
                raise PinError("the artifact changed since its plan was made; nothing was done")
            _write_kept(root, doc["keep"], Path(spec.artifact).name, data, doc)
            head = git_run(root, "rev-parse", "HEAD", text=True)
            led.append("retiring", {"pin": spec.name, "plan": doc, "nonce": nonce, "authorization": verified.tag,
                                    "approved_by": verified.principal,
                                    "commit": head.stdout.strip() if head.returncode == 0 else None})
            consume()
            last = {"plan": doc, "authorization": verified.tag, "commit": head.stdout.strip() if head.returncode == 0 else None}
        for r in _roots(doc):
            _remove(root, r)
        kept = f"{doc['keep']}/{Path(doc['artifact']).name}"
        rec = {"pin": spec.name, "package": doc["package"], "version": doc["version"],
               "artifact_sha256": doc["artifact_sha256"], "kept": kept, "removed": doc["remove"],
               "commit": last.get("commit"), "authorization": last.get("authorization")}
        led.append("retire", rec)
        return rec
    finally:
        release_owner_lock(root, "pins", lock)


def restore(root: Path, cfg: Any, name: str) -> dict[str, Any]:
    """Copy the kept artifact back and run the pin's own commands; it counts as restored only when they pass (Z8)."""
    from .fsutil import owner_lock, release_owner_lock
    from .ledger import Ledger

    lock = owner_lock(root, "pins")
    if lock is None:
        raise PinError("another pins command is running; nothing was done")
    try:
        spec = next((p for p in cfg.pin if p.name == name), None)
        if spec is None:
            raise PinError(f"no [[pin]] named {name!r}")
        if not spec.check_command:
            raise PinError(f"{name} declares no check_command: a restore cannot be verified, so it is not done")
        entries = ledger_entries(root, cfg)
        last = last_event(entries, spec.name)
        if not last or last["kind"] != "retire":
            raise PinError(f"{name} is not retired")
        if last.get("version") != spec.version or last.get("package") != spec.package:  # Z9: the same pin
            raise PinError(f"the declaration of {name} is not the pin that was retired ({last.get('package')} "
                           f"{last.get('version')})")
        kept = _real_inside(root, last["kept"])
        if not kept.is_file() or kept.is_symlink() or sha_file(kept) != last["artifact_sha256"]:
            raise PinError(f"the kept artifact {last['kept']} is missing or changed: it cannot be restored")
        art = _real_inside(root, spec.artifact)
        art.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kept, art)
        runs = {}
        for key, cmd in (("install", spec.install_command), ("check", spec.check_command)):
            if cmd:
                r = subprocess.run(cmd.replace("{artifact}", shlex.quote(str(art))), shell=True, cwd=root,
                                   capture_output=True, timeout=3600)
                runs[key] = r.returncode
                if r.returncode != 0:
                    break  # Z8: no check after a failed install
        ok = runs.get("check") == 0 and runs.get("install", 0) == 0
        commit = last.get("commit")
        removed = {r["path"]: r.get("sha256") for r in last.get("removed", []) if r["path"] != spec.artifact
                   and "dir" not in r and "link" not in r}
        recoverable = []
        for path_, want in removed.items():  # AA7 (0.17.0): git must hold exactly the removed bytes
            blob = git_run(root, "cat-file", "blob", f"{commit}:{path_}") if commit else None
            if blob is not None and blob.returncode == 0 and sha_bytes(blob.stdout) == want:
                recoverable.append(path_)
        rec = {"pin": spec.name, "artifact_sha256": last["artifact_sha256"], "runs": runs, "from_commit": commit,
               "recoverable_from_git": recoverable, "not_in_git": sorted(set(removed) - set(recoverable))}
        led = Ledger(root / settings(cfg).ledger, "pins", cfg.steward.repo_id, base=root)
        led.append("restore" if ok else "restore_failed", rec)
        rec["ok"] = ok
        return rec
    finally:
        release_owner_lock(root, "pins", lock)


def records(root: Path, cfg: Any) -> list[tuple[str, str, str, dict[str, Any]]]:
    """R-73, for every pin declared or retired in the ledger (Z9)."""
    out = []
    entries = ledger_entries(root, cfg)
    declared = {p.name: p for p in cfg.pin}
    retired_names = {e["pin"] for e in entries if e.get("kind") in ("retire", "retiring")}
    for name in sorted(set(declared) | retired_names):
        spec = declared.get(name)
        last = last_event(entries, name)
        if last and last["kind"] == "retiring":
            out.append((name, "INCOMPLETE", "a retirement was interrupted",
                        {"code": "R-73.retirement_incomplete", "message": f"steward pins retire {name} --resume"}))
            continue
        if last and last["kind"] == "retire":
            try:
                kept = _real_inside(root, last["kept"])
                ok_path = kept.is_file() and not kept.is_symlink()
            except PinError:
                ok_path = False
            if not ok_path:
                out.append((name, "FAIL", "retired, and its kept artifact is gone or reached through a link",
                            {"code": "R-73.artifact_missing", "path": last["kept"]}))
            elif sha_file(kept) != last["artifact_sha256"]:
                out.append((name, "FAIL", "retired, and its kept artifact changed",
                            {"code": "R-73.artifact_changed", "path": last["kept"]}))
            elif spec is not None and (spec.version != last.get("version") or spec.package != last.get("package")):
                out.append((name, "FAIL", f"the name now declares another pin than the one retired",
                            {"code": "R-73.identity_changed", "value": f"{last.get('package')} {last.get('version')}"}))
            else:
                missing = [p for p in (spec.protects if spec else []) if not (root / p).exists()]
                out.append((name, "PASS" if not missing else "INCOMPLETE",
                            "retired; its artifact is kept and matches" if not missing else "a record it protects is missing",
                            {} if not missing else {"code": "R-73.protected_missing", "value": ", ".join(missing)}))
            continue
        if spec is None:
            continue
        art = root / spec.artifact
        if not art.is_file() or art.is_symlink():
            out.append((name, "INCOMPLETE", "its artifact is not present", {"code": "R-73.artifact_absent", "path": spec.artifact}))
        elif spec.sha256 and sha_file(art) != spec.sha256:
            out.append((name, "FAIL", "its artifact is not the declared sha256", {"code": "R-73.artifact_changed", "path": spec.artifact}))
        else:
            missing = [p for p in spec.protects if not (root / p).exists()]
            out.append((name, "PASS" if not missing else "INCOMPLETE",
                        "installed and matching" if not missing else "a record it protects is missing",
                        {} if not missing else {"code": "R-73.protected_missing", "value": ", ".join(missing)}))
    return out
