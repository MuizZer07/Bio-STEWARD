---
name: paper-kit
description: Set up and run a paper project (preprint, conference, journal, thesis) in LaTeX with a spec, venue profile and checks. Use when starting or restructuring a paper, or choosing a venue.
---

# Paper kit

Start by saying in one line that you are using this skill and why.

A paper is planned before it is drafted. The spec fixes the story, the questions, the contributions and how strongly
each may be worded, what must never be claimed, and every limitation. steward checks the spec, the venue profile,
leftover placeholders and the LaTeX build log. Authors decide the content.

## 1. Set up
```bash
steward init --paper              # paper/ with spec.toml, venue.toml, main.tex, refs.bib (never overwrites)
steward init --paper review-2027  # a second paper in papers/review-2027/
```
If `steward.toml` already exists, `init` prints the `[paper.<name>]` table to add (and the schema
`steward.toml/0.2`); it never edits the file. LaTeX is the primary format. Markdown, Quarto and DOCX are secondary.

## 2. Write the spec with the authors (`spec.toml`)
- `story`: one paragraph: problem, gap, what was done, what it shows, why it matters.
- `questions`: the research questions the paper answers.
- `contributions`: each with `strength` fixed **before drafting** and matched to the evidence:
  - `demonstrates`: confirmatory evidence exists (a benchmark contract and results);
  - `suggests`: evidence exists but is exploratory, small or indirect;
  - `explores`: design, method or preliminary work without supporting results.
- `never_claim`: statements the paper must not make (overreach the authors have ruled out).
- `limitations`: all of them. A limitation found later is added here and in the text.
- `names`: fixed names and definitions, used identically in text, figures and tables.

The authors approve the spec. Do not upgrade a contribution's strength while drafting; propose it to the authors with
the new evidence.

## 3. Record the venue (`venue.toml`)
Copy rules from the venue's **current** call or author guide: page and word limits, anonymity, required sections and
declarations, figure formats. Set `source_url` (`url:https://…`) and `retrieved` (date). Rules change; a profile with
no source is reported UNKNOWN. Never fill a limit from memory.

## 4. Numbers, figures and citations
- Never type a result number that no script or result file produced. Until the values registry exists, cite the
  result file in a LaTeX comment next to each number, and re-check numbers after every rerun.
- Figures and tables are built by scripts from result files; do not edit artwork by hand.
- Citations come from the publisher or an identifier lookup (DOI, PMID, arXiv). Never invent an entry, a DOI or a
  page number; mark what you could not find and tell the authors.

## 5. Check while drafting
```bash
latexmk -pdf main.tex                  # in the paper directory
steward check paper --summary          # R-08 spec and venue, R-09 placeholders, R-12 build log
```
- R-09 lists `TODO`, `TBD`, `FIXME`, `XX`, `[CONFIRM`, `[RESULT` markers (configurable). Draft mode ignores LaTeX
  comments; final mode does not.
- R-12 reads the LaTeX log: undefined references or citations, duplicate labels and errors are failures; a "rerun"
  request is incomplete. Rebuild before checking: the log must belong to the current sources.
- For the full meaning of each status, see the `using-steward` skill.

## 6. Writing conventions worth keeping
- Say each thing once: the abstract summarises; the introduction does not preview results; the discussion interprets
  rather than restates.
- Every figure or table backs a claim in the text and is cited where that claim is made.
- No internal names, versions, debug markers or tool names in the text or artwork.
- Limitations and negative results are reported (see `negative-results`).

When the paper is close to submission, use `submission-readiness`.
