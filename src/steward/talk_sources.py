"""Talk source adapters (PresentationKit slices): Beamer (.tex), Quarto / reveal.js (.qmd, .md), PPTX (.pptx), and
Keynote (.key, checked through its exported PDF). Each adapter yields the same facts so rules R-24 … R-29 apply to
every engine:

- text units: (where, line_or_slide, text), speaker notes included;
- frame titles; value references; images (by path, or by content hash for PPTX);
- slide count; layout: minimum font size (normalised to a 960 pt wide slide) and text outside the slide.

Facts an engine cannot provide are None, and rules report them as not assessed or UNKNOWN, never as passing.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SLIDE_WIDTH_PT = 960.0  # 13.333 in, a 16:9 presentation slide: font limits mean the same across engines
_TEX_COMMENT = re.compile(r"(?<!\\)%.*$")
_QVAR = re.compile(r"\{\{<\s*var\s+([^\s>]+)\s*>\}\}")
_TVAL = re.compile(r"\\val\{([^}]*)\}")


@dataclass
class Facts:
    engine: str
    text: list[tuple[str, int, str]] = field(default_factory=list)  # (where, line or slide, text)
    raw_lines: dict[tuple[str, int], str] = field(default_factory=dict)  # for literal-ok markers
    titles: list[str] = field(default_factory=list)
    value_refs: list[tuple[str, int, str]] = field(default_factory=list)
    includes: list[tuple[str, int, str, bool]] = field(default_factory=list)  # (where, line, target, is_graphic)
    image_hashes: list[tuple[str, int, str]] = field(default_factory=list)  # (where, slide, sha256): PPTX
    slide_count: int | None = None
    layout: dict[str, Any] | None = None  # {"min_font": float, "small": [...], "outside": [...]}
    notes: list[str] = field(default_factory=list)  # adapter remarks (e.g. engine limits)


def engine_of(main: str) -> str:
    ext = Path(main).suffix.lower()
    return {".tex": "beamer", ".qmd": "quarto", ".md": "quarto", ".pptx": "pptx", ".key": "keynote"}.get(ext, "unknown")


# ---------------------------------------------------------------- PDF layout (any engine that produces a PDF)
def pdf_layout(path: Path, min_font: float) -> dict[str, Any] | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
    except Exception:
        return None
    small: list[dict[str, Any]] = []
    outside: list[dict[str, Any]] = []
    smallest = None
    for n, page in enumerate(reader.pages, start=1):
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        scale = SLIDE_WIDTH_PT / w if w else 1.0

        def visit(text, cm, tm, font_dict, font_size, n=n, w=w, h=h, scale=scale):
            if not text.strip():
                return
            a, b, c, d, e, f = tm
            A, B, C, D, E, F = cm
            cc, dd = c * A + d * C, c * B + d * D
            x, y = e * A + f * C + E, e * B + f * D + F
            size = font_size * (cc * cc + dd * dd) ** 0.5 * scale
            nonlocal smallest
            smallest = size if smallest is None else min(smallest, size)
            if size + 0.05 < min_font and len(small) < 50:
                small.append({"page": n, "value": round(size, 1), "text": text.strip()[:30]})
            if (x < -1 or y < -1 or x > w + 1 or y > h + 1) and len(outside) < 50:
                outside.append({"page": n, "text": text.strip()[:30]})

        try:
            page.extract_text(visitor_text=visit)
        except Exception:
            return None
    return {"min_font": None if smallest is None else round(smallest, 1), "small": small, "outside": outside,
            "pages": len(reader.pages)}


# ---------------------------------------------------------------- Beamer and Quarto (text sources)
_FRAME = re.compile(r"\\begin\{frame\}(?:<[^>]*>)?(?:\[[^\]]*\])?\{([^}]*)\}|\\frametitle\{([^}]*)\}|\\(?:sub)?section\*?\{([^}]*)\}")
_INCLUDE_TEX = re.compile(r"\\(includegraphics(?:\[[^\]]*\])?|input|include)\{([^}]*)\}")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
_MD_INCLUDE = re.compile(r"\{\{<\s*include\s+([^\s>]+)\s*>\}\}")


def _text_files(root: Path, tdir: str, exts: tuple[str, ...]) -> list[str]:
    base = root / tdir
    return sorted(p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file() and p.suffix in exts) if base.is_dir() else []


def beamer(root: Path, tt: Any, read) -> Facts:
    f = Facts("beamer")
    for rel in _text_files(root, tt.dir, (".tex",)):
        text = read(rel).decode("utf-8", errors="replace")
        for n, raw in enumerate(text.splitlines(), start=1):
            line = _TEX_COMMENT.sub("", raw)
            f.raw_lines[(rel, n)] = raw
            f.text.append((rel, n, line))
            f.titles += [t for grp in _FRAME.findall(line) for t in grp if t]
            f.value_refs += [(rel, n, k) for k in _TVAL.findall(line)]
            f.includes += [(rel, n, a, k.startswith("includegraphics")) for k, a in _INCLUDE_TEX.findall(line)]
    return f


def quarto(root: Path, tt: Any, read) -> Facts:
    f = Facts("quarto")
    slides = 0
    for rel in _text_files(root, tt.dir, (".qmd", ".md")):
        text = read(rel).decode("utf-8", errors="replace")
        in_yaml = text.startswith("---")
        for n, raw in enumerate(text.splitlines(), start=1):
            if n > 1 and in_yaml and raw.strip() == "---":
                in_yaml = False
                continue
            if in_yaml:
                continue
            line = re.sub(r"<!--.*?-->", "", raw)
            f.raw_lines[(rel, n)] = raw
            f.text.append((rel, n, line))
            mt = re.match(r"^(#{1,2})\s+(.*)$", line)
            if mt:
                f.titles.append(mt.group(2).strip())
                if mt.group(1) == "##":
                    slides += 1
            f.value_refs += [(rel, n, k) for k in _QVAR.findall(line)]
            f.includes += [(rel, n, a, True) for a in _MD_IMAGE.findall(line)]
            f.includes += [(rel, n, a, False) for a in _MD_INCLUDE.findall(line)]
    f.slide_count = slides  # reveal.js: one slide per level-2 heading
    f.notes.append("slide count from level-2 headings; layout checks need a PDF export (decktape or print-to-PDF)")
    return f


# ---------------------------------------------------------------- PPTX (python-pptx, optional)
def pptx(root: Path, tt: Any, read, min_font: float) -> Facts:
    f = Facts("pptx")
    rel = tt.rel(tt.main)
    try:
        from pptx import Presentation
        from pptx.util import Emu
    except ImportError:
        f.notes.append("python-pptx not installed (extra [talk]); PPTX facts unavailable")
        return f
    read(rel)
    prs = Presentation(str(root / rel))
    sw, sh = int(prs.slide_width), int(prs.slide_height)
    scale = SLIDE_WIDTH_PT / Emu(sw).pt
    small, outside = [], []
    smallest = None
    f.slide_count = len(prs.slides)
    for n, slide in enumerate(prs.slides, start=1):
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            f.titles.append(slide.shapes.title.text_frame.text.strip())
        for shp in slide.shapes:
            if shp.left is not None and shp.width is not None and (shp.left < 0 or shp.top < 0 or shp.left + shp.width > sw or shp.top + shp.height > sh):
                outside.append({"page": n, "text": (shp.name or "")[:30]})
            if shp.shape_type == 13:  # picture
                f.image_hashes.append((rel, n, hashlib.sha256(shp.image.blob).hexdigest()))
            if shp.has_text_frame:
                for para in shp.text_frame.paragraphs:
                    line = "".join(r.text for r in para.runs)
                    if line.strip():
                        f.text.append((rel, n, line))
                        f.raw_lines[(rel, n)] = f.raw_lines.get((rel, n), "") + line
                    for r in para.runs:
                        if r.font.size is not None and r.text.strip():
                            size = r.font.size.pt * scale
                            smallest = size if smallest is None else min(smallest, size)
                            if size + 0.05 < min_font:
                                small.append({"page": n, "value": round(size, 1), "text": r.text.strip()[:30]})
        if slide.has_notes_slide:
            note = slide.notes_slide.notes_text_frame.text
            f.text += [(rel, n, l) for l in note.splitlines() if l.strip()]
    f.layout = {"min_font": None if smallest is None else round(smallest, 1), "small": small, "outside": outside,
                "pages": f.slide_count}
    f.notes.append("font sizes inherited from the slide master are not visible to the check (only explicit sizes)")
    return f


# ---------------------------------------------------------------- Keynote (exported PDF)
def keynote(root: Path, tt: Any, read) -> Facts:
    f = Facts("keynote")
    pdf = root / tt.rel(tt.resolved_pdf())
    if not pdf.is_file():
        f.notes.append("export the Keynote file to PDF first: steward talk export NAME (macOS)")
        return f
    text = _pdf_pages(pdf)
    if text is None:
        f.notes.append("PDF text unavailable (install poppler or pypdf)")
        return f
    f.slide_count = len(text)
    for n, page in enumerate(text, start=1):
        lines = [l for l in page.splitlines() if l.strip()]
        if lines:
            f.titles.append(lines[0].strip())
        for l in lines:
            f.text.append((tt.rel(tt.resolved_pdf()), n, l))
            f.raw_lines[(tt.rel(tt.resolved_pdf()), n)] = f.raw_lines.get((tt.rel(tt.resolved_pdf()), n), "") + l
    f.notes.append("Keynote images cannot be traced to displays; speaker notes are not in the PDF export")
    return f


def _pdf_pages(path: Path) -> list[str] | None:
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=120)
        if out.returncode == 0:
            pages = out.stdout.decode("utf-8", errors="replace").split("\f")
            return pages[:-1] if pages and not pages[-1].strip() else pages
    try:
        from pypdf import PdfReader
        return [p.extract_text() or "" for p in PdfReader(str(path)).pages]
    except Exception:
        return None


def export_keynote(src: Path, out_pdf: Path) -> None:
    """Export a Keynote document to PDF with AppleScript (macOS, Keynote installed). Opens Keynote."""
    if sys.platform != "darwin":
        raise RuntimeError("Keynote export needs macOS")
    script = (f'tell application "Keynote"\n set d to open POSIX file "{src}"\n'
              f' export d to POSIX file "{out_pdf}" as PDF\n close d saving no\nend tell')
    res = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode("utf-8", errors="replace").strip() or "osascript failed")


def facts(root: Path, tt: Any, read, min_font: float) -> Facts:
    eng = engine_of(tt.main)
    if eng == "beamer":
        return beamer(root, tt, read)
    if eng == "quarto":
        return quarto(root, tt, read)
    if eng == "pptx":
        return pptx(root, tt, read, min_font)
    if eng == "keynote":
        return keynote(root, tt, read)
    f = Facts("unknown")
    f.notes.append(f"unsupported slide source {tt.main}")
    return f
