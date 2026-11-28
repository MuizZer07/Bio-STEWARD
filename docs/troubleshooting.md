# Troubleshooting

1. **Read the code, not only the reason.** Every detail has a code such as `R-42.no_manifest`.
2. **`steward explain R-42`** prints what the rule checks, each of its codes with a one-line description (0.23.0:
   every code has one), and the fix.
3. **`steward report .steward/report.json --format text --rule R-42`** shows one rule's full evidence
   (after `steward check --output .steward/report.json`).
4. **An `internal_error`** is a toolkit defect: report it with the command and the code.

Common first findings:

| Code | Usually | Fix |
|---|---|---|
| `R-07.local_path` | a home path in a committed file | use a relative path, or mark a deliberate example line `steward: allow R-07` |
| `R-33.*` UNKNOWN | the trust root is not pinned | `steward authorize pin` (once, on your machine) |
| `R-38.decisions_rewritten` | an earlier decision was edited | restore it; add a new entry instead |
| `R-42.no_manifest` | built but no manifest | `steward release manifest` |
| `R-61.conflict_marker` | a merge left markers | resolve the conflict |

Every code with its fix: the [rule reference](reference/rules.md).

## Installing without network access

`uv pip install "bio-steward @ git+…"` resolves its dependencies (pydantic and a few others) from PyPI. In a sandbox
without network, point uv at a cache that already holds them (`UV_CACHE_DIR=… uv pip install --offline …`), or
install from a wheel built where the network is available (`uv build --wheel`, then `uv pip install dist/*.whl`).
