---
name: manuscript-review
description: Review a draft with deterministic checks first, then advisory scientific, methodological and editorial comments kept apart; also structure responses to peer review. Use when asked to review a draft or answer reviewers.
---

# Manuscript review

Start by saying in one line that you are using this skill and why.

A review separates what a tool can establish from what needs judgment. Objective failures come from `steward
check`; everything else is a recommendation the authors may accept or reject. The authors remain responsible for
the claims, the authorship and the submission.

## 1. Objective checks first
```bash
steward check paper --summary --output .steward/review.json      # --final if the draft is meant to be final
steward report .steward/review.json --format text --rule R-10    # details for each non-PASS rule
```
List every FAIL, INCOMPLETE and UNKNOWN verbatim under **Verification results**. Do not soften or reinterpret them.

## 2. Advisory review (label each item)
Under **Recommendations**, each item names its kind and its location (section, line, display):
- **Scientific:** does each claim follow from its evidence? Is strength matched to the spec? Overstatement
  (preliminary sounding certain) and understatement (validated work hedged into vagueness) both count.
- **Methodological:** are baselines appropriate and equally tuned? Could leakage, confounding or multiple comparisons
  explain a result? Are uncertainty and negative results reported?
- **Literature:** is the closest work cited and compared on equal terms? (`prior-work-grounding`)
- **Editorial:** structure, repetition across text, figures and tables, clarity, consistent names, figure legibility.

Mark confidence (high, medium, low) and never present a recommendation as a verification result.

## 3. Responding to peer review
Create `paper/RESPONSE.md` with one entry per reviewer point:
```markdown
### R1.3: <the reviewer's point, quoted verbatim>
- **Response:** what was done, or a reasoned disagreement with evidence
- **Change:** section and line in the revised manuscript (or "no change", with the reason)
- **Evidence:** values, displays, runs or citations that support the response
```
- Every point gets an entry; group nothing silently.
- New numbers go through the values registry and new figures through the display manifest, then `steward check`.
- Keep the tone factual. The authors approve every response before it is sent.

## Never
- Present the review as an acceptance prediction or a certificate of correctness.
- Edit the authors' text silently during a review; propose changes.
