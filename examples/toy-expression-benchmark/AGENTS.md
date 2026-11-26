# Agent instructions

<!-- >>> steward -->
## Research-engineering checks (steward)
This repository uses steward. Before reporting work as ready:
1. Run `steward check --summary` and read the whole summary line (PASS, FAIL, INCOMPLETE, UNKNOWN, NOT_APPLICABLE).
   The `using-steward` skill explains every status.
2. A gate that is NOT ELIGIBLE is not ready. Fix FAIL first, then INCOMPLETE. Report every UNKNOWN to the human
   verbatim; never treat it as a pass.
3. Do not edit `steward.toml` to make a check pass without telling the human.
4. Quote the report's coverage statement: checks cover declared rules, not scientific validity.
<!-- <<< steward -->
