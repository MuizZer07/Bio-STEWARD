# Recorded inputs (not generated)

`test/fixtures/` belongs to `scripts/fixtures.mjs` (every file there is regenerated from the pinned CLI and checked
by `npm run fixtures -- --verify`). The files here are recorded once and kept unchanged.

## `sprint/`: a sprint ledger recorded by CLI 0.20.6 (T13, AC-S9)

- `2026-11-27-vscode-0.1.jsonl`: the sprint ledger that `steward sprint` (0.20.6) wrote while it ran this
  repository's sprint `2026-11-27-vscode-0.1`, tasks T01 – T08, byte for byte as it was at commit `0dd2193` of
  `development/sprints/`. It holds every kind of line the live sprint view reads: `genesis`, `opened`, `order`
  (`go` and `skip`), and `state` (`running`, `checking`, `done`, `failed`, with checks and exit codes, including a
  failed check).
- `2026-11-27-vscode-0.1.toml`: that sprint's file at the same commit.

The unit suite `test/unit/sprint.test.ts` reads both and checks every displayed state, time and exit code against
the ledger lines. A second test runs a scratch sprint on the pinned CLI (a shell task that commits twice) when
`.cli/` is installed, so the view is also checked against a ledger written during the test.
