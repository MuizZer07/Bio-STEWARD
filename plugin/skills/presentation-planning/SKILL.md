---
name: presentation-planning
description: Plan a talk from its confirmed research stage, purpose, audience, duration and feedback intent before building slides. Use when preparing any presentation, poster or demo.
---

# Presentation planning

Start by saying in one line that you are using this skill and why.

A talk is planned before slides exist. The plan (`talks/<name>/talk.toml`) records what stage the research is in,
why the presenter is presenting, to whom, for how long, and what feedback they want. These are independent: a
completed project can still be presented to ask for targeted decisions.

## 1. Scaffold and fill the plan
```bash
steward init --talk <name>          # talk.toml (TBD plan) and a Beamer skeleton; prints the config table if needed
steward talk plan <name>            # lists missing fields; suggests a pattern; shows the claim ceiling
```
Fill from what exists (`steward.toml`, the linked paper, saved preferences). **Ask only for what is missing.**

## 2. The research stage is confirmed, never inferred
Stages: concept, feasibility, development, evaluation, completed, published (projects may add their own). If the
stage is not recorded, propose one with your reasons (what exists, what has been evaluated) and ask the presenter
to confirm. Only then set `stage_source = "confirmed"`. Until then `steward check` reports UNKNOWN.

## 3. Purpose, audience, feedback
- Purpose: e.g. brainstorm, proposal, design-review, progress-update, preliminary-results, conference-talk,
  journal-seminar, defense, poster, lightning, software-demo, public-communication.
- Feedback: `open` (invite criticism and alternatives), `targeted` (list `unresolved_decisions`; the talk must show
  each one), `informational` (no feedback-request slides), `defense` (prepare Q&A backup slides).
- Never add "future work", "open questions" or "feedback requested" slides that the intent does not call for, and
  never drop limitations because a talk is informational or the work is finished.

## 4. Outline and claims
```bash
steward talk plan <name> --write-outline    # appends the suggested [[outline]]; edit order, titles and emphasis
```
List each claim the slides make in `[[claims]]` with its status (`proposed`, `implemented`, `preliminary`,
`validated`, `published`, `unknown`) and evidence (`contract:`, `value:`, `doi:`). Claims above the stage's ceiling
need evidence that satisfies them (rule R-23).

## 5. Preferences
`steward talk prefs <name> --compact` shows the presenter's resolved style (talk → project → context → global) and
which layer set each key. One-off wishes go into the talk's `[overrides]`. If a wish looks permanent, propose saving
it (`steward talk prefs --set KEY VALUE --layer ...`) and save only after the presenter agrees.

Show the plan (stage, purpose, audience, duration, feedback, outline, claims) to the presenter and get approval
before building slides (`presentation-building`).
