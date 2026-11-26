---
name: presentation-building
description: Build slides in Beamer from an approved talk plan, with numbers and figures from the shared evidence and the presenter's style preferences. Use when creating or revising slides.
---

# Presentation building

Start by saying in one line that you are using this skill and why.

Slides follow the approved plan (`presentation-planning`). Beamer is the primary format; build with `latexmk -pdf
slides.tex` in the talk directory.

## Evidence on slides
- Numbers come from the linked paper's values registry: `\input{<path to paper>/values}` in the preamble, then
  `\val{key}`. Never type a result. Numbers that are options or design constants carry `% literal-ok` on their line.
- Figures and tables come from the display manifest (`\input` or `\includegraphics` of a declared output). A slide
  variant of a paper figure is declared as its own display. Never paste screenshots of results.
- Wording matches each claim's declared status: preliminary results sound preliminary; validated results are stated
  plainly, without artificial hedging. Proposed methods are never presented as implemented.

## Structure
- One frame per outline entry as a starting point; adjust to the time. `steward talk plan` shows the slide budget
  (from duration and density); R-28 checks the built PDF against it.
- `targeted` talks show every unresolved decision; `defense` talks end with backup slides for expected questions;
  stages from evaluation onwards present limitations (R-25).
- Speaker notes (`\note{}`) follow the presenter's `notes.mode` preference and the same claim rules as slides.

## Style
- Apply the resolved preferences (`steward talk prefs <name> --compact`): theme, density, palette, typography,
  motion, terminology (`language.avoid`).
- Legible at the back of the room: large fonts, few words, one message per slide, colour-blind-safe palettes, text
  contrast at or above `accessibility.min_contrast` (R-28 computes it from the palette).

## Other engines
- **Quarto / reveal.js** (`main = "slides.qmd"`): numbers as `{{< var key >}}`; `steward talk values <name>
  --write` generates `_variables.yml` from the paper's registry; one slide per `##` heading. Font and bounds checks
  need a PDF export (decktape or print to PDF) saved as the talk's `pdf`.
- **PPTX** (`main = "slides.pptx"`, extra `[talk]`): slide text, notes, titles, explicit font sizes and shape
  positions are checked; pictures are matched to displays by content hash. Sizes inherited from the master are not
  visible to the check.
- **Keynote** (`main = "slides.key"`): `steward talk export <name>` (macOS) writes the PDF the checks read; images
  cannot be traced to displays and speaker notes are not in the export.

## Check
```bash
steward check talk --summary           # R-21 … R-29
steward check talk --final --summary   # before presenting: unregistered numbers block
```
Fix overflowing frames (`Overfull \vbox` in the log) and every FAIL; report UNKNOWN items to the presenter.
