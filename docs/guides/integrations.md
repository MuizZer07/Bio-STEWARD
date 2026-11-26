# GitHub Action, pre-commit and the agent plugin

## GitHub Action
```yaml
name: steward
on: [push, pull_request]
permissions:
  contents: read                                  # the check only reads
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09   # v5.1.0, pinned by commit
        with:
          fetch-depth: 0                          # history and tags: baselines, append-only checks, approvals
          fetch-tags: true
          persist-credentials: false              # the token is not left in the checkout
      - id: steward
        uses: MuizZer07/Bio-STEWARD@v0.20.5      # pin a tag you reviewed, or its commit SHA
        with:
          gate: default                           # or routine, release, submission …
          final: "false"                          # "true" or "false" only; "true" for a submission's final checks
```
- The toolkit is installed at the action's own version, in its own environment, from a runner folder (never from
  the checkout). The job fails unless the gate is ELIGIBLE; the output `eligible` says `true` or `false` (it is absent
  when setup itself failed).
- **What the gate means on a pull request.** The gate's rules come from the checked-out `steward.toml`, so a pull
  request can change which rules `default` requires. To make the policy binding, pin the trust root in CI as
  [the CI guide](../ci.md) shows (`STEWARD_TRUST_*`): R-33 then reports any unsigned policy change in every gate.
- **The report.** The full JSON report is written to a fresh runner folder outside the checkout (output `report`).
  It holds the project's identifier, the rule results with their subjects, details and evidence paths; the summary
  in the log shows subjects too. Upload it only where its readers may see those:
  ```yaml
      - if: always()
        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9   # v7.0.2, pinned by commit
        with: {name: steward-report, path: "${{ steps.steward.outputs.report }}"}
  ```
- **While the repository is private**, the action can be used only by repositories that the owner's Actions sharing
  settings allow; installing it needs no token beyond that.
- Every third-party action here, and inside the Bio-STEWARD action (`actions/setup-python` v6.3.0), is pinned by its
  commit and runs on Node 24. Pin Bio-STEWARD itself by a reviewed tag or its commit SHA too.

## pre-commit
```yaml
# .pre-commit-config.yaml (pre-commit 3.2 or newer; Python 3.11 or newer for the hook)
repos:
  - repo: https://github.com/MuizZer07/Bio-STEWARD
    rev: v0.16.0
    hooks:
      - id: steward-check
```
Then `pre-commit install`. The hook checks the commit's checkout and blocks only when the default gate is NOT
ELIGIBLE because of a FAIL; INCOMPLETE and UNKNOWN results do not block, a checkout without `steward.toml` is skipped,
and an unknown gate name blocks. It is the commit hook only: the pre-push checks (protected branches, the gate on each
pushed tip) come from `steward hooks install`. Use one or the other for commits, not both.

## Claude Code plugin
The repository can be added as a plugin marketplace (`.claude-plugin/marketplace.json`); installing `bio-steward`
installs the curated payload in `plugin/`: the skills and the plugin manifest only, generated from `skills/` by
`tools/build_plugin.py` (the tests check it is current). The `steward` command must be installed too. Adding the
marketplace itself clones the repository, development records included, into Claude Code's marketplace folder; the
installed plugin contains none of them.
