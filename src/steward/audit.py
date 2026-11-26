"""The Progress Audit's data (0.14.0; DESIGN_BRIEF_sprint §4; SP5): `steward audit progress` gathers, read-only, what
the `progress-audit` skill needs to judge how far the project is and how useful it is.

1. **Where we are:** version, branch, latest tag, the known issues the changelog lists for this version.
2. **Is it used:** per consumer (release notices and items in the exchange): what they adopted, what they filed, how long
   filing took to ship, what is open; and, for consumers checked out on this machine, how many areas they configure.
3. **What they report:** items by kind and by the version they were filed against.
4. **Pending:** open exchange items, waiting signatures, milestones and their state, unfinished sprint tasks.
5. **Reach:** what a stranger needs to adopt it (licence, citation, guide, quick start, community files, packaging).

It never changes anything. The judgement (what to improve, in what order) is the skill's, from this evidence.
"""

from __future__ import annotations

import datetime as dt
import re
import statistics
import tomllib
from pathlib import Path
from typing import Any

from .fsutil import git_run

SETTLED = {"shipped", "adopted", "closed", "merged", "declined", "noted", "superseded", "withdrawn"}


def _version(root: Path) -> str:
    from . import __version__

    return __version__


def where(root: Path) -> dict[str, Any]:
    br = git_run(root, "rev-parse", "--abbrev-ref", "HEAD", text=True)
    tag = git_run(root, "describe", "--tags", "--abbrev=0", "--match", "v*", text=True)
    version = _version(root).split(".dev")[0]
    try:
        version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"].split(".dev")[0]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    clog = root / "CHANGELOG.md"
    known: list[str] = []
    if clog.is_file():
        text = clog.read_text(encoding="utf-8", errors="replace")
        m = re.search(rf"^### Known issues in {re.escape(version)}\s*\n(.*?)(?=^##)", text, re.M | re.S) or \
            re.search(r"^### Known issues in [0-9.]+\s*\n(.*?)(?=^##)", text, re.M | re.S)
        if m:
            known = [l.split("|")[1].strip() for l in m.group(1).splitlines()
                     if l.startswith("| ") and not l.startswith(("| ID", "|---"))]
    project_version = None
    try:  # W5 (0.14.0): the audited project's own version, apart from the toolkit's
        project_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"project_version": project_version, "toolkit_version": _version(root),
            "branch": br.stdout.strip() if br.returncode == 0 else None,
            "latest_tag": tag.stdout.strip() if tag.returncode == 0 else None, "known_issues": known}


def _days(a: str | None, b: str | None) -> float | None:
    try:
        return (dt.datetime.fromisoformat(b.replace("Z", "+00:00")) - dt.datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds() / 86400
    except (AttributeError, ValueError, TypeError):  # W4 (0.15.0): naive and zoned times never stop the audit
        return None


def usage(root: Path, cfg: Any) -> dict[str, Any]:
    from . import cleanup as cu
    from . import exchange as xc

    if cfg.exchange is None or not xc.folder(root).is_dir():
        return {"note": "no [exchange]: adoption by other projects is not recorded here"}
    hist = xc.states(root)
    obs = xc.observations(root) if hasattr(xc, "observations") else {}
    items = xc.items(root)
    consumers: dict[str, dict[str, Any]] = {}
    for code in sorted(set(cfg.exchange.consumers) | set(cfg.exchange.peers)  # AB10: a configured peer counts too
                       | {Path(r).stem.split("-")[0] for r, _ in items.get("inbox", [])}):
        if code == cfg.exchange.code:
            continue
        c: dict[str, Any] = {"filed": 0, "by_kind": {}, "by_version": {}, "open": [], "days_to_ship": [], "notices": {}}
        for rel, text in items.get("inbox", []):
            iid = Path(rel).stem
            if not iid.startswith(code + "-"):
                continue
            try:
                head = xc.parse(text)[0]
            except (ValueError, RecursionError):
                continue
            if head.get("kind") == "response":
                continue
            c["filed"] += 1
            c["by_kind"][head.get("kind")] = c["by_kind"].get(head.get("kind"), 0) + 1
            c["by_version"][str(head.get("against") or "?")] = c["by_version"].get(str(head.get("against") or "?"), 0) + 1
            e = hist.get(iid, [])
            if xc.current(e) not in SETTLED:
                c["open"].append(iid)
            shipped = next((x for x in e if x.get("state") == "shipped"), None)
            if shipped and e:
                d = _days(e[0].get("time"), shipped.get("time"))
                if d is not None:
                    c["days_to_ship"].append(round(d, 2))
        for rel, text in [*items.get("outbox", []), *items.get("oneway", [])]:  # W5: one-way notices too
            iid = Path(rel).stem
            try:
                head = xc.parse(text)[0]
            except (ValueError, RecursionError):
                continue
            if head.get("kind") == "release" and head.get("to") == code:
                seen = [o.get("state") for o in (obs.get(iid, []) if isinstance(obs, dict) else [])]
                c["notices"][str(head.get("tag"))] = seen[-1] if seen else xc.current(hist.get(iid, [])) or "filed"
        ds = c.pop("days_to_ship")
        c["median_days_to_ship"] = round(statistics.median(ds), 2) if ds else None
        consumers[code] = c
    # areas each consumer configures, where it is checked out on this machine (the registry or [exchange] peers)
    from .rules import AREAS

    claims: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for proj in dict.fromkeys([*cu.registered(), *cu._peers(root)]):
        if proj.resolve() == root.resolve():
            continue
        try:
            doc = tomllib.loads((proj / "steward.toml").read_text(encoding="utf-8"))
            ex = doc.get("exchange") if isinstance(doc.get("exchange"), dict) else {}
        except (OSError, ValueError):
            continue
        if isinstance(ex.get("code"), str):
            claims.setdefault(ex["code"], []).append((proj, doc))
    for code, found in claims.items():
        if code not in consumers:
            continue
        if len(found) > 1:  # W2 (0.14.0): two checkouts claim one code: neither is believed
            consumers[code]["checkout"] = {"status": "ambiguous: several checkouts on this machine claim this code"}
            continue
        proj, doc = found[0]
        ex = doc.get("exchange") or {}
        if True:
            tables = set(doc)
            chk: dict[str, Any] = {"status": "read from its checkout on this machine (its own claims, not verified here)",
                                   "areas_configured": sorted(a for a in AREAS if a in tables or a.replace("-", "_") in tables)}
            uses = (ex.get("uses") or {}).get(cfg.exchange.code) if isinstance(ex.get("uses"), dict) else None
            if isinstance(uses, str) and re.fullmatch(r"v?\d+(\.\d+){0,3}", uses):
                chk["uses"] = uses
            try:  # what the consumer recorded about each notice: only from a verified ledger, kept apart from ours
                from .ledger import verify

                lp = proj / xc.FOLDER / "log.jsonl"
                v = verify(lp) if lp.is_file() and not lp.is_symlink() else None
                if v is not None and not (v.errors or v.torn_tail):
                    theirs: dict[str, list[dict[str, Any]]] = {}
                    for e in v.entries:
                        if e.get("kind") == "state":
                            theirs.setdefault(e.get("item"), []).append(e)
                    chk["notices"] = {}
                    for rel, text in [*items.get("outbox", []), *items.get("oneway", [])]:
                        iid = Path(rel).stem
                        head = xc.parse(text)[0]
                        if head.get("kind") == "release" and head.get("to") == code and theirs.get(iid):
                            chk["notices"][str(head.get("tag"))] = xc.current(theirs[iid])
                elif v is not None:
                    chk["notices_status"] = "its ledger is not intact: not read"
            except Exception:  # noqa: BLE001 - another project's ledger never breaks the audit
                chk["notices_status"] = "its ledger could not be read"
            try:  # 0.18.0: items its committed outbox addresses here that this project has not received yet
                from .fsutil import git_run

                head = git_run(proj, "rev-parse", "--verify", "HEAD^{commit}", text=True, timeout=30)
                if head.returncode == 0:
                    have = set(hist) | {Path(r).stem for r, _ in items.get("inbox", [])}
                    waiting = []
                    for fname, data in xc.peer_outbox(proj, head.stdout.strip()):
                        try:
                            h = xc.parse(data.decode("utf-8"))[0]
                        except (ValueError, UnicodeDecodeError, RecursionError):
                            continue
                        if h.get("to") == cfg.exchange.code and xc.valid_id(h.get("id")) and h["id"] not in have:
                            waiting.append(h["id"])
                    chk["not_received"] = sorted(waiting)
            except Exception:  # noqa: BLE001
                chk["not_received_status"] = "its outbox could not be read"
            consumers[code]["checkout"] = chk
    return {"consumers": consumers}


def pending(root: Path, cfg: Any) -> dict[str, Any]:
    from . import authorize as az
    from . import exchange as xc
    from . import milestones as ms
    from . import sprint as sp

    out: dict[str, Any] = {}
    if cfg.exchange is not None and xc.folder(root).is_dir():
        hist = xc.states(root)
        out["exchange_open"] = sorted(Path(r).stem for r, _ in xc.items(root).get("inbox", [])
                                      if xc.current(hist.get(Path(r).stem, [])) not in SETTLED)
        own = []  # W5: this project's own requests still open
        for r, text in xc.items(root).get("outbox", []):
            try:
                kind = xc.parse(text)[0].get("kind")
            except (ValueError, RecursionError):
                continue
            if kind != "release" and xc.current(hist.get(Path(r).stem, [])) not in SETTLED:
                own.append(Path(r).stem)
        out["own_open"] = sorted(own)
    out["signatures_waiting"] = [f"{q['action']} ({q['nonce'][:12]})" for q in az.pending(root) if q["state"] == "waiting"]
    try:
        out["milestones"] = [{"id": r["id"], "state": r["state"], "days_left": r["days_left"]} for r in ms.timeline(root, cfg)]
    except Exception as e:  # noqa: BLE001 - an invalid milestones file is reported, never a crash
        out["milestones"] = [{"error": f"the milestones file is not valid ({type(e).__name__})"}]
    sprints = []
    d = root / sp.DIR
    for f in sorted(d.glob("*.toml")) if d.is_dir() else []:
        sf, err = sp.validate_file(f)
        if sf is None:  # W4: an unusable sprint is reported, never silently left out
            sprints.append({"sprint": f.stem, "unavailable": "its plan is not valid (steward sprint check)"})
            continue
        try:
            st = sp.states(sf, sp.events(root, sf.sprint.id))
        except (ValueError, OSError):  # W4 (0.17.0): an unreadable ledger, too, is named, never a lost section
            sprints.append({"sprint": sf.sprint.id, "unavailable": "its ledger is not intact or cannot be read"})
            continue
        open_ = [t for t, s in st.items() if s["state"] not in ("done", "skipped")]
        if open_:
            sprints.append({"sprint": sf.sprint.id, "open": open_})
    out["sprints"] = sprints
    return out


REACH = [("LICENSE", "a licence"), ("CITATION.cff", "a citation file"), ("README.md", "a README"),
         ("docs/index.md", "a user guide"), ("docs/quickstart.md", "a quick start"), ("CONTRIBUTING.md", "contribution guidelines"),
         ("CODE_OF_CONDUCT.md", "a code of conduct"), ("SECURITY.md", "a security policy"), ("action.yml", "a GitHub Action"),
         (".pre-commit-hooks.yaml", "pre-commit hooks"), ("examples", "worked examples")]


def reach(root: Path) -> dict[str, Any]:
    have = {what: (root / path).exists() for path, what in REACH}
    import importlib.metadata as md

    try:
        md.distribution("bio-steward")
        installed = True
    except md.PackageNotFoundError:
        installed = False
    return {"present": sorted(k for k, v in have.items() if v), "missing": sorted(k for k, v in have.items() if not v),
            "installed_here_as_a_package": installed,
            "note": "PyPI, Zenodo and a public repository are D3 decisions (DESIGN_BRIEF_public_release §5 – §6)"}


WITHHELD = "(withheld: a private term or a local path)"


def _redact(v: Any, terms: list[Any]) -> Any:
    """W3 (0.14.0): every string of the evidence passes the term lists and the local-path check."""
    from . import privacy as pv

    if isinstance(v, str):
        return WITHHELD if pv.scan_text(v, terms, True, honour_marker=False)[0] else v
    if isinstance(v, list):
        return [_redact(x, terms) for x in v]
    if isinstance(v, dict):
        return {(_redact(k, terms) if isinstance(k, str) else k): _redact(x, terms) for k, x in v.items()}
    return v


def _section(fn, *a) -> dict[str, Any]:
    """W4 (0.15.0): one section that cannot be gathered is named as unavailable; the others still are."""
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        return {"unavailable": f"could not be gathered ({type(e).__name__})"}


def progress(root: Path, cfg: Any) -> dict[str, Any]:
    from . import authorize as az
    from . import privacy as pv

    was = az.READ_ONLY
    az.READ_ONLY = True  # W1 (0.14.0): signature checks that would write temporary files report unavailable instead
    try:
        doc = {"schema": "steward.progress_audit/0.1", "where": _section(where, root), "usage": _section(usage, root, cfg),
               "pending": _section(pending, root, cfg), "reach": _section(reach, root)}
    finally:
        az.READ_ONLY = was
    terms = [t for s_ in pv.load(root, cfg) if s_.state == "ok" for t in s_.terms]
    return _redact(doc, terms)


def render(doc: dict[str, Any]) -> str:
    """X4 (0.15.0): a section that could not be gathered is shown as unavailable, never as empty; `doc` is not changed."""
    def gone(k: str) -> str | None:
        return doc[k].get("unavailable") if isinstance(doc.get(k), dict) else "missing"

    lines: list[str] = ["## 1. Where we are"]
    if gone("where"):
        lines.append(f"- unavailable: {gone('where')}")
    else:
        w = doc["where"]
        lines += [f"- project version {w['project_version'] or '(no pyproject.toml)'} on {w['branch']}; latest tag "
                  f"{w['latest_tag']}; toolkit {w['toolkit_version']}",
                  f"- known issues listed for this version: {len(w['known_issues'])}" +
                  (f" ({', '.join(w['known_issues'][:12])})" if w["known_issues"] else "")]
    lines += ["", "## 2. Use by other projects"]
    if gone("usage"):
        lines.append(f"- unavailable: {gone('usage')}")
    else:
        u = doc["usage"]
        if "note" in u:
            lines.append(f"- {u['note']}")
        for code, c in sorted(u.get("consumers", {}).items()):
            lines.append(f"- **{code}:** filed {c['filed']} ({', '.join(f'{k} {v}' for k, v in sorted(c['by_kind'].items()))}); "
                         f"open {len(c['open'])}; median days to ship {c['median_days_to_ship']}; notices "
                         + (", ".join(f"{t}: {s_}" for t, s_ in sorted(c["notices"].items())) or "none"))
            if c["by_version"]:
                lines.append(f"  - filed against: {', '.join(f'{v} ({n})' for v, n in sorted(c['by_version'].items()))}")
            chk = c.get("checkout")
            if chk:
                lines.append(f"  - its checkout here: {chk['status']}" + (
                    f"; configures {len(chk['areas_configured'])} areas" if "areas_configured" in chk else "")
                    + (f"; uses {chk['uses']}" if chk.get("uses") else "")
                    + (f"; its notice states: {', '.join(f'{t}: {s_}' for t, s_ in sorted(chk['notices'].items()))}"
                       if chk.get("notices") else "") + (f"; {chk['notices_status']}" if chk.get("notices_status") else ""))
                if chk.get("not_received"):
                    lines.append(f"  - in its committed outbox, not received here: {', '.join(chk['not_received'][:12])} "
                                 "(steward exchange pull, or receive)")
            else:
                lines.append("  - not checked out on this machine as far as steward knows: its adoption is what it sent "
                             "back (it registers once `steward check` runs there with 0.13.0 or later)")
    lines += ["", "## 3. Pending"]
    if gone("pending"):
        lines.append(f"- unavailable: {gone('pending')}")
    else:
        p = doc["pending"]
        lines += [f"- exchange items open here: {len(p.get('exchange_open', []))}" +
                  (f" ({', '.join(p['exchange_open'][:12])})" if p.get("exchange_open") else ""),
                  f"- this project's own requests still open: {len(p.get('own_open', []))}" +
                  (f" ({', '.join(p['own_open'][:12])})" if p.get("own_open") else ""),
                  f"- signatures waiting: {len(p['signatures_waiting'])}" +
                  (f" ({', '.join(p['signatures_waiting'])})" if p["signatures_waiting"] else ""),
                  "- milestones: " + (", ".join(f"{m['id']} {m['state']} ({m['days_left']} days)" if "id" in m else m["error"]
                                                for m in p["milestones"]) or "none"),
                  "- sprints with open tasks: " + (", ".join(
                      f"{x['sprint']} ({', '.join(x['open'])})" if "open" in x else f"{x['sprint']} (unavailable: {x['unavailable']})"
                      for x in p["sprints"]) or "none")]
    lines += ["", "## 4. Reach (what a new adopter finds)"]
    if gone("reach"):
        lines.append(f"- unavailable: {gone('reach')}")
    else:
        r = doc["reach"]
        lines += [f"- present: {', '.join(r['present']) or 'none'}", f"- missing: {', '.join(r['missing']) or 'none'}",
                  f"- {r['note']}"]
    lines += ["", "Read-only: nothing was changed. The progress-audit skill turns this into ranked recommendations and "
              "offers a sprint."]
    return "\n".join(lines)
