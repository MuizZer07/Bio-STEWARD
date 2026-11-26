"""A documentation site for each project (0.11.0; RELEASE_v0.11.0_SPEC; DESIGN_BRIEF_public_release §4).

`steward docs init` writes a MkDocs skeleton; `steward docs build` generates pages from the project's own records.
Every page names the records it came from (path and hash), carries no build time (the same records give the same
bytes), and passes the project's term lists and the local-path check before anything is written. Decisions and
exchange items are opt-in, and only their titles are shown.
"""

from __future__ import annotations

import hashlib
import re
import json
import os
import tomllib
from pathlib import Path
from typing import Any

from .fsutil import matching_files

KINDS = ("overview", "contracts", "runs", "values", "releases", "decisions", "exchange", "timeline")
TITLES = {"overview": "Overview", "contracts": "Benchmark contracts", "runs": "Runs", "values": "Reported values",
          "releases": "Releases", "decisions": "Decisions", "exchange": "Requests between projects",
          "timeline": "Milestones", "studies": "Studies", "research": "Research records",
          "comparisons": "Pipeline comparisons", "models": "Model cards"}


class DocsError(ValueError):
    pass


class PublicationError(DocsError):
    pass


def source(root: Path, cfg: Any, rel: str, *, read=None, hash_file=None) -> Path:
    """A record a page may read: inside the project, reached without links, and not part of a sealed dataset (T6)."""
    from . import integrity as ig
    from .fsutil import escapes_root

    p = root / rel
    if escapes_root(rel):
        raise DocsError(f"{rel} is outside the project")
    cur = root
    for part in Path(rel).parts:
        cur = cur / part
        if cur.is_symlink():
            raise DocsError(f"{rel} is reached through a link; its contents are not published")
    if (getattr(cfg, "integrity", None) is not None and p.is_file()
            and ig.sealed_owner(root, cfg, rel, read=read, hash_file=hash_file)):
        raise DocsError(f"{rel} belongs to a sealed dataset; it is never published")
    return p


def scan(root: Path, cfg: Any, text: str) -> list[str]:
    """Publication privacy scan: every configured term list must be usable (an unusable list is a refusal, never a
    clean scan), and no line waiver applies (T2, T3)."""
    from . import privacy as pv

    from .records import read_rel

    lists = pv.load(root, cfg, read=lambda rel: read_rel(root, rel))  # AF12: term lists read without links
    broken = [s.name for s in lists if s.state in ("missing", "unreadable") or s.errors]  # an empty list is fine
    if broken:
        return [f"term list(s) {', '.join(broken)} cannot be used"]
    terms = [t for s in lists for t in s.terms]
    found, _ = pv.scan_text(text, terms, True, honour_marker=False)
    return sorted({h["term"].label if h["kind"] == "term" else "local path" for h in found})


def _read_nofollow(root: Path, rel: str) -> bytes:
    """The bytes of a record, read through its folder walked without links (W8)."""
    from .fsutil import open_dir_beneath

    dfd = open_dir_beneath(root, tuple(Path(rel).parent.parts))
    try:
        fd = os.open(Path(rel).name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
    finally:
        os.close(dfd)
    with os.fdopen(fd, "rb") as f:
        return f.read()


def _src(root: Path, rels: list[Any]) -> str:
    parts = []
    fixed = {r[0]: r[1] for r in rels if isinstance(r, tuple)}  # (rel, digest) read once by the page builder (W8)
    for rel in sorted(fixed):
        label = _literal(rel.replace("\r", " ")) if any(c in rel for c in "`\r\n") else f"`{rel}`"
        parts.append(f"{label} ({fixed[rel]})")
    for rel in sorted(set(r for r in rels if isinstance(r, str) and r not in fixed)):
        if "*" in rel:  # T14: a group of records (the exchange items), named by pattern, file count and one digest
            files = sorted(q for q in root.glob(rel) if q.is_file() and not q.is_symlink())
            d = hashlib.sha256()
            for q in files:
                d.update(q.relative_to(root).as_posix().encode() + b"\0" + hashlib.sha256(q.read_bytes()).digest())
            parts.append(f"`{rel}` ({len(files)} files, {d.hexdigest()[:12]})")
            continue
        p = root / rel
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.is_file() else "absent"
        parts.append(f"`{rel}` ({h})")
    return "> Generated from " + (", ".join(parts) if parts else "the configuration") + \
        " by `steward docs build`. Do not edit: change the records and build again.\n"


def _literal(v: Any) -> str:
    """W7 (0.14.0): free text shown as text: Markdown and HTML punctuation escaped."""
    import re as _re

    return _re.sub(r"([\\`*_{}\[\]()<>#+!|~])", r"\\\1", str(v).replace("\n", " "))


def _cell(v: Any) -> str:
    return str(v).replace("|", "/").replace("\n", " ") if v is not None else "—"


def page_overview(root: Path, cfg: Any) -> tuple[str, list[str]]:
    s = cfg.steward
    tables = [k for k in ("paper", "talk", "run", "policy", "integrity", "evidence", "release", "storage", "exchange",
                          "repro", "boundary", "tasks", "changelog", "branches", "containers", "dependencies", "session",
                          "agents") if getattr(cfg, k, None)]
    body = [f"- **Project:** {s.project}", f"- **Profile:** {s.profile}",
            f"- **Constitution:** version {s.constitution or 'not declared'}",
            f"- **Governed areas:** {', '.join(tables) or 'the core only'}"]
    return "\n".join(body) + "\n", ["steward.toml"]


def page_contracts(root: Path, cfg: Any) -> tuple[str, list[str]]:
    from .models import Contract

    files = matching_files(root, cfg.paths.contracts)
    out = []
    files = [f for f in files if not f.startswith(cfg.docs.generated.rstrip("/") + "/")]  # T13
    for rel in files:
        try:
            c = Contract.model_validate(tomllib.loads(source(root, cfg, rel).read_text(encoding="utf-8")))
        except (ValueError, OSError):
            out.append(f"## `{rel}`\n\nNot a valid contract (see `steward check contract`).\n")
            continue
        out.append(f"## {c.id}: {c.title}\n\n- **Analysis:** {c.analysis}")
        out.append("- **Datasets:** " + ", ".join(f"{d.id} (version {d.version})" for d in c.datasets))
        out.append("- **Splits:** " + ", ".join(f"{s.name} ({s.role})" for s in c.splits.sets))
        out.append("- **Baselines:** " + ", ".join(b.name for b in c.baselines))
        out.append(f"- **Metrics:** {', '.join(m.name for m in c.metrics.defs)} (primary: {c.metrics.primary})")
        if c.thresholds:
            out.append("- **Thresholds:** " + ", ".join(f"{t.metric} {t.comparator} {t.value} ({t.against})" for t in c.thresholds))
        out.append("")
    return ("\n".join(out) if out else "No benchmark contracts.\n"), files


def page_runs(root: Path, cfg: Any) -> tuple[str, list[str]]:
    from .ledger import verify
    from .models import RunSection

    rc = cfg.run or RunSection()
    p = source(root, cfg, rc.ledger)
    if not p.is_file():
        return "No runs recorded.\n", []
    v = verify(p)
    if v.errors or v.torn_tail:  # T11: an invalid ledger is never presented as the record
        raise DocsError(f"{rc.ledger} is not intact; recover it before publishing runs")
    entries = v.entries
    started = {e["run"]: e for e in entries if e.get("kind") == "started"}
    rows = ["| Run | Label | Status | Duration (s) | Limits | Exit |", "|---|---|---|---|---|---|"]
    for e in entries:
        if e.get("kind") not in ("outcome", "interrupted"):
            continue
        s = started.get(e.get("run"), {})
        lim = ", ".join(f"{k}={v:g}" for k, v in sorted((s.get("limits") or {}).items()) if isinstance(v, (int, float)))
        rows.append(f"| {_cell(e.get('run'))} | {_cell(s.get('label'))} | {_cell(e.get('status', 'interrupted'))} | "
                    f"{_cell(e.get('duration_s'))} | {_cell(lim or None)} | {_cell(e.get('exit_code'))} |")
    from . import charts
    from .cli_research import run_rows

    chart = ""
    try:
        recent = run_rows(root, cfg)[-25:]
    except ValueError:
        recent = []
    _raw_scan(root, cfg, "runs", [r.get("label") for r in recent])  # AE2: labels before the chart escapes them
    if recent:  # 0.18.0: the same records, drawn (the last 25 runs)
        chart = "\n" + charts.bars(recent, "duration_s", "Run duration (last 25 runs)", "s") + "\n" + charts.legend_md() + "\n\n"
    return chart + "\n".join(rows) + "\n", [rc.ledger]


def page_values(root: Path, cfg: Any) -> tuple[str, list[str]]:
    out, srcs = [], []
    for name, pp in sorted(cfg.paper.items()):
        rel = pp.rel(pp.values)
        p = source(root, cfg, rel)
        if not p.is_file():
            continue
        srcs.append(rel)
        try:
            doc = tomllib.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            out.append(f"## Paper `{name}`\n\nThe values registry is not valid.\n")
            continue
        out += [f"## Paper `{name}`\n", "| Value | Source | How |", "|---|---|---|"]
        for vname, v in sorted((doc.get("values") or {}).items()):
            v = v if isinstance(v, dict) else {}
            how = v.get("pointer") or (f"count {v['count']}" if v.get("count") else None) or (
                f"derived: {v['derive']}" if v.get("derive") else None)
            out.append(f"| `{vname}` | {_cell(v.get('source'))} | {_cell(how)} |")
        out.append("")
    return ("\n".join(out) if out else "No values registry.\n"), srcs


def page_releases(root: Path, cfg: Any) -> tuple[str, list[str]]:
    from .models import ReleaseSection

    rc = cfg.release or ReleaseSection()
    p = source(root, cfg, rc.manifest)
    if not p.is_file():
        return "No release manifest yet.\n", []
    try:
        man = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return "The release manifest is not valid.\n", [rc.manifest]
    out = [f"- **Version:** {_cell(man.get('version'))}", "", "| Artifact | SHA-256 | Size |", "|---|---|---|"]
    for name, a in sorted((man.get("artifacts") or {}).items()):
        out.append(f"| {_cell(name)} | `{_cell((a or {}).get('sha256'))}` | {_cell((a or {}).get('size'))} |")
    for name, b in sorted((man.get("bundles") or {}).items()):
        out.append(f"| bundle {_cell(name)} | `{_cell((b or {}).get('sha256'))}` | {_cell((b or {}).get('size'))} |")
    for img in man.get("images") or []:
        out.append(f"| image {_cell(img.get('tag'))} | `{_cell(img.get('digest'))}` | {_cell(img.get('platform'))} |")
    return "\n".join(out) + "\n", [rc.manifest]


def page_decisions(root: Path, cfg: Any) -> tuple[str, list[str]]:
    from . import integrity as ig

    out, srcs = [], []
    for rel in ig.decision_logs(root, cfg):
        p = source(root, cfg, rel)
        if not p.is_file():
            continue
        srcs.append(rel)
        titles, fenced = [], False
        for l in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if l.lstrip().startswith(("```", "~~~")):
                fenced = not fenced
            elif not fenced and re.match(r"^## \d{4}-\d{2}-\d{2}: \S", l):  # T5: dated entry headings only
                titles.append(l[3:].strip())
        out += [f"## `{rel}`", ""] + [f"- {t}" for t in titles] + [""]
    return ("\n".join(out) if out else "No decisions log.\n"), srcs


def page_exchange(root: Path, cfg: Any) -> tuple[str, list[str]]:
    from . import exchange as xc

    if cfg.exchange is None or not xc.folder(root).is_dir():
        return "No exchange folder.\n", []
    # U11 (0.12.0): every file the page draws on passes the source guard first (no links, nothing sealed)
    source(root, cfg, xc.FOLDER)
    if (root / xc.FOLDER / "log.jsonl").exists() or (root / xc.FOLDER / "log.jsonl").is_symlink():
        source(root, cfg, f"{xc.FOLDER}/log.jsonl")
    for sub in xc.SUBDIRS:
        d = root / xc.FOLDER / sub
        if d.is_symlink():
            raise DocsError(f"{xc.FOLDER}/{sub} is reached through a link; its contents are not published")
        for q in sorted(d.glob("*.md")) if d.is_dir() else []:
            source(root, cfg, q.relative_to(root).as_posix())
    hist = xc.states(root)
    rows = ["| Item | Place | Kind | Title | State |", "|---|---|---|---|---|"]
    for place, entries in xc.items(root).items():
        for rel, text in entries:
            try:
                head, _ = xc.parse(text)
            except (ValueError, tomllib.TOMLDecodeError):
                head = {}
            iid = head.get("id", Path(rel).stem)
            rows.append(f"| {_cell(iid)} | {place} | {_cell(head.get('kind'))} | {_cell(head.get('title'))} | "
                        f"{_cell(xc.current(hist.get(iid, [])))} |")
    return "\n".join(rows) + "\n", [f"{xc.FOLDER}/log.jsonl", f"{xc.FOLDER}/*/*.md"]  # T14: the item files too


def page_timeline(root: Path, cfg: Any) -> tuple[str, list[str]]:
    """Milestones (0.14.0, opt-in): titles, kinds, due dates and recorded outcomes. Days left and progress change every
    day, so they stay in `steward timeline`; the page holds only what the records fix."""
    from . import milestones as ms

    p = source(root, cfg, ms.FILE)
    if not p.is_file():
        return "No milestones.\n", []
    data = _read_nofollow(root, ms.FILE)  # W8 (0.15.0): one read: the rows and the digest describe the same bytes
    src = (ms.FILE, hashlib.sha256(data).hexdigest()[:12])
    try:
        mf = ms.MilestonesFile.model_validate(tomllib.loads(data.decode("utf-8")))
    except Exception:  # noqa: BLE001
        return "The milestones file is not valid.\n", [src]
    rows = ["| Milestone | Kind | Due | Outcome |", "|---|---|---|---|"]
    for m in sorted(mf.milestone if mf else [], key=lambda x: x.due):
        rows.append(f"| {_literal(m.title)} | {m.kind} | {m.due.isoformat()} | {_cell(m.outcome.state if m.outcome else None)} |")
    return "\n".join(rows) + "\n", [src]


def _raw_scan(root: Path, cfg: Any, page: str, values: Any) -> None:
    """AE2: the record values as written, scanned before rendering: escaping for Markdown, HTML or SVG must never hide
    a protected term from the publication scan. The diagnostic names the list, never the term."""
    def strings(v: Any) -> list[str]:
        if isinstance(v, dict):
            return [x for k, w in v.items() for x in [str(k), *strings(w)]]
        if isinstance(v, list):
            return [x for w in v for x in strings(w)]
        return [str(v)] if v is not None else []
    bad = scan(root, cfg, "\n".join(strings(values)))
    if bad:
        raise PublicationError(f"{page}: {', '.join(bad)}")


def page_studies(root: Path, cfg: Any, *, strict: bool = False) -> tuple[str, list[str]]:
    """Study cards (0.18.0): inputs, references, tools and the papers that cite each study, with its R-75 check."""
    from . import records as rc

    if cfg.studies is None:
        return "No [studies] configured.\n", []
    source(root, cfg, cfg.studies.dir)  # AE1: the folder is reached without links
    def read(rel: str) -> bytes:
        source(root, cfg, rel)
        return rc.read_rel(root, rel)

    reader = read if strict else None
    studies, bad = rc.load_studies(root, cfg, reader)
    if strict and bad:
        raise DocsError("a study record cannot be published; see `steward check studies`")
    for rel, _st in studies.values():
        source(root, cfg, rel)  # AE1: no record from a sealed dataset or behind a link
    _raw_scan(root, cfg, "studies", [st.model_dump(mode="json") for _, st in studies.values()])
    if not studies:
        return "No study records.\n", []
    verdict = {Path(subj).stem: st for subj, st, _, _ in rc.check_studies(root, cfg, reader)}
    cards = [rc.card(st, verdict) for _, (_, st) in sorted(studies.items())]
    return "\n".join(cards), sorted(rel for rel, _ in studies.values())


def page_research(root: Path, cfg: Any) -> tuple[str, list[str]]:
    from . import records as rc

    if cfg.research is None:
        return "No [research] configured.\n", []
    source(root, cfg, cfg.research.dir)
    recs, _ = rc.load_research(root, cfg)
    for rel, _r in recs.values():
        source(root, cfg, rel)
    _raw_scan(root, cfg, "research", [r.model_dump(mode="json") for _, r in recs.values()])
    return rc.research_page(root, cfg), sorted(rel for rel, _ in recs.values())


def page_comparisons(root: Path, cfg: Any) -> tuple[str, list[tuple[str, str]]]:
    from itertools import groupby

    from .charts import bars
    from .compare import history

    try:
        records = history(root, cfg)
    except (ValueError, OSError) as exc:
        raise DocsError(str(exc)) from exc
    if not records:
        return "No comparisons recorded.\n", []
    records.sort(key=lambda saved: (saved.comparison.name, saved.comparison.completed, saved.comparison.order, saved.path))
    body = ["Each bar shows the agreement recorded for a pair of runs.\n"]
    _raw_scan(root, cfg, "comparisons", [saved.comparison.name for saved in records])
    for name, group in groupby(records, key=lambda saved: saved.comparison.name):
        rows, chart = [], []
        for saved in group:
            doc = saved.comparison
            agree = doc.agreement
            pct = 100 * agree.equal / agree.total
            chart.append({"label": doc.completed, "status": "other", "percent": pct})
            rows.append(f"| {doc.completed} | {agree.equal} | {agree.total} | {pct:.2f}% |")
        body += [f"## {_literal(name)}\n", bars(chart, "percent", "Agreement over time", "%", maximum=100),
                 "| Runs completed (UTC) | Keys in agreement | Total keys | Agreement |", "|---|---:|---:|---:|",
                 *rows, ""]
    return "\n".join(body), [(saved.path, saved.digest[:12]) for saved in records]


def page_models(root: Path, cfg: Any) -> tuple[str, list[tuple[str, str]]]:
    from functools import cache

    from .models_records import card, check_models, ledger_path, study_path
    from .records import RecordRefused, _sha_file, read_rel
    from .rules import Ctx
    from .status import Status

    if not cfg.model:
        return "No models recorded.\n", []
    _raw_scan(root, cfg, "models", [model.model_dump(mode="json") for model in cfg.model])
    ctx = Ctx(root, config=cfg)
    checks = check_models(ctx)
    if any(check.status is not Status.PASS for check in checks):
        raise DocsError("models with missing or changed evidence; see `steward check models`")

    def read_optional(rel: str) -> bytes | None:
        if not Path(rel).parts or "\x00" in rel:
            raise DocsError("a model publication rule names an invalid path")
        try:
            return read_rel(root, rel)
        except RecordRefused as exc:
            if exc.reason == "missing":
                return None
            raise

    @cache
    def hash_file(rel: str) -> str | None:
        # Reuse the checked snapshot and stream any other file matched by a sealed dataset.
        return ctx.inputs[rel] if rel in ctx.inputs else _sha_file(root, rel)

    paths = {"steward.toml", ledger_path(cfg)}
    for model in cfg.model:
        paths.add(model.contract)
        paths.update(study_path(cfg, sid) for sid in model.training_studies)
    try:
        for rel in sorted(paths | {model.weights.path for model in cfg.model}):
            source(root, cfg, rel, read=read_optional, hash_file=hash_file)
    except DocsError:
        raise
    except (OSError, KeyError, RecursionError, ValueError) as exc:
        raise DocsError("model sources could not be checked against the project's publication rules") from exc

    cards = [card(model) for model in sorted(cfg.model, key=lambda model: (model.name, model.version))]
    return "\n".join(cards), [(rel, ctx.inputs[rel][:12]) for rel in sorted(paths)]


BUILDERS = {"overview": page_overview, "contracts": page_contracts, "runs": page_runs, "values": page_values,
            "releases": page_releases, "decisions": page_decisions, "exchange": page_exchange,
            "timeline": page_timeline, "studies": page_studies, "research": page_research,
            "comparisons": page_comparisons, "models": page_models}


def build_pages(root: Path, cfg: Any) -> dict[str, str]:
    """file name -> page text, for every published kind and the index. Raises DocsError when a page holds a private
    term or a local path (nothing is written then)."""
    dc = cfg.docs
    pages: dict[str, str] = {}
    for kind in dc.publish:
        body, srcs = BUILDERS[kind](root, cfg)
        pages[f"{kind}.md"] = f"# {TITLES[kind]}\n\n{_src(root, srcs)}\n{body}"
    title = dc.title or cfg.steward.project
    pages["index.md"] = (f"# {title}\n\n{_src(root, ['steward.toml'])}\n"
                         + "\n".join(f"- [{TITLES[k]}]({k}.md)" for k in dc.publish) + "\n")
    bad = {name: scan(root, cfg, text) for name, text in pages.items()}
    bad = {k: v for k, v in bad.items() if v}
    if bad:
        raise DocsError("; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(bad.items())))
    return pages


MARK = "> Generated from "


def retired(root: Path, cfg: Any, current: set[str]) -> list[str]:
    """Pages this tool generated earlier that the current configuration no longer publishes (T1)."""
    from .fsutil import LinkRefused, open_dir_beneath

    gen = cfg.docs.generated.rstrip("/")
    try:
        dfd = open_dir_beneath(root, tuple(Path(gen).parts))
    except LinkRefused:
        return []
    try:
        names = sorted(os.listdir(dfd))
    finally:
        os.close(dfd)
    out = []
    for n in names:
        p = root / gen / n
        if n.endswith(".md") and n not in current and p.is_file() and not p.is_symlink() and \
                MARK in p.read_text(encoding="utf-8", errors="replace")[:400]:
            out.append(f"{gen}/{n}")
    return out


MKDOCS = """# Generated by `steward docs init`; edit freely. Build: pip install mkdocs-material && mkdocs build --strict
site_name: {title}
theme:
  name: material
docs_dir: {dir}
nav:
  - Home: index.md
  - Project:
{nav}
"""

PAGES_WORKFLOW = """# Generated by `steward docs init --pages`. Publishes the project site on GitHub Pages (free for public repositories).
# The site is published only after `steward docs build` succeeds (its privacy check) and the committed pages match.
name: docs
on:
  push:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install the toolkit and MkDocs (pinned)
        run: pipx install "git+https://github.com/MuizZer07/Bio-STEWARD.git@{tag}" && pip install "mkdocs-material==9.5.50"
      - name: Regenerate the pages (refuses on private terms or local paths)
        run: steward docs build
      - name: The committed pages must equal the regenerated ones
        run: git diff --exit-code -- {generated}
      - run: mkdocs build --strict -d site
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
  deploy:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
    steps:
      - uses: actions/deploy-pages@v4
"""


def init_files(root: Path, cfg: Any, pages_workflow: bool) -> dict[str, str]:
    dc = cfg.docs
    gen_rel = Path(dc.generated).relative_to(dc.dir).as_posix()  # T9: the settings keep it strictly inside dir
    nav = "\n".join(f"      - {TITLES[k]}: {json.dumps(gen_rel + '/' + k + '.md')}" for k in dc.publish)  # U16
    files = {"mkdocs.yml": MKDOCS.format(title=json.dumps(dc.title or cfg.steward.project), dir=json.dumps(dc.dir), nav=nav),
             f"{dc.dir}/index.md": f"# {dc.title or cfg.steward.project}\n\nWrite the project's introduction here. The pages under "
                                   f"*Project* are generated from its records by `steward docs build`.\n"}
    if pages_workflow:
        from . import __version__

        files[".github/workflows/steward-docs.yml"] = PAGES_WORKFLOW.replace("{tag}", "v" + __version__.split(".dev")[0]) \
            .replace("{generated}", dc.generated)
    bad = {name: scan(root, cfg, text) for name, text in files.items()}  # T4: the scaffold is scanned too
    bad = {k: v for k, v in bad.items() if v}
    if bad:
        raise DocsError("; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(bad.items())))
    return files

