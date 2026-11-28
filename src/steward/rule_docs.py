"""What each rule is for, in plain words (0.10.0 U1). `steward explain R-xx` prints it, and the user guide's
reference pages are generated from it (tools/build_rule_reference.py), so the two never disagree.

Each entry: `checks` (what is evaluated), `why` (what goes wrong without it, often when an agent writes the code),
`not` (what a PASS does not mean), and `scope` ("project" or "multi-project" governance).
"""

from __future__ import annotations

from .code_docs import CODE_DOCS  # noqa: F401 - re-exported for callers and tests

D = dict

RULE_DOCS: dict[str, dict[str, str]] = {
    "R-01": D(checks="steward.toml (and any overlay) parses, matches the schema, keeps paths inside the repository, "
              "and has its required process records.",
              why="Every other rule reads the configuration; a broken one must stop the gate, not pass quietly.",
              **{"not": "The configured rules are the right ones for the project."}, scope="project"),
    "R-02": D(checks="Each benchmark contract is a valid steward.contract/0.1 file.",
              why="A contract an agent cannot parse cannot hold it to a design.",
              **{"not": "The design is good, only that it is well formed."}, scope="project"),
    "R-03": D(checks="A contract's parts agree: datasets, splits, baselines, metrics, thresholds and outputs refer to "
              "each other consistently.", why="Inconsistent contracts let a comparison drift without anyone deciding it.",
              **{"not": "The comparison is balanced, or the metrics suit the question."}, scope="project"),
    "R-04": D(checks="A confirmatory profile has a benchmark contract.",
              why="Confirmatory claims need a design fixed before results exist.",
              **{"not": "The contract was written before the results."}, scope="project"),
    "R-05": D(checks="Each prior-work record passes its schema.", why="Novelty claims rest on recorded prior work.",
              **{"not": "The search for prior work was complete."}, scope="project"),
    "R-06": D(checks="A confirmatory profile has a prior-work record.", why="A claim of novelty needs its comparison.",
              **{"not": "The work is new."}, scope="project"),
    "R-07": D(checks="Files in the privacy scan's scope contain no controlled-access accessions, listed terms or "
              "absolute home paths with user names.", why="Private identifiers, names and paths can appear in code and documents.",
              **{"not": "No private information exists in other forms (images, binaries, paraphrases)."}, scope="project"),
    "R-08": D(checks="The paper's spec file passes its schema.", why="PaperKit's other checks read it.",
              **{"not": "The paper's argument holds."}, scope="project"),
    "R-09": D(checks="No placeholder (TODO, TBD, [RESULT …]) is left in the manuscript.",
              why="An agent's draft can keep placeholders that look finished.",
              **{"not": "The text says the right thing."}, scope="project"),
    "R-10": D(checks="Every number in the manuscript comes from the values registry, which comes from result files.",
              why="A number typed by hand, or by an agent, drifts from the results it claims to report.",
              **{"not": "The result files are themselves right."}, scope="project"),
    "R-11": D(checks="Figures and tables match the display lock (their sources and hashes).",
              why="A regenerated figure must not silently replace the one the text describes.",
              **{"not": "The figure shows what it should."}, scope="project"),
    "R-12": D(checks="The paper builds from source with its declared engine.", why="A paper that only builds on one "
              "machine is not a submission.", **{"not": "The PDF reads well."}, scope="project"),
    "R-13": D(checks="The venue's limits and requirements (length, anonymity, required sections).",
              why="Desk rejections for form are avoidable.", **{"not": "The venue will accept the paper."}, scope="project"),
    "R-14": D(checks="Every citation key resolves to a bibliography entry, and entries carry identifiers.",
              why="Agents invent plausible references; unresolved keys catch some of them.",
              **{"not": "The cited work says what the text claims."}, scope="project"),
    "R-15": D(checks="Numbers repeated across abstract, text, tables and talk agree.",
              why="Edits update one place and not the others.", **{"not": "The numbers are right."}, scope="project"),
    "R-21": D(checks="The talk plan passes its schema.", why="The talk checks read it.", **{"not": "The talk is good."}, scope="project"),
    "R-22": D(checks="The talk's stage (internal, conference, public) was confirmed by a human.",
              why="What may be shown depends on the audience; an agent cannot decide it.",
              **{"not": "The confirmation was accurate."}, scope="project"),
    "R-23": D(checks="Slides claim no more than the paper or the results support.",
              why="Talks overstate; the ceiling is the evidence.", **{"not": "The claims hold."}, scope="project"),
    "R-24": D(checks="Numbers on slides come from the values registry.", why="As R-10, for talks.",
              **{"not": "The result files are right."}, scope="project"),
    "R-25": D(checks="The talk states its limitations.", why="Limitations disappear first under time pressure.",
              **{"not": "Every limitation is listed."}, scope="project"),
    "R-26": D(checks="The talk follows its declared structure.", why="A planned structure survives editing.",
              **{"not": "The structure is effective."}, scope="project"),
    "R-27": D(checks="Talk figures match their sources.", why="As R-11, for talks.",
              **{"not": "The figures are readable."}, scope="project"),
    "R-28": D(checks="Measurable visual properties of the slides (bounds, sizes, contrast, resolution).",
              why="Some slide problems are measurable.", **{"not": "The slides look good."}, scope="project"),
    "R-29": D(checks="Strong wording on slides is listed for human review (advisory).",
              why="Overclaiming words are easy to miss.", **{"not": "The wording is acceptable."}, scope="project"),
    "R-31": D(checks="Every ledger is an intact hash chain (no edit, gap or torn tail).",
              why="Ledgers are the record of what ran, was spent and was decided; an agent must not rewrite them.",
              **{"not": "A consistent rewrite of the whole ledger is detected without an anchor."}, scope="project"),
    "R-32": D(checks="Runs are recorded, finished, and their outputs match the records.",
              why="A result without a run record cannot be traced to code and inputs.",
              **{"not": "The run's computation was right."}, scope="project"),
    "R-33": D(checks="Policy files match the pinned baseline, and the trust root is pinned outside the repository.",
              why="An agent can edit policy in the working tree; the pin makes that visible.",
              **{"not": "Whoever holds the signing key used it carefully."}, scope="project"),
    "R-34": D(checks="Spend records are within budget, or approved past it.", why="Paid calls by agents add up.",
              **{"not": "Calls made outside steward were counted."}, scope="project"),
    "R-35": D(checks="Frozen protocol files, cohorts and parameters have not changed since they were frozen.",
              why="Confirmatory work must not change its design after seeing results.",
              **{"not": "The frozen design was a good one."}, scope="project"),
    "R-36": D(checks="Datasets are declared with their roles and hashes, and their links name declared datasets.", why="Sealed and spent data must be known.",
              **{"not": "The data is what its label says."}, scope="project"),
    "R-37": D(checks="Sealed data was not used without a signed unseal.", why="Held-out data used early is no longer held out.",
              **{"not": "Data copied outside steward was not used."}, scope="project"),
    "R-38": D(checks="Gated integrity actions carry signed approvals and decisions, and every decisions log is "
              "append-only.", why="Decisions are the owner's; rewriting them rewrites history.",
              **{"not": "The decisions were wise."}, scope="project"),
    "R-39": D(checks="A run under a frozen contract used the frozen version.", why="Results must come from the design that was fixed.",
              **{"not": "The run itself was right."}, scope="project"),
    "R-40": D(checks="Each claim in the claim map points at evidence that exists and matches it.",
              why="Claims drift from their evidence as work continues.", **{"not": "The evidence supports the claim."}, scope="project"),
    "R-41": D(checks="Prior-work links resolve.", why="Dead links make prior work uncheckable.",
              **{"not": "The linked work is relevant."}, scope="project"),
    "R-42": D(checks="A release has its required files, a manifest that matches the distributions and bundles, and "
              "an audit with no development files, secrets or private terms.",
              why="What ships must be what was declared, and nothing more.", **{"not": "The software does what it should."}, scope="project"),
    "R-43": D(checks="An independent review is recorded before a release, with its findings closed.",
              why="No agent approves its own work.", **{"not": "The review found everything."}, scope="project"),
    "R-44": D(checks="Runtime modules match their recorded fingerprints, or a neutral change is acknowledged.",
              why="Silent changes to shared code change frozen behaviour.", **{"not": "An acknowledged change is neutral."}, scope="project"),
    "R-45": D(checks="Splits do not share IDs, groups or time ranges.", why="Leakage between splits inflates results.",
              **{"not": "Undeclared kinds of leakage are absent."}, scope="project"),
    "R-46": D(checks="Benchmark datasets match their declared hashes.", why="A changed dataset is a different benchmark.",
              **{"not": "The dataset is suitable."}, scope="project"),
    "R-47": D(checks="The results matrix is complete and meets its thresholds.", why="Missing cells hide failures.",
              **{"not": "The results generalise."}, scope="project"),
    "R-48": D(checks="The declared comparison was made against the declared baselines.",
              why="Changing the comparison after the results is cherry-picking.", **{"not": "The baselines are strong."}, scope="project"),
    "R-49": D(checks="Each leakage type is declared as checked, not applicable, or unknown.",
              why="Undeclared leakage types stay unknown, never silently clean.", **{"not": "There is no leakage."}, scope="project"),
    "R-50": D(checks="Registered large artifacts are present with their hashes.", why="Results depend on artifacts outside git.",
              **{"not": "The artifacts can still be retrieved."}, scope="project"),
    "R-51": D(checks="The project declares the constitution, the installed version, and its records.",
              why="Every project governed the same way follows the same rules.", **{"not": "The rules were followed."}, scope="multi-project"),
    "R-52": D(checks="Each reproduction contract has a passing check on the current tree.",
              why="Published outputs must still be re-derived after every change.",
              **{"not": "The reproduction ran on independent hardware."}, scope="project"),
    "R-53": D(checks="Exchange items pass their schema, are uniquely numbered, in their places, with legal state transitions, and "
              "what this project sends holds no public term. An outbox item without a receipt after the configured number "
              "of days is advisory. Check the peer's ref and ask it to pull and commit the receipt. An outbox item that "
              "differs from the bytes the peer's committed receipt records is INCOMPLETE at once. Untracked files that "
              "git ignores, and untracked OS metadata files (.DS_Store, Thumbs.db, desktop.ini, ._*), are left out.",
              why="Requests between projects must not get lost, duplicated or decided twice.",
              **{"not": "The other project agrees with the recorded state."}, scope="multi-project"),
    "R-54": D(checks="Received items are unchanged since they were received, and get a decision in time.",
              why="An inbox edited after receipt no longer records what was asked.",
              **{"not": "The decision was the right one."}, scope="multi-project"),
    "R-55": D(checks="The session handoff is current, within budget, well formed and private-free (advisory).",
              why="A new agent session should start from one short record, not a transcript.",
              **{"not": "The handoff mentions everything that matters."}, scope="multi-project"),
    "R-56": D(checks="Declared packages import no forbidden module, and pyproject declares no forbidden distribution.",
              why="Libraries that must stay independent drift as agents add convenient imports.",
              **{"not": "Computed imports were checked."}, scope="project"),
    "R-57": D(checks="Task IDs are unique, open tasks are on the board, and its next ID is unused.",
              why="Several agents filing tasks collide on IDs.", **{"not": "The board is up to date in substance."}, scope="project"),
    "R-58": D(checks="Changes since the last release have Unreleased changelog entries with their fields (advisory).",
              why="Release notes written at the end miss changes.", **{"not": "The entries describe the changes well."}, scope="project"),
    "R-59": D(checks="History follows the declared branch model: tagged release commits, no-ff merges, branch names.",
              why="A branch model kept by hand erodes.", **{"not": "The merged work was reviewed."}, scope="project"),
    "R-60": D(checks="Skill copies for several agent harnesses match the one canonical copy.",
              why="Two drifting copies give two agents different instructions.", **{"not": "The skills are right."}, scope="project"),
    "R-61": D(checks="No committed text file holds an unresolved merge-conflict marker.",
              why="Parallel agents and merges leave markers in records.", **{"not": "The merge was resolved correctly."}, scope="project"),
    "R-62": D(checks="Agent attempts and scores are recorded append-only, no attempt is scored by its author, and "
              "with `[agents] may_score` each score is by an agent the table lets score that attempt's author.",
              why="Self-scored work is not evaluated work.", **{"not": "The scores are accurate."}, scope="multi-project"),
    "R-63": D(checks="Frozen file sets (agent prompts, tools, configuration, golden fixtures) are unchanged, or "
              "re-recorded with a decision.", why="A frozen agent version must stay frozen.",
              **{"not": "The frozen version behaves well."}, scope="project"),
    "R-64": D(checks="Container build contexts hold no dev-only paths, secrets, outside links or large unignored folders.",
              why="Images copy what the context holds.", **{"not": "The image is secure."}, scope="project"),
    "R-65": D(checks="Compose services set their declared keys, keep user data on named volumes, and ship what they "
              "must.", why="Container-only failures never show in a native run.", **{"not": "The services work together."}, scope="project"),
    "R-66": D(checks="Each pinned dependency changed since the last release has a complete parity record.",
              why="Upgrading a scientific library can change results.", **{"not": "The parity harnesses were sufficient."}, scope="project"),
    "R-67": D(checks="A contract's minimum number of units reaches its target power in the recorded table.",
              why="An underpowered confirmatory test wastes the held-out data.",
              **{"not": "The development effects predict the confirmatory ones."}, scope="project"),
    "R-69": D(checks="The generated site pages, README block and SVG assets match their current records and hold no "
              "private term or local path. The site and README each have their own opt-in.",
              why="Readers rely on documentation that reflects the project's records.",
              **{"not": "The site explains the project well."}, scope="project"),
    "R-68": D(checks="Every staged run was launched with its recorded GO and accrual minimum.",
              why="Outcome stages must wait for the owner's GO.", **{"not": "The GO was well judged."}, scope="project"),
    "R-70": D(checks="development/milestones.toml matches its schema, names tasks and exchange items that exist, and every "
              "milestone past its due time has a recorded outcome (met, moved with a decision, or dropped).",
              why="A deadline that passes silently is planning nobody can learn from; a milestone naming missing work "
              "reports progress it cannot measure.",
              **{"not": "The milestone is achievable, or its progress is enough."}, scope="project"),
    "R-71": D(checks="Each sprint file under development/sprints/ matches its schema (no cycles, a done command per "
              "task), and its ledger is intact.",
              why="A sprint dispatches agents unattended; a malformed plan or an edited ledger misreports what ran.",
              **{"not": "The tasks are the right ones, or their done commands test enough."}, scope="project"),
    "R-72": D(checks="A sprint whose window has ended has its report, and every task it records as done has every "
              "done command recorded with exit 0.",
              why="The report lists the branches waiting for the human's merge; without it, finished work is lost "
              "track of.", **{"not": "The merged work does what the task asked."}, scope="project"),
    "R-73": D(checks="Each declared pin's artifact is present and matches its digest; a retired pin's kept artifact is "
              "present and matches what the pins ledger recorded; the records a pin protects exist.",
              why="Frozen records depend on the exact version that produced them; losing its artifact makes them "
              "unreproducible.", **{"not": "The pinned version is free of defects, or the protected records are right."},
              scope="project"),
    "R-74": D(checks="Deprecated pins still used by the project's code (by import or by a declared reference), and pins whose retirement conditions all hold "
              "(advisory).", why="Pins accumulate; deprecation first shows who still depends on one before it goes.",
              **{"not": "Retiring is safe for code outside the repository."}, scope="project"),
    "R-75": D(checks="When a study declares chromosome sizes, VCF and SAM header contigs and BED intervals are "
                     "checked against the declared genome. Every study record's inputs, results and plan are "
                     "present and match their recorded sha256; studies "
                     "that depend on a changed one, and the papers citing them, are stale; the same input in two studies is "
                     "listed; declared references agree across studies. Sample sheets are checked for complete confounding "
                     "and strong imbalance. A recorded Bioconductor version has major.minor release form.",
              why="A reanalysis or a reviewer needs to know exactly which data, references and tools produced a result, "
                  "and which papers go stale when they change.",
              **{"not": "That the data or references are the right ones for the question."}, scope="project"),
    "R-76": D(checks="Research-direction records (advisory): literature reviews older than [research] stale_days, reviews "
                     "without an included source, contributions without their nearest prior work or difference, gaps "
                     "marked addressed or accepted without a decision, dead-end reviews without a decision.",
              why="What was searched, found and decided while developing a project should outlive the chat it happened in.",
              **{"not": "That the search was complete, or that a contribution is novel."}, scope="project"),
    "R-77": D(checks="For a paper that declares a citations record: every bibliography entry with a DOI or PMID has a "
                     "record, and the recorded title it resolves to is the cited title.",
              why="Made-up or mismatched citations are a documented failure of AI-assisted writing.",
              **{"not": "That a citation supports the sentence that cites it."}, scope="project"),
    "R-78": D(checks="For a benchmark contract with [llm_eval]: no group (study, series) in both tuning and test, no "
                     "model judging its own answers, test cases public before a candidate's training cutoff (reported), "
                     "and the prompts held in a [[frozen]] set.",
              why="Language-model evaluations on published science leak through training data, shared studies and "
                  "moving prompts.",
              **{"not": "That a model never saw a case: a cutoff is the provider's statement."}, scope="project"),
    "R-79": D(checks="The declared SPDX licence is the one LICENSE, pyproject.toml, package.json, DESCRIPTION and "
                     "CITATION.cff state.", why="A package that states two licences cannot be relied on by anyone.",
              **{"not": "That the licence suits the project (not legal advice)."}, scope="project"),
    "R-80": D(checks="Every dependency's licence (from its installed metadata: License-Expression, classifiers, the "
                     "licence field) against the policy for the distribution state: incompatible fails, unknown is "
                     "UNKNOWN, weak copyleft passes with its obligation where the policy allows, a copyleft package "
                     "declared in [licence] use as only invoked as a separate tool passes with its obligations; a "
                     "public project's third-party notices name every dependency.",
              why="A licence conflict found at release blocks a release already tagged; found on the commit that adds "
                  "it, it costs a package swap.", **{"not": "Legal compliance: declared rules and metadata only."},
              scope="project"),
    "R-81": D(checks="Copied, ported, translated or vendored code and bundled assets declared in third_party, and "
                     "files whose SPDX-License-Identifier or Derived-from header names another licence, against the "
                     "policy.", why="A translation of copyleft code is a derivative work; no package manager sees it.",
              **{"not": "That undeclared copied code is absent (R-82 only hints)."}, scope="project"),
    "R-83": D(checks="Declared data tables for Ensembl suffix consistency, species symbol casing and obsolete HGNC "
              "symbols, as well as column types, identifier shapes, missing values, counts, p-values, fold changes "
              "and sample alignment. The contract validates a declared log base.",
              why="Table exports can silently change identifiers, values or sample labels.",
              **{"not": "That every identifier is current or that any scientific conclusion follows."},
              scope="project"),
    "R-82": D(checks="Advisory: code comments such as 'ported from', 'translated from' or 'adapted from' in files "
                     "with no declaration.", why="Undeclared ports are found by reading; the hint points the reader.",
              **{"not": "Anything by itself: a hint is never a pass or a fail."}, scope="project"),
    "R-85": D(checks="Every accession recorded by a study that lists the paper appears in the paper's data-availability "
                     "statement: the file its spec names (data_availability), else the section under a 'Data "
                     "availability' heading in its sources.",
              why="Journals and reviewers check that every dataset used is named; a missing accession is found late, "
                  "by someone else.",
              **{"not": "That the accessions are public, or that the statement is complete beyond the recorded studies."},
              scope="project"),
    "R-84": D(checks="Advisory: each shadow stage has a current comparison tied to two successful recorded runs and "
                     "their unchanged outputs.", why="Review agreement and every disagreement before using the candidate.",
              **{"not": "That the methods are interchangeable or that the owner approved the switch."}, scope="project"),
    "R-86": D(checks="Model weights and training study fingerprints, the declared weights licence expression, and "
                     "exact card metrics from a successful run on the recorded weights, contract and current splits.",
              why="A model's recorded metrics can become stale when weights or benchmark splits change.",
              **{"not": "Scientific validity, proof of training, or permission to distribute the weights."}, scope="project"),
    "R-87": D(checks="Advisory: with [stranger_test] declared, a stranger-test record (development/assessment/"
                     "DATE-stranger-test-TAG-AGENT.md) not older than max_age_days.",
              why="Whether a newcomer can get value from a release is found by trying it, from the outside, before "
                  "the release; the project's own developers cannot see it any more.",
              **{"not": "That the project is useful: the record says what one stranger met."}, scope="project"),
    "R-88": D(checks="Advisory: with [tidy] declared, the counts of steward tidy from the repository's records: open "
                     "board tasks untouched for stale_days, board statuses a sprint ledger contradicts, own exchange "
                     "items still open after their response, a handoff older than handoff_days or a state page naming "
                     "no version as recent as the latest tag, received items not acknowledged in time, merged sprint "
                     "branches and worktrees.",
              why="Stale tasks and pages cost attention, and for agents tokens, at every session; naming them lets the "
                  "owner archive, delete or keep each one.",
              **{"not": "That a listed item should go: nothing is archived or deleted unless the owner asks. Memory "
                        "folders and the peers' checkouts are outside the repository: steward tidy lists them."}, scope="project"),
    "R-89": D(checks="Advisory: with [delegation] declared, each agent it names (the master and every worker) is "
                     "installed: its CLI is on PATH or in its known install folder. Nothing is run.",
              why="A delegated task given to an agent that is not installed fails before it starts, and the master "
                  "learns it only then.",
              **{"not": "That the agent is signed in or within its usage limits: steward agents status shows what "
                        "the availability ledger recorded."}, scope="multi-project"),
}


# Result codes that the source builds at run time from a small, fixed set of values (0.10.0 review S9). The codes a
# rule passes to a local helper (`bad("invalid")` for `f"R-53.{code}"`) are read from the source; these are not.
DYNAMIC_CODES: dict[str, list[str]] = {
    "R-07": ["R-07.list_unreadable", "R-07.list_empty"],
    "R-10": ["R-10.source_missing", "R-10.source_unknown", "R-10.source_error"],
    "R-13": ["R-13.title_words", "R-13.abstract_words", "R-13.title_words_over", "R-13.abstract_words_over",
             "R-13.missing_section",
             "R-13.missing_declaration"],
    "R-32": ["R-32.interrupted", "R-32.failed", "R-32.killed"],
    "R-35": ["protocol.drift", "cohort.changed", "params.changed"],
    "R-42": ["R-42.terms_unavailable", "R-42.excluded", "R-42.private_term_in_name", "R-42.policy_term_in_name",
             "R-42.local_path", "R-42.private_term", "R-42.policy_term", "R-42.forbidden_member",
             "R-42.missing_member", "R-42.missing_artifact", "R-42.version_mismatch"],
    "R-88": ["R-88.stale_task", "R-88.contradiction", "R-88.stale_page", "R-88.exchange", "R-88.leftover"],
}
