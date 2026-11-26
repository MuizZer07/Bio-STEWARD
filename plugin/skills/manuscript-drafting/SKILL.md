---
name: manuscript-drafting
description: Draft or revise paper sections from the approved spec, with registered numbers, cited displays, matched claim strength and stated limitations. Use when writing or revising any manuscript section.
---

# Manuscript drafting

Start by saying in one line that you are using this skill and why.

Drafting follows the paper spec (`spec.toml`, see `paper-kit`). The authors own the content and the voice; this
skill keeps the draft traceable and honest.

## Before writing a section
- Re-read the spec: story, questions, contributions and their `strength`, `never_claim`, `limitations`, `names`.
- Check which values and displays the section needs exist (`steward paper values`, `steward paper displays`).
  If evidence is missing, write the section's structure and mark the gap with a placeholder (`[RESULT: ...]`); never
  fill it with an invented or remembered number.

## Section by section
- **Abstract:** problem, approach, main results (registered values), one limitation if it changes the reading;
  within the venue's word limit.
- **Introduction:** problem, gap (grounded in `prior-work-grounding` records), contributions worded at their spec
  strength. Do not preview results in detail.
- **Methods:** enough to reproduce: data and identifiers, splits, baselines, metrics, the comparison procedure and
  its settings (from the benchmark contract, through `\val{}`), software and versions in a data/code availability
  statement.
- **Results:** one claim per paragraph, each backed by a cited display or registered values; report uncertainty
  where computed; report negative and null results (see `negative-results`).
- **Discussion:** interpret, do not restate; compare with the closest work on equal terms; every spec limitation appears.
- **Declarations:** what the venue requires (data and code availability, competing interests, author contributions,
  funding, ethics). Ask the authors for anything you cannot know.

## Wording rules
- Claim strength matches evidence: `demonstrates` needs confirmatory evidence; `suggests` for exploratory or
  indirect evidence; `explores` for design or preliminary work. Never upgrade strength while drafting; propose it.
- Never use a phrase listed in `never_claim`. Avoid unqualified "novel", "first", "state of the art" unless the
  authors approved the claim and the prior-work record supports it.
- Use the fixed `names` consistently in text, figures and tables.
- Say each thing once across text, figures and tables.

## Revising after peer review
Use `manuscript-review` for the response procedure: every reviewer point gets a change or a reasoned reply, and the
location of the change.

## After each drafting session
```bash
steward paper values --write && latexmk -pdf main.tex   # in the paper directory for latexmk
steward check paper --summary
```
Report the summary line and any FAIL or INCOMPLETE to the authors.
