---
name: submission-readiness
description: Prepare a preprint, conference or journal submission with final-mode checks, the venue checklist and a clean package. Use when a paper is close to submission or a deadline.
---

# Submission readiness

Start by saying in one line that you are using this skill and why.

Readiness means the checks that can be automated pass in final mode, the venue's remaining requirements are checked by
a person, and the authors approve. Passing checks says nothing about the paper's scientific merit or its chance of
acceptance.

## 1. Re-read the venue rules
Open the venue's current call or author guide (the `source_url` in `venue.toml`). If anything changed since
`retrieved`, update the profile and the date first. Deadlines, page limits and anonymity rules are the usual changes.

## 2. Build cleanly
```bash
latexmk -C && latexmk -pdf main.tex      # in the paper directory: a clean, complete build
```

## 3. Run the final-mode checks
```bash
steward check --final --summary --output .steward/submission.json
steward report .steward/submission.json --format text --rule R-09   # details for any non-PASS rule
```
- Final mode makes R-09 scan LaTeX comments too, because source packages can expose them, and makes overfull boxes in
  the build log (R-12) block.
- If the project defines a `submission` gate, run it with `--gate submission`.
- R-07 (if configured) scans text, figures and PDFs for private terms. An UNKNOWN there means some PDF could not be
  read: install Poppler (`pdftotext`) and re-run.

Fix every FAIL and INCOMPLETE. Report every UNKNOWN to the authors.

## 4. Walk the human checklist
Go through the `[[checklist]]` items in `venue.toml` and these common items. Mark each with evidence, not memory:
- Page and word limits on the built PDF (main text and total), abstract and title length.
- Double-blind venues: no author names, affiliations, acknowledgements, funding identifiers or self-identifying links
  (repositories, project pages) in the text, metadata, figures or supplementary files. Check the PDF metadata
  (`pdfinfo main.pdf`).
- Required sections and declarations (data and code availability, competing interests, author contributions,
  funding, ethics).
- Figures: formats, resolution, legible at print size, colour-blind-safe, captions complete.
- References: every entry real and complete; DOIs where they exist.
- Supplementary material: complete, within limits, consistent with the main text.
- Every number traceable to a result file; every limitation from `spec.toml` stated.

## 5. Package
- PDF-only venues: the built PDF plus supplementary files.
- Source venues (for example arXiv): a clean source tree. Remove comments, unused files and build by-products with an
  existing tool (for example `arxiv_latex_cleaner`), rebuild from the cleaned tree, and run the final checks on it.
- Record what was submitted: `steward paper manifest` (every file with its SHA-256 and the commit), in the task's
  Outcome. For software releases: `steward release audit` and `steward release manifest`.

## 6. Hand over
Give the authors the summary line, the gate line, the open human checklist items and the package list. The authors
approve and submit; never submit on their behalf.

## Preprint, conference, journal
- Preprint: licence choice and server rules; no peer review, so the limitations must stand on their own.
- Conference: strict page limits and anonymity; supplementary material often has separate limits.
- Journal: declarations, cover letter, suggested reviewers, data availability statements; formatting may be relaxed
  at first submission.
