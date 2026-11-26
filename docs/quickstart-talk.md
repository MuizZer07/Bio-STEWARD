# Quick start: a talk that shares the paper's numbers

```bash
steward init --talk lab-update
steward check talk --summary
steward check --summary
```

Expected gate: `Gate default: NOT ELIGIBLE` until the plan is filled in: R-21 (the plan's `TBD` fields), R-22 (a
human confirms the research stage), R-23, R-25, R-26 and R-28 (they follow from the stage, the duration and the
structure).

1. `steward talk plan lab-update --write-outline` drafts the structure from `talks/lab-update/talk.toml`.
2. Slides use the same values registry as the paper, so a number cannot differ between them (R-15, R-24).
3. A human confirms the audience (R-22): what may be shown depends on it.

Ask your agent: *"Use the presentation-planning skill for the lab update."*
