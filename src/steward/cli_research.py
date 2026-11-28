"""Commands of 0.18.0: `steward study`, `steward research`, `steward task brief|template`, `steward paper citations`
and `steward diff runs`."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from .interface import wants_json, write_json
from .status import EXIT_DATAERR, EXIT_OK, EXIT_USAGE

ID_RX = r"^[a-z0-9][a-z0-9._-]{0,63}$"


def _cfg(args: argparse.Namespace):
    from .cli import _config

    return _config(args)


def _new_file(root: Path, rel: str, text: str) -> bool:
    from .fsutil import safe_write

    if (root / rel).exists():
        print(f"steward: {rel} exists; never overwritten", file=sys.stderr)
        return False
    safe_write(root, rel, text.encode("utf-8"), exclusive=True)
    return True


def _write_out(root: Path, path: Path, text: str, alias_of: Path | None = None) -> str | None:
    """Write an explicit export (AE13): inside the repository through `safe_write` (no link at any component); outside
    it, never through a final link. Never onto the file it was made from. None when written, else why not."""
    import os

    from .fsutil import LinkRefused, safe_write

    absp = Path(os.path.abspath(path))
    if os.path.islink(absp):
        return f"{path} is a link"
    if alias_of is not None and absp.exists() and os.path.samefile(absp, alias_of):
        return f"{path} is the file the brief is made from"
    try:
        rel = absp.relative_to(root.resolve())
    except ValueError:
        rel = None
    if rel is None and Path(os.path.realpath(absp)).is_relative_to(root.resolve()):
        return f"{path} reaches the repository through a link"
    try:
        if rel is not None:
            safe_write(root, rel.as_posix(), text.encode("utf-8"))
            return None
        fd = os.open(absp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return None
    except (LinkRefused, OSError) as e:
        return f"{path}: refused ({getattr(e, 'strerror', None) or e})"


def _check_id(i: str) -> bool:
    import re

    if not re.match(ID_RX, i):
        print("steward: an ID is lowercase letters, digits, '.', '_' or '-' (at most 64)", file=sys.stderr)
        return False
    return True


def _record_input(root: Path, rel: str, ident: str, source: str, accession: str | None, url: str | None,
                  files: list[dict]) -> str | None:
    """Add one [[inputs]] table to a study record (0.19.0 add-input, 0.20.0 data fetch). None when written, else why
    not; the record must stay valid."""
    import re as _re
    import tomllib as _tl

    from . import records as rc
    from .fsutil import safe_write

    q = lambda v: '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'  # noqa: E731
    block = ["[[inputs]]", f"id = {q(ident)}", f"source = {q(source)}"]
    if accession:
        block.append(f"accession = {q(accession)}")
    if url:
        block.append(f"url = {q(url)}")
    block.append(f"retrieved = {date.today().isoformat()}")
    inline = lambda f: "{ " + ", ".join(f"{k} = {q(v) if isinstance(v, str) else v}" for k, v in f.items() if v is not None) + " }"  # noqa: E731
    block.append("files = [" + ", ".join(inline(f) for f in files) + "]")
    try:
        text = rc.read_rel(root, rel).decode("utf-8")
    except rc.RecordRefused as e:
        return str(e)
    # AN4: a new [[inputs]] element goes at the end of the record, after every table, so no existing input's own
    # subtables ([inputs.references], [[inputs.files]], with any spacing) can ever change owner
    new = text.rstrip("\n") + "\n\n" + "\n".join(block) + "\n"
    try:
        rc.Study.model_validate(_tl.loads(new))
    except Exception as e:  # noqa: BLE001
        return f"the record would not be valid ({str(e).splitlines()[0][:120]}); nothing written"
    safe_write(root, rel, new.encode("utf-8"))
    return None


# ---------------------------------------------------------------- steward stranger-test (0.20.2, STW-041)
def cmd_stranger(args: argparse.Namespace) -> int:
    from . import stranger as stg
    from .fsutil import safe_write

    root, cfg = _cfg(args)
    if cfg is None:
        return EXIT_USAGE
    if cfg.stranger_test is None:
        from .models import StrangerTestSection

        cfg = cfg.model_copy(update={"stranger_test": StrangerTestSection()})  # the generic test, until declared
        if args.stranger_command == "brief":
            print("note: no [stranger_test] in steward.toml: the generic missions are used (declare audience and "
                  "missions for a sharper test; docs: the stranger-test guide)", file=sys.stderr)
    if args.stranger_command == "brief":
        try:
            text = stg.brief(root, cfg, args.tag, args.agent, str(args.output) if args.output else "BRIEF.md")
        except ValueError as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_USAGE
        if args.output is None:
            sys.stdout.write(text)
            return EXIT_OK
        err = _write_out(root, args.output, text)
        if err:
            print(f"steward: {err}", file=sys.stderr)
            return EXIT_DATAERR
        print(f"{args.output}: stranger-test brief for {args.agent} ({args.tag})")
        return EXIT_OK
    try:
        text = args.report.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"steward: {args.report}: {e}", file=sys.stderr)
        return EXIT_USAGE
    if not re.search(r"^# Stranger test of ", text, re.M):
        print("steward: not a stranger-test report (it needs its '# Stranger test of …' title)", file=sys.stderr)
        return EXIT_DATAERR
    rel = stg.record_path(args.tag, args.agent)
    try:
        safe_write(root, rel, text.encode("utf-8"), exclusive=True)
    except FileExistsError:
        print(f"steward: {rel} exists; a record is never overwritten", file=sys.stderr)
        return EXIT_DATAERR
    except OSError as e:
        print(f"steward: {rel}: {e}", file=sys.stderr)
        return EXIT_DATAERR
    print(f"{rel}: recorded (R-87)")
    return EXIT_OK


# ---------------------------------------------------------------- steward example (0.20.0, B6)
EXAMPLES = {"biology": "biology-geo"}


def cmd_example(args: argparse.Namespace) -> int:
    """Copy a bundled worked example into a new folder, with a repository ID of its own."""
    import os
    import re
    import shutil
    import subprocess
    import uuid

    from .resources import _base

    try:
        src = _base("examples") / EXAMPLES[args.name]
    except FileNotFoundError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    dest = Path(args.dest)
    if os.path.islink(dest) or (dest.exists() and (not dest.is_dir() or any(dest.iterdir()))):
        print(f"steward: {dest} exists and is not an empty folder", file=sys.stderr)
        return EXIT_USAGE
    shutil.copytree(src, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".steward", "__pycache__", "*.pyc"))
    cfg = dest / "steward.toml"
    cfg.write_text(re.sub(r'^repo_id = "[^"]*"', f'repo_id = "{uuid.uuid4()}"', cfg.read_text(encoding="utf-8"),
                          count=1, flags=re.M), encoding="utf-8")
    inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=dest, capture_output=True, text=True)
    if inside.returncode != 0:  # 0.20.1: a first commit, so the README's undo (git checkout -- .) works
        subprocess.run(["git", "init", "-q"], cwd=dest, check=False)
        subprocess.run(["git", "add", "-A"], cwd=dest, check=False)
        subprocess.run(["git", "-c", "user.name=steward example", "-c", "user.email=example@localhost", "commit", "-q",
                        "--no-gpg-sign", "-m", f"the {args.name} example, as shipped"], cwd=dest, check=False,
                       capture_output=True)
    print(f"{dest}: the {args.name} example ({src.name})\nNext:\n  1. cd {dest}\n  2. steward check --summary\n"
          f"  3. read README.md: what each check shows, and how to break it on purpose")
    return EXIT_OK


# ---------------------------------------------------------------- steward data (0.20.0, B1)
def cmd_data(args: argparse.Namespace) -> int:
    """`steward data fetch`: the only command of this group, and the only one that reaches the network."""
    from . import biodata as bd
    from . import records as rc

    root, cfg = _cfg(args)
    if cfg is None:
        return EXIT_USAGE
    if cfg.studies is None:
        print("steward: add a [studies] table to steward.toml (dir = \"development/studies\")", file=sys.stderr)
        return EXIT_USAGE
    studies_, _ = rc.load_studies(root, cfg)
    if args.study not in studies_:
        print(f"steward: no study {args.study} (steward study new {args.study} --title …)", file=sys.stderr)
        return EXIT_USAGE
    rel, st = studies_[args.study]
    try:
        source, acc = bd.parse_spec(args.source)
    except bd.FetchError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_USAGE
    ident = acc if source != "URL" else args.source
    if any(i.id == ident for i in st.inputs):  # checked before anything is downloaded
        print(f"steward: {args.study} already records an input {ident}; fetch all its files in one command (--file "
              "repeats)", file=sys.stderr)
        return EXIT_USAGE
    if args.sha256 and not __import__("re").fullmatch(r"[0-9a-fA-F]{64}", args.sha256):
        print("steward: --sha256 takes 64 hexadecimal characters", file=sys.stderr)
        return EXIT_USAGE
    dest = args.dest or f"data/raw/{acc if source != 'URL' else 'url'}"
    try:
        plan = bd.resolve(source, acc, args.file)
        if args.sha256 and len(plan.files) != 1:
            raise bd.FetchError("--sha256 names one file; this fetch has " + str(len(plan.files)))
        if args.dry_run:
            for f in plan.files:
                extra = ", ".join(x for x in (f"{f.size} bytes" if f.size is not None else "",
                                              f"md5 {f.md5}" if f.md5 else "") if x)
                print(f"{dest.rstrip('/')}/{f.name}  ←  {f.url}" + (f"  ({extra})" if extra else ""))
            print(f"(dry run: nothing was downloaded; {len(plan.files)} file(s) would be recorded in {rel})")
            return EXIT_OK
        got = []
        for f in plan.files:
            path, sha, size, fetched = bd.download(root, dest, f, args.sha256, progress=print)
            if not fetched:
                print(f"kept {path}: already present and matching")
            got.append({"path": path, "sha256": sha, "size": size, "md5": f.md5, "url": f.url})
    except bd.FetchError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    url = plan.files[0].url if source == "URL" else None
    err = _record_input(root, rel, ident, source, acc if source != "URL" else None, url, got)
    if err:
        print(f"steward: {err} (the files stay in {dest})", file=sys.stderr)
        return EXIT_DATAERR
    print(f"{rel}: input {ident} recorded with {len(got)} file(s), their sizes and sha256"
          + (", checked against the archive's md5" if any(g["md5"] for g in got) else ""))
    return EXIT_OK


# ---------------------------------------------------------------- steward study
def cmd_study(args: argparse.Namespace) -> int:
    from . import records as rc

    root, cfg = _cfg(args)
    if cfg is None:
        return EXIT_USAGE
    if cfg.studies is None:
        print("steward: add a [studies] table to steward.toml (dir = \"development/studies\")", file=sys.stderr)
        return EXIT_USAGE
    c = args.study_command
    if c == "new":
        if not _check_id(args.id):
            return EXIT_USAGE
        rel = f"{cfg.studies.dir.rstrip('/')}/{args.id}.toml"
        text = rc.STUDY_TEMPLATE.format(id=args.id, title=args.title.replace('"', "'"), kind=args.kind,
                                        today=date.today().isoformat())
        if not _new_file(root, rel, text):
            return EXIT_DATAERR
        print(f"{rel}: created; fill in its inputs and references, then: steward study fingerprint {args.id} --write")
        return EXIT_OK
    if c == "add-input":  # 0.19.0 (STW-006): no hand-editing of the record
        from .records import RecordRefused, read_rel
        from .fsutil import escapes_root, safe_write

        studies_, _ = rc.load_studies(root, cfg)
        if args.id not in studies_:
            print(f"steward: no study {args.id} (steward study new {args.id} --title …)", file=sys.stderr)
            return EXIT_USAGE
        bad = [f for f in args.file if escapes_root(f) or rc._sha_file(root, f) is None]
        if bad:
            print(f"steward: not a file in the repository (or reached through a link): {', '.join(bad)}", file=sys.stderr)
            return EXIT_USAGE
        rel, st = studies_[args.id]
        ident = args.accession or args.url or args.source
        if any(i.id == ident for i in st.inputs):
            print(f"steward: {args.id} already records an input {ident}", file=sys.stderr)
            return EXIT_USAGE
        refs = [{"path": f, "sha256": rc._sha_file(root, f)} for f in args.file]
        err = _record_input(root, rel, ident, args.source, args.accession, args.url, refs)
        if err:
            print(f"steward: {err}", file=sys.stderr)
            return EXIT_DATAERR
        print(f"{rel}: input {ident} recorded with {len(args.file)} fingerprinted file(s)")
        return EXIT_OK
    if c == "fingerprint" and args.accept is not None:  # 0.20.2 (STW-040): a deliberate change, recorded as one
        if args.write:
            print("steward: --accept and --write do different things; run them separately", file=sys.stderr)
            return EXIT_USAGE
        try:
            old, new = rc.accept(root, cfg, args.id, args.accept)
        except (ValueError, rc.RecordRefused) as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_DATAERR
        print(f"{args.accept}: accepted ({old[:12]} → {new[:12]}); recheck the papers that cite {args.id}")
        return EXIT_OK
    if c == "fingerprint":
        try:
            rows, missed = rc.fingerprint(root, cfg, args.id, args.write)
        except (ValueError, rc.RecordRefused) as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_USAGE
        bad = 0
        for path, rec, act in rows:
            state = "missing" if act is None else "unrecorded" if rec is None else "ok" if rec == act else "CHANGED"
            bad += state in ("missing", "CHANGED")
            print(f"{state:<11} {path}  {act or ''}")
        if args.write:
            wrote = sum(1 for _, rec, act in rows if rec is None and act is not None) - len(missed)
            print(f"recorded {wrote} digest(s); a recorded one is never overwritten (edit a changed one deliberately)")
            for m in missed:
                print(f"steward: {m}: not written; record it inline as {{ path = \"{m}\", sha256 = \"…\" }}",
                      file=sys.stderr)
        return EXIT_DATAERR if bad or missed else EXIT_OK
    studies, invalid = rc.load_studies(root, cfg)
    verdict = {}
    for subj, st, _, _ in rc.check_studies(root, cfg):
        verdict[Path(subj).stem] = st
    if c == "list":
        rows = [{"id": sid, "title": s.title, "kind": s.kind, "status": s.status, "check": verdict.get(sid),
                 "inputs": len(s.inputs), "papers": s.papers} for sid, (_, s) in sorted(studies.items())]
        if wants_json(args):
            write_json(args, {"studies": rows, "invalid": [r for r, _ in invalid]})
            return EXIT_OK
        from .newest import newest_first

        for r in newest_first(rows, lambda r: None, lambda r: r["id"]):  # X05: a study has no date; highest ID first
            print(f"{r['check'] or '—':<11} {r['id']:<24} {r['status']:<8} {r['title']}")
        for rel, err in invalid:
            print(f"{'INVALID':<11} {rel}: {err}")
        return EXIT_OK
    if c == "show":
        if args.id not in studies:
            print(f"steward: no study {args.id}", file=sys.stderr)
            return EXIT_USAGE
        rel, study = studies[args.id]
        if wants_json(args):
            write_json(args, {"path": rel, "check": verdict.get(args.id),
                              "study": study.model_dump(mode="json", by_alias=True)})
        else:
            sys.stdout.write(rc.card(study, verdict))
        return EXIT_OK
    return EXIT_USAGE


# ---------------------------------------------------------------- steward research
def cmd_research(args: argparse.Namespace) -> int:
    from . import records as rc

    root, cfg = _cfg(args)
    if cfg is None:
        return EXIT_USAGE
    if cfg.research is None:
        print("steward: add a [research] table to steward.toml (dir = \"development/research\")", file=sys.stderr)
        return EXIT_USAGE
    if args.research_command == "new":
        if not _check_id(args.id):
            return EXIT_USAGE
        rel = f"{cfg.research.dir.rstrip('/')}/{args.id}.toml"
        text = rc.RESEARCH_TEMPLATES[args.kind].format(id=args.id, title=args.title.replace('"', "'"),
                                                       today=date.today().isoformat())
        if not _new_file(root, rel, text):
            return EXIT_DATAERR
        print(f"{rel}: created ({args.kind}); the research-review skill says how to fill it "
              "(install it with: steward init --skills DIR --kits research)")
        return EXIT_OK
    recs, bad = rc.load_research(root, cfg)
    verdict = {Path(s).stem: (st, d) for s, st, _, d in rc.check_research(root, cfg, rc.today_utc())}
    if wants_json(args):
        rows = [{"id": i, "kind": r.kind, "title": r.title, "date": r.date.isoformat(),
                 "check": verdict.get(i, ("—",))[0]} for i, (_, r) in sorted(recs.items())]
        write_json(args, {"records": rows, "invalid": [rel for rel, _ in bad]})
        return EXIT_OK
    for i, (_, r) in sorted(recs.items(), key=lambda kv: kv[1][1].date, reverse=True):
        st, det = verdict.get(i, ("—", []))
        print(f"{st:<11} {r.date}  {r.kind:<9} {i:<24} {r.title}")
        for d in det:
            print(f"{'':13}{d.get('message') or d['code']}")
    for rel, err in bad:
        print(f"{'INVALID':<11} {rel}: {err}")
    return EXIT_OK


# ---------------------------------------------------------------- steward task brief / template
def _dispatch(args: argparse.Namespace) -> int:
    """0.20.4 (STW-046): `steward task dispatch TASK --to codex|antigravity`."""
    import datetime as _dt

    from . import briefs as br
    from . import dispatch as dp
    from .fsutil import find_root, git_run

    src: Path = args.task
    if not src.is_file():
        print(f"steward: {src} not found", file=sys.stderr)
        return EXIT_USAGE
    root = (args.repo.resolve() if args.repo else find_root(Path.cwd())) or Path.cwd()
    task_text = src.read_text(encoding="utf-8")
    left = br.unfilled(task_text)
    if left:
        print(f"steward: {src} still holds template placeholders in: {', '.join(left)}; fill them first", file=sys.stderr)
        return EXIT_USAGE
    git = {}
    b = git_run(root, "rev-parse", "--abbrev-ref", "HEAD", text=True, timeout=10)
    h = git_run(root, "rev-parse", "--short", "HEAD", text=True, timeout=10)
    if b.returncode == 0:
        git["branch"] = b.stdout.strip()
    if h.returncode == 0:
        git["commit"] = h.stdout.strip()
    if args.agent == "auto":
        return _dispatch_auto(args, root)
    agent_key = "codex" if args.agent == "codex" else "gemini"
    prompt = br.brief(task_text, agent_key, root, git)
    prompt = prompt.rsplit("\n---\nHow to run:", 1)[0] + "\n"  # the footer is for a human; the dispatch runs it
    if not args.implement:
        prompt += ("\nThis checkout is the commit under review, detached and clean: a local clone with its own .git, "
                   "so git log, git diff and git show work here, with every branch and tag. Do not modify any file; "
                   "scratch work only in a temporary folder. Print your full report as your answer.\n")
    if args.inline:
        docs, cut = dp.scope_documents(root, task_text)
        prompt = dp.inline_prompt(prompt, docs, cut)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", br.parse_task(task_text)["fields"].get("ID") or src.stem).strip("-") or "task"
    stamp = _dt.date.today().isoformat()
    report = args.output or root / dp.DIR / f"{stamp}-{name}-{args.agent}.md"
    args.report_path = report  # D02: where `--to auto` reads this run's ending
    try:
        cwd = root if args.dry_run else dp.checkout(root, name) if args.implement else dp.review_clone(root, name)
        cmd = dp.command(args.agent, prompt, cwd, root, args.implement, args.model, args.inline)
    except (OSError, RuntimeError, ValueError) as e:  # W12c (N3b): OSError covers a refused link (LinkRefused)
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_USAGE
    shown = [c if len(c) < 200 else f"<the brief, {len(c)} characters>" for c in cmd]
    print("Dispatch: " + " ".join(shown) + f"\n  in: {cwd}\n  report: {report}")
    if args.dry_run:
        print("(dry run: nothing was run)")
        return EXIT_OK
    report.parent.mkdir(parents=True, exist_ok=True)
    errors = report.with_suffix(".err")
    with open(report, "w", encoding="utf-8") as out, open(errors, "w", encoding="utf-8") as err:
        code = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err).returncode
    text_out, text_err = report.read_text(encoding="utf-8"), errors.read_text(encoding="utf-8")
    dirty = dp.changed(cwd)
    if not args.implement:
        dp.remove_checkout(root, cwd)
    if args.agent == "antigravity" and not text_out.strip() and dp.AGY_DENIED.search(text_err):
        print("steward: Antigravity produced no report: its headless mode refused a command it was not allowed to "
              "run. Run again with --inline (the documents in the prompt, an answer in text only); never "
              "--dangerously-skip-permissions.", file=sys.stderr)
        return EXIT_DATAERR
    if code != 0 or not text_out.strip():
        print(f"steward: the agent exited {code} with no usable report; see {errors}", file=sys.stderr)
        return EXIT_DATAERR
    if dirty and not args.implement:
        print(f"warning: the reviewer changed {len(dirty)} file(s) in its checkout (removed): {'; '.join(dirty[:5])}",
              file=sys.stderr)
    where = f" (its checkout: {cwd}; nothing committed)" if args.implement else ""
    print(f"{report}: the {args.agent} report{where}. Read it, then record it in development/assessment/.")
    return EXIT_OK


HEADLESS = ("codex", "antigravity")  # the agents `steward task dispatch` can run headless


def _dispatch_auto(args: argparse.Namespace, root: Path) -> int:
    """0.23.0 (STW-061 D02): `steward task dispatch TASK --to auto`. The first available worker of [delegation] with a
    headless dispatch runs it; a run that ends in "cannot run" is recorded in the availability ledger and the next
    worker runs it. When none can, the command says who (the master) or until when (on_limit = wait), and exits 75."""
    import copy
    import datetime as _dt

    from pydantic import ValidationError

    from . import delegation as dg
    from .models import load_config

    try:
        cfg = load_config(root)
    except (OSError, ValueError, ValidationError) as e:
        print(f"steward: --to auto needs a valid steward.toml ({str(e).splitlines()[0][:160]})", file=sys.stderr)
        return EXIT_USAGE
    if cfg is None or cfg.delegation is None:
        print("steward: --to auto needs [delegation] in steward.toml (steward agents setup writes it)", file=sys.stderr)
        return EXIT_USAGE
    d = cfg.delegation
    tried: list[str] = []
    while True:
        now = _dt.datetime.now(_dt.timezone.utc)
        try:
            c = dg.choose(root, cfg, [], now, tried, only=HEADLESS)
        except ValueError as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_DATAERR
        if c.agent is None or c.role == "master":  # the master is the caller here: it is named, never run
            brief = {"claude-code": "claude", "codex": "codex"}.get(d.master, "gemini")
            what = (f"try again after {c.until}, or " if c.until else "") + (
                f"the master {d.master} does it itself (steward task brief {args.task} --for {brief})")
            print(f"steward: no worker can run this dispatch ({c.why}); {what}", file=sys.stderr)
            return 75
        print(f"delegation: {c.agent} takes it ({c.why})")
        one = copy.copy(args)
        one.agent, one.model = c.agent, args.model or d.models.get(c.agent)
        code = _dispatch(one)
        report = getattr(one, "report_path", None)
        if code == EXIT_OK or args.dry_run or report is None:
            return code
        texts = []
        for p in (report, report.with_suffix(".err")):
            try:
                texts.append(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
        end = dg.ending(c.agent, "\n".join(texts), now)
        if end is None:  # a task failure, not "cannot run": said by the dispatch above
            return code
        try:
            src = report.with_suffix(".err").resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            src = report.with_suffix(".err").name
        try:
            dg.record_ending(root, cfg.steward.repo_id, end, src)
        except Exception as e:  # noqa: BLE001 - the next worker still runs; the ledger problem is said
            print(f"warning: the availability ledger was not written ({type(e).__name__})", file=sys.stderr)
        print(f"redelegated: {c.agent} cannot run ({end.kind}" + (f", resets {end.reset}" if end.reset else "") + ")")
        tried.append(c.agent)


def cmd_task(args: argparse.Namespace) -> int:
    from . import briefs as br

    if args.task_command == "dispatch":
        return _dispatch(args)

    if args.task_command == "board":
        from .cockpit import parse_now, task_board

        root, cfg = _cfg(args)
        if cfg is None:
            return EXIT_USAGE
        try:
            now = parse_now(args.now)
        except ValueError as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_USAGE
        rows = task_board(root, cfg, now, use_default=True)
        if wants_json(args):
            write_json(args, {"board": cfg.tasks.board if cfg.tasks else None, "tasks": rows})
        elif rows:
            from .cockpit import last_changed
            from .newest import newest_first

            changed = last_changed(root, [row["path"] for row in rows])  # X05: newest first, by its latest change
            for row in newest_first(rows, lambda r: changed.get(r["path"]), lambda r: r["id"]):
                marks = [m for m, on in (("archived", row["archived"]), ("stale", row["stale"])) if on]
                suffix = f" ({', '.join(marks)})" if marks else ""
                print(f"{row['id']:<16} {row['status']:<14} {row['path']}{suffix}")
        else:
            print("no task records")
        return EXIT_OK

    if args.task_command == "template":
        if not args.name:
            print("Brief templates: " + ", ".join(br.TEMPLATES) + "\n(steward task template NAME > development/tasks/ID-NAME.md)")
            return EXIT_OK
        if args.name not in br.TEMPLATES:
            print(f"steward: no template {args.name}; choose from {', '.join(br.TEMPLATES)}", file=sys.stderr)
            return EXIT_USAGE
        text = br.template(args.name)
        if getattr(args, "output", None):  # 0.20.2 (STW-040): written in place, folders made, never over a file
            import os

            root_ = (args.repo.resolve() if args.repo else None) or Path.cwd()
            if os.path.lexists(args.output):
                print(f"steward: {args.output} exists; a task is never overwritten by its template", file=sys.stderr)
                return EXIT_DATAERR
            out_abs = Path(os.path.abspath(args.output))
            if not out_abs.is_relative_to(root_.resolve()):
                out_abs.parent.mkdir(parents=True, exist_ok=True)
            why = _write_out(root_, args.output, text)
            if why:
                print(f"steward: {why}; nothing written", file=sys.stderr)
                return EXIT_DATAERR
            print(f"{args.output}: the {args.name} template; fill in its fields, then: steward task brief "
                  f"{args.output} --for AGENT --output BRIEF.md")
            return EXIT_OK
        sys.stdout.write(text)
        return EXIT_OK
    src: Path = args.task
    if not src.is_file():
        print(f"steward: {src} not found", file=sys.stderr)
        return EXIT_USAGE
    from .fsutil import find_root, git_run

    root = (args.repo.resolve() if args.repo else find_root(Path.cwd())) or Path.cwd()
    git = {}
    b = git_run(root, "rev-parse", "--abbrev-ref", "HEAD", text=True, timeout=10)
    h = git_run(root, "rev-parse", "--short", "HEAD", text=True, timeout=10)
    if b.returncode == 0:
        git["branch"] = b.stdout.strip()
    if h.returncode == 0:
        git["commit"] = h.stdout.strip()
    task_text = src.read_text(encoding="utf-8")
    left = br.unfilled(task_text)
    if left:  # 0.20.2 (STW-040): said, not hidden; the brief is still written
        print(f"warning: {src} still holds template placeholders in: {', '.join(left)}; fill them before sending",
              file=sys.stderr)
    text = br.brief(task_text, args.agent, root, git)
    if args.output:  # the footer names the file the brief is in, as given (AQ9: the footer line only)
        import shlex

        head, sep, foot = text.rpartition("\nHow to run: ")
        if sep:
            text = head + sep + foot.replace("$(cat BRIEF.md)", f"$(cat {shlex.quote(str(args.output))})")
    from . import privacy as pv
    from .cli import _config

    terms: list[Any] = []
    if (root / "steward.toml").is_file():  # AE12: a brief leaves the repository; its screen fails closed
        _, cfg = _config(args)
        if cfg is None:
            print("steward: steward.toml is not valid, so the brief cannot be screened; nothing written", file=sys.stderr)
            return EXIT_DATAERR
        lists = pv.load(root, cfg)
        broken = [x.name for x in lists if x.state in ("missing", "unreadable") or x.errors]
        if broken:
            print(f"steward: term list(s) {', '.join(broken)} cannot be used, so the brief cannot be screened",
                  file=sys.stderr)
            return EXIT_DATAERR
        terms = [t for x in lists for t in x.terms]
    hits, _ = pv.scan_text(text, terms, True, honour_marker=False)  # no line waiver: the brief is published
    if hits:
        print(f"steward: the brief holds {len(hits)} term-list or local-path hit(s) (lines "
              f"{', '.join(str(h['line']) for h in hits[:10])}); reword the task first", file=sys.stderr)
        return EXIT_DATAERR
    if args.output:
        why = _write_out(root, args.output, text, alias_of=src)
        if why:
            print(f"steward: {why}; nothing written", file=sys.stderr)
            return EXIT_DATAERR
        print(f"{args.output}: brief for {br.AGENTS[args.agent]['name']}")
    else:
        sys.stdout.write(text)
    return EXIT_OK


# ---------------------------------------------------------------- steward paper citations
def cmd_paper_citations(args: argparse.Namespace) -> int:
    from . import records as rc
    from .cli import _paper_ctx
    from .fsutil import escapes_root, safe_write

    got = _paper_ctx(args)
    if got is None:
        return EXIT_USAGE
    root, name, pp = got
    if not pp.citations:
        print(f"steward: add citations = \"citations.toml\" to [paper.{name}] to keep a verification record", file=sys.stderr)
        return EXIT_USAGE
    rel = pp.rel(pp.citations)
    if escapes_root(rel):
        print(f"steward: {rel} is outside the repository", file=sys.stderr)
        return EXIT_USAGE
    import tomllib

    try:
        have: dict[str, Any] = {}
        try:
            have = {r.key: r for r in rc.CitationsFile.model_validate(
                tomllib.loads(rc.read_rel(root, rel).decode("utf-8"))).citation}
        except rc.RecordRefused as e:
            if e.reason != "missing":
                raise
        cited, problems, _ = rc.cited_entries(root, pp, lambda r: rc.read_rel(root, r))
    except rc.RecordRefused as e:
        print(f"steward: refused: {e}", file=sys.stderr)
        return EXIT_DATAERR
    json_output = wants_json(args)
    if not json_output:
        for d in problems:
            print(f"steward: {d.get('message', d['code'])}", file=sys.stderr)
    todo, mismatch, ok = [], [], 0
    for _, e, cid in cited:
        r = have.get(e.key)
        if r is not None and r.id.lower() == cid:
            a_, b_ = rc.norm_title(r.title), rc.norm_title(e.fields.get("title", ""))
            if a_ and a_ == b_:
                ok += 1
            else:
                mismatch.append((e.key, cid, r.title))
            continue
        todo.append((e, cid))
    if json_output:
        write_json(args, {"paper": name, "path": rel, "verified": ok,
                          "mismatched": [{"key": key, "id": cid, "title": title} for key, cid, title in mismatch],
                          "unverified": [{"key": e.key, "id": cid} for e, cid in todo],
                          "problems": problems})
        return EXIT_DATAERR if mismatch or problems else EXIT_OK
    if not args.fetch:
        print(f"{ok} verified, {len(mismatch)} mismatched or untitled, {len(todo)} without a record (--fetch resolves them)")
        for k, cid, t in mismatch:
            print(f"MISMATCH  {k}: {cid} resolves to {t!r}")
        for e, cid in todo:
            print(f"UNVERIFIED {e.key}: {cid}")
        return EXIT_DATAERR if mismatch or problems else EXIT_OK
    added, failed = 0, []
    for e, cid in todo:
        got_t = rc.fetch_title(cid)
        if got_t is None:
            failed.append((e.key, cid))
            continue
        have[e.key] = rc.CitationRecord(key=e.key, id=cid, title=got_t[0], checked=rc.today_utc(), via=got_t[1])
        added += 1
        a_, b_ = rc.norm_title(got_t[0]), rc.norm_title(e.fields.get("title", ""))
        if not a_ or a_ != b_:
            mismatch.append((e.key, cid, got_t[0]))
    safe_write(root, rel, rc.render_citations(list(have.values())).encode("utf-8"))  # validated before writing
    print(f"{rel}: {added} recorded; {len(failed)} could not be resolved; {len(mismatch)} title mismatch(es)")
    for k, cid, t in mismatch:
        print(f"MISMATCH  {k}: {cid} resolves to {t!r}")
    for k, cid in failed:
        print(f"UNRESOLVED {k}: {cid}")
    return EXIT_DATAERR if mismatch or failed or problems else EXIT_OK  # AE10: an unresolved lookup is not success


# ---------------------------------------------------------------- steward diff runs
def run_rows(root: Path, cfg: Any, label: str | None = None) -> list[dict[str, Any]]:
    from .fsutil import glob_match
    from .ledger import verify
    from .models import RunSection

    rc_ = cfg.run or RunSection()
    p = root / rc_.ledger
    if not p.is_file():
        return []
    from .records import RecordRefused, _open_rel

    try:  # AE5: the ledger is reached without links, inside the repository
        import os as _os

        _os.close(_open_rel(root, rc_.ledger))
    except RecordRefused as e:
        raise ValueError(str(e)) from None
    v = verify(p)
    if v.errors or v.torn_tail:
        raise ValueError(f"{rc_.ledger} is not intact; recover it first")
    started = {e["run"]: e for e in v.entries if e.get("kind") == "started"}
    rows = []
    for e in v.entries:
        if e.get("kind") not in ("outcome", "interrupted"):
            continue
        s = started.get(e.get("run"), {})
        lab = s.get("label") or ""
        if label and not glob_match(lab, label):
            continue
        rows.append({"run": e.get("run"), "label": lab, "status": e.get("status", "interrupted"),
                     "duration_s": e.get("duration_s"), "peak_rss_mb": e.get("peak_rss_mb"),
                     "exit_code": e.get("exit_code"), "time": e.get("time")})
    return rows


def cmd_diff_runs(args: argparse.Namespace, root: Path, cfg: Any) -> int:
    from . import charts

    try:
        rows = run_rows(root, cfg, args.label)
    except ValueError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    if wants_json(args):
        write_json(args, {"runs": rows})
    else:
        print(f"{'Label':<28} {'Status':<11} {'Duration s':>11} {'Peak MB':>9}  Run")
        from .newest import newest_first

        for r in newest_first(rows, lambda r: r["time"], lambda r: r["run"]):  # X05: newest first
            d = f"{r['duration_s']:.1f}" if isinstance(r["duration_s"], (int, float)) else "—"
            m = f"{r['peak_rss_mb']:.0f}" if isinstance(r["peak_rss_mb"], (int, float)) else "—"
            print(f"{(r['label'] or '—')[:28]:<28} {r['status']:<11} {d:>11} {m:>9}  {r['run']}")
    if args.svg:
        metric = {"duration": ("duration_s", "s", "Run duration"), "memory": ("peak_rss_mb", "MB", "Peak memory")}[args.metric]
        why = _write_out(root, args.svg, charts.bars(rows, metric[0], metric[2], metric[1]))
        if why:
            print(f"steward: {why}; nothing written", file=sys.stderr)
            return EXIT_DATAERR
        print(f"{args.svg}: chart of {len(rows)} run(s)", file=sys.stderr)
    return EXIT_OK


# ---------------------------------------------------------------- steward licence (0.19.0, REQ-012)
def cmd_licence(args: argparse.Namespace) -> int:
    import json

    from . import licence as li
    from .records import read_rel

    root, cfg = _cfg(args)
    if cfg is None:
        return EXIT_USAGE
    if cfg.licence is None:
        print('steward: add [licence] to steward.toml (declared = "MIT", distribution = "internal")', file=sys.stderr)
        return EXIT_USAGE
    read = lambda r: read_rel(root, r)
    rows, problems = li.inventory(root, cfg, read)
    for p in problems:
        print(f"steward: {p}", file=sys.stderr)
    if args.licence_command == "inventory":
        if wants_json(args):
            write_json(args, {
                "declared": cfg.licence.declared, "distribution": cfg.licence.distribution,
                "policy": cfg.licence.policy, "dependencies": rows,
            })
        else:
            print(f"{cfg.licence.declared} · {cfg.licence.distribution} · {cfg.licence.policy}")
            for r in rows:
                print(f"{r['status']:<16} {r['name']} {r['version']}: {r['licence'] or 'UNKNOWN'}  ({r['why']})")
            print(li.LEGAL)
        return EXIT_DATAERR if any(r["status"] in ("FAIL", "UNKNOWN") for r in rows) or problems else EXIT_OK
    project = li.project_name(root, read) or cfg.steward.project
    if args.format == "cyclonedx":
        from . import __version__  # noqa: F401  (the toolkit version is not the project's)

        version = ""
        try:
            import tomllib

            version = tomllib.loads(read("pyproject.toml").decode("utf-8")).get("project", {}).get("version", "")
        except (OSError, ValueError):
            pass
        text = json.dumps(li.cyclonedx(rows, project, version), indent=2, sort_keys=True) + "\n"
    else:
        text = li.notices_text(rows, cfg, project)
    if args.write:
        if args.format != "md":
            print("steward: --write writes the Markdown notices file; print the SBOM with --format cyclonedx", file=sys.stderr)
            return EXIT_USAGE
        why = _write_out(root, root / cfg.licence.notices, text)
        if why:
            print(f"steward: {why}; nothing written", file=sys.stderr)
            return EXIT_DATAERR
        print(f"{cfg.licence.notices}: {len(rows)} dependencies")
    else:
        sys.stdout.write(text)
    return EXIT_OK


# ---------------------------------------------------------------- steward release go-public (0.20.3, STW-044)
def _go_public(root: Path, cfg: Any, args: argparse.Namespace) -> int:
    """Readiness, the plan, and with --apply the steps, in order."""
    from . import golive as gl
    from . import publish as pb
    from .fsutil import git_run
    from .models import PublishSection

    dev = args.dev_name or f"{args.name}-dev"
    bad = gl.check_names(args.owner, args.name, dev)
    if bad:
        print(f"steward: {bad}", file=sys.stderr)
        return EXIT_USAGE
    tag = args.tag
    if tag is None:
        tags = sorted(git_run(root, "tag", "--list", "v*", text=True, timeout=10).stdout.split(), key=pb._vkey)
        if not tags:
            print("steward: no v* tag to publish; tag a release first", file=sys.stderr)
            return EXIT_USAGE
        tag = tags[-1]
    public_url = f"https://github.com/{args.owner}/{args.name}.git"
    have = cfg.publish
    check_cfg = cfg if have and have.remote and have.author else cfg.model_copy(update={
        "publish": (have or PublishSection()).model_copy(update={
            "remote": (have.remote if have else None) or public_url,
            "author": (have.author if have else None) or "release <noreply@example.org>"})})
    try:
        ready = gl.readiness(root, check_cfg, tag)
    except pb.PublishError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    print(f"Readiness of {tag}: {ready.files} public file(s); " + ("nothing to fix" if ready.clean else
          f"{sum(map(len, ready.groups.values()))} finding(s)"))
    for kind, _rx, fix in list(gl.KINDS) + [("other", None, "see each line")]:
        items = ready.groups.get(kind, [])
        if items:
            print(f"  {kind} ({len(items)}): {fix}")
            for it in items[:5]:
                print(f"    {it}")
            if len(items) > 5:
                print(f"    … {len(items) - 5} more (steward release publish {tag} --dry-run lists them all)")
    if have is None or not have.author:
        print("  [publish] author: set it to the public identity (a name and a no-reply address) before publishing")
    steps = gl.plan(root, cfg, args.owner, args.name, dev, tag, public=args.public)
    print("Plan" + ("" if args.apply else " (nothing is changed without --apply)") + ":")
    import shlex

    for i, (what, cmd) in enumerate(steps, 1):
        shown = "(written by steward)" if cmd[0] == "steward-internal" else "$ " + shlex.join(cmd)  # AR4: quoted
        print(f"  {i}. {what}\n     {shown}")
    ok = ready.clean and have is not None and bool(have.author)
    if not args.apply:
        return EXIT_OK if ok else EXIT_DATAERR  # AR4: a missing author is not ready either
    if not ok:
        print("steward: not applied: fix the readiness findings (and [publish] author) first", file=sys.stderr)
        return EXIT_DATAERR
    why = gl.preflight(root, cfg, args.owner, args.name, tag, steps)  # AR3: before anything changes
    if why:
        print(f"steward: not applied: {why}", file=sys.stderr)
        return EXIT_DATAERR
    for i, (what, cmd) in enumerate(steps, 1):
        r = gl.run_step(root, cmd)
        if r.returncode != 0:
            print(f"steward: step {i} failed ({what}): {(r.stderr or r.stdout).strip()[:300]}", file=sys.stderr)
            print(f"done before it: {', '.join(w for w, _ in steps[:i - 1]) or 'nothing'}", file=sys.stderr)
            return EXIT_DATAERR
        print(f"done {i}. {what}")
    if args.public:
        print(f"{args.owner}/{args.name} is public with {tag}; development continues in {args.owner}/{dev}")
    else:
        print(f"{args.owner}/{args.name} holds {tag} and is private: look at it on GitHub (README, files, the one "
              f"release commit, the tag), then make it public:\n  $ {' '.join(gl.make_public(args.owner, args.name))}\n"
              f"Development continues in {args.owner}/{dev}.")
    return EXIT_OK


# ---------------------------------------------------------------- steward release publish|status|setup (STW-007, STW-020)
def cmd_publish(args: argparse.Namespace) -> int:
    from . import publish as pb
    from .fsutil import find_root

    top = (args.repo.resolve() if args.repo else find_root(Path.cwd())) or Path.cwd()
    if args.release_command == "setup" and (top / "steward.toml").is_symlink():  # AF18: refused before it is read
        print("steward: steward.toml is a link; refused", file=sys.stderr)
        return EXIT_DATAERR
    root, cfg = _cfg(args)
    if cfg is None:
        return EXIT_USAGE
    if args.release_command == "go-public":
        return _go_public(root, cfg, args)
    try:
        if args.release_command == "setup":
            mode, remote, author = args.mode, args.remote, args.author
            if mode is None and sys.stdin.isatty():  # asked, when a human is at the terminal; flags for agents
                print("How should released versions go public?\n  mirror: one clean commit per release in a separate "
                      "public repository; development stays private (recommended)\n  open: development itself is "
                      "public; private records move to a separate private repository")
                mode = (input("mode [mirror/open] (mirror): ").strip() or "mirror")
                remote = remote or (input("public repository URL or path (leave empty to set later): ").strip() or None)
                author = author or (input("public author (a name and your no-reply address): ").strip() or None)
            if mode not in ("mirror", "open"):
                print("steward: give --mode mirror or --mode open", file=sys.stderr)
                return EXIT_USAGE
            if cfg.publish is not None:
                print("steward: [publish] already exists in steward.toml; edit it there", file=sys.stderr)
                return EXIT_USAGE
            from .fsutil import safe_write
            from .records import RecordRefused, read_rel

            try:  # AF18: never appended through a link
                current = read_rel(root, "steward.toml").decode("utf-8")
            except RecordRefused as e:
                print(f"steward: steward.toml cannot be extended ({e})", file=sys.stderr)
                return EXIT_DATAERR
            safe_write(root, "steward.toml", (current + pb.setup_text(mode, remote, author)).encode("utf-8"))
            print(f"[publish] mode = {mode} written to steward.toml")
            if mode == "open":
                plan = pb.open_plan(root, cfg)
                print("Plan for open development (nothing is moved, rewritten or pushed by this command):")
                print(f"  move to a private records repository: {', '.join(plan['move_to_records']) or 'nothing'}"
                      " (then set [paths] records)")
                print(f"  author addresses in the history: {len(plan['authors'])}; commits with private content: "
                      f"{plan['commits_with_private_content']}")
                print(f"  read: {plan['coverage']}")
                for o in plan["options"]:
                    print(f"  option: {o}")
            else:
                print("Next: tag a release, then `steward release publish vX.Y.Z --dry-run`, then without --dry-run, then --push.")
            return EXIT_OK
        if args.release_command == "status":
            st = pb.status(root, cfg)
            if wants_json(args):
                write_json(args, st)
                return EXIT_OK
            print(f"mode {st['mode']} · public {st['remote'] or '(not set)'}")
            print(f"last public release: {st['last_public'] or 'none'}" + ("" if st["last_public_pushed"] is None else
                  (" (pushed)" if st["last_public_pushed"] else " (not pushed yet)")))
            print(f"not yet published: {', '.join(st['unpublished']) or 'nothing'}")
            return EXIT_OK
        res = pb.publish(root, cfg, args.tag, push=args.push, dry_run=args.dry_run)
    except pb.PublishError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    print(f"{res['tag']}: {res['files']} public file(s); {res['ids_removed']} private ID(s) removed from the changelog")
    for f in res["findings"]:
        print(f"REFUSED  {f}")
    if res["findings"]:
        print("steward: nothing published: fix the findings above", file=sys.stderr)
        return EXIT_DATAERR
    if args.dry_run:
        print("dry run: the export is clean; nothing was written")
        return EXIT_OK
    print(f"committed {res.get('commit')} and tagged {res['tag']} in the staging clone ({res['branch']})")
    print(f"pushed to {res['remote']}" if res["pushed"] else
          f"not pushed: review it in {cfg.publish.staging}, then `steward release publish {res['tag']} --push`")
    return EXIT_OK


# ---------------------------------------------------------------- steward channel (STW-019)
def cmd_channel(args: argparse.Namespace) -> int:
    import shlex
    import subprocess

    from . import publish as pb

    root, cfg = _cfg(args)
    if cfg is None:
        return EXIT_USAGE
    chans = {c.name: c for c in cfg.channel}
    if args.channel_command == "status":
        st = pb.channel_state(root)
        if wants_json(args):
            write_json(args, {"channels": [
                {"name": name, "channel": st.get(name, {}).get("channel"), "tag": st.get(name, {}).get("tag"),
                 "time": st.get(name, {}).get("time")} for name in sorted(chans)
            ]})
            return EXIT_OK
        if not chans:
            print("no [[channel]] declared")
        for n in sorted(chans):
            s = st.get(n)
            print(f"{n}: " + (f"{s['channel']}" + (f" {s['tag']}" if s.get("tag") else "") + f" (since {s['time']})" if s else "not switched by steward yet"))
        return EXIT_OK
    ch = chans.get(args.name)
    if ch is None:
        print(f"steward: no [[channel]] named {args.name}; declared: {', '.join(sorted(chans)) or 'none'}", file=sys.stderr)
        return EXIT_USAGE
    cmd = pb.channel_command(ch, args.which, args.tag)
    print("install command: " + " ".join(shlex.quote(c) for c in cmd))
    if not args.yes:
        print("(printed only; run it with --yes)")
        return EXIT_OK
    try:
        r = pb.run_installer(cmd)  # W12 F4: from an empty temporary directory, so no project file steers it
    except OSError:
        print("steward: could not start the installer; the recorded channel is unchanged", file=sys.stderr)
        return EXIT_DATAERR
    if r.returncode != 0:
        print(f"steward: the install failed (exit {r.returncode}); the recorded channel is unchanged", file=sys.stderr)
        return EXIT_DATAERR
    pb.record_channel(root, ch.name, args.which, args.tag)
    print(f"{ch.name}: now on {args.which}" + (f" {args.tag}" if args.tag else ""))
    return EXIT_OK
