---
name: presentation-review
description: Review a talk for stage-consistent claims, overstatement and understatement, audience fit and feedback intent, keeping objective check results apart from advice. Use before presenting or when asked to review slides.
---

# Presentation review

Start by saying in one line that you are using this skill and why.

## 1. Objective results first
```bash
steward check talk --summary --output .steward/talk-review.json
steward report .steward/talk-review.json --format text --rule R-29   # strong wording listed for review
```
Report every FAIL, INCOMPLETE and UNKNOWN verbatim under **Verification results**.

## 2. Advisory review (label each item with its slide)
- **Stage consistency:** do slides, captions, notes and the conclusion match the confirmed stage? Proposed methods
  must not read as implemented, preliminary results as validated, incomplete work as finished.
- **Overstatement and understatement:** R-29 lists strong words when no claim is validated; judge each in context.
  Equally, flag completed, validated work that is hedged into vagueness.
- **Audience fit:** depth, jargon and examples for the declared audience; time per slide for the duration.
- **Feedback intent:** targeted talks make each decision easy to answer; informational talks do not ask for a
  redesign; defense talks anticipate the hardest questions with backup slides.
- **Visuals:** one message per slide, legibility, colour-blind-safe encoding (R-28 checks contrast and frame
  overflow only).

Mark confidence for each recommendation and never present it as a verification result.

## 3. Preferences
If the presenter repeatedly asks for the same style change, propose saving it as a preference
(`presentation-planning`, step 5). Never save it without their agreement.
