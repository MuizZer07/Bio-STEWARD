---
name: prior-work-grounding
description: Record closest prior methods, comparisons, claimed differences and distinguishing experiments; never judge novelty. Use when claiming a contribution, choosing baselines, writing related work, or after a failed experiment.
---

# Prior-work grounding

Start by saying in one line that you are using this skill and why.

The goal is a checkable record of how a proposed method relates to existing work. It supports a human's judgment of
novelty; it never replaces it. Tools never assess novelty.

## When to use it
- Before claiming that a method or result is new.
- When choosing baselines for a benchmark contract.
- After a failed or negative experiment: search for known causes and remedies before the next attempt, and cite
  what you find.

## Start from the template
```bash
mkdir -p development/prior_work
cp development/templates/prior_work.prior.toml development/prior_work/<name>.prior.toml
steward check prior-work
```

## 1. Search
- Search more than one source (for example PubMed, Europe PMC, bioRxiv / medRxiv, arXiv, Semantic Scholar, and the
  documentation of the tools the field uses).
- Search for the task, for the method family, and for the dataset. Methods are often published under another
  community's vocabulary.
- Record what you searched, so a human can repeat it, in the record's comments or the task spec.

## 2. Record the works
For each relevant work add a `[[works]]` entry:
- `relation`: `closest_method` (the most similar approaches; at least one), `baseline` (to be compared against), or
  `related`;
- `identifier`: `doi:10.…`, `pmid:…`, `arxiv:…` or `url:https://…`, copied from the source;
- `summary`: what it does, in your words.

**Never fabricate a citation or identifier.** If you cannot find the identifier, write `unknown` and say so. A
plausible-looking DOI that does not exist is worse than `unknown`.

## 3. Compare
Add `[[comparisons]]` rows for the dimensions that matter (input data, model class, supervision, evaluation,
assumptions, compute). `ours` describes the proposed method; `theirs` maps each work ID to its value. Write
`TBD` where you do not know yet.

## 4. Claim differences, and how to test them
For each claimed difference add a `[[claimed_differences]]` entry: one specific statement, and the experiments that
would show it, as `evidence = ["contract:<benchmark-id>"]`. A difference with no distinguishing experiment is a
hypothesis; say so.

## 5. Leave the judgment to the human
Keep `[judgment] novelty = "pending"`. Only the human writes a judgment there, and only they decide whether a
contribution is new. Present the record and the open questions; do not write a verdict.

## Check it
`steward check prior-work`: R-05 checks the schema, identifier syntax (not whether the work exists) and that
comparisons refer to listed works; R-06 requires a record with a `closest_method` work under the confirmatory
profile. A PASS says the record is well-formed. It says nothing about whether the literature search was complete.

## After a failure
When an experiment fails or a result is negative:
1. Record the outcome (do not drop it).
2. Search for known causes and remedies; add the works you rely on to a prior-work record.
3. State the remedy you propose and the evidence for it before the next step.
