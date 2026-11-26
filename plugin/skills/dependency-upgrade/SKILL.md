---
name: dependency-upgrade
description: Upgrade a pinned dependency with parity harnesses, a record and approval before the pins move. Use before changing a pin.
---

# Upgrading a pinned dependency, with parity

Start by saying in one line that you are using this skill and why.


For a pinned scientific library whose results your project depends on. R-66 (`[dependencies]`) checks that every
pin changed since the last release tag has a complete record. The order matters: the pins move last.

1. **Scratch environment first.** Install the new version beside the current one (a new virtual environment or
   container); never in the project's own environment.
2. **Run the parity harnesses one at a time, under limits.** Use `steward run --wall … --mem … --slot heavy` for each,
   so a slow or memory-hungry harness is stopped and recorded rather than left running.
3. **Compare row by row with the previous version's evidence.** `steward diff run A B --tol …` compares two run records
   with declared tolerances; a difference is a finding, never silently accepted.
4. **Run the library's own checks** if it ships them (its test suite or request checks).
5. **Write the record** in `development/upgrades/` (the `[dependencies] records` globs):
   ```toml
   schema   = "steward.upgrade/0.1"
   package  = "scanpy"
   old      = "1.10.1"
   new      = "1.11.0"
   approval = "2026-11-23: move scanpy to 1.11"   # the decisions-log heading
   [[harnesses]]
   name    = "parity-a"
   verdict = "pass"            # pass | accepted (with a note) | differs | failed
   [[harnesses]]
   name    = "parity-b"
   verdict = "accepted"
   note    = "within the declared tolerance"
   ```
6. **Get the owner's approval** and record it in the decisions log under the heading the record names.
7. **Only then move the pins** in the declared files and commit them with the record. `steward check dependencies`
   is PASS when each changed pin has a record whose every harness passed or was accepted.

Requirement-style pins (`name==version`, `name @ git+…@tag`) are read; lock files in other formats are not, so list
the file that holds the pins you change by hand.
