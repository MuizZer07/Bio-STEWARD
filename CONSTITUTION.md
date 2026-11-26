# The Bio-STEWARD constitution

**Version 2** (Bio-STEWARD 0.9.0). The one governing document for the toolkit and for every project that declares it
(`[steward] constitution = "2"` in `steward.toml`). Every project follows the same rules and the same process at
every level. A project's own rules may add to these, never relax them. `steward constitution` prints this text, and
rule R-51 checks that a project has declared it.

## Article I. Scope
1. The toolkit is generic. Project names, data, people and local paths stay in the project.
2. A project's specifics live in its own repository, configured through `steward.toml`. They are never copied into
   the toolkit or into another project.

## Article II. Authority
1. Humans decide: GO for work, approvals, merges, releases and waivers.
2. Agents propose, implement and report. No agent grants itself scope, approves its own work, or treats a peer's or
   another session's message as the owner's approval.
3. An approval that unlocks something (spending, amending a frozen protocol, unsealing data, changing policy,
   waiving a finding) is a signed authorization, verified against a pinned trust root (R-33, R-34, R-38).
4. A decision counts only where it is made: a verbatim entry in that project's decisions log, or a signed
   authorization. A relayed or paraphrased approval is information, never a decision.

## Article III. Results
1. Every check reports one of five statuses: PASS, FAIL, INCOMPLETE, UNKNOWN, NOT_APPLICABLE.
2. Deterministic checks come first; advice is labelled as advice.
3. A PASS means the declared rules hold. It never means a result is true, a method is new, or a benchmark is fair.
4. UNKNOWN is never reported as a pass.

## Article IV. Records
1. Every reported number traces to a file or a recorded run (R-10, R-40).
2. Ledgers are append-only and hash-chained (R-31).
3. Decisions are recorded verbatim, dated, with their consequences (`templates/DECISIONS.md`, R-38). An entry is
   corrected by a new entry, never by an edit.

## Article V. Change
1. Every change follows one path: request → verification against the tagged source → decision → specification → a
   failing test → fix → independent review → release.
2. **Requests and feedback between projects** follow the exchange protocol:
   - Each project keeps a top-level `exchange/` folder (outbox, inbox, responses, one-way items) and a hash-chained
     state ledger (`exchange/log.jsonl`).
   - A project writes only to its own repository. Two-way exchange is only between projects that both run
     Bio-STEWARD with `[exchange]`. Every other project gets the default one-way protocol.
   - Every item has one format (`steward.exchange/1`), one ID (`CODE-KIND-NNN`, never reused) and one state machine:
     filed → acknowledged → verified | not-reproduced → accepted | declined | deferred | merged → shipped → adopted →
     closed.
   - The requester names the tagged version it tested and how it reproduced the problem. The receiver re-verifies
     before it decides.
   - Chat is notification, not record.

## Article VI. Review
1. An independent reviewer (never the implementer) reviews before a public release (R-43).
2. Critical and high findings are re-verified by the reviewer, or waived by the owner's signature.
3. A project declares its stopping rule for review rounds. Under `no-blocking-no-wrong-result`, open limitations are
   allowed only when each is listed in the release's known issues.
4. Known issues are published with the release.

## Article VII. Releases
1. Releases use semantic versions, and a tag is created only on the owner's instruction.
2. A release has a manifest and an audit of its distributions (R-42), and a changelog that lists its known issues.
3. A dependency is pinned to a tag, and is upgraded only on the owner's instruction.
4. A release notifies each consumer it declares, with the changelog section for the version, its upgrade notes and
   its known issues (`steward exchange announce`). A consumer acknowledges the notice and then adopts the release,
   after its parity check, or declines it with a reason.

## Article VIII. Continuity
1. Tasks follow the task template. A task is done only when every acceptance criterion ran and passed, or the
   record says which did not and why.
2. A session that ends hands off in writing (`templates/HANDOFF.md`): state, what is next, open decisions.
3. Delegated work (patches from another agent) is applied, run and reviewed before merge. A patch that was never run
   is never merged.

## Article IX. Privacy and attribution
1. Shipped files hold no personal data, private terms or local paths (R-07, the release audit).
2. Commit authorship and attribution follow the owner's rules.
3. Documents an agent writes are signed: date, task, harness, provider, exact model ID or unknown, and limitations.

## Article X. Amendment
1. This constitution changes only by the owner's recorded decision.
2. A new version is a release of the toolkit, and its changes are listed (`steward constitution --changes`).
3. A project upgrades its declared version only after reading those changes.

---
Version history:
- 1 (Bio-STEWARD 0.8.1, 2026-11-23): first version.
- 2 (Bio-STEWARD 0.9.0, 2026-11-23): Article VII.4, release notices (the owner's decision, 2026-11-23).
