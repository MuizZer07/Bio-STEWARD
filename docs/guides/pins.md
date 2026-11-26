# Retire a pinned dependency: deprecate, keep the artifact, drop the install

Frozen records (locks, freezes, plan hashes) depend on the exact version of a library that produced them, so a
project can end up keeping several versions side by side. `[[pin]]` declares each one, with what it protects and when
it may go; `steward pins` handles the rest the same way in every project. No agent retires a pin by hand.

## The stages
| State | Meaning |
|---|---|
| active | in use; no retirement planned |
| deprecated | declared with `deprecated = { reason, target }`: still installed; R-74 reports code that still uses it |
| retire-eligible | deprecated, no tracked code uses it, and every `retire_when` condition holds (computed) |
| retiring | its plan is recorded and removal was interrupted: `steward pins retire NAME --resume --authorization TAG` (the same approval) finishes it |
| retired | its artifact, manifest and checksum are kept in `pins/retired/<name>/`; its install is gone |

Callers always count: a pin that declares neither `module` nor `references`, or whose callers cannot be read, is never
eligible, and a pin that `protects` records needs an `after:` condition. Conditions: `no_callers` (no tracked file is a
caller by the pin's rule: a Python file importing its `module`, a static scan of import statements, or a file naming
one of its `references`; files under `ignore_callers` are listed but do not count), `superseded_by:<version>` (that version is
pinned and installed), `after:<record path>` (the record exists), `after:milestone:<id>` (the milestone is recorded as
met), `never`. The commented template in `steward.toml` gives the recommended policy.

### Pins that share one import name
Versions of one library usually import as the same module, and a caller picks a version by the folder it puts first
on `sys.path` or by the loader script it runs. A `module` scan then counts every caller of any version as a caller of
every pin. Name what tells this pin's callers apart instead:

```toml
[[pin]]
name = "lib-1"
module = "lib"
references = ["vendor/lib_1/", "scripts/load_lib_1.py"]   # tracked files that mention one of these are its callers
callers = "references"          # the default when references is set; "module" or "both" also work
ignore_callers = ["audits/finished/**"]   # finished records kept as evidence: listed, never blocking
```

Both scans take each file's kind from git's index: a submodule or a tracked link holds no text and is left out, while
a tracked file that is now a folder or a link, or is reached through a linked folder, counts as unreadable. The
reference scan reads every tracked file as bytes. It skips the pin's own install paths and artifact, the records
it `protects` (its `after:` condition covers those), `steward.toml`, the pins ledger and the keep folder. A file that
cannot be read still blocks eligibility, even under an `ignore_callers` glob. `steward pins status` names the rule
that found each caller (`module`, `reference`, or both) and marks the ignored ones.

## Retire
```bash
steward pins status                                   # each pin's state and why; the object a retirement signs
steward authorize prepare pin.retire --object sha256:<from status> --expires 2026-12-31T23:59:59Z
steward authorize sign <nonce>                        # the human's step
steward pins retire lib-1-0 --authorization steward/auth/<nonce>
```
The approval is for this **plan**: the pin, its version, its artifact path and bytes, every install path with every
file under it, and the keep folder. Any change to them needs a new approval, and each approval is used once; R-33 must
pass. Retirement refuses links and overlaps (git, the keep folder, other pins), writes and reads back the kept
artifact, manifest and checksum, records the plan before removing anything, removes each planned path only while it
is what the plan recorded, and records every removed entry with its digest and the commit before the removal. Commit
the removal.

## Restore
`steward pins restore lib-1-0` copies the kept artifact back and runs `install_command` and then `check_command`
(required); the pin counts as restored only when they pass, otherwise it stays retired. It prints the `git checkout`
for the removed files that the recorded commit holds, and names those it does not.

R-73 fails when a retired pin's kept artifact is gone or changed, so any frozen record that depends on it can still be
reproduced.
