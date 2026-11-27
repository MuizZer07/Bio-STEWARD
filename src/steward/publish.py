"""Release publishing and install channels (0.19.0; STW-007, STW-019, STW-020; Muiz, 2026-11-25: model A, supervised
by steward in every project).

**Model A, the release mirror.** Development stays in the private repository (`origin`). Each release is published to
a separate public repository as one clean commit, built from the release tag:

1. the tag's files are exported (`git archive`), keeping only the public paths (`[publish] include` minus
   `exclude`; development records and the exchange are always left out);
2. private item IDs (`ABC-REQ-012` and the like) are removed from the published changelog;
3. the export is scanned: every configured term list (no line waiver), local paths with a user name, and the licence
   gate (R-79 – R-81) when `[licence]` is configured; any finding refuses the publish;
4. the export replaces the content of a **staging clone** of the public repository (never the working checkout, whose
   `origin` is never touched), is committed with the declared public author and tagged;
5. it is pushed to the public repository only with `--push`, after the summary has been shown.

**Model B, open development**, can be chosen later with `steward release setup`: the plan moves development records
to a private records repository and lists what in the history is not public-safe; nothing is rewritten or pushed by
the plan.

**Install channels** let a project switch a tool it uses between its stable (public) and development (private) source
in one command, and record which one it is on.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .models import Channel, PublishSection as PublicSection, Strict, Text  # noqa: F401

ALWAYS_PRIVATE = ["development/**", "exchange/**", ".steward/**", "**/.steward/**", ".claude/**", ".agents/**",
                  "**/__pycache__/**", "**/*.pyc", "**/.DS_Store", "steward.local.toml"]
DEFAULT_PUBLIC = ["**/*"]
ANY_ID = r"(?<![\w-])({codes})-(?:REQ|DEF|FB|RSP|Q|REL)-\d{{2,}}(?![\w-])"
PRIVATE_ID = re.compile(ANY_ID.format(codes="[A-Z]{2,6}"))


class PublishError(ValueError):
    pass


def settings(cfg: Any) -> PublicSection:
    pub = getattr(cfg, "publish", None)
    if pub is None:
        raise PublishError("no [publish] table: run `steward release setup` first")
    return pub


def _author_env(author: str | None) -> dict[str, str]:
    m = re.match(r"^\s*(.+?)\s*<([^>]+)>\s*$", author or "")
    return {} if not m else {"GIT_AUTHOR_NAME": m.group(1), "GIT_AUTHOR_EMAIL": m.group(2),
                             "GIT_COMMITTER_NAME": m.group(1), "GIT_COMMITTER_EMAIL": m.group(2)}


def _git(cwd: Path, *args: str, check: bool = True, author: str | None = None, text: bool = True,
         network: bool = False) -> subprocess.CompletedProcess:
    """git for publishing. Local work (AF2) runs isolated: no inherited GIT_* variables, no system or user
    configuration, the safe settings (no hooks, filters' programs, fsmonitor or transports). Only `network` calls (the
    fetch and push of `--push`) use the user's own git environment, for its credentials, still without hooks."""
    from .fsutil import SAFE_GIT_CONFIG, git_env

    if network:
        env = dict(os.environ)
        cmd = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "submodule.recurse=false"]
    else:
        env = git_env()
        cmd = ["git", "--no-optional-locks", *[a for c in SAFE_GIT_CONFIG for a in ("-c", c)],
               "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false", "-c", "core.attributesFile=/dev/null"]
    env.update(_author_env(author))
    r = subprocess.run([*cmd, *args], cwd=cwd, capture_output=True, text=text, env=env)
    if check and r.returncode != 0:
        err = r.stderr if text else r.stderr.decode("utf-8", "replace")
        raise PublishError(f"git {' '.join(args[:2])} failed: {err.strip()[:300]}")
    return r


def stage_dir(root: Path, pub: PublicSection) -> Path:
    """AF1: the staging clone lives under `.steward/`, reached without links, never the checkout or outside it."""
    from .fsutil import escapes_root

    if os.path.isabs(pub.staging) or pub.staging.startswith("/"):  # AF1: never an absolute spelling
        raise PublishError("[publish] staging must be a relative folder under .steward/ (for example .steward/publish)")
    rel = os.path.normpath(pub.staging)
    if escapes_root(rel) or not re.fullmatch(r"\.steward/[A-Za-z0-9_-][A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]+)*", rel):
        raise PublishError("[publish] staging must be a folder under .steward/ (for example .steward/publish)")
    cur = root
    for part in Path(rel).parts:
        cur = cur / part
        if cur.is_symlink():
            raise PublishError(f"{rel} is reached through a link; refused")
    path = root / rel
    if path.resolve() in (root.resolve(), (root / ".steward").resolve()) or \
            not path.resolve().is_relative_to((root / ".steward").resolve()):
        raise PublishError(f"{rel} is not a folder of its own under .steward/")
    if (path / ".git").is_symlink() or ((path / ".git").exists() and not (path / ".git").is_dir()):
        raise PublishError(f"{rel}/.git is not a folder of its own; refused")  # AF1: metadata never elsewhere
    return path


ALLOWED_STAGE_CONFIG = re.compile(r"^(core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|"
                                  r"precomposeunicode)|remote\.origin\.(url|fetch)|branch\.[^.]+\.(remote|merge)|"
                                  r"init\.defaultbranch)=", re.I)


def _stage_config_ok(stage: Path) -> list[str]:
    """AF2: the staging repository's own configuration holds only what steward wrote (no filters, drivers, hooks,
    signing programs, URL rewrites or push URLs); anything else is named and refuses."""
    r = _git(stage, "config", "--local", "--list", check=False)
    if r.returncode != 0:  # AF2: an unreadable configuration is never an empty one
        return ["(the configuration cannot be read)"]
    return [ln.split("=", 1)[0] for ln in (r.stdout or "").splitlines() if ln and not ALLOWED_STAGE_CONFIG.match(ln)]


def private_paths(cfg: Any) -> list[str]:
    """AF4: every path that holds this project's private records: the fixed ones, the configured records root,
    the exchange folder and every configured term list."""
    from . import privacy as pv

    out = list(ALWAYS_PRIVATE)
    rec = getattr(getattr(cfg, "paths", None), "records", None)
    if rec:
        out.append(rec.rstrip("/") + "/**")
    out += [s.file for s in pv.sources(cfg)]
    return out


def private_id_re(cfg: Any, pub: PublicSection) -> re.Pattern[str] | None:
    """Item IDs of the projects this one exchanges with (consumers, peers) and any declared private codes."""
    ex = getattr(cfg, "exchange", None)
    codes = set(pub.private_codes) | (set(ex.consumers) | set(ex.peers) if ex else set())
    return re.compile(ANY_ID.format(codes="|".join(sorted(map(re.escape, codes))))) if codes else None


def _public(rel: str, pub: PublicSection, private: list[str]) -> bool:
    from .fsutil import glob_match

    if any(glob_match(rel, p) for p in private + list(pub.exclude)):
        return False
    return any(glob_match(rel, p) for p in pub.include)


class Export(dict):
    """{path: bytes} of one export, with the paths git records as executable (AI3: each export keeps its own)."""

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.executable: set[str] = set()


def export(root: Path, tag: str, pub: PublicSection, private: list[str]) -> Export:
    """{path: bytes} of the tag's public files (links and submodules are left out)."""
    r = _git(root, "archive", "--format=tar", tag, check=False, text=False)
    if r.returncode != 0:
        raise PublishError(f"tag {tag} cannot be exported: {r.stderr.decode('utf-8', 'replace').strip()[:200]}")
    out = Export()
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
        for m in tf.getmembers():
            if m.isfile() and _public(m.name, pub, private):
                f = tf.extractfile(m)
                if f is not None:
                    out[m.name] = f.read()
                    if m.mode & 0o111:
                        out.executable.add(m.name)
    if not out:
        raise PublishError("nothing to publish: no file of the tag matches [publish] include")
    return out


def redact(text: str, rx: re.Pattern[str] | None = None) -> tuple[str, int]:
    """The changelog without private item IDs: `(ABC-REQ-012)` and lists of IDs become nothing; a sentence keeps its
    words. Returns (text, how many IDs were removed)."""
    rx = rx or PRIVATE_ID
    n = len(rx.findall(text))
    t = rx.sub("", text)
    t = re.sub(r"\(\s*(?:[,;:]\s*)*\)", "", t)                    # empty brackets left behind
    t = re.sub(r"(?:,\s*){2,}", ", ", t)
    t = re.sub(r"\(\s*,\s*", "(", t)
    t = re.sub(r",\s*\)", ")", t)
    t = re.sub(r"[ \t]+([,.;:])", r"\1", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t, n


def scan_export(root: Path, cfg: Any, files: dict[str, bytes], pub: PublicSection, lists: Any = None) -> list[str]:
    """Findings that refuse the publish (AF4, AF12): term lists read without links (an unusable list refuses), hits
    in file names and contents (no line waiver), local paths, private item IDs, and binary files that `[publish]
    binary` does not allow (they cannot be scanned). A finding names the file and line, never the private value."""
    from . import privacy as pv
    from .fsutil import glob_match
    from .records import read_rel

    lists = lists if lists is not None else pv.load(root, cfg, read=lambda rel: read_rel(root, rel))
    broken = [s.name for s in lists if s.state in ("missing", "unreadable") or s.errors]
    if broken:
        return [f"term list(s) {', '.join(broken)} cannot be used, so the export cannot be scanned"]
    terms = [t for s in lists for t in s.terms]
    ids = private_id_re(cfg, pub)
    out = []
    for rel, data in sorted(files.items()):
        hits, _ = pv.scan_text(rel, terms, False, honour_marker=False)
        if hits or (ids and ids.search(rel)):  # AF4: no part of the private path is printed
            out.append("(a file whose path holds a private term or item ID)")
            continue
        try:
            opaque = b"\x00" in data or (data.decode("utf-8") is None)
        except UnicodeDecodeError:
            opaque = True  # not text: it cannot be scanned either
        if opaque:
            if not any(glob_match(rel, g) for g in pub.binary):
                out.append(f"{rel}: a binary file cannot be scanned; allow its kind in [publish] binary or exclude it")
            continue
        text = data.decode("utf-8", errors="replace")
        hits, _ = pv.scan_text(text, terms, True, honour_marker=False)
        for h in hits[:3]:
            what = "a local path with a user name" if h["kind"] == "local_path" else f"term list {h['term'].label}"
            out.append(f"{rel}:{h['line']}: {what}")
        if ids:
            for n, line in enumerate(text.splitlines(), start=1):
                if ids.search(line):
                    out.append(f"{rel}:{n}: a private item ID")
                    break
    return out


def _blob_sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _tree_matches(stage: Path, ref: str, files: dict[str, bytes]) -> bool:
    """AF2, AF3: the staged commit holds exactly the scanned paths and bytes."""
    r = _git(stage, "ls-tree", "-r", "-z", ref, check=False, text=False)
    if r.returncode != 0:
        return False
    got = {}
    for rec in r.stdout.split(b"\0"):
        if rec:
            meta, _, name = rec.partition(b"\t")
            mode, _, sha = meta.split()
            got[name.decode("utf-8", "surrogateescape")] = (mode.decode(), sha.decode())
    exe = getattr(files, "executable", set())
    return got == {rel: ("100755" if rel in exe else "100644", _blob_sha(d)) for rel, d in files.items()}


def build(root: Path, cfg: Any, tag: str) -> tuple[dict[str, bytes], int, list[str]]:
    """(files, private IDs removed, findings): the tag's public export, redacted and scanned, with the licence gate
    run on that export at public strictness (AF5)."""
    pub = settings(cfg)
    if _git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}", check=False).returncode != 0:
        raise PublishError(f"no tag {tag}")
    files = export(root, tag, pub, private_paths(cfg))
    removed = 0
    if pub.redact_ids and pub.changelog in files:
        t, removed = redact(files[pub.changelog].decode("utf-8", errors="replace"), private_id_re(cfg, pub) or PRIVATE_ID)
        files[pub.changelog] = t.encode("utf-8")
    from . import privacy as pv
    from .records import read_rel

    lists = pv.load(root, cfg, read=lambda rel: read_rel(root, rel))  # AK3: read once, used by both scans
    findings = scan_export(root, cfg, files, pub, lists)
    if findings:  # AF4: the licence gate names files; it runs once nothing private is left to name
        return files, removed, findings + ["licence: not checked until the privacy findings are fixed"]
    lcfg = cfg
    listed = _git(root, "ls-tree", "--name-only", tag, "--", "steward.toml", check=False)
    if listed.returncode != 0:  # AJ1: absence is established, never assumed from a failed read
        return files, removed, ["licence: the tag's steward.toml cannot be listed, so its [licence] cannot be checked"]
    if listed.stdout.strip():  # AF5: the tag's own [licence] decides, whether or not steward.toml is published
        shown = _git(root, "show", f"{tag}:steward.toml", check=False, text=False)
        try:
            from .models import LicenceSection

            if shown.returncode != 0:
                raise ValueError("unreadable")
            doc = tomllib.loads(shown.stdout.decode("utf-8"))
            sec = doc.get("licence")
            if sec is not None:
                if not isinstance(sec, dict):
                    raise ValueError("not a table")
                lcfg = cfg.model_copy(update={"licence": LicenceSection.model_validate(sec)})
        except Exception:  # noqa: BLE001
            return files, removed, ["licence: the tag's steward.toml or its [licence] table cannot be read"]
    if getattr(lcfg, "licence", None) is not None:
        from .licence import release_findings

        found = [f"licence: {f}" for f in release_findings(root, lcfg, files)]  # AF5: the export itself
        findings += _screen(lists, cfg, pub, found)  # AJ2: a path from the tag's configuration is screened too
    return files, removed, findings


def _screen(lists: Any, cfg: Any, pub: PublicSection, lines: list[str]) -> list[str]:
    """Findings with every line that names a private term, a local path or a private item ID withheld (AJ2), by the
    term lists the export scan used (AK3)."""
    from . import privacy as pv

    if any(s.state in ("missing", "unreadable") or s.errors for s in lists):
        return ["licence: findings withheld: a term list cannot be used to screen them"] if lines else []
    terms = [t for s in lists for t in s.terms]
    ids = private_id_re(cfg, pub)
    out = []
    for ln in lines:
        hits, _ = pv.scan_text(ln, terms, True, honour_marker=False)
        out.append("licence: a finding that names a private term, local path or item ID (withheld)"
                   if hits or (ids and ids.search(ln)) else ln)
    return out


def publish(root: Path, cfg: Any, tag: str, push: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Build the public commit for `tag` in the staging clone; push only with `push`. Returns a summary."""
    pub = settings(cfg)
    if pub.mode != "mirror":
        raise PublishError("[publish] mode is open: development itself is public; publish by pushing the tag")
    if not pub.remote:
        raise PublishError("[publish] remote is not set")
    if not pub.author:
        raise PublishError("[publish] author is not set (the public identity, e.g. a no-reply address)")
    stage = stage_dir(root, pub)
    files, removed, findings = build(root, cfg, tag)  # always: also before a push of a commit built earlier (AF3)
    summary: dict[str, Any] = {"tag": tag, "files": len(files), "ids_removed": removed, "findings": findings,
                               "remote": pub.remote, "branch": pub.branch, "pushed": False}
    if findings or dry_run:
        return summary
    if not (stage / ".git").is_dir():  # AF6: created locally; the network is used only by --push
        if stage.exists():
            raise PublishError(f"{pub.staging} exists and is not a staging clone; remove it first")
        stage.mkdir(parents=True)
        _git(stage, "init", "-q", "-b", pub.branch)
        _git(stage, "remote", "add", "origin", pub.remote)
    if (_git(stage, "config", "--get", "remote.origin.url", check=False).stdout or "").strip() != pub.remote:
        raise PublishError("the staging clone's origin is not [publish] remote; remove .steward staging and publish again")
    bad_cfg = _stage_config_ok(stage)
    if bad_cfg:
        raise PublishError(f"the staging clone's configuration has settings steward did not write: {', '.join(bad_cfg)}")
    _branch_is_built(stage)  # AF3: on every path, before anything is built or sent
    snap = _refs(stage)  # AK1, AL1: before anything, remote-tracking refs and HEAD included
    sent: dict[str, bool] = {}
    try:
        remote_tip = _remote_state(stage, pub, tag) if push else None  # AI1: known before any local ref changes
        _stage_and_send(stage, pub, tag, files, push, remote_tip, sent)
    except BaseException as e:
        if not sent:  # AL1: once the release is public, its local commit and tag are kept
            bad = _restore_refs(stage, snap)  # AK1: a refusal or failure leaves the staging refs as they were
            if bad:
                raise PublishError(f"{e}; and the staging refs could not be restored ({', '.join(bad[:3])}): remove "
                                   f"{pub.staging} and publish again") from e
        raise
    summary["pushed"] = push
    summary["commit"] = _git(stage, "rev-parse", "--short", f"{tag}^{{commit}}").stdout.strip()  # AJ3: what was sent
    return summary


def _refs(stage: Path) -> tuple[dict[str, str], str, str]:
    """(every ref, HEAD's branch or "", HEAD's commit when detached or "")."""
    r = _git(stage, "for-each-ref", "--format=%(objectname) %(refname)", "refs/heads", "refs/tags", "refs/steward",
             "refs/remotes")
    head = (_git(stage, "symbolic-ref", "-q", "HEAD", check=False).stdout or "").strip()
    detached = "" if head else (_git(stage, "rev-parse", "--verify", "--quiet", "HEAD", check=False).stdout or "").strip()
    return dict(reversed(ln.split(" ", 1)) for ln in r.stdout.splitlines() if ln), head, detached


def _restore_refs(stage: Path, snap: tuple[dict[str, str], str, str]) -> list[str]:
    """Put every ref back; the refs that could not be restored (AL1: errors are reported, never ignored)."""
    before, head, detached = snap
    now = _refs(stage)[0]
    bad = []
    for ref in now:
        if ref not in before and _git(stage, "update-ref", "-d", ref, check=False).returncode != 0:
            bad.append(ref)
    for ref, sha in before.items():
        if now.get(ref) != sha and _git(stage, "update-ref", ref, sha, check=False).returncode != 0:
            bad.append(ref)
    if head and _git(stage, "symbolic-ref", "HEAD", head, check=False).returncode != 0:
        bad.append("HEAD")
    if detached and _git(stage, "update-ref", "--no-deref", "HEAD", detached, check=False).returncode != 0:
        bad.append("HEAD")
    return bad


def _stage_and_send(stage: Path, pub: PublicSection, tag: str, files: "Export", push: bool, remote_tip: str | None,
                    sent: dict[str, bool]) -> None:
    have = _git(stage, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}", check=False).returncode == 0
    if have:
        if not _tree_matches(stage, tag, files):
            raise PublishError(f"{tag} in the staging clone differs from the tag's scanned export; remove that tag there")
    else:
        has_head = _git(stage, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0
        _git(stage, "checkout", "-q", *(["-B", pub.branch] if has_head else ["--orphan", pub.branch]))
        _git(stage, "rm", "-rq", "--cached", "--ignore-unmatch", ".")
        for p in sorted(stage.iterdir()):
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
        for rel, data in files.items():
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            dest.chmod(0o755 if rel in files.executable else 0o644)
        _git(stage, "add", "-A")
        msg = f"Release {tag}\n\nPublished by steward from the release tag; development history is kept privately."
        if has_head and _git(stage, "diff", "--cached", "--quiet", check=False).returncode == 0:
            raise PublishError("the export is identical to the last public commit; nothing to publish")
        _git(stage, "commit", "-q", "-m", msg, author=pub.author)
        if not _tree_matches(stage, "HEAD", files):  # AF2: what is committed is what was scanned
            raise PublishError("the staged commit differs from the scanned export; nothing published")
        _git(stage, "tag", "-a", tag, "-m", f"{tag} (public release)", author=pub.author)
    if push:
        _push(stage, pub, tag, remote_tip, sent)


def _built(stage: Path) -> set[str]:
    return set(_git(stage, "rev-list", "--no-walk", "--tags", check=False).stdout.split()) | \
        set(_git(stage, "for-each-ref", "--format=%(objectname)", "refs/steward/pushed/", check=False).stdout.split())


def _branch_is_built(stage: Path) -> None:
    """AF3: the staging branch tip is a release commit steward built or sent, and so is every commit below it."""
    born = _git(stage, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0
    listed = _git(stage, "for-each-ref", "--format=%(refname)", "refs/heads/", check=False)
    if listed.returncode != 0:  # AF3: branches that cannot be listed cannot be audited
        raise PublishError("the staging clone's branches cannot be listed; remove .steward staging and publish again")
    heads = (["HEAD"] if born else []) + listed.stdout.split()
    if not heads:  # AF3: an unborn HEAD still has its other branches checked
        return
    built = _built(stage)
    branch = _current(stage)
    history = _git(stage, "rev-list", *heads).stdout.split()  # AF3: every local branch, not only the checked-out one
    remote = _git(stage, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/HEAD", check=False).stdout.strip()
    public = set(_git(stage, "rev-list", f"refs/remotes/origin/{branch}", check=False).stdout.split())
    if any(c not in built and c not in public for c in history) or (remote and remote not in public):
        raise PublishError("the staging branch holds commits steward did not build; remove .steward staging and publish again")


def _current(stage: Path) -> str:
    return (_git(stage, "symbolic-ref", "--short", "HEAD", check=False).stdout or "").strip() or "main"


def _remote_state(stage: Path, pub: PublicSection, tag: str) -> str | None:
    """The public branch tip (None when the branch does not exist yet), after checking the destination and that `tag`
    is neither public already nor older than a public release. No evidence is never read as none (AI1)."""
    bad_cfg = _stage_config_ok(stage)
    if bad_cfg:
        raise PublishError(f"the staging clone's configuration has settings steward did not write: {', '.join(bad_cfg)}")
    eff = (_git(stage, "remote", "get-url", "--push", "origin", check=False, network=True).stdout or "").strip()
    if eff != pub.remote:  # the push URL after the user's rewrites (insteadOf, pushurl) must be the configured one
        raise PublishError("the effective push destination is not [publish] remote (a URL rewrite or push URL?)")
    tip = _advertised(stage, pub)  # AL2: read before and after the tag listing, which then describes this tip
    listed = _git(stage, "ls-remote", "--tags", "--refs", "origin", check=False, network=True)
    if listed.returncode != 0:
        raise PublishError("the public repository's tags cannot be listed; nothing pushed")
    refs = [ln.split("\t", 1)[1] for ln in (listed.stdout or "").splitlines() if "\t" in ln]
    public_tags = [r[len("refs/tags/"):] for r in refs if r.startswith("refs/tags/")]  # AM3: the whole name
    if tag in public_tags:
        raise PublishError(f"{tag} is already public; nothing pushed")
    try:  # AG1, AK2: only semantic versions are ordered; any other public tag stops the push
        mine = semver_key(tag)
        newer = [t for t in public_tags if semver_key(t) >= mine]
    except ValueError as e:
        raise PublishError(f"{e}; release order cannot be checked, nothing pushed") from None
    if newer:  # never older contents over a newer public release
        raise PublishError(f"a newer release is already public ({max(newer, key=semver_key)}); {tag} is not pushed")
    if tip is None:
        if _advertised(stage, pub) is not None:
            raise PublishError(f"the public branch {pub.branch} appeared while it was checked; nothing pushed (run again)")
        return None
    fetched = _git(stage, "fetch", "-q", "origin", pub.branch, check=False, network=True)
    if fetched.returncode != 0:  # the public branch exists: its tip must be fetched, or nothing is sent
        raise PublishError(f"the public branch {pub.branch} cannot be fetched; nothing pushed")
    got = _git(stage, "rev-parse", "FETCH_HEAD").stdout.strip()
    # AL2: the tags were listed while the branch stood at `tip`, and it still does; a release published meanwhile
    # moves the branch, and a branch that moves after this makes the push a non-fast-forward, which is rejected
    if got != tip or _advertised(stage, pub) != tip:
        raise PublishError(f"the public branch {pub.branch} moved while it was checked; nothing pushed (run again)")
    return tip


def _advertised(stage: Path, pub: PublicSection) -> str | None:
    heads = _git(stage, "ls-remote", "--heads", "origin", f"refs/heads/{pub.branch}", check=False, network=True)
    if heads.returncode != 0:
        raise PublishError("the public repository's branches cannot be listed; nothing pushed")
    line = (heads.stdout or "").split()
    return line[0] if line else None


def _push(stage: Path, pub: PublicSection, tag: str, remote_tip: str | None, sent: dict[str, bool]) -> None:
    """AF3, AG1: send exactly one new commit, the tag's tree on top of the public tip, and the tag, atomically, to the
    configured remote only. A release older than the public tip, or already public, is refused. `remote_tip` is the
    one lookup made before staging (AK1); a remote that moved since rejects the non-forced push."""
    commit = _git(stage, "rev-parse", f"{tag}^{{commit}}").stdout.strip()
    if remote_tip and remote_tip == commit:  # AH1: the branch already holds it; send the missing tag alone
        # AM2: with the branch at the same commit in one atomic push: a branch that moved since the check makes the
        # branch update a non-fast-forward, which is rejected, and the tag with it
        _git(stage, "push", "-q", "--atomic", f"--force-with-lease=refs/heads/{pub.branch}:{remote_tip}", "origin",
             f"{commit}:refs/heads/{pub.branch}", f"refs/tags/{tag}", network=True)
        sent["sent"] = True
        _record_sent(stage, pub, tag, commit, branch=False)
        return
    if remote_tip:
        if _git(stage, "merge-base", "--is-ancestor", commit, remote_tip, check=False).returncode == 0:
            raise PublishError(f"{tag} is older than the public branch; nothing pushed")
        parents = _git(stage, "rev-list", "--parents", "-n", "1", commit).stdout.split()[1:]
        if parents != [remote_tip]:  # exactly one new commit: the tag's tree on the public tip
            tree = _git(stage, "rev-parse", f"{commit}^{{tree}}").stdout.strip()
            msg = _git(stage, "log", "-1", "--format=%B", commit).stdout
            author = _git(stage, "log", "-1", "--format=%an <%ae>", commit).stdout.strip()
            commit = _git(stage, "commit-tree", tree, "-p", remote_tip, "-m", msg, author=author).stdout.strip()
            _git(stage, "tag", "-d", tag)
            _git(stage, "tag", "-a", tag, "-m", f"{tag} (public release)", commit, author=author)
    elif _git(stage, "rev-list", "--parents", "-n", "1", commit).stdout.split()[1:]:
        # AF3: the first publication sends one commit with no parent: the scanned tree alone, no earlier history
        tree = _git(stage, "rev-parse", f"{commit}^{{tree}}").stdout.strip()
        msg = _git(stage, "log", "-1", "--format=%B", commit).stdout
        author = _git(stage, "log", "-1", "--format=%an <%ae>", commit).stdout.strip()
        commit = _git(stage, "commit-tree", tree, "-m", msg, author=author).stdout.strip()
        _git(stage, "tag", "-d", tag)
        _git(stage, "tag", "-a", tag, "-m", f"{tag} (public release)", commit, author=author)
    _git(stage, "branch", "-f", pub.branch, commit) if _git(stage, "symbolic-ref", "--short", "HEAD",
                                                              check=False).stdout.strip() != pub.branch else \
        _git(stage, "reset", "-q", "--soft", commit)
    # AG1: both refs, or neither. AM2: only while the public branch is exactly the tip that was checked (the lease
    # never forces anything: the commit always descends from that tip, or the branch must not exist yet)
    _git(stage, "push", "-q", "--atomic", f"--force-with-lease=refs/heads/{pub.branch}:{remote_tip or ''}", "origin",
         f"{commit}:refs/heads/{pub.branch}", f"refs/tags/{tag}", network=True)
    sent["sent"] = True
    _record_sent(stage, pub, tag, commit, branch=True)


def _record_sent(stage: Path, pub: PublicSection, tag: str, commit: str, branch: bool) -> None:
    """AG2, AL1: the local record that `tag` was sent. A failure here never undoes the publication: it says so, and
    the next `release publish TAG --push` (the tag is then public) or `release status` shows the state."""
    try:
        if branch:
            _git(stage, "update-ref", f"refs/remotes/origin/{pub.branch}", commit)
        _git(stage, "update-ref", f"refs/steward/pushed/{tag}", commit)
    except (PublishError, OSError, subprocess.SubprocessError) as e:
        import shlex

        raise PublishError(f"{tag} is public, but its local record could not be written ({e}); run: git -C "
                           f"{shlex.quote(str(stage))} update-ref refs/steward/pushed/{tag} {commit}") from None  # AM4


def status(root: Path, cfg: Any) -> dict[str, Any]:
    """The last public release, the development tags not yet published; local refs only, no network (AF6)."""
    pub = settings(cfg)
    stage = stage_dir(root, pub)
    dev = sorted((t for t in _git(root, "tag", "--list", "v*").stdout.split()), key=_vkey)
    has = (stage / ".git").is_dir()
    published = sorted(_git(stage, "tag", "--list", "v*").stdout.split(), key=_vkey) if has else []
    last = published[-1] if published else None
    newer = [t for t in dev if last is None or _vkey(t) > _vkey(last)]
    sent = set(_git(stage, "for-each-ref", "--format=%(refname:lstrip=3)", "refs/steward/pushed/").stdout.split()) if has else set()
    pushed = (last in sent) if has and last else None  # AG2: only what steward recorded as sent
    newer = [t for t in dev if t not in sent]  # AG2: every development tag steward has not recorded as sent
    return {"mode": pub.mode, "remote": pub.remote, "last_public": last, "last_public_pushed": pushed,
            "unpublished": newer, "staging": pub.staging if has else None}


SEMVER = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
                    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")


def semver_key(t: str) -> tuple:
    """AK2: the precedence of a semantic version tag (v1.2.3, v1.2.3-rc.1, v1.2.3+build); build metadata is ignored
    and a pre-release sorts before its release, identifiers compared as SemVer 2.0.0 says. ValueError otherwise."""
    m = SEMVER.match(t)
    if not m:
        raise ValueError(f"{t} is not a semantic version tag (vMAJOR.MINOR.PATCH[-pre][+build])")
    pre = m.group(4)
    if not t.isascii() or (pre and any(x.isdigit() and len(x) > 1 and x[0] == "0" for x in pre.split("."))):
        raise ValueError(f"{t} is not a semantic version tag (non-ASCII digits, or a pre-release number with a leading zero)")
    ids = tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in pre.split(".")) if pre else ()
    return (int(m[1]), int(m[2]), int(m[3]), 0 if pre else 1, ids)


def _vkey(t: str) -> tuple:
    """A sort key for listing tags that never raises: semantic versions in precedence order, after any other tag."""
    try:
        return (1, semver_key(t))
    except ValueError:
        return (0, (t,))


# ---------------------------------------------------------------- setup (A or B)
def setup_text(mode: str, remote: str | None, author: str | None) -> str:
    lines = ["", "[publish]                        # 0.19.0: how released versions are published (steward release setup)",
             f'mode = "{mode}"                    # mirror: one clean commit per release in a public repository; open: development in public']
    if remote:
        lines.append(f'remote = "{remote}"')
    if author:
        lines.append(f'author = "{author}"')
    lines += ['# include = ["**/*"]              # the public paths; development/ and exchange/ are never published',
              '# exclude = []', '# binary = ["**/*.png", "**/*.pdf"]   # binary kinds allowed (they cannot be scanned)', ""]
    return "\n".join(lines)


def open_plan(root: Path, cfg: Any) -> dict[str, Any]:
    """Model B, as a plan only: what moves to a private records repository, and what in the history is not
    public-safe. It reads author addresses and whole commit messages (subjects and bodies); file contents in the
    history are not read, and the plan says so (AF16)."""
    from . import privacy as pv
    from .records import read_rel

    lists = [s for s in pv.load(root, cfg, read=lambda rel: read_rel(root, rel)) if s.state == "ok"]
    terms = [t for s in lists for t in s.terms]
    log = _git(root, "log", "--all", "--name-only", "--diff-merges=first-parent",
               "--format=%x1e%H%x1f%ae%x1f%B%x1f", check=False).stdout.split("\x1e")  # AH3: merges' paths too
    authors, risky = set(), []
    for rec in log:
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 4:
            continue
        authors.add(parts[1])
        scanned = parts[2] + "\n" + parts[3]  # the whole message and the paths the commit changed
        hits, _ = pv.scan_text(scanned, terms, True, honour_marker=False)
        if hits or PRIVATE_ID.search(scanned):
            risky.append(parts[0][:12])
    moved = [p for p in ("development", "exchange") if (root / p).is_dir()]
    return {"move_to_records": moved, "authors": sorted(authors), "commits_with_private_content": len(risky),
            "examples": risky[:10],
            "coverage": "scanned: whole commit messages and the paths each commit changed (a merge against its first "
                        "parent); listed, not scanned: author "
                        "addresses; not read: file contents in the history (inspect them, e.g. git log -p, before a rewrite)",
            "options": ["start a fresh public history at the next release (simplest, nothing private carried over)",
                        "rewrite the history (only with a signed approval; every clone must be replaced)"]}


# ---------------------------------------------------------------- install channels (STW-019)
def channel_command(ch: Channel, which: str, tag: str | None) -> list[str]:
    src = ch.stable if which == "stable" else ch.dev
    spec = f"{ch.name} @ {src}" + (f"@{tag}" if tag else "")
    return installer_command(ch.installer, spec)


def installer_command(installer: str, spec: str, *, python: str = "python") -> list[str]:
    """The install command for `spec`. W12 F4: a repository's files never steer it. `uv --no-config` reads no
    uv.toml or pyproject.toml [tool.uv] (index, find-links, overrides); `python -P` does not put the working
    directory on sys.path, so a planted pip.py is not imported. `-P` rather than `-I`: `-I` also drops the user
    site-packages, which changes where pip installs for a `pip install --user` setup. Run it with `run_installer`."""
    return {"uv-tool": ["uv", "tool", "install", "--no-config", "--force", spec],
            "pipx": ["pipx", "install", "--force", spec],
            "pip": [python, "-P", "-m", "pip", "install", "--force-reinstall", spec]}[installer]


def run_installer(argv: list[str], run: Any = None) -> subprocess.CompletedProcess:
    """Run an installer in the foreground with its working directory in a fresh, empty temporary directory, outside
    every repository (W12 F4): no file of the project the command was started from is found as configuration or as a
    module. Raises OSError when the installer cannot start."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="steward-install-") as empty:
        return (run or subprocess.run)(argv, cwd=empty)


STATE = ".steward/channels.json"


def channel_state(root: Path) -> dict[str, Any]:
    p = root / STATE
    try:
        return json.loads(p.read_text()) if p.is_file() and not p.is_symlink() else {}
    except (OSError, ValueError):
        return {}


def record_channel(root: Path, name: str, which: str, tag: str | None) -> None:
    from .fsutil import safe_write

    st = channel_state(root)
    st[name] = {"channel": which, "tag": tag, "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    safe_write(root, STATE, (json.dumps(st, indent=2, sort_keys=True) + "\n").encode())


def load_toml(root: Path) -> dict[str, Any]:
    return tomllib.loads((root / "steward.toml").read_text(encoding="utf-8"))
