"""`steward init`: scaffold a repository. Creates only what is missing; never overwrites (RELEASE_v0.1_SPEC §6).

The only edits to existing files are the delimited blocks steward owns: in .gitignore always, in AGENTS.md only
when its markers already exist or with --agents-md.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from string import Template

from .resources import skills_dir, template

GI_BEGIN, GI_END = "# >>> steward", "# <<< steward"
AG_BEGIN, AG_END = "<!-- >>> steward -->", "<!-- <<< steward -->"

TEMPLATE_FILES = {
    "development/DECISIONS.md": "DECISIONS.md",
    "development/templates/task.md": "task.md",
    "development/templates/benchmark.contract.toml": "benchmark.contract.toml",
    "development/templates/prior_work.prior.toml": "prior_work.prior.toml",
}


@dataclass
class Action:
    verb: str  # create | skip | update | unchanged | print
    path: str
    note: str = ""
    content: str | None = None

    def line(self, dry: bool) -> str:
        verb = f"would {self.verb}" if dry and self.verb in ("create", "update") else self.verb
        return f"{verb:<14} {self.path}{'  (' + self.note + ')' if self.note else ''}"


def _block(begin: str, end: str, body: str) -> str:
    return f"{begin}\n{body.rstrip()}\n{end}\n"


def _replace_block(text: str, begin: str, end: str, block: str) -> str | None:
    """Text with the owned block replaced, or None when the markers are absent or malformed."""
    i, j = text.find(begin), text.find(end)
    if i == -1 or j == -1 or j < i:
        return None
    return text[:i] + block.rstrip("\n") + text[j + len(end):]


def paper_block(name: str) -> str:
    pdir = "paper" if name == "main" else f"papers/{name}"
    return (f'\n[paper.{name}]                 # PaperKit: LaTeX is the primary format\n'
            f'dir  = "{pdir}"\nmain = "main.tex"\nmode = "draft"              # `steward check --final` before submission\n')


PAPER_FILES = {"spec.toml": "paper/spec.toml", "venue.toml": "paper/venue.toml",
               "main.tex": "paper/main.tex", "refs.bib": "paper/refs.bib", "values.toml": "paper/values.toml"}


def bundles() -> dict[str, list[str]]:
    import tomllib

    data = tomllib.loads((skills_dir() / "BUNDLES.toml").read_text(encoding="utf-8"))
    return {name: list(b["skills"]) for name, b in data.items()}


def talk_block(name: str, paper: str | None) -> str:
    link = f'paper = "{paper}"              # share its values registry and display manifest\n' if paper else ""
    return (f'\n[talk.{name}]                 # PresentationKit: Beamer is the primary format\n'
            f'dir  = "talks/{name}"\nmain = "slides.tex"\n{link}mode = "draft"\n')


def project_name(root: Path) -> str:
    """The main repository's directory name, also from a linked worktree (AR-02); the directory name otherwise."""
    from .fsutil import git_run

    try:
        out = git_run(root, "rev-parse", "--path-format=absolute", "--git-common-dir", text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            common = Path(out.stdout.strip())
            if common.name == ".git":
                return common.parent.name
    except OSError:
        pass
    return root.resolve().name


OPTIONAL_TEMPLATES = {"contract": "benchmark.contract.toml", "prior-work": "prior_work.prior.toml"}


def skills_block(root: Path, skills: list[Path]) -> str:
    rel = [os.path.relpath(d, root).replace(os.sep, "/") for d in skills]
    return (f'\n[skills]                      # one canonical copy; the other harness directories link to it\n'
            f'canonical = "{rel[0]}"\ncopies = [{", ".join(chr(34) + r + chr(34) for r in rel[1:])}]\n')


def plan(root: Path, profile: str, agents_md: bool, skills: list[Path] | Path | None, paper: str | None = None,
         kits: list[str] | None = None, talk: str | None = None, project: str | None = None,
         templates: list[str] | None = None) -> list[Action]:
    acts: list[Action] = []
    if isinstance(skills, Path):
        skills = [skills]
    several = bool(skills) and len(skills) > 1  # 0.9.0 B7 (REQ-014)
    cfg = root / "steward.toml"
    if cfg.exists():
        if several and "[skills]" not in cfg.read_text(encoding="utf-8"):
            acts.append(Action("print", "steward.toml", "exists; steward.toml is never edited. Add this table",
                               skills_block(root, skills)))
        acts.append(Action("skip", "steward.toml", "exists; repo_id and profile kept"))
        if talk is not None and f"[talk.{talk}]" not in cfg.read_text(encoding="utf-8"):
            acts.append(Action("print", "steward.toml", "exists; steward.toml is never edited. Add this table (and set "
                               'schema = "steward.toml/0.2")', talk_block(talk, None)))
    else:
        text = Template(template("steward.toml.tmpl")).substitute(
            repo_id=str(uuid.uuid4()), project=json.dumps(project or project_name(root)), profile=profile,
            paper_block=(paper_block(paper) if paper is not None else "") + (talk_block(talk, paper) if talk else ""),
        ) + (skills_block(root, skills) if several else "")
        acts.append(Action("create", "steward.toml", f"profile {profile}", text))
    if talk is not None:
        for fname in ("talk.toml", "slides.tex"):
            rel = f"talks/{talk}/{fname}"
            acts.append(Action("skip", rel, "exists") if (root / rel).exists() else Action("create", rel, "talk", template(f"talk/{fname}")))
    if paper is not None:
        pdir = "paper" if paper == "main" else f"papers/{paper}"
        for fname, tname in PAPER_FILES.items():
            rel = f"{pdir}/{fname}"
            acts.append(Action("skip", rel, "exists") if (root / rel).exists() else Action("create", rel, "paper", template(tname)))
    # AR-03: the contract and prior-work templates only for a confirmatory profile, or when asked for
    wanted = set(templates or []) | (set(OPTIONAL_TEMPLATES) if profile == "confirmatory" else set())
    optional = {v for k, v in OPTIONAL_TEMPLATES.items() if k not in wanted}
    for rel, name in TEMPLATE_FILES.items():
        if name in optional:
            continue
        acts.append(Action("skip", rel, "exists") if (root / rel).exists() else Action("create", rel, "", template(name)))

    gi_block = _block(GI_BEGIN, GI_END, ".steward/")
    gi = root / ".gitignore"
    if not gi.exists():
        acts.append(Action("create", ".gitignore", "steward block", gi_block))
    else:
        text = gi.read_text(encoding="utf-8")
        new = _replace_block(text, GI_BEGIN, GI_END, gi_block)
        if new is None:
            new = text + ("" if text.endswith("\n") or not text else "\n") + gi_block
        acts.append(Action("unchanged", ".gitignore", "steward block current") if new == text
                    else Action("update", ".gitignore", "steward block", new))

    agents_text = template("agents_block.md")
    if several:
        rel = [os.path.relpath(d, root).replace(os.sep, "/") for d in skills]
        agents_text = agents_text.rstrip() + (f"\n- Skills: the one copy is in `{rel[0]}`; "
                                              + ", ".join(f"`{r}`" for r in rel[1:]) + " link to it. Edit only the copy.\n")
    ag_block = _block(AG_BEGIN, AG_END, agents_text)
    ag = root / "AGENTS.md"
    if not ag.exists():
        acts.append(Action("create", "AGENTS.md", "steward block", "# Agent instructions\n\n" + ag_block))
    else:
        text = ag.read_text(encoding="utf-8")
        new = _replace_block(text, AG_BEGIN, AG_END, ag_block)
        if new is not None:
            acts.append(Action("unchanged", "AGENTS.md", "steward block current") if new == text
                        else Action("update", "AGENTS.md", "steward block", new))
        elif agents_md:
            sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
            acts.append(Action("update", "AGENTS.md", "steward block appended (--agents-md)", text + sep + ag_block))
        else:
            acts.append(Action("print", "AGENTS.md", "exists without a steward block; left untouched. Add this snippet, "
                               "or rerun with --agents-md", ag_block))

    if skills:
        chosen = {n for k in (kits or ["core"]) for n in bundles()[k]}
        for src in sorted(p for p in skills_dir().iterdir() if (p / "SKILL.md").is_file() and p.name in chosen):
            dest = skills[0] / src.name
            rel = dest.relative_to(root).as_posix() if dest.is_relative_to(root) else str(dest)
            acts.append(Action("skip", rel + "/", "exists") if dest.exists() else Action("create", rel + "/", "skill", str(src)))
        for other in skills[1:]:
            rel = other.relative_to(root).as_posix()
            acts.append(Action("skip", rel, "exists") if other.exists() or other.is_symlink()
                        else Action("create", rel, "skills link", str(skills[0])))
    return acts


def apply(root: Path, acts: list[Action], skills: Path | None) -> None:
    for a in acts:
        if a.verb not in ("create", "update"):
            continue
        if a.note == "skills link" and a.verb == "create":
            dest = root / a.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            target = os.path.relpath(a.content, dest.parent)  # type: ignore[arg-type]
            try:
                os.symlink(target, dest, target_is_directory=True)
            except OSError:  # no links here (some filesystems): a pointer file instead (R-60 reads it)
                dest.mkdir()
                (dest / "STEWARD_SKILLS").write_text(os.path.relpath(a.content, dest) + "\n", encoding="utf-8")  # type: ignore[arg-type]
            continue
        if a.note == "skill" and a.verb == "create":
            dest = Path(a.path.rstrip("/"))
            dest = dest if dest.is_absolute() else root / dest
            shutil.copytree(a.content, dest)  # type: ignore[arg-type]
            continue
        target = root / a.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if a.verb == "create":
            with open(target, "x", encoding="utf-8", newline="\n") as f:  # "x": never overwrite, even in a race
                f.write(a.content or "")
        else:
            target.write_text(a.content or "", encoding="utf-8", newline="\n")
