# Principles

Bio-STEWARD is built on a few rules. They hold for every check it runs, whether you use one rule or all of them.
Projects that want the full governance text for themselves and their peers can declare the
[constitution](https://github.com/MuizZer07/Bio-STEWARD/blob/main/CONSTITUTION.md) (`steward constitution`); nobody
has to.

1. **Humans decide; agents propose.** An agent implements and reports. Approving work, spending, amending a frozen
   protocol, unsealing held-out data and changing policy are human decisions, recorded as signed approvals.
2. **A PASS means the declared rules hold, nothing more.** It says nothing about whether a finding holds outside them,
   whether a method is new, or whether a comparison is balanced. Every check names what it does not check.
3. **Five statuses, and UNKNOWN is never a pass.** PASS, FAIL, INCOMPLETE, UNKNOWN, NOT_APPLICABLE. When evidence is
   unavailable, the check says so.
4. **Numbers trace to files.** Every value a paper or talk declares in its values registry comes from a result file
   or a recorded run, and numbers typed into the text without a source are reported.
5. **Records are append-only.** Ledgers are hash-chained; decisions are recorded verbatim and corrected by new
   entries, never by edits.
6. **Fixed before results.** Benchmark designs, splits and protocols are frozen and hashed; a confirmatory run recorded
   before the freeze, or a change after it, is reported, and a change needs a recorded decision. Sealed data is
   refused as a declared input of `steward run`.
7. **Nothing private leaves the project.** Committed files and the scanned contents of release artifacts are checked
   for the declared private terms and for local paths; what could not be scanned is reported.
8. **The toolkit is generic.** A project's specifics live in its own repository and configuration.
9. **Known limits are published.** Each release lists its known issues and what to do until they are fixed.
