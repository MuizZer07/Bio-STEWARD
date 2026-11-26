"""Container checks (0.9.0, REQ-003 – 005): build contexts, compose parity, image bundles.

Nothing here runs Docker. A build context is read with its `.dockerignore` (patterns relative to the context, the
last match wins, `!` re-includes); compose files are read as YAML (the `[containers]` extra); a `docker save`
archive is read for the image tags its `manifest.json` lists.
"""

from __future__ import annotations

import fnmatch
import io
import json
import os
import tarfile
from pathlib import Path
from typing import Any

from .fsutil import glob_match

SECRET_NAMES = (".env", "*.env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "*.p12", "*.pfx")


def ignore_patterns(ctx: Path) -> list[tuple[bool, str]]:
    p = ctx / ".dockerignore"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        pat = line[1:] if neg else line
        pat = pat.strip().lstrip("/").rstrip("/")
        if pat.startswith("./"):
            pat = pat[2:]
        if pat:
            out.append((neg, pat))
    return out


def ignored(rel: str, pats: list[tuple[bool, str]]) -> bool:
    state = False
    for neg, pat in pats:
        if glob_match(rel, pat) or glob_match(rel, pat + "/**") or (
                "/" not in pat and any(fnmatch.fnmatchcase(part, pat) for part in rel.split("/")[:1])):
            state = not neg
    return state


def audit_context(root: Path, rel_ctx: str, dev_only: list[str], max_mb: float) -> list[dict[str, Any]]:
    """Findings for one build context: links leaving it or into dev-only paths, secret-like files, large folders."""
    ctx = root / rel_ctx
    cur = root
    for part in Path(rel_ctx).parts:  # Q25: the context itself must not be reached through a link
        cur = cur / part
        if cur.is_symlink():
            return [{"code": "R-64.link_context", "path": rel_ctx, "message": "the build context is reached through a link"}]
    pats = ignore_patterns(ctx)
    negations = any(neg for neg, _ in pats)
    base = ctx.resolve()
    dev = [Path(d).expanduser() if Path(d).expanduser().is_absolute() else (root / d) for d in dev_only]
    dev = [d.resolve() for d in dev]
    findings: list[dict[str, Any]] = []
    sizes: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(ctx, followlinks=False):
        here = Path(dirpath)
        keep = []
        for d in sorted(dirnames):
            rel = (here / d).relative_to(ctx).as_posix()
            if d == ".git" or (ignored(rel, pats) and not negations):  # Q25: a later `!` may re-include below
                continue
            if (here / d).is_symlink():
                filenames.append(d)  # judged as a link below, never entered
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            p = here / name
            rel = p.relative_to(ctx).as_posix()
            if ignored(rel, pats):
                continue
            if p.is_symlink():
                try:
                    target = p.resolve()
                except OSError:
                    findings.append({"code": "R-64.link_dangling", "path": f"{rel_ctx}/{rel}"})
                    continue
                if any(target == d or d in target.parents for d in dev):
                    findings.append({"code": "R-64.dev_only", "path": f"{rel_ctx}/{rel}", "message": "resolves into a dev-only path"})
                elif target != base and base not in target.parents:
                    findings.append({"code": "R-64.link_outside", "path": f"{rel_ctx}/{rel}", "message": "leaves the build context"})
                continue
            real = p.resolve()
            if any(real == d or d in real.parents for d in dev):  # Q25: regular files inside a dev-only folder
                findings.append({"code": "R-64.dev_only", "path": f"{rel_ctx}/{rel}", "message": "inside a dev-only path"})
                continue
            if any(fnmatch.fnmatchcase(name, s) for s in SECRET_NAMES):
                findings.append({"code": "R-64.secret_file", "path": f"{rel_ctx}/{rel}", "message": "not in .dockerignore"})
            top = rel.split("/", 1)[0] if "/" in rel else None
            if top is not None:
                try:
                    sizes[top] = sizes.get(top, 0) + p.stat().st_size
                except OSError:
                    pass
    for top, n in sorted(sizes.items()):
        if n > max_mb * (1 << 20):
            findings.append({"code": "R-64.large_folder", "path": f"{rel_ctx}/{top}/", "value": round(n / (1 << 20), 1),
                             "message": f"{n / (1 << 20):.1f} MB not ignored (limit {max_mb:g} MB)"})
    return findings


# ---------------------------------------------------------------- compose (REQ-005)
def _env_keys(service: dict[str, Any], compose_dir: Path) -> set[str]:
    keys: set[str] = set()
    env = service.get("environment") or {}
    if isinstance(env, dict):  # Q26: a key without a value is not set (it would come from the host, unchecked)
        keys |= {str(k) for k, v in env.items() if v not in (None, "")}
    elif isinstance(env, list):
        keys |= {str(e).split("=", 1)[0] for e in env if "=" in str(e) and str(e).split("=", 1)[1] != ""}
    files = service.get("env_file") or []
    for f in [files] if isinstance(files, (str, dict)) else files:
        path = f.get("path") if isinstance(f, dict) else f
        p = compose_dir / str(path)
        if p.is_file():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    keys.add(line.split("=", 1)[0].removeprefix("export ").strip())
    return keys


def _volume_targets(service: dict[str, Any], named: set[str]) -> set[str]:
    out = set()
    for v in service.get("volumes") or []:
        if isinstance(v, str):
            parts = v.split(":")
            if len(parts) >= 2 and parts[0] in named:
                out.add(parts[1])
        elif isinstance(v, dict) and v.get("type", "volume") == "volume" and v.get("source") in named:
            out.add(str(v.get("target")))
    return out


def audit_compose(root: Path, cc: Any) -> list[dict[str, Any]]:
    import yaml  # the [containers] extra; the caller reports UNKNOWN without it

    findings: list[dict[str, Any]] = []
    for rel in cc.compose:
        doc = yaml.safe_load((root / rel).read_text(encoding="utf-8")) or {}
        services = doc.get("services") or {}
        named = set((doc.get("volumes") or {}).keys())
        cdir = (root / rel).parent
        for svc, keys in sorted(cc.urls.items()):
            if svc not in services:
                findings.append({"code": "R-65.unknown_service", "path": rel, "value": svc})
                continue
            have = _env_keys(services[svc] or {}, cdir)
            for k in keys:
                if k not in have:
                    findings.append({"code": "R-65.missing_key", "path": rel, "value": f"{svc}.{k}",
                                     "message": "not set in environment or env_file: inside a container it falls back"})
        for svc, paths in sorted(cc.user_data.items()):
            if svc not in services:  # Q26
                findings.append({"code": "R-65.unknown_service", "path": rel, "value": svc})
                continue
            targets = _volume_targets(services[svc] or {}, named)
            for path in paths:
                if path not in targets:
                    findings.append({"code": "R-65.user_data_not_volume", "path": rel, "value": f"{svc}:{path}",
                                     "message": "user data without a named volume is lost when the container is rebuilt"})
    for ship in cc.ship_with_image:
        sp = root / ship
        if sp.is_symlink() or not sp.exists():  # Q26: a shipped path must exist, as itself
            findings.append({"code": "R-65.ship_missing", "value": ship})
            continue
        ctx = next((c for c in cc.contexts if ship == c or ship.startswith(c.rstrip("/") + "/")), None)
        if ctx is None:
            findings.append({"code": "R-65.ship_outside", "value": ship, "message": "in no declared build context"})
        elif ignored(ship[len(ctx.rstrip("/")) + 1:], ignore_patterns(root / ctx)):
            findings.append({"code": "R-65.ship_ignored", "value": ship, "message": f"excluded by {ctx}/.dockerignore"})
    return findings


# ---------------------------------------------------------------- image bundles (REQ-004)
ARCHIVE_EXT = (".tar", ".tar.gz", ".tgz", ".tar.zst")


def archives(d: Path) -> list[Path]:
    return sorted(p for p in d.iterdir() if p.is_file() and p.name.endswith(ARCHIVE_EXT)) if d.is_dir() else []


def archive_tags(p: Path) -> list[str] | None:
    """The image tags a `docker save` archive lists in its manifest.json (empty when it has none)."""
    try:
        with tarfile.open(p) as t:
            m = t.extractfile("manifest.json")
            doc = json.load(io.TextIOWrapper(m, encoding="utf-8")) if m else []
    except (tarfile.TarError, KeyError, OSError, ValueError):
        return None
    if not isinstance(doc, list) or not all(isinstance(e, dict) for e in doc):  # R18
        return None
    tags = []
    for e in doc:
        rt = e.get("RepoTags")
        rt = [] if rt is None else rt  # R18 (0.12.0): only an absent or null list means "no tags"; "", false, 0, {} do not
        if not isinstance(rt, list) or not all(isinstance(x, str) for x in rt):
            return None
        tags += rt
    return sorted(set(tags))
