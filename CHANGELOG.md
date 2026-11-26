# Changelog

Pre-release. Not published on PyPI. Versions follow semantic versioning once released.

## Unreleased

## 0.20.4 (2026-11-25): the public README and documentation, checked
Pre-release, not on PyPI. Per Muiz, 2026-11-25: "make sure everything in the read me and docs are accurate.. also have
a list of agents/capabilites it is offering". Documentation only; no change to checks, formats or behaviour.

### Added
- [What it offers](docs/capabilities.md): the agents it works with, its 24 Agent Skills by kit, its commands by what
 you do and its 81 rules by area, generated from the toolkit (`tools/build_capabilities.py`; a test keeps it current).
- `tools/check_docs.py` and a test: every link in the public README and docs reaches a published file, every documented
 command and option exists, every rule ID named exists.

### Fixed
- README: a plain version badge (the status badge's escaping was fragile), current test count, the newer commands in
 the command table (`data fetch`, `example`, `check --rule`, `compare`, `tokens`, `licence`, `release go-public`,
 `stranger-test`); the roadmap removed; no link into the private development records.
- The paper guide named `paper displays --lock`; the option is `--record`.
- The CI guide installs from the public repository first; the token steps are for a private fork.

### Upgrade notes (from 0.20.3)
- None.

## 0.20.3 (2026-11-25): public on GitHub; going public with a release mirror, for any project
Pre-release, not on PyPI. Per Muiz, 2026-11-25: "make this Bio-STEWARD-dev and Bio-STEWARD for the public one.. add
this in the release option 1 feature in the package as well". The first public release: development continues in a
private repository; each release is published to the public one (model A). Tasks STW-043 and STW-044. 0.20.2 was not
tagged: its changes, and the fixes from its review, ship here.

### Added
- **`steward release go-public --owner OWNER --name NAME [--dev-name …] [--tag …] [--apply]`** (STW-044): the
 readiness of a release for the public (its export scanned as `release publish` does, each kind of finding with its
 fix), the plan (rename the development repository, point `origin` at it, create the public repository, record
 `[publish]`, publish the tag), and with `--apply` the steps in order, refused while anything would leak. The release
 repository is created private, so the owner looks before it is made public (`--public` to skip the look). See
 [publishing](docs/guides/publish.md#go-public-in-one-command).

### Fixed (the 0.20.2 review, STW-042, Gemini 4 Neon; development/assessment/2026-11-25-review-v0.20.2-192ebfa.md)
- **`study fingerprint --accept`** (AQ1): edits only the named file's own entry (inline or table form, either quote
 style; never a samples matrix or a comment), replaces its sha256 and size from one read and drops the archive's md5,
 then parses the record again: the file carries the new digest and every other file its old one, or nothing is
 written. `--accept ""` and `--accept` with `--write` refuse.
- **R-87** (AQ2): records are read without following links and must hold a report's title; a future-dated record is
 ignored and said so; the record is the verdict's evidence; a hyphen in a tag (`v1.0.0-rc1`) is read correctly.
- R-83 with only `p = 0` no longer says a file is missing (AQ3).
- `stranger-test brief` (AQ4): runs from a folder beside the repository and reads the brief by its full path
 (`--output` honoured); a tag or a repository path that is not a plain value is refused.
- Zenodo (AQ5): two files of one name in different folders keep their folders in the local name; `--file` takes the
 archive's key or the local name.
- The benchmark guide's fix step (AQ6); `task template --output` makes folders anywhere and never overwrites (AQ7);
 R-75's general hint and `check --rule` order details most specific first (AQ8); `task brief --output` changes only
 its footer, with the path as given (AQ9).

### Fixed (the re-verification, STW-045, Gemini 4 Neon; development/assessment/2026-11-25-reverification-v0.20.3-604c692.md)
- AQ1 – AQ6 verified. AR1: the public export names no adopter: this project's own `steward.toml` (its exchange table)
 and a one-off internal tool stay private, an example in the scrub tool is synthetic, test names are neutral, and a
 test scans the whole export against the project's own codes and adopter names (read at run time).
- AR2 – AR4: `go-public` records `[publish] remote` first (also into an existing table); before any change it refuses
 a `[publish] remote` naming another repository, a tag that is not a semantic version, a missing or signed-out `gh`,
 and a public repository it cannot rule out; an SSH `origin` stays SSH; the plan is shell-quoted; a missing author is
 not ready.

### Changed (a public-ready export, STW-043)
- Adopters' item IDs in source, tests and docs are neutral references (`FB-018`); test data and names use neutral
 codes; synthetic home paths in tests are built at run time. The development history keeps the originals.
- Bio-STEWARD declares `[publish]` (the public repository, the public author, the binaries checked by hand),
 `[licence] distribution = "public"` with development tools set apart, and ships `THIRD_PARTY_NOTICES.md`.

### Upgrade notes (from 0.20.1)
- No configuration changes. To go public the same way: `steward release go-public --owner … --name …`.

## 0.20.2 (2026-11-25, not tagged; shipped in 0.20.3): the stranger test for any project; what the Codex stranger test met
Pre-release, not on PyPI. Per Muiz, 2026-11-25: "yes do it. also add this stranger test in the features … keep this
generic". From the STW-016 stranger test by Codex (development/assessment/2026-11-25-stranger-test-v0.20.1-codex.md).
Tasks STW-040 and STW-041.

### Added
- **The stranger test, for any project** (STW-041; `[stranger_test]`, `steward stranger-test brief|record`, R-87
 advisory): before a release, an agent that has never seen the project installs the release in an empty folder,
 reads only what a newcomer sees, tries the project's own declared missions (between first contact and "follow one
 guide, then break something and fix it"), and reports a verdict, a friction log, unclear words, the output it had to
 read, and ranked suggestions for the project's audience. The report is filed in `development/assessment/`; R-87
 reports when none is recent. Nothing in it is specific to a field. See the [stranger-test
 guide](docs/guides/stranger-test.md).
- `steward study fingerprint ID --accept PATH`: record a changed file's new bytes on purpose (its sha256 and size; the
 archive's md5 dropped).
- `steward task template NAME --output FILE` (folders made).
- R-83: p-values of exactly 0 (an underflow) are reported once per column; an adjusted column equal to the raw one on
 every row fails.

### Changed
- A changed input's next step names both ways out: restore the file, or accept the new bytes on purpose.
- Each result's most specific details come first (a sample finding before the changed digest of its file).
- A new project's summary names its passing rules and says that an eligible gate there means nothing is broken, not
 that anything is verified; the release-review recommendation appears only in confirmatory projects.
- R-45's checked detail and R-76's draft detail are in words (R-76 names the fields to fill for each kind).
- `task brief` warns about template placeholders left in a task, says "none yet" for an empty history, and its footer
 names the file it was written to; Codex's read-only note and the acceptance criteria agree.
- `data fetch`: a missing archive record or an unreachable archive is a clear refusal; a Zenodo file in a folder is
 saved under its own name. Checked live once against ENA (resolution and md5s), ArrayExpress and Zenodo (downloads).

### Fixed
- The research-review install hint (it named `--for reanalysis`, which does not install a skill into an existing folder).
- Docs: the README no longer says the toolkit never fetches data; "CEL" explained; a runnable three-sample split check
 in the benchmark guide; installing without network; a glossary (profile, gate, GO reference, advisory, stranger test).

### Not in this release
- Built-in controlled-access identifier patterns for R-07: dbGaP and EGA study and dataset accessions are public
 metadata that papers must cite, so a pattern would flag correct text; participant-level identifiers have no common
 shape. Use a project term list for the identifiers that must stay private.

### Known issues in 0.20.2
| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| — | — | 0.20.2 has had no independent re-verification yet | treat R-83 – R-87 as beta |

### Upgrade notes (from 0.20.1)
- No configuration changes. Optional: declare `[stranger_test]` (audience, missions) for a sharper stranger test.

## 0.20.1 (2026-11-25): what a newcomer met in the first hour; the waived 0.19.0 findings
Pre-release, not on PyPI. From the STW-016 stranger test (Gemini in Antigravity,
development/assessment/2026-11-25-stranger-test-v0.20.0-gemini.md); per Muiz, 2026-11-25: "yes write up and start
implement it". Tasks STW-033 and STW-037.

### Changed
- **`--summary` shows what failed and where**: up to two detail lines (file:row:column and the message) under each
 FAIL, INCOMPLETE and UNKNOWN result, and how many more there are. Every non-PASS result is still listed.
- **`steward check --rule R-xx`**: checks that rule's areas and prints its results with every detail; `steward
 report FILE --rule R-xx` prints the same focused view (an explicit `--format` keeps the full rendering).
- `steward check --format json --output FILE` writes the file and prints one line saying where, not the JSON.
- `steward init --paper` and `--for paper` add `[paper.main]` to an existing `steward.toml` and write a starter
 `paper/values.toml`; the LaTeX skeleton inputs the generated values. The paper quick start shows `values.toml`.
- `steward example` makes a first commit, so the example README's undo (`git checkout --.`) works.
- The benchmark contract template shows how to declare every leakage type (R-49).
- R-83 findings quote the cell (`'7-Sep' looks like a spreadsheet date`).

### Fixed
- README: version, rule count (80) and the rules table (R-79 – R-86).
- The generated values file names `steward paper values --write` (it named a flag that does not exist).
- The recipes and the benchmark guide start with `steward init --for …`; `steward data fetch` and `steward study
 add-input` are in the reanalysis recipe.
- R-75 with no study yet suggests `steward study new`; the research-review hint says how to install the skill.
- **AM1** (High, waived in 0.19.0): a requirements file is read as pip reads it: a byte-order mark is skipped, and an
 include, constraint, editable or local entry anywhere on a line refuses (also after another option).
- **AM2**: the missing-tag push sends the branch at the same commit in the same atomic push, with the checked tip as a
 lease, so a branch that moved (forward or back) since the check rejects it, tag included.
- **AM3**: a public tag is judged by its whole name (`varchive/refs/tags/v0.1.0` is not `v0.1.0`).
- **AM4**: the recovery command after a failed local record quotes the staging path.
- **The 0.20.0 release review** (STW-032, Gemini 4 Neon in Antigravity;
 development/assessment/2026-11-25-review-v0.20.0-30efa29.md, AN1 – AN11):
 - `data fetch` opens every file it reads or writes as a plain file with one link (a hard-linked `.part` or target,
 a FIFO or a folder refuses), writes every byte, refuses a transfer shorter than the size the server stated,
 restarts after a 416 on resume, and normalises the archive's md5 (ENA and Zenodo, upper case; ENA's empty slots
 keep md5s and sizes aligned) (AN1, AN8);
 - R-75 lists every sample finding (no cap at 50); a missing or linked matrix is its own finding with its path, and
 the sheet's findings stay (AN2, AN3); chromosome names are read from SAM's RNAME column, from every BGZF block and
 from the whole file (AN7);
 - `data fetch` and `study add-input` insert a new input after the existing inputs' own subtables (AN4);
 - R-84 accepts only this repository's run ledger, and one stale comparison of the latest pair makes the stage
 stale (AN5, AN6);
 - `count = "rows"` leaves out a TSV header; the worked example's paper says 25 samples (AN9);
 - R-85 and R-13 ignore headings in fenced code and YAML front matter; a fence closes only on its own marker; bold
 body text is not a heading (AN10, AN11).
- **The 0.20.1 re-verification** (STW-038, Gemini 4 Neon;
 development/assessment/2026-11-25-reverification-v0.20.1-35e2e4f.md, AO1 – AO3 and partial verdicts): `check --rule`
 always checks the rule's own areas and exits by that rule alone (AO1); code fences follow CommonMark (a one-line
 ```` ```code``` ```` is inline code; a fence closes only with the same marker, at least as long) (AO2, AN10, AN11);
 `init --paper` refuses a linked `steward.toml` before writing anything (AO3); a new study input is appended after
 every table, so no input's subtables change owner in any spelling (AN4); `.sam.bgz` reads RNAME (AN7); both public
 pushes carry the checked tip as a lease, so a branch rewound after the check is refused too (AM2); `report --rule`
 accepts lower case. The second re-verification (STW-039,
 development/assessment/2026-11-25-reverification-2-v0.20.1-43b1710.md) verified those and found AP1: `check --rule`
 crashed when the rule was not applicable; it now exits 0 for a rule that is not applicable.

### Known issues in 0.20.1
| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| — | — | the 0.20.0 review's findings are fixed here; 0.20.1 itself has had no independent re-verification yet | treat R-83 – R-86 as beta |

### Upgrade notes (from 0.20.0)
- No configuration changes. `--format json --output FILE` no longer prints the JSON: read FILE, or drop `--output`.
- A values registry entry `count = "rows"` on a `.tsv` or `.tab` file now leaves out the header row: run `steward paper
 values --write` and check the number.

## 0.20.0 (2026-11-25): biology: public data, conventions, samples, data availability, a real worked example
Pre-release, not on PyPI. Per Muiz, 2026-11-25: "I agree with all the biology ideas" (B1 – B6) and "finish 0.20, we
will review it with codex later". STW-012, STW-022 and STW-023 were implemented by Codex in parallel and reviewed and
merged by the implementer. The independent release review (STW-032) is deferred by the owner and runs after the tag.

### Added
- **Fetch public data with provenance** (STW-011; `steward data fetch SOURCE:ACCESSION --study ID`): GEO series
 matrices and supplementary files, ENA/SRA runs, ArrayExpress files, Zenodo records and plain URLs, downloaded into
 the repository (resuming a partial download), checked against the archive's md5 and size where it publishes them
 (and `--sha256` when given), and recorded in the study with URL, retrieval date, size and sha256. A mismatch
 records nothing. The only command here that uses the network. See the [public data guide](docs/guides/public-data.md).
- **Conventions and sample metadata on study records** (STW-013, R-75): organism, NCBI taxon, coordinate base,
 chromosome naming (checked against BED, GTF, GFF and VCF files) and the identifier mapping table with its version;
 an input whose declared conventions differ from its study's fails. `[samples]`: required fields, allowed values,
 duplicates, and every matrix column in the sheet and the reverse, each finding with its file and row.
- **Data availability** (STW-014, R-85): a paper's data-availability statement must name every accession of the
 studies that list the paper.
- **A real public worked example** (STW-015; `steward example biology DIR`): GSE7621 (Parkinson's disease substantia
 nigra, 25 samples) fetched with its checksum, its samples checked, a pre-written differential-expression plan run
 with the standard library, the output tables under data contracts, and a short paper whose numbers come from the
 results; its README lists five ways to break it and what each check then says. Checked in CI.
- **Markdown papers**: R-13 reads Markdown headings for a venue's required sections and declarations.
- **Model records and cards** (R-86). Check weights and training study fingerprints, tie metrics to a recorded
 evaluation on the current splits, and publish [model cards](docs/guides/model-records.md) on the project site.
- **Table data contracts** (R-83). Check declared CSV, TSV, series matrices and differential expression tables for
 format errors, and compare matrix sample columns with a sample sheet. See the [data contracts guide](docs/guides/data-contracts.md).
- **Pipeline comparisons** (STW-023). Record agreement and disagreements between two runs, check current evidence for
 shadow stages with advisory R-84, and show agreement over time on the [project site](docs/guides/pipeline-comparisons.md).

### Known issues in 0.20.0
| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| — | — | the independent release review of 0.20.0 (STW-032) has not run yet (owner decision) | treat the new rules R-83 – R-86 as beta |
| AM1 – AM4 | High – Low | carried from 0.19.0 (waived): see Known issues in 0.19.0 | fixed in 0.20.1 |
| — | Low | `steward data fetch` is tested against a fake archive; GEO was fetched for real once, ENA, ArrayExpress and Zenodo were not | fetch with `--dry-run` first |

### Upgrade notes (from 0.19.0)

- Study records gain optional fields (`[references]` organism, taxon, coordinate_base, chromosome_naming, mapping;
 `[inputs.references]`; `[samples]`; per-file size, md5 and url); existing records stay valid. In the study template,
 top-level keys (plan, results, papers) now come before the first table, where TOML needs them.
- Add `[[data.contract]]` entries to check selected tables. Projects without entries can keep their existing configuration.
- Set `shadow = true` in a stage's `[[stages]]` entry to enable R-84 for that stage.

## 0.19.0 (2026-11-25): ready to publish: licences, releases, delivery, tokens, onboarding
Pre-release, not on PyPI. Per Muiz, 2026-11-25: "yes lets start.. assign tasks to codex for parallel implementations..
go on with the 0.19 release". STW-008, STW-010, STW-017 and STW-018 were implemented by Codex in parallel and reviewed
and merged by the implementer.

### Added
- **Token use per task** (STW-018; `steward task start|done`, `steward tokens check|report`): usage read from
 selected Claude Code, Codex and Gemini CLI logs, per task, agent and model; budgets with warnings at 80 % and
 100 % (terminal, a Claude Code hook, the status line); cost from the spend prices; the largest tool outputs and the
 most-read files. See the [token guide](docs/guides/tokens.md).
- **Publish stable releases, keep development private** (model A, supervised by steward; `[publish]`, `steward release
 setup|publish|status`): each release tag is exported (public paths only; development records and the exchange
 never), private item IDs are removed from the changelog, the export is scanned (term lists without waivers, local
 paths, the licence gate), and it is committed as one clean commit with the public author in a staging clone, never
 the working checkout; pushed only with `--push`. `setup --mode open` plans a later move to open development
 (model B) without moving, rewriting or pushing anything.
- **Install channels** (`[[channel]]`, `steward channel use NAME stable|dev [--tag] [--yes]`, `channel status`):
 switch a tool between its public stable and private development source, and record which one is in use.
- **Licence governance from the first commit** (; `[licence]`, **R-79 – R-82**, `steward licence
 inventory|notices`, the `licence-compliance` skill in a new `licence` kit): the declared SPDX licence checked
 against LICENSE and the package metadata; every dependency's licence (License-Expression, classifiers, the licence
 field) judged by a policy profile for the distribution state (internal, network, public), unknown never a pass,
 weak copyleft passing with its obligation; copied or ported code declared in `third_party` or by
 `SPDX-License-Identifier:` / `Derived-from:` headers; advisory hints for undeclared ports; dated exceptions; current
 third-party notices or a CycloneDX SBOM for a public project; the lockfile change named on the commit; the release
 manifest records the inventory and is refused with an open licence FAIL or UNKNOWN; release notices carry a licence
 summary. The task template asks for the source of copied or ported code. Not legal advice.

- **Requests reach their receivers** (STW-008): `[exchange] peers` take a `ref` (read that branch whatever the peer's
 checkout shows) or a git `url` (fetched shallowly with the safe git settings); peers are also discovered from the
 machine registry; `steward session start` and `exchange status` list items waiting at peers and this project's
 items a peer has not received (from the receiver's committed ledger and receipt hash); R-53 reports, as advice, an
 outbox item with no receipt after `delivery_days` (14).

- **An interactive README for every project** (STW-010; `steward docs readme [--pypi]`): a generated block between
 markers in the project's README, with locally generated light and dark SVG badges (gate, last release, studies,
 open items), a card of what the project checks, a lifecycle diagram and study cards; prose outside the markers is
 kept; `--pypi` prints a variant without diagrams; R-69 reports a stale or missing block.

- **Onboarding from the stranger test** (STW-006): `steward init --for benchmark|reanalysis|paper|agents|licence`
 writes what a goal needs and ends with the first commands to run; a project with nothing configured is told where
 to start; the summary puts the results that need action right after the gate, and a broken `steward.toml` is said
 once, first; `steward --help` groups the commands; `steward study add-input` records a data source and fingerprints
 its files without editing the record; a task can name how its brief is run (`- **Run:**`).
- **Token cost, measured** (STW-009): `steward check --quiet` is one line when every gate is eligible and nothing
 needs attention; the summary counts the areas not configured instead of naming them; the README states the measured
 sizes, and a test keeps the first summary of a new project within budget.

### Fixed (the release review b142183 and its re-verifications b544d17, ebcf843, f9beeac, e3e2847, c268cd2, 87063e2 and e5e903d)
Review: development/assessment/2026-11-25-review-v0.19.0-b142183.md (AF1 – AF19); re-verifications:
development/assessment/2026-11-25-reverification-v0.19.0-b544d17.md (AG1 – AG5) and
development/assessment/2026-11-25-reverification-v0.19.0-ebcf843.md (AH1 – AH3) and
development/assessment/2026-11-25-reverification-v0.19.0-f9beeac.md (AI1 – AI4) and
development/assessment/2026-11-25-reverification-v0.19.0-e3e2847.md (AJ1 – AJ3) and
development/assessment/2026-11-25-reverification-v0.19.0-c268cd2.md (AK1 – AK6) and
development/assessment/2026-11-25-reverification-v0.19.0-87063e2.md (AL1 – AL4). The seventh,
development/assessment/2026-11-25-reverification-v0.19.0-e5e903d.md, left AM1 – AM4 open; Muiz waived them for this
release under Article VI (DECISIONS.md, 2026-11-25), and they are listed under Known issues.
- **Publishing, model A** (AF1 – AF6, AG1, AG2): the staging clone is a folder of its own under `.steward/` (never
 `.steward` itself, the checkout or a link; its `.git` is a folder of its own); local git runs without inherited
 variables, system or user configuration, signing or an attributes file, and refuses a staging configuration that
 holds anything steward did not write (filters, drivers, push URLs, rewrites); the staged tree must equal the scanned
 export, file modes included (each export keeps its own); every local staging branch (also with an unborn HEAD) must hold
 only releases steward built or sent; `--push` re-exports and re-scans, requires the effective push URL to be `[publish] remote`, and,
 in one lookup before any local ref changes, refuses when the public tags or branch cannot be listed or fetched (no
 evidence is never read as none) and when the branch moves while it is read (the tags are listed between two
 readings of the same tip); a refusal or failure before the push restores every staging ref (or says which could
 not be), and once the push succeeded the release's local commit and tag are kept; it sends
 exactly one new commit with its tag atomically: on the public tip, or, for the first publication, with no parent;
 it sends only a missing tag when the public branch already holds the release, and refuses a release that is already
 public or not newer than every public release, by semantic-version precedence (build metadata ignored); a tag that
 is not a semantic version (SemVer 2.0.0, ASCII digits, no leading zero in a pre-release number) stops the push, since release order cannot be checked; the commit it reports is the one sent; `release status` counts a release
 as pushed only when steward recorded sending it, and lists every development tag not sent. The configured records
 root and term lists are never exported; private item IDs and terms in file paths or contents refuse (no part of a
 private path is printed: the licence gate runs only once none is left to name, and its own findings are screened
 by the same term lists, or all withheld when a list cannot be used); non-text files need `[publish]
 binary`. The licence gate judges exactly the published files at public strictness (a LICENSE and current notices
 among them), by the tag's own `[licence]` table when it has one (published or not), else the working one; a tag whose
 `steward.toml` cannot be listed or read refuses; INCOMPLETE
 refuses like FAIL and UNKNOWN.
- **Network** (AF6, AH2): only `release publish --push`, `exchange pull`, `exchange status --fetch`, `exchange
 announce` (for a consumer declared by URL), `paper citations --fetch` and `channel use --yes` (an install you ask
 for) reach the network; staging, `release status`, `session start`, `check` and numbering new exchange items never
 do. Numbering with a URL peer uses the IDs recorded at its last pull, and refuses until there is one; a pull whose
 ledger cannot be verified marks that peer's record unverified (numbering refuses; its IDs come back at the next
 verified pull), and a malformed record refuses with how to restore it (AI2).
 `exchange announce` numbers all its notices once, one per distinct consumer, before it marks anything shipped
 (AI4, AK5).
- **Licences** (AF7, AF9 – AF12, AG3): an unreadable lockfile or a nameless package entry is never an empty inventory;
 a locked package needs a version, as text (a requirements line pinned with `==`; an include (`-r`, `-c`, also `-rFILE`), editable
 or local entry refuses; a release notice then says the inventory is unavailable, never a count), and installed metadata of exactly that version; an exception covers only its
 exact licence (`-only`, `-or-later` and `WITH` clauses differ) and scope; a third-party declaration never hides a conflicting header; `WITH` needs an
 exception identifier; summaries keep an `AND`'s copyleft; a notices line must match name, version and licence
 exactly; a linked environment (any folder its pattern passes through, never expanded beneath a link), distribution folder or term list is a problem, never a clean result; an unreadable committed lockfile is
 noted separately.
- **Paths without links** (AF12, AF15, AF18, AG5): metadata, term lists (also for the site and README), policy files,
 the approval queue and `steward.toml` appends are read and written inside the repository without following links;
 a refusal carries its reason, so an absent folder is absent evidence and a linked one is refused; `init --for` and
 `release setup` exit with an error on a linked `steward.toml`, before reading or writing anything.
- **Exchange** (AF13, AG4): a receiver's ledger counts only when its genesis names the exchange ledger and the
 receiver's repo_id; a malformed receiver configuration makes that peer unchecked.
- **Token reports** (AF14): by design they show numbers, model names and files relative to the repository; files
 outside it, log paths and session IDs are not shown (logs by number, sessions by a short hash), and a path or model
 name that holds a private term is withheld. Contents never leave the logs.
- **Also:** the open-development plan scans whole commit messages and changed paths (a merge against its first
 parent) and says it does not read file contents (AF16, AH3); README fences (AF17); `check --quiet` never hides delivery or upgrade advice (AF19); one changelog
 section per version, with its known issues (AF8).

### Changed
- `steward authorize prepare policy.change` takes the object R-33 checks when `--object` is left out and refuses a
 different one, showing both; `steward authorize sign` says whether a policy payload still matches R-33 before the
 key prompt.

### Known issues in 0.19.0
| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| U9 | Low | a response whose binding is malformed is still received (R-53 flags it; nothing is imported) | read R-53 after a pull |
| R3 | Low | `session close --end` takes a process with the lock file open as its holder | stop toolkit processes yourself when in doubt |
| R7 | Low | an inbox item received before 0.9.0 has no receipt hash and cannot gain one | R-54 lists them as unverified |
| AM1 | High | a requirements-file include hidden behind a byte-order mark, or after another option on the same line (`--find-links. -r x.in`), is read as no packages: R-80 can PASS on an empty inventory and a release notice can say `Dependencies: 0` | declare `uv.lock` or `poetry.lock` as `[licence] lockfile`, or a requirements file with one `name==version` per line and no includes |
| AM2 | Medium | `release publish --push` when the public branch already holds the release (only the tag is sent): a branch that advances with a newer release after the check does not stop the tag | publish releases only through steward, one at a time |
| AM3 | Medium | a public tag name that contains `refs/tags/` (e.g. `varchive/refs/tags/v0.1.0`) is ordered by its last part | do not create such tags in the public repository |
| AM4 | Low | the recovery command printed after a failed local record is not quoted for a staging path with spaces | quote the path when you run it |
| — | Low | `release publish --push`: a newer tag pushed to the public repository by someone else without moving its branch, after steward listed the tags, is not seen (the release branch itself cannot move: a non-fast-forward push is rejected) | publish releases only through steward |
| — | Low | token reports: no single regression covers every private marker with numbers in all three log formats (each is covered separately) | — |
| — | Low | the token report's "input" count includes cached reads; HTTPS and SSH peer URLs and live agent hooks are tested only with local fixtures | read the cache columns; check a URL peer once by hand |

### Upgrade notes (from 0.18.0)
- Leave out `--object` when preparing a policy change, or pass the exact `R-33.object` value.
- New rules R-79 – R-82 are NOT_APPLICABLE until `[licence]` is declared; R-82 is advisory. The default gate now names
 68 rules.
- `--summary` counts the areas that are not configured (`--all` still names them).

## 0.18.0 (2026-11-25): research records, briefs, charts, and a new face
Pre-release, not on PyPI. Per Muiz, 2026-11-24: "yes go on.. we need those fixed first..", for, 
and; and "I like your ideas.. add them all according to suggestions as well as my notes on them. Also do
the branding changes. Include all of them in 0.18".

### Added: research records and agentic tooling
- **Study records** (`[studies]`, **R-75**, `steward study new|list|show|fingerprint`): one file per study (a
 reanalysis, an experiment, a claim and its plan) with its inputs (accessions, retrieval dates, file fingerprints),
 references (genome build, annotation release, identifier namespace, database versions), tools, plan, results, the
 papers that cite it and the studies it builds on. R-75 fails a missing or changed file; makes every dependent study
 stale and names the papers citing them; lists the same input recorded by two studies; and, with `consistent`,
 reports studies that disagree on references.
- **Research-direction records** (`[research]`, **R-76** advisory, `steward research new|list`): literature reviews,
 novelty maps (nearest prior work, including the group's own), gap and flaw lists with decisions, and dead-end
 reviews (negative results, options with evidence, the decision). R-76 reports stale reviews (`stale_days`),
 contributions without their nearest work, and undecided gaps and dead ends. The **research-review** skill (a new
 `research` kit) says how to fill them; novelty stays the human's call.
- **Dispatch briefs** (`steward task brief TASK --for codex|gemini|claude|generic`, `steward task template`): a task
 file becomes a self-contained prompt with the repository state and the agent's conventions; it passes the term
 lists first. Five templates: review, reverification, literature-review, novelty-check, figure-check.
- **Runs compared and charted** (`steward diff runs [--label GLOB] [--svg FILE] [--metric duration|memory]`), and the
 project site's runs page draws the last 25 runs. New site pages: **studies** (study cards) and **research**.
- **Citation records** (optional per paper, `[paper.NAME] citations`, **R-77**, `steward paper citations NAME
 [--fetch]`): each DOI (Crossref) or PMID (PubMed) resolved once and its title recorded; R-77 fails a cited title
 that is not the recorded one. Checks never use the network.
- **Evaluating language models** (`[llm_eval]` in a benchmark contract, **R-78**): a study (group) in both tuning and
 test fails, as does a model judging itself; test cases public before a candidate's training cutoff, unknown cutoffs
 and prompts outside a `[[frozen]]` set are reported.

### Added: the new face
- The README, rebuilt: a hero diagram, an animated terminal demo, "what it catches", the two halves (agentic
 engineering, research and development), a lifecycle diagram, kits, collapsible commands, rules and roadmap.
- The user guide: a landing page with cards per audience, **Recipes** (tabs per job), **Works with** (skill
 libraries, workflow engines, data versioning), the research-records guide, light and dark themes, Mermaid diagrams.
- PyPI metadata: a one-line description, keywords, classifiers and project links, and a PyPI page (`docs/pypi.md`)
 whose images use absolute links.

### Added: adopter feedback
- **Superseded and withdrawn received items**: a received item that is still open can be closed as
 `steward exchange state ID superseded --by NEW-ID` (another received item from the same sender, with its receipt) or
 `withdrawn --note WHY`; `respond` takes both too. Its file may then be removed: R-53 accepts the missing file and
 any response to it, and the ledger keeps the receipt with the file's hash. `exchange status` lists such an item as
 "(file removed)".
- **Term lists before receiving**: `steward exchange receive` and `pull` check an incoming item against
 this project's own R-07 term lists and local-path check, for the path it would have in `inbox/`. On a hit the item
 is refused, the ledger is unchanged, and the lines are named (a private list's term never is). `--allow-terms` takes
 it anyway and records that in the receipt. In a pull, a refused item never stops the others.
- **The furthest observation**: `exchange status` shows, for this project's own items, the state furthest
 along the lifecycle that the receiver reported (a release notice's `shipped` beats a later response's `accepted`),
 and the latest one too when it differs (`observed_latest` in `--json`).
- **Pin callers by reference**: `[[pin]] references = [...]` names the folders or loader scripts that
 tell this pin's callers apart when versions share one import name; `callers = "module" | "references" | "both"`
 (default: references when set, else module); `ignore_callers = [globs]` for finished records kept as evidence
 (listed, not blocking). An unreadable file still blocks eligibility. `steward pins status` names the rule that found
 each caller.
- `steward check --help` names the machine-registry opt-out (`STEWARD_NO_REGISTRY=1`; `[storage.clean] registry =
 false`).
- `steward audit progress` lists, for each peer checked out on this machine, the items its committed outbox addresses
 here that are not received yet (found in the Progress Audit of 2026-11-24).

### Fixed (the final review, 72ed51c)
Review: development/assessment/2026-11-25-review-v0.18.0-72ed51c.md (task STW-005; AE1 – AE15, all fixed; then the
implementer's own review, per Muiz: "if errors, then do review yourself").
- **AE1, AE5:** study, research and citation records, cases files, plans and the runs ledger are read only inside the
 repository and never through a link at any component; the site's studies and research pages also refuse records in
 a sealed dataset.
- **AE2:** the site scans record values as written, before Markdown, HTML or SVG escaping can hide a protected term.
- **AE3:** R-78 never passes on unusable evidence: no test cases, no candidate model, cases without a group or ID, a
 case recorded twice with different splits or groups, dates with trailing text; duplicate rows count once.
- **AE4:** titles compare by their words in any script; an empty title never matches.
- **AE6:** a study's plan is fingerprinted (`plan_sha256`); a changed or missing plan makes its dependants and their
 papers stale.
- **AE7:** `study fingerprint --write` never writes into a comment, never overwrites a digest, checks every write by
 reading the record back, and says which digests it could not write (exit 65).
- **AE8:** records made from a template are drafts (`status = "draft"`, R-76.draft) until filled; the dead-end template
 holds no decision.
- **AE9:** R-77 checks the entries the manuscript cites, including a DOI or PubMed URL; a citation without a
 bibliography is reported.
- **AE10:** citation records are written with every control character escaped and read back before writing; a fetch
 that leaves an identifier unresolved exits 65.
- **AE11:** R-78 accepts the prompts only when their `[[frozen]]` set is recorded and intact (R-63's verdict).
- **AE12:** a brief is refused when its screen cannot run (invalid configuration, unusable term lists); line waivers
 never apply to it.
- **AE13:** `--output` and `--svg` never write through a link, and a brief never overwrites its own task file.
- **AE14:** every file R-75, R-77 and R-78 rely on is an input of the verdict's digest.
- **AE15:** the pages describe R-78 as exposure by date (a cutoff is the provider's statement) and R-76 as advisory
 for the default gate.

### Fixed (the 0.18.0 review, 02a6f80)
Review: development/assessment/2026-11-24-review-v0.18.0-02a6f80.md (task STW-001; AB1 – AB11). Re-verification:
development/assessment/2026-11-24-reverification-v0.18.0-6430a12.md (task STW-002; AB3, AB5, AB10, AB11 verified; the
rest completed in the second pass below).
- **AB1:** the caller scans take each file's kind from git's index and read it without following links: a tracked
 file replaced by a folder or a link, or reached through a linked folder, makes the evidence unavailable (never "no
 callers"); a submodule's gitlink is left out by its index mode.
- **AB2:** a pull screens a response before importing this project's own original from the peer's inbox, and the
 original at its outbox path: a refused item writes nothing.
- **AB3:** recovering the receipt of an item left in `inbox/` without a state passes the same screen.
- **AB4:** an item ID that matches a private term is withheld from the refusal.
- **AB5, AB6, AB9:** one criterion decides whether a received item's file may be gone: a hashed receipt; a history
 ending superseded or withdrawn (or closed right after); a superseded item's replacement received from the same
 sender. The command's advice, R-53, `exchange status`, a later receive and `state ID closed` after the removal all
 use it. Only received requests, defects, feedback and questions can be superseded or withdrawn.
- **AB7:** a response to a removed item must name, in its Answers binding, the bytes the receipt recorded.
- **AB8:** an item holding a NUL byte anywhere is refused, with or without a privacy policy (stricter than R-07,
 which skips such a file as binary and checks nothing).
- **AB10:** the audit lists a configured peer's waiting items even before anything is received from it.
- **AB11:** the pins guide and the upgrade note describe reference-only pins and `ignore_callers`.
- R-54 compares the ledger's UTC times with today's UTC date: in the hours when the local date was still a day behind
 UTC, every fresh receipt was reported as `R-54.future_date` (found by the test run of this fix pass).

### Fixed (the re-verification, 6430a12)
- **AC1:** a tracked link replaced by a regular file is scanned; a genuine link is still not followed. The module
 scan reads with universal newlines (CRLF and CR files are callers too).
- **AC2:** a FIFO or any other special entry in place of a caller is unavailable evidence, opened without blocking.
- **AC3:** a response left in `inbox/` without a receipt is screened before anything is imported for it.
- **AC4:** a chain of replacements stays valid as each is removed: a replacement that was itself removed by the same
 test counts.
- **AC5:** a response to the item without an Answers binding keeps its file (the command says so; R-53 agrees).
- **AC6:** `respond` uses the inbox state machine: a received response or release notice cannot be superseded or
 withdrawn, by either command.
- **AC7:** R-53 checks a response's binding in the file it parsed, so a renamed response is a `name_mismatch`.
- The partial verdicts: an ID matching any private term is withheld wherever its list applies (AB4); a receipt digest
 must be exactly 64 lowercase hex characters (AB6).

### Fixed (the second re-verification, 80fd6af)
Re-verification: development/assessment/2026-11-24-reverification-v0.18.0-80fd6af.md (task STW-003; AC1 verified).
- **AD1:** a pull refuses a NUL byte in a response or in the original it would import before anything is written,
 with or without `--allow-terms`.
- **AD2:** a peer code that matches a private term is withheld from every line a pull prints.
- **AD3:** the removal test gets the same evidence everywhere: only valid items named by their ID count as present.
- **AD4:** a chain of replacements is walked iteratively, so its length is unbounded; a cycle fails.

### Changed
- **Y10 dropped** (Muiz, 2026-11-24: "forget about the security and code of contact. I dont want it"): no private
 security or conduct contact is listed. Security reports go through GitHub's private vulnerability reporting (enabled
 with the public release); conduct reports go to the maintainer through GitHub.

### Known issues in 0.18.0
| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| U9 | Low | a response whose binding is malformed is still received (R-53 flags it; nothing is imported) | read R-53 after a pull |
| R3 | Low | `session close --end` takes a process with the lock file open as its holder (the system does not say which process holds a flock) | stop toolkit processes yourself when in doubt |
| R7 | Low | an inbox item received before 0.9.0 has no receipt hash and cannot gain one | R-54 lists them as unverified |

The JOSS draft's author list, affiliations and acknowledgements are left for the maintainer.

### Upgrade notes (from 0.17.0)
- `exchange receive` and `pull` now refuse an item that hits your R-07 term lists. If a pull reports one, ask the
 sender to re-file it, or take it with `--allow-terms` and then supersede it.
- `exchange status --json`: `observed` is now the furthest observation, not the last one; the last one is in
 `observed_latest` when it differs.
- Without `references` or `ignore_callers`, pins behave as in 0.17.0, except that a tracked file now a folder or a
 link counts as unreadable evidence.
- New rules R-75, R-77 and R-78 are NOT_APPLICABLE until `[studies]`, a paper's `citations` or a contract's
 `[llm_eval]` is declared; R-76 is advisory. The default gate now names 65 rules.

## 0.17.0 (2026-11-24): pinned-dependency retirement
Pre-release, not on PyPI. Per Muiz, 2026-11-24: "Yes.. also go for deprecated soon tag as well.. start 0.17", for
. Review: development/assessment/2026-11-24-review-v0.17.0-70599e1.md (Z1 – Z10; the five high findings and
the medium ones fixed in one pass).

### Fixed (the 0.17.0 review)
- **Z1:** a retirement plan refuses links and overlaps with git, the toolkit's records, the keep folder, another pin or
 a protected record; the kept files are written inside the held keep folder and read back.
- **Z2:** the plan is recorded (`retiring`) before anything is removed; an interruption shows in R-73 and
 `steward pins retire NAME --resume` finishes the same plan.
- **Z3:** the approval signs the whole plan (artifact path and bytes, every install path and file, the keep folder);
 R-33 must pass before a retirement.
- **Z4:** one pins command at a time; each path is removed through its held parent only while it is what the plan
 recorded.
- **Z5:** the pins ledger records the approval's nonce, so its use is not lost if the authorization ledger moves.
- **Z6, Z7:** callers always count; a missing `module` or unreadable evidence blocks eligibility; multi-name imports
 are found; a protecting pin needs an `after:` condition; `superseded_by` needs the newer pin's artifact present.
- **Z8:** restore needs a `check_command` and counts only when the commands pass (no check after a failed install);
 the artifact path is quoted.
- **Z9:** R-73 checks every pin retired in the ledger, also after its declaration is removed or its name reused.
- **Z10:** every removed entry (files, links, folders) is recorded; restore names what git can and cannot recover.

### Added
- **Pinned dependencies**: `[[pin]]` (package, version, artifact, its import `module`, the `install`
 paths, the records it `protects`, `retire_when` conditions, an optional `deprecated` stage, restore commands).
 States: active → **deprecated** (still installed, reported while imported) → retire-eligible (computed) → retired.
- **`steward pins status`** (each pin's state, why, and the object a retirement approval signs), **`steward pins
 retire NAME --authorization TAG`** (a single-use signed `pin.retire` approval for that pin, version and artifact;
 the artifact, a manifest and its checksum are kept in `pins/retired/<name>/` and verified before the install paths
 and the original artifact are removed; every removed path is recorded with its digest in `development/pins.jsonl`),
 and **`steward pins restore NAME`** (from the kept artifact; runs the pin's install and check commands; prints the
 `git checkout` for the removed version-specific code).
- **R-73 `pins.records`** (in the default gate): a pin's artifact is present and matches; a retired pin's kept
 artifact is present and unchanged; the records it protects exist. **R-74 `pins.retirement`** (advisory): deprecated
 pins still imported, and eligible pins.
- The recommended retirement policy in the `steward.toml` template, and the guide "Retire a pinned dependency".

### Fixed (the open known issues, before the tag; Muiz: "Try fixing those first")
- **Y5:** every action is pinned by commit and runs on Node 24 (`actions/setup-python` v6.3.0 in the Action;
 `actions/checkout` v5.1.0 and `actions/upload-artifact` v7.0.2 in the guide).
- **Y7:** the plugin installs the curated `plugin/` payload (the skills, the manifest and the licence), generated by
 `tools/build_plugin.py` and checked current by the tests.
- **X5, W9, V5:** a registration reads the registry through its held folder, creates that folder without a path-based
 `mkdir`, and treats a registry with any non-string entry as empty.
- **W4:** an unreadable sprint ledger is named in the audit. **V7:** the cleanup ledger's lock and chain are taken before
 anything is deleted. **V15:** any task state before the sprint's opened record is reported. **U5:** a received item
 is kept only for exactly its receipt. **U7:** a backtick opener whose info string holds a backtick is not a fence.
 **U15:** a lock in `--dist` is read only with no link below the folder. **R4:** a cache replaced meanwhile is left
 aside, never renamed back.

### Fixed (the follow-up review of these fixes, e974326)
Review: development/assessment/2026-11-24-review-v0.17.0-fixes-e974326.md (AA1 – AA9; the four high findings and the
medium ones fixed).
- **AA1:** `steward pins retire NAME --resume` needs the signed approval of the recorded plan (same object, same
 nonce) and R-33 to pass; a nonce the interrupted run had not recorded as used is recorded then.
- **AA2:** resume checks the kept artifact before removing anything more.
- **AA3, AA5:** a folder is moved aside under a name only its plan uses, checked there against the planned entries,
 then removed; a changed folder is left aside; an interrupted removal finishes from the aside folder. Unreadable
 trees and entries other than files, links and folders refuse the plan.
- **AA4:** overlaps are compared as normalized paths, and the keep folder never lands on another pin or a protected
 record.
- **AA6:** R-74 is UNKNOWN when callers cannot be told. **AA7:** restore calls a file recoverable only when git holds
 its removed bytes, and quotes the paths. **AA8:** an unreadable registry keeps cleanup's `shared` confirmation.
 **AA9:** the plugin build and its freshness check refuse links.

### Known issues in 0.17.0
| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| Y10 | Medium | the private security and conduct contacts are to be chosen by the maintainer before the public release | — |
| U9 | Low | a response whose binding is malformed is still received (R-53 flags it; nothing is imported) | read R-53 after a pull |
| R3 | Low | `session close --end` takes a process with the lock file open as its holder (the system does not say which process holds a flock) | stop toolkit processes yourself when in doubt |
| R7 | Low | an inbox item received before 0.9.0 has no receipt hash and cannot gain one | R-54 lists them as unverified |

The JOSS draft's author list, affiliations and acknowledgements are left for the maintainer.

### Upgrade notes (from 0.16.0)
- None required: without `[[pin]]`, R-73 and R-74 are NOT_APPLICABLE. The default gate now names 62 rules.

## 0.16.0 (2026-11-24): public-beta preparation
Pre-release, not on PyPI. Per Muiz, 2026-11-24 ("Yes", to starting the public-beta preparation). Nothing is published:
making the repository public, PyPI, Zenodo and marketplace listings remain the owner's D3 decision. Review:
development/assessment/2026-11-24-review-v0.16.0-32e774c.md (Y1 – Y14; the two high findings and the documentation
findings fixed).

### Fixed (the 0.16.0 review)
- **Y1:** the Action installs the toolkit from a runner folder, in isolated mode, into its own environment, with no
 expression in shell source.
- **Y2:** the report goes to a fresh runner folder outside the checkout (output `report`); no report input.
- **Y3:** `final` must be `true` or `false`; output writes fail the step; `eligible` is documented as absent on setup
 failure.
- **Y4, Y6, Y11:** the guide says what a pull request can change in the gate and how to make the policy binding, what
 the report and log contain and how to upload the report, and how the pre-commit hook is set up and when it blocks.
- **Y8:** the scrub check covers `CITATION.cff` and `pyproject.toml`; a test checks its inventory.
- **Y9:** the README, the principles and the paper say what is enforced (controlled operations, declared values,
 recorded runs, scanned contents), not more.
- **Y12, Y13, Y14:** the bug template's name; an `Unreleased` heading; the dev setup command; checkout-only tests skip
 in a source archive; the JOSS file is marked a draft with the current criteria.

### Added
- **Community files:** `CONTRIBUTING.md` (a failing test first; generic only; plain language; a response promise of
 7 days, 3 for security; how AI-written parts are declared), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1),
 `SECURITY.md` (private vulnerability reporting; what counts), issue templates (bug, with a false-PASS box; feature)
 and a pull-request template.
- **The principles page** (`docs/principles.md`): the rules every check keeps, for users who do not adopt the
 constitution.
- **A GitHub Action** (`action.yml`): installs the toolkit at the action's own version, runs
 `steward check --gate …` (`final` for submissions), writes the full report, and fails unless the gate is ELIGIBLE.
- **pre-commit hooks** (`.pre-commit-hooks.yaml`, id `steward-check`).
- **The Claude Code plugin and marketplace manifests** (`.claude-plugin/`): the skills as a plugin.
- **The tagline** in the README, and the guide "GitHub Action, pre-commit and the plugin".
- **A JOSS draft** (`paper/paper.md`, `paper/paper.bib`): summary and statement of need; the author list,
 affiliations and acknowledgements are left for the maintainer.

### Known issues in 0.16.0
| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| Y5 | Medium | the Action uses `actions/setup-python` at a moving major tag (Node runtime unverified on today's runners); a commit-SHA pin needs a hosted smoke test | pin the Action itself to a reviewed tag or SHA |
| Y7 | Medium | the plugin marketplace fetches the whole repository, internal development records included; a curated payload comes with the public release | use the plugin only inside adopting projects |
| Y10 | Medium | the private security and conduct contacts are to be confirmed by the maintainer before the public release; GitHub's private reporting is enabled then | — |

The known issues of 0.15.0 still apply (X5 and the partially verified notes, R3, R7). The Action's check step is run
locally by the tests; the Action, the pre-commit hook and the plugin have not yet had a live run on GitHub or in
Claude Code.

### Upgrade notes (from 0.15.0)
- None required.

## 0.15.0 (2026-11-24): the 0.14.0 known issues
Pre-release, not on PyPI. Per Muiz, 2026-11-24: "keep working on your next thing". Review:
development/assessment/2026-11-24-review-v0.15.0-0442dbd.md (X1 – X7; the two high findings and X3, X4, X6, X7 fixed).

### Fixed (the 0.15.0 review)
- **X1:** R-42 reports a declared lock the manifest could not hash (`R-42.lock_unavailable`), never a match.
- **X2:** `session close --end --dry-run` scans the text it prints exactly; hash-bound allowances apply only to it.
- **X3:** a cleanup plan from an older version is refused (write a new plan); no partial deletion is recorded for it.
- **X4:** the audit shows a section it could not gather as unavailable, never as empty, and rendering changes nothing.
- **X6:** an ID in indented code is an example, not delivered work.
- **X7:** one peer that cannot be resolved no longer hides the others from the shared-use check.

### Fixed (the known issues of 0.14.0)
- **W4:** the audit names a section it cannot gather and an unusable sprint, and survives malformed peer tables and
 mixed timestamps.
- **W8:** the timeline page takes its rows and its digest from one read of the milestones file.
- **W9:** the machine registry is written inside its folder, held without links (lock, temporary file, replacement).
- **The partially verified notes:** V5 (malformed peer tables), V7 (the cleanup ledger must be writable before any
 deletion; partial deletions are recorded by entries as well as bytes), V9 (one verified exchange read), V15 (task
 states need the sprint's opened record), U5 (only the intended ledger entry keeps a file), U7 (CommonMark fences),
 U9 (a malformed binding or a missing original imports nothing), U14 (the `--end` preview leaves hash-bound
 allowances to the final check), U15 (locks read only without any link), S9 (no fragments as remedies), R4 (the
 session cache stays held while it is moved; restored only into an empty name).

### Known issues in 0.15.0
| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| X5 | Medium | a registration reads the registry by path after locking its held folder, so a folder swapped meanwhile can mix two registries | keep the config home a plain folder |
| (notes) | — | partially verified: W4 (a sprint ledger read error drops the pending section), W9 (the folder is created before the guarded walk; links are resolved), V5, V7 (the append lock is not tried before deleting), V15 (a state before a later opened record), U5, U7 (opener info strings), U9, U15 (the dist fallback), R4 (restoration race) | see the review |
| R3 | Low | `session close --end` takes a process with the lock file open as its holder (the system does not say which process holds a flock) | stop toolkit processes yourself when in doubt |
| R7 | Low | an inbox item received before 0.9.0 has no receipt hash and cannot gain one | R-54 lists them as unverified |

### Upgrade notes (from 0.14.0)
- None required. Cleanup plans written by 0.13 or 0.14 lack an entry count; write a new plan before `--apply`.

## 0.14.0 (2026-11-24): the 0.13.0 known issues, the Progress Audit
Pre-release, not on PyPI. Per Muiz, 2026-11-24: "Yes fix and implement these." Review:
development/assessment/2026-11-24-review-v0.14.0-1ea76b2.md (W1 – W9; the three high findings and W5 – W7 fixed).

### Fixed (the 0.14.0 review)
- **W1:** the audit runs its gate checks with signature verification read-only (unavailable evidence, no writes).
- **W2:** another checkout's claims (version used, areas, notice states) are shown apart from this project's records,
 only from a verified ledger, and not at all when two checkouts claim one code.
- **W3:** every string of the audit passes the term lists and the local-path check; errors name their kind, never
 their text.
- **W5:** the project's own version is told from the toolkit's; one-way notices and this project's own open requests
 are counted.
- **W6:** the skill gathers its evidence without registering the checkout (`STEWARD_NO_REGISTRY=1`).
- **W7:** timeline titles on the documentation site are shown as text (Markdown and HTML punctuation escaped).

### Added
- **The Progress Audit:** say "Progress Audit" to an agent with the `progress-audit` skill (new `[manage]` bundle:
 `--kits core,manage`). `steward audit progress [--json]` gathers the evidence, read-only: where the project is, its
 use by other projects (filed items by kind and version, open items, days to ship, notice states, versions used and
 areas configured), pending work (items, signatures, milestones, sprints) and reach (what a new adopter finds or
 misses). The skill ranks improvements and offers a sprint with sign-ahead or sign-later advice.
- **The documentation site's timeline page** (opt-in `"timeline"`): milestone titles, kinds, due dates and outcomes.
- `steward init` registers the project in the machine registry (opt-out as for `check`).

### Fixed (the known issues of 0.13.0)
- **V5:** registry updates are serialised; a malformed registry reads as empty; shared use is also found through
 `[exchange]` peers, links one level down and project-relative cache settings.
- **V7:** a partly failed deletion is recorded with what it removed; the cleanup plan and ledger are written without
 links.
- **V9:** the timeline uses final checks for submissions, preprints and releases (or as a milestone says); a broken
 exchange ledger is unavailable evidence; R-70 counts only valid item files.
- **V14:** `sprint start --watch` waits for a future window and sleeps while nothing can start; without `--watch` it
 returns at once with the reason.
- **V15:** R-71 binds a sprint's ledger to its file and plan and checks each task's transitions; R-72 needs the current
 report and every declared done command recorded with exit 0.
- **The partially verified 0.12.0 notes:** U5 (every create-then-record path keeps a file whose state reached the
 ledger), U6 (a 0.12 chain of a linked original is restored), U7 (retries observe only after the receipt check; fences
 close with their own marker), U9 (legacy receipts need a verified peer chain; a bound response must name the
 original's bytes), U14 (`session close --end`), U15 (every recorded file; repository locks without links), S9 (the
 reference lists each code's remedy), R4 (the session cache is moved aside before removal).

### Known issues in 0.14.0
All are required tasks of the next release.

| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| W4 | Medium | a peer `[exchange]` table with wrongly typed fields or mixed timestamps can stop the audit; a sprint with an invalid plan is left out of "pending" silently | run `steward sprint check` on each sprint |
| W8 | Medium | the timeline page parses and hashes its source in separate reads | rebuild the site if the milestones file changed meanwhile |
| W9 | Medium | the registry writer's parent folder and temporary file are not guarded against links | keep the config home a plain folder |
| (notes) | — | partially verified: V5 (mixed-type registries; malformed peer tables), V7 (an unwritable ledger opened after deletion; zero-byte partial deletions), V9 (a second exchange read), V15 (state without an `opened` record), U5 (any later state counts as the append), U7 (fence length), U9 (malformed `Answers` during import), U14 (the preview scan), U15 (manifest lock reads), S9 (fragments of dynamic messages as remedies), R4 (the cache name window) | see the review |
| R3 | Low | `session close --end` takes a process with the lock file open as its holder (the system does not say which process holds a flock) | stop toolkit processes yourself when in doubt |
| R7 | Low | an inbox item received before 0.9.0 has no receipt hash and cannot gain one | R-54 lists them as unverified |

### Upgrade notes (from 0.13.0)
- None required. To use the Progress Audit, install the skill: `steward init --skills.agents/skills --kits core,manage`
 (it never overwrites existing files).

## 0.13.0 (2026-11-24): storage cleanup, milestones and the timeline, supervised sprints
Pre-release, not on PyPI. Per development/design/RELEASE_v0.13.0_SPEC.md, on Muiz's decisions of 2026-11-24 ("go for
0.13 after codex review and tagging 0.12"; "yes use the recommended answers"). Review:
development/assessment/2026-11-24-review-v0.13.0-1677b00.md (V1 – V15; the nine high findings and V8 fixed in one pass).

### Fixed (the 0.13.0 review)
- **V1 – V4, V6 (storage cleanup):** `--apply` deletes only what a fresh scan still finds as planned, and shows the
 real target; a folder whose contents changed is skipped; deletion reaches its parent without links and never crosses
 a nested mount; ledgers, registered artifacts, sealed data, frozen files and recorded run outputs anywhere beneath a
 location keep it; any home folder and anything overlapping a shared cache are kept; an active run's outputs or a
 broken run ledger keep a folder; when some of your own processes cannot be inspected, deletion needs `proceed`;
 other projects' use is read afresh. A broken cleanup ledger refuses before anything is deleted (part of V7).
- **V8:** a milestone whose tasks cannot be read is not ready; R-70 reports `R-70.no_board`.
- **V10 – V13 (sprints):** a sprint id is never a path, and the file's id must match; a reused worktree must be that
 task's own on its own branch; uncommitted work is never done, and done names the checked commit; one dispatcher per
 sprint, and work an ended dispatcher left is marked failed; acceptance checks stop with the sprint and the window,
 and nothing starts after a stop.

### Added
- **Project storage cleanup** (`steward storage scan`, `clean --plan`, `clean --apply`): this project's temporary
 storage on every disk (toolkit and Python caches, build and docs by-products, declared folders, link targets, and
 shared user caches listed only), with its volume, size and other users (other steward projects on this machine,
 open files, active runs). `--apply` checks each location again (identity, disk, git, records, sealed data, runs,
 open files), asks for each in a terminal (the word `shared` for a folder another project uses), deletes through
 held descriptors without following links, records each deletion in `development/storage-cleanup.jsonl`, and reports
 the space freed per disk. `[storage.clean] paths` and `registry`; the machine registry of steward projects
 (`<config home>/projects.toml`, opt-out).
- **Milestones and `steward timeline`:** `development/milestones.toml` (due time with its time zone, kind, gate,
 tasks, items, needed signatures, buffer); soonest first, days left, progress from the records, ready / on track /
 at risk / late, and the recorded outcome. R-70 `milestones.valid` (advisory).
- **Supervised sprints:** `development/sprints/<id>.toml` and its hash-chained ledger; `steward sprint plan` (from
 the board, the exchange or a milestone), `check`, `start [--watch]`, `go [--retry]`, `hold`, `skip`, `stop [--now]`,
 `status`, `report`, `signatures`; claude-code, codex and shell adapters; each task through `steward run` in its
 own worktree and branch; tasks start on order by default; a task is done only when its `done` commands pass; the
 branches wait for the human's merge; sign-ahead or sign-later advice for the signatures tasks need. R-71
 `sprint.valid` and R-72 `sprint.closed` (advisory).
- Guides: "Clean up a project's storage", "Plan to a deadline", "Run a supervised sprint"; the `using-steward`
 skill points to cleanup and to approvals while the human is away.

### Fixed (the known issues of 0.12.0)
- **U5:** exchange rollback never replaces an entry that appeared meanwhile; a failed write removes only its own file;
 an item whose receipt reached the ledger is kept.
- **U6:** chained hook removal restores the original in one rename; a foreign hook replaced with `--force` is never
 recorded as steward's; manifest records are typed; a chained link is bound by its target.
- **U7:** `announce` reads the changelog at the tag, ignores IDs in code blocks and lists only this release's items; a
 consumer records shipment only of items it sent to that sender, and a retry completes them.
- **U9:** `pull` imports an original only after the response and the whole original validate and the peer's ledger
 records receiving it.
- **U14:** every occurrence of a term is counted against its allowances; the handoff applies them as R-07 does.
- **U15:** `release manifest --output` never overwrites a recorded file or writes through a link; locks in `--dist`
 are read only inside it.
- **S9, S10, R4, R18:** remedies of helper-built codes; the core quick start from the installed wheel; owner locks
 released through a move-aside check; a bundle entry bound only with its record hash.

### Known issues in 0.13.0
All are required tasks of the next release.

| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| V5 | Medium | concurrent registrations can overwrite each other in the machine registry; `init` does not register; peers and nested links are not consulted for shared use | run `steward check` once in each project |
| V7 | Medium | a partially failed recursive deletion is not recorded; plan and ledger folders are not checked for links | check the folder after an error |
| V9 | Medium | the timeline evaluates gates without `--final` and reads the exchange ledger without checking it | run `steward check --final --gate submission` before a submission |
| V14 | Medium | `sprint start --watch` returns before a future window opens, and can poll quickly while a held task waits | start it inside the window |
| V15 | Medium | R-71 and R-72 do not bind the ledger to the sprint's plan or check its transitions; R-72 accepts an older report | regenerate the report after the sprint |
| (notes) | — | partially verified 0.12.0 fixes: U5 (announce and import roll back without the receipt check), U6 (a 0.12 chain with a linked original), U7 (retry order; mismatched fence markers), U9 (legacy receipts accept any state), U14 (`session close --end` handoff scope), U15 (other recorded files and repository locks), S9 (the generated reference lacks per-code remedies), R4 (session cache removal by name) | see the review |
| R3 | Low | `session close --end` takes a process with the lock file open as its holder | stop toolkit processes yourself when in doubt |
| R7 | Low | an inbox item received before 0.9.0 has no receipt hash and cannot gain one | R-54 lists them as unverified |

### Upgrade notes (from 0.12.0)
- None required. Storage cleanup, milestones and sprints are opt-in. `steward check` now adds this checkout to the
 machine registry; turn it off with `[storage.clean] registry = false` or `STEWARD_NO_REGISTRY=1`.
- The default gate is unchanged (61 rules); R-70 – R-72 are advisory.
- `exchange announce` reads the changelog as committed at the tag: commit the release section before tagging.

## 0.12.0 (2026-11-24): every known issue fixed, the adopters' requests, signing later
Pre-release, not on PyPI. Per development/design/RELEASE_v0.12.0_SPEC.md, on Muiz's decisions of 2026-11-24 ("lets
fix all the known issues, any requests/feeback from any of the consumers and then aim for 0.12 release today"; "yes
to all three, go ahead"). Review: development/assessment/2026-11-24-review-v0.12.0-1eb02cd.md (U1 – U17; the six high
findings and U8, U10, U12, U16, U17 fixed in one pass).

### Known issues in 0.12.0
All are required tasks of 0.13.0.

| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| U5 | Medium | exchange rollback restores a foreign entry by rename, which can replace one that appeared meanwhile; a ledger sync failure after a complete append can leave a receipt without its item | rare (needs a concurrent writer or a disk error); check `steward exchange status` after an error |
| U6 | Medium | a failed forced hook replacement, or a failed restore rename during removal, can leave a user hook removed or inactive; malformed manifest fields inside an object pass | if `hooks install --force` or `hooks remove` reports an error, check `.git/hooks` by hand |
| U7 | Medium | `announce` reads the working-tree changelog, counts IDs inside fenced code, and the consumer records shipment by item name alone; a retry after receipt skips missing observations | commit the changelog before announcing; keep item IDs out of code blocks in delivered sections |
| U9 | Medium | `pull` imports an original by the peer's own claims, before the response is validated | review an imported original before relying on it |
| U14 | Low | allowed occurrences after a refused one on the same line are not counted; the handoff check ignores occurrence allowances | — |
| U15 | Medium | `release manifest --output` follows a linked ancestor and can overwrite an input artifact; R-42 reads `--dist` locks without the same checks | write the manifest to a plain folder outside the artifacts |
| (notes) | — | partially verified: S9 (remedies of helper-built codes), S10 (no from-install walkthrough), R3 (an open file is taken as the lock holder), R4 (cache path reopened before removal; lock release by name), R7 (two state reads; an item with state but no receipt), R18 (`record_bound: true` with a null hash) | see the review |

U1 (design): while a policy change waits for its signature, R-33 is INCOMPLETE and the pre-commit hook (which blocks only
on FAIL) lets commits through; every gate that requires R-33 stays NOT ELIGIBLE. This is the approved behaviour of
signing later; the queue entry must now be this repository's, against the trusted baseline.

### Fixed (the known issues of 0.11.0 and 0.10.0)
- **T8:** a bare home directory (`/Users/name`, `C:\Users\name`) is a local path, in pages and everywhere else.
- **T9:** `[docs] dir` and `generated` are plain relative folder names, and `generated` is a folder inside `dir`;
 anything MkDocs cannot build is a configuration error.
- **T14:** an exchange page cites the item files too (pattern, count and one digest), so a body-only edit makes it stale.
- **S4:** `hooks install` is one recorded transaction (the manifest first, then the hooks, then the manifest again);
 a failure part way leaves every hook recorded and removable. An unreadable manifest is refused, never treated as
 empty. A stock 0.9.0 chained hook is adopted by `hooks install --chain`.
- **S5:** R-53 fails an exchange item that is not UTF-8 anywhere in the file, the body included.
- **S6:** the scrub check reports a failed or empty inventory and unreadable files, and finds adopter codes.
- **S7:** creating an exchange item leaves nothing behind when it fails.
- **S8:** the reference generator writes through a held directory and refuses links.
- **S9:** `steward explain` and the reference list codes built at run time, and give each code's own fix where the
 source has one.
- **S10:** each quick start states its expected gate, and the test runs it to that gate; the install line pins the
 version the pages describe.
- **The partially verified 0.9.0 notes:** R1 (an overlay never reshapes an invalid base gate), R3 (a process is stopped
 only when it holds its own ownership lock and its command line names steward; a failed stop is reported), R4 (bundle
 sidecars never through links; staged worktrees carry their owner), R5 (a chained original is restored only while it
 is the file that was chained; unrecorded hooks count only when byte-exact), R6 (rollback moves the entry aside
 first), R7 (an inbox file without a state gets its receipt), R10 (R-54 judges from one verified read), R12 (R-58
 tells absent from unreadable; only an Unreleased heading starts its section), R14 (R-63 tells an unborn repository
 from an unreadable HEAD), R17 (every power row is validated), R18 (RepoTags; legacy bundle entries), R20 (a job's
 group is signalled even when its tree cannot be listed; a supervision error still records an outcome).

### Fixed and added (requests and defects from the adopters)
- **:** `exchange announce` ships each received item the changelog names as delivered (it refuses
 undecided ones); the notice lists each consumer's shipped items and the consumer records them; R-53 reports an item
 deferred to a version a later release has passed (`R-53.deferred_stale`).
- **:** R-59 applies both the last tag and `[branches] since`.
- **:** R-57 reads a next ID before a full stop, and a status followed by a qualifier.
- **:** `session close` skips steward's ledger lock files.
- **:** the handoff is scanned with each term list's scope, as R-07 scans that path.
- **:** `[branches] release_tag_on = "merged-parent"`, in R-59 and pre-push.
- **:** a re-filed item may alias the merged item that names it.
- **:** `exchange pull` imports this project's own items that exist only in the peer's inbox.
- **:** `steward run` holds signals from before the run is recorded, so a signal during setup still
 records an interrupted outcome and exits 128 + N; an interrupted run never records exit code 0.
- **:** pre-push verifies `steward/auth/*` and anchor tags as signed records instead of gating their commit.
- **:** the `steward.toml` template shows `[[terms]]` (with `allow_occurrence`) and `[exchange]`.
- **:** a received item's `shipped` note must start with an existing release tag; `exchange init` writes
 the state tables, generated from the state machines.
- **:** a received response is noted (`acknowledged → noted`) with no decision clock; a response records the
 hash of the item it answers, and one that answers other bytes (an ID collision) is not recorded against the item.
- **:** `[[terms.allow_occurrence]]`: one accepted occurrence (path, term, context, count, file hash),
 narrower than a whole-file `allow`, in R-07 and the release audit.
- **:** `release manifest --output FILE`; a relative lock beside the artifacts is read from `--dist`.
- The R-33 fix hint names `--expires`.

### Fixed (the 0.12.0 review)
- **U1:** a queued approval counts only for this repository and the trusted baseline.
- **U2:** pre-push verifies a reserved tag by the object pushed, under its own name, against the pinned trust root.
- **U3:** `sign-pending` signs exactly the bytes it showed, reads the queue without links, and never signs another
 repository's payload.
- **U4:** exchange IDs (`responds_to`, shipped lists) are checked before any path is built from them.
- **U8, U10:** a malformed or foreign `## Answers` block is a mismatch; an alias needs a merge into the new ID, in
 this project's outbox.
- **U11:** the exchange documentation page never reads a linked or sealed record.
- **U12:** a signal after the job ended makes `steward run` exit 128 + N.
- **U13:** a job whose tree cannot be listed is still escalated to KILL; cleanup is incomplete when the process table
 cannot be read.
- **U16:** `mkdocs.yml` quotes the docs folder and the navigation paths.
- **U17:** a tracked record that looks like a lock file still counts in `session close`.
- R-67: a huge JSON integer in a power row is invalid, never an internal error.

### Added
- **Signing later:** `steward authorize pending` and `sign-pending` (with `--all-projects`); while the policy files
 are exactly a prepared `policy.change`, R-33 is INCOMPLETE `awaiting_signature`, not FAIL. Guide: "Sign ahead, or
 sign later".

### Upgrade notes (from 0.11.0)
- **Hooks installed by 0.9.0 with `--chain`:** run `steward hooks install --chain` once (it adopts the exact 0.9.0
 wrapper and records it); then `hooks remove` works as usual.
- **A chained hook's original** is now bound by hash: if you edit `pre-commit.local` after chaining, `hooks remove`
 leaves it in place and says so.
- **`[docs]`:** `generated` must be a folder inside `dir` with plain names (the defaults are).
- **Exchange:** `respond … shipped` needs a note starting with an existing tag (`v1.2.0: …`). Received responses can be
 moved to `noted`. To get the state tables, delete `exchange/README.md` and run `steward exchange init`.
- **Responses written by 0.12.0** carry a `## Answers` line in their body; older readers ignore it.
- **`session close`** ignores steward's lock files; a personal global git excludes file is not consulted (it can hide
 real records), so add project ignores to the repository's `.gitignore`.
- **R-42:** a release manifest written before 0.10.0 whose bundle entries have no record binding is reported as
 `R-42.bundle_record_stale`; run `steward release manifest` again.
- Upgrading from 0.10.0: follow the 0.11.0 upgrade notes as well.

## 0.11.0 (2026-11-24): a documentation site for each project
Pre-release, not on PyPI. Released on Muiz's decision after one fix pass of the review: "Go ahead and tag and push".
Per development/design/RELEASE_v0.11.0_SPEC.md. Review: development/assessment/2026-11-24-review-v0.11.0-4dd0531.md
(T1 – T14; the six high findings and T7, T10 – T13 fixed).

### Known issues in 0.11.0
All are required tasks of the next release, with the known issues of 0.10.0 below.

| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| T8 | Medium | the local-path check misses a bare home directory with no path after it (in pages and elsewhere) | review generated pages before publishing; keep home paths out of titles |
| T9 | Medium | `[docs] dir` and `generated` are checked only for escaping the repository; an equal, detached or YAML-significant setting gives a site MkDocs cannot build | keep the defaults, or a plain `generated` folder inside `dir` |
| T14 | Low | exchange pages cite the state ledger but not the item files, so a body-only edit does not make the page stale | — (bodies are never published) |

### Added
- **`steward docs init [--pages]` and `steward docs build`:** a MkDocs site for the adopting project, generated from
 its records (overview, benchmark contracts, runs, reported values, releases; decisions and exchange items opt-in,
 titles only). Each page names its records by path and hash; the same records give the same bytes; every page
 passes the term lists and the local-path check before anything is written. `--pages` adds a GitHub Pages workflow.
- **R-69 `docs.current`:** the generated pages exist, match the records, and hold nothing private.
- The guide page "Publish your project's documentation".

### Fixed (the 0.11.0 review)
- **T1:** a page whose source is gone is removed by `docs build` and reported by R-69.
- **T2:** an unusable term list refuses publication; it is never a clean scan.
- **T3:** the R-07 line waiver does not apply to the publication scan.
- **T4, T10:** the Pages workflow regenerates and compares the pages before a read-only build, and deploys from a
 separate job; the scaffold itself is scanned.
- **T5:** decision titles come only from dated entry headings outside code blocks.
- **T6:** sources are read only inside the project, never through links, and never when sealed.
- **T7, T12:** R-69 refuses a linked folder and compares bytes.
- **T11, T13:** an invalid run ledger or a generated contract is never published.

### Upgrade notes (from 0.10.0)
- None required. `steward docs` is opt-in: R-69 is NOT_APPLICABLE until `[docs]` is configured (`steward docs init`).
- Upgrading from 0.9.0: follow the 0.10.0 upgrade notes as well.

## 0.10.0 (2026-11-24): hardening and usability
Pre-release, not on PyPI. Released on Muiz's decision after one fix pass of the review, as for 0.9.0: "Go ahead and
tag and push". Per development/design/RELEASE_v0.10.0_SPEC.md. Review:
development/assessment/2026-11-24-review-v0.10.0-d04235b.md (S1 – S10; the three high findings fixed).

### Known issues in 0.10.0
All are required tasks of the next release. None is a known false pass of a configured rule except S5.

| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| S4 | Medium | hook installation changes the hooks before writing the manifest; a failed manifest write can leave a wrapper unrecorded | if `hooks install` reports an error, run `steward hooks remove`, then install again |
| S5 | Medium | R-53 reads exchange items with invalid bytes replaced, so a corrupt body under a valid header can pass | — (items are written by steward) |
| S6 | Medium | `tools/scrub_check.py` ignores a failed `git ls-files` and unreadable files | run it in a checkout whose index is readable |
| S7 | Medium | exchange creation can leave an item if tracking its directory fails after the write | remove the stray outbox item by hand |
| S8 | Medium | `tools/build_rule_reference.py` writes by pathname, through links | do not link `docs/reference` |
| S9 | Low | `explain` and the rule reference miss some interpolated result codes and give one fix per rule | — |
| S10 | Low | the quick-start test does not follow each quick start from install to an ELIGIBLE gate | — |
| R1, R3 – R7, R10, R12, R14, R17, R18, R20 | (notes) | the review rated these 0.9.0 fixes partially verified; its notes list remaining edge cases | see the review |

### Fixed (the 0.10.0 review)
- **S1:** run cleanup never raises or hides the outcome; process enumeration falls back to observed members, and an
 incomplete cleanup is recorded.
- **S2:** an unreadable trust pin is unavailable evidence (R-33 UNKNOWN, R-38 blocks, verification refuses), never a
 fall-back to the repository's own policy.
- **S3:** ownership locks are taken over only when regular, singly linked and this user's, and released or swept only
 while still the held inode.

### Fixed (the known issues of 0.9.0)
- **R3:** `session close --end` stops only a process that holds steward's ownership lock (`.steward/owners/`), with a
 matching identity and command line.
- **R4:** cache removal and bundle writes keep the checked directory descriptor through the change.
- **R5, Q7:** hooks are owned by a manifest of what steward wrote (`.steward-hooks.json`, by hash); every hook change
 goes through the checked hooks-directory descriptor.
- **R6:** exchange rollback works in the directory descriptor held since the item was created.
- **R20:** `steward run` marks its job with a token and signals only token-bearing or observed members of its group.
- **R1, R7, R10 – R12, R14, R16 – R18:** overlay rule ids and malformed gates; observations once, after an intact
 receipt; R-54 clocks from acknowledgement; redacted, budgeted session-end output; R-58, R-63 and R-66 git failures
 are UNKNOWN; the frozen writer needs a heading; whole upgrade transitions; R-67 table validation; image lists and
 per-archive tags; stale bundle records.
- **Found by fuzzing:** huge TOML integers, deeply nested JSON and non-UTF-8 exchange items no longer crash a rule.

### Added
- **`steward explain R-xx`:** what a rule checks, why, its result codes and fixes, and what a PASS does not mean.
- **A quiet summary:** not-applicable rules are folded onto one line that names each; `--summary --all` lists them.
- **The user guide** (`docs/`, MkDocs Material, `mkdocs.yml`): start page, quick starts, the worked example, guides
 for single- and multi-project governance, concepts, troubleshooting, and generated rule and command references
 (`tools/build_rule_reference.py`). Published on GitHub Pages when the repository is public.
- **Hardening:** the scenario suite (17 threats), seeded fuzzing of 23 parsed file types, property tests, performance
 budgets (`STEWARD_SLOW=1`), and the scrub check (`tools/scrub_check.py`).

### Upgrade notes (from 0.9.0)
- Installed hooks are recorded in `.git/hooks/.steward-hooks.json`; run `steward hooks install --force` once so an
 existing installation is recorded (a chained one: `steward hooks remove`, then `hooks install --chain`).
- `steward check --summary` folds not-applicable rules; scripts that counted those lines should use `--all`.

## 0.9.0 (2026-11-24): exchange step 2, release notices, session sign-off, the overlay, new checks
Pre-release, not on PyPI. Released on Muiz's decision after one fix pass of the re-verification: "Fix and move on to
0.10 after first fix pass.. but we need them to be fixed in 0.10". Per development/design/RELEASE_v0.9.0_SPEC.md.
Reviews: development/assessment/2026-11-23-review-v0.9.0-711db5d.md (Q1 – Q33, fixed) and
2026-11-24-reverification-f895128.md (R1 – R21; the false-pass and integrity ones fixed).

### Known issues in 0.9.0
All are required tasks of 0.10.0. Each is a gap in hardening, not a known false pass of a configured rule.

| ID | Severity | Issue | Until 0.10.0 |
|---|---|---|---|
| R3 | High | `session close --end` identifies steward's processes by pid, start time and command line, not by a recorded ownership token | run `--end` only in your own checkout; it never signals a process whose identity changed |
| R4 | High | session cleanup and bundle publication re-open checked folders by pathname | do not run them while another process rearranges the repository |
| R5 | High | a chained hook wrapper is recognised by its text | do not edit installed hooks by hand; `hooks remove` before changing them |
| R6 | High | exchange rollback keeps its identity map per path, with a short check-to-unlink interval | — (rollback happens only after a failed ledger write) |
| R20 | High | `steward run` has a short setup interval before its process group is watched, and the group identity is not re-verified | — |
| Q7 | (limit) | hook installation writes by pathname after checking each component | install hooks when nothing else is changing the repository |
| R1, R7, R10 – R12, R14, R16 – R18 | Medium | overlay edge cases, duplicate observations on retry, decision clocks after verification, session-close output, changelog and tag-read failures, frozen-record replacement order, power-table coverage, release-evidence normalisation | see the re-verification report |

### Fixed (the known issues of 0.8.1)
- **P1:** pre-push refuses a pushed tip without `steward.toml` when the invoking checkout's policy is pinned (an env
 trust root, a per-user pin for the checkout, or a pin for its repo_id), whatever `--unconfigured` says.
- **P2:** `steward ledger recover` runs every check of an append before its first write. It truncates through the
 checked descriptor and creates the quarantine file exclusively, in a directory reached without links.
- **P3:** ledger and lock opens never block (a FIFO is refused at once), and a multiply linked lock file is refused
 before it is locked.
- **P4:** hook installation checks every component of the hooks path for links, from the repository (or the
 filesystem root, for a path outside it) down.
- **P5:** a pushed tip whose paths collide on a case-insensitive or normalising volume is refused, on any volume; the
 `exchange/` link check ignores case; blob reads are bounded by bytes (64 MiB per read, 256 MiB per blob).
- **Spec §9 limit:** exchange writes and the exchange ledger walk from the repository by directory descriptor, so an
 ancestor replaced after the check cannot redirect a write.

### Fixed (requests received for 0.9.0)
- ** (high):** R-38 no longer passes when no base holds the decisions log: it checks the log's own history
 and the working tree (`R-38.append_only_history`).
- **:** template-format decision entries may wrap a field or nest a list under it.
- **:** a linked worktree's or submodule's `.git` file is never scanned.
- **:** R-07 checks local paths with term lists alone, as the release audit does.
- **:** `/home/` or `/Users/` inside a web URL is not a local path (a `file://` URL still is).
- ** (high):** a SIGINT, SIGTERM or SIGHUP to `steward run` now stops its job's process tree first,
 records the run as interrupted, releases the slot afterwards, and exits 128 + the signal.
- **:** pre-push refuses when its temporary worktree cannot be removed.
- ** – 027:** the requester's side of the exchange: pulled responses are observations of the receiver's
 state; outbox items may reach `shipped` or `adopted` from `filed`; a receiver's tag is stated, not looked up here.


- **Per-artifact release audit rules:** `[[release.artifact]]` with `match`, `forbid` and `require`,
 and `[release.checks]` with `expect` and `same_version`. New audit codes `forbidden_member`, `missing_member`,
 `missing_artifact` and `version_mismatch`, shared by `steward release audit` and R-42.
- **R-56 `boundary.imports`:** `[boundary]` packages, forbidden imports (AST: `import`, `from`, literal
 dynamic imports; a computed one is UNKNOWN) and forbidden distributions in `pyproject.toml` (dependencies, extras,
 dependency groups; `allow_groups` exempts e.g. `dev`).
- **R-57 `tasks.board`:** `[tasks]`: unique IDs across specs and archive, open specs on the board, a
 `Next unused ID:` above every ID in use, statuses from the task template.
- **R-58 `changelog.unreleased`, advisory:** files changed since the last release tag need a non-empty
 `Unreleased` section changed in the same range. The default gate does not require it; a named gate may.
- **R-59 `branches.model`:** `[branches]`: every first-parent commit of the release branch tagged,
 `--no-ff` merges into the integration branch since the last tag, branch names from `task_patterns`. Pre-push refuses
 an untagged tip of the release branch.
- **One canonical skills directory and R-60 `skills.copies`:** `init --skills A --skills B` writes one
 copy in A and a relative link at B (a `STEWARD_SKILLS` pointer file where links cannot be made), names A in the
 AGENTS block and in `[skills]`. R-60 reports drift, dangling links and missing copies.
- **Release bundles:** `steward release bundle NAME --paths … [--test-report CMD]` writes a
 byte-deterministic zip (sorted entries, fixed time, modes 0644 / 0755, fixed creator system and level) and a
 `NAME.bundle.json` record into `[release] bundles` (default `dist/bundles`). The manifest records every bundle;
 R-42 fails on `R-42.bundle_mismatch`.
- **Reproduction gate and R-52 `repro.current`:** contracts `steward.repro/0.1` (`[repro] contracts`),
 `steward repro manifest ID --from DIR` (reference hashes in the tool's canonical form: bytes, or sorted JSON without
 the volatile pointers), `steward repro check ID --work DIR` (exact, or per-pointer tolerances against the
 `reference` copies; one entry in `development/repro.jsonl`). R-52 needs a passing check on the current tree, with
 the current contract and manifest. The replay itself stays with `steward run`.
- **Exchange protocol, step 2:**
 - `steward exchange pull [PEER]`: items addressed here, read from each `[exchange] peers` repository's committed
 outbox (never its working tree; nothing written to it). An ineligible peer is refused with its reason and the
 one-way command. Each received item records the peer, its commit and the file's hash. A changed item is never
 replaced.
 - `steward exchange respond ID STATE --note …`: a response item and the state change, recorded together.
 - **R-54 `exchange.inbox`:** an inbox item edited after it was received fails; an acknowledged item without a
 decision after `[exchange] ack_days` is INCOMPLETE.
 - R-53 checks this project's outbox, one-way and response items against its public term lists.
- **Session sign-off and resumption (section G; DESIGN_session_handoff, approved S1 – S5):**
 - `steward session close --decisions-logged --next … [--question …] [--agreement …] [--read-first …]`: refuses
 with uncommitted process records (unless `--allow-dirty`), lists open findings and exchange items by ID, and
 writes one `HANDOFF.md` (`[session] handoff`) within `[session] budget_words` (default 600, at most 1 500) after
 the R-07 term lists and the local-path check. It copies no record and reads no transcript.
 - `--end` also stops the toolkit's own processes for this repository (unfinished `steward run` supervisors, the
 MCP server via its new `.steward/mcp.pid`), removes leftover staged pre-push worktrees and `.steward/cache/`, and
 prints `[session] end_hint`: Bio-STEWARD cannot end or delete the agent session or its transcript.
 - `steward session start` prints the constitution version and the handoff, nothing else.
 - **R-55 `session.handoff`, advisory:** present, its seven headings, within budget, no private text, committed,
 and not older than the last decisions-log commit.
- **R-61 `files.conflict_markers`, on by default:** unresolved merge-conflict markers FAIL (also at
 pre-commit); `steward: allow conflict-markers` exempts a file.
- **Several decisions logs:** `[integrity] decisions` takes a list or globs; R-38 checks each log.
- **Changelog entry fields:** `[changelog] entry_pattern` and `ready`; R-58 `entry_malformed`, and
 `not_ready` under `--final`.
- **Declared shipped secrets:** `[[release.shipped_secret]]` with a decision: reported
 (`R-42.shipped_secret`), not refused.
- **Attribution ledger and R-62 `agents.ledger`:** `steward agents attempt|score`; self-scores, scores
 of unknown attempts and overrides without a reason are refused and FAIL.
- **Dataset roles per consumer:** `consumers = { study = "role" }`, a `reserved` role, and
 `steward integrity access DATASET --consumer X --use develop|confirm|metadata` (allow or deny, with the reason).
- **Staged runs and R-68 `stages.records`:** `[[stages]]` (`reads`, `go`) and `[accrual]`;
 `steward stage run NAME -- CMD` refuses an outcome stage without its GO and the accrual stage below its minimum.
- **Run supervision:** `steward run --hang-cpu S` (no CPU progress, not log silence),
 `--socket-timeout S` (passed as `STEWARD_SOCKET_TIMEOUT`), and `steward shards plan` (longest-first balanced
 shards with a merge step).
- **Power planning and R-67 `benchmark.power`:** `steward benchmark power CONTRACT --effects FILE`
 (sign-flip or bootstrap, seeded) writes a power table; a contract's `minimum_units` below its `power_target` at a
 declared shrink is INCOMPLETE.
- **Frozen sets and R-63 `frozen.sets`:** `[[frozen]]` file sets (agent prompts, tool definitions,
 configuration, golden fixtures); `steward frozen record NAME` (a new version needs `--decision`).
- **Dependency upgrade parity and R-66 `dependencies.parity`:** a pin changed since the last release
 tag needs a complete `steward.upgrade/0.1` record; the procedure is the new core skill `dependency-upgrade`.
- **Container build contexts and R-64 `containers.context`:** per context and its `.dockerignore`,
 links leaving the context or into `dev_only` paths, secret-like files and large unignored folders FAIL.
- **Image bundles:** `steward release manifest --image TAG=DIGEST[@PLATFORM] --archives DIR`, and
 `steward release verify DIR` (changed, missing and extra archives and image tags).
- **Compose parity and R-65 `containers.compose`:** declared keys per service, user data on named
 volumes, shipped paths not dockerignored. Needs the new `[containers]` extra (PyYAML); UNKNOWN without it.
- **Skills `container-release` and `dependency-upgrade` (012):** the two procedures; the core bundle's
 description budget is 325 words (Muiz's decision).
- **Configuration overlay (B9), additions only:** `steward.local.toml`, or the file named by
 `STEWARD_CONFIG_OVERLAY`, may add gates, add rules to a gate (an overlay `default` gate keeps every default rule),
 raise `min_evaluated`, set `records_required = true` and add record globs. Any other key fails R-01
 (`R-01.overlay_refused`); never `[policy]`, trust settings or term lists. R-01 and R-33 report its hash.
- **Hook chaining:** `steward hooks install --chain` keeps an existing hook (also a symlink) as
 `NAME.local` and runs it before steward's; `steward hooks remove` restores it.
- **`[branches] protected`:** branch protection for the hooks without declaring `[release]`.
- **`[policy] state = "pending"` ** for a decided policy whose trust root is not set up yet.
- **docs/ci.md:** CI install from a private repository, a workflow, the approval key and the CI trust
 root.
- **Release notices:** item kind `release` (`CODE-REL-NNN`) with `version`, `tag`, `previous` and `breaking`;
 `[exchange] consumers` and `steward exchange announce vX.Y.Z` (one notice per consumer, with the CHANGELOG section;
 refused without its "Upgrade notes" or its tag; a consumer that is not a peer gets a one-way notice to export). The
 consumer acknowledges, then adopts (with a parity note) or declines. R-53 adds `R-53.upgrade_available`, never
 blocking, until then; `[exchange] uses` names the version a consumer uses.

### Upgrade notes (from 0.8.1)
- **Shipped secrets need a signed `waive` authorization** (constitution Article II.3): add
 `authorization = "steward/auth/<nonce>"` to each `[[release.shipped_secret]]`, with `[policy]` and a pinned trust
 root. Without it the member stays refused.
- R-61 is on by default: a committed conflict marker now FAILs the default gate.
- **Constitution 2:** read `steward constitution --changes`, then set `constitution = "2"` under `[steward]`. Until
 then R-51 reports `R-51.version_differs` (INCOMPLETE).
- `steward exchange new` skips IDs that a configured peer's committed ledger has recorded for this project's code.
- A pinned checkout now refuses to push a branch without `steward.toml`. Push such a branch from an unpinned checkout,
 or add a `steward.toml` to it.
- A blob over 256 MiB in a pushed tip refuses the push.
- Eight new rules (R-52, R-54 – R-60) and seven new areas; each is NOT_APPLICABLE until its table is added. A gate that lists
 rules explicitly is unchanged. The default gate requires R-52, R-54, R-56, R-57, R-59 and R-60 once configured, not R-55 or R-58.
- R-53 now fails when an item this project sends contains a term from a public term list.
- R-07 now checks local home paths when only `[[terms]]` lists are configured; set `[privacy] local_paths = false` to
 keep the 0.8.1 behaviour.
- R-38 may now FAIL where it passed: a rewritten decisions log is found even when no base holds the log.
- R-42 no longer fails on missing `LICENSE`, `README.md` or citation problems before a distribution is built;
 `steward check --final` and a built `dist/` still fail them.
- `steward run` stopped by a signal exits 130 / 143 / 129 and records `interrupted` (was: exited at once and left the
 job running).
- `steward exchange pull` also reads a peer's `responses/`; `steward exchange status` shows the receiver's last
 observed state.

## 0.8.1 (2026-11-23): adopter requests, one constitution, the exchange protocol
Pre-release, not on PyPI. Released on Muiz's decision with the known issues below, all planned for 0.9.0: "Push the
unresolved issues to the next release.. lets tag and release 0.8.1 after this".

### Known issues in 0.8.1
From the last re-verification (development/assessment/2026-11-23-reverification-a544ae3.md):

| ID | Severity | Issue | Until 0.9.0 |
|---|---|---|---|
| P1 | High | A pushed tip without `steward.toml` skips the pre-push gate, even from a pinned checkout | install the hooks with `steward hooks install --force --unconfigured refuse`; remote branch protection stays the enforcement point |
| P2 | High | `steward ledger recover` writes the quarantine file and the truncated ledger by pathname, before the link checks of an append | run it only on a ledger that is a regular file; check with `ls -l` first |
| P3 | Medium | A ledger replaced by a FIFO can block an append before it is refused; a hard-linked lock file shares its lock | keep `exchange/` and the ledgers as plain committed files; R-53 fails on links |
| P4 | Medium | Hook installation checks the hooks directory and its parent for links, not higher ancestors | install hooks only into a real directory; `--dry-run` shows the path |
| P5 | Medium | On a case-insensitive filesystem, two files in a pushed tip whose names differ only in case collapse into one when staged; large blobs are read whole | avoid case-only name differences; CI on a case-sensitive filesystem stays the check |
| (spec §9) | — | A directory replaced concurrently between the exchange guard's check and the open could redirect a write; this needs `openat`, and is a same-user concurrent-process limit | — |

Per development/design/RELEASE_v0.8.1_SPEC.md and DESIGN_exchange_protocol.md. It includes 0.8.0, which was
finalized but not tagged.
- **The constitution** (CONSTITUTION.md, version 1):
 - one governing document for the toolkit and every project that declares it (`constitution = "1"`);
 - `steward constitution [--version | --changes]`;
 - R-51 `governance.constitution`;
 - `init` declares it, and the agents block names it.
- **The exchange protocol, step 1:**
 - a fixed `exchange/` folder (outbox, inbox, responses, oneway) with a hash-chained state ledger;
 - the `steward.exchange/1` item format, with IDs `CODE-KIND-NNN`, never reused;
 - one state machine, and the default one-way protocol for projects without Bio-STEWARD;
 - `steward exchange init / new / state / receive / status / export`;
 - R-53 `exchange.items`.
- **Defects from adopters:**
 - git hooks work from linked worktrees, and gain `--dry-run` and `--protect`;
 - pre-commit blocks only on its gate's FAIL, and is quiet otherwise;
 - pre-push checks each pushed commit in a detached worktree, refuses deleting a protected branch, and skips
 unconfigured commits with a notice;
 - `init` names the main repository, takes `--project`, and writes templates by profile;
 - R-42 never passes with nothing built;
 - the gate line counts what it rests on, and `min_evaluated` sets a minimum;
 - the summary has a "Configured: N of M areas" line;
 - the `using-steward` rule catalogue is generated from the rules;
 - an invalid configuration blocks every gate.
- **Privacy:**
 - named `[[terms]]` lists, public or private, each with a scope, `allow` globs, case sensitivity and regex
 patterns;
 - `substr:` terms, and term labels as `list:line`;
 - the inline marker `steward: allow R-07`;
 - local home-path detection in R-07 and in the release audit;
 - binary assets excluded by default, and not-evaluated files counted by extension;
 - one audit function for R-42 and `steward release audit`.
- **Trust model:**
 - `authorize pin` stores the baseline commit, and `prepare` uses the trusted baseline;
 - R-33 reports a moving baseline, and FAILs when `[policy]` is removed while a trust root is pinned;
 - public term lists are part of the policy bundle;
 - `STEWARD_TRUST_SIGNERS` accepts the signer line, and the README has a CI recipe.
 - **Migration: re-run `steward authorize pin`** after upgrading.
- **Runs:**
 - shared slot directories (`[run] slots_dir`, `STEWARD_SLOTS_DIR`) and `--wait-timeout`;
 - the slot scope is recorded without a local path;
 - run records write the home directory as `~`.
- **Release:** `manifest --identity KEY=VALUE` with `[release] identities`, and `manifest --dist DIR`.
- **Records:**
 - `[paths] records` (the root of every default record path) and `records_required`;
 - the decisions-log entry format (opt-in) and the append-only check without a signing policy;
 - finding classes, the `no-blocking-no-wrong-result` stopping rule with known issues, and `accepted_on_tests`.
- **Templates and skills:**
 - the task template gains ID, branch, dependencies, owner, approver, work log and follow-ups, with the close-out
 rule;
 - new `HANDOFF.md` and `parity.md` templates;
 - patch-mode delegation and adoption companions;
 - README: installing before PyPI.
- **The pre-release review** (development/assessment/2026-11-23-review-v0.8.1-a615ec5.md) found N1 – N4 high,
 N5 – N10 and N12 medium, and N11 and N13 low. All were fixed before the tag, each with a regression test:
 - the pre-push hook no longer checks out the pushed tree (no checkout hook, no filter);
 - hook scripts hold no configured values in shell text;
 - a `repo_id` edit cannot detach the pin, and R-33 joins every gate while a trust root is pinned;
 - exchange writes never follow links out of the repository.
 - Pre-push checks each pushed ref's **tip**; intermediate commits are not checked.
### Upgrade notes (from 0.7.0)
1. Pin the new tag in your development requirements: `bio-steward @ git+…@v0.8.1`, or
 `uv tool install …@v0.8.1`.
2. **Re-pin the trust root:** run `steward authorize pin`. Old pins stored a branch name; 0.8.1 stores the commit
 and the checkout. Until you re-pin, R-33 reports `R-33.baseline_moving`.
3. **Reinstall the hooks:** `steward hooks install --force [--gate NAME]`. The scripts now only call steward. Remove
 any local pre-push adaptation first.
4. **Declare the constitution:** add `constitution = "1"` under `[steward]` (R-51 recommends it until you do), and
 read it with `steward constitution`.
5. **Term lists:** `[privacy] denylist_file` keeps working as the private list `denylist`. Reports now name terms as
 `list:line` instead of `#k`.
6. **Expect these new results:**
 - local home paths in committed files are now found (R-07 `local_path`). Rewrite them, or mark example lines with
 `steward: allow R-07`;
 - R-42 with nothing built is NOT_APPLICABLE (INCOMPLETE with `--final`).
7. **Templates:** `init` writes the contract and prior-work templates only for a confirmatory profile, or with
 `--templates`.
8. **Requests to the toolkit** now go to your own `exchange/outbox/` (`steward exchange init`, then `new`), with a
 one-line notice. Never write into another repository.

- **Deferred with notes to 0.9.0 (there is no 0.8.2):** SR-002, SR-008, AR-05, the AR-07 rule, AR-08, AR-09, AR-14, AR-15, exchange
 step 2, and the SR-006 overlay.

## 0.8.0 (2026-11-23, finalized, not tagged; released within 0.8.1): storage and an optional MCP server
Pre-release, not on PyPI. Per development/design/RELEASE_v0.8_SPEC.md.

The pre-release review (Codex, at 29ec92a) found one high issue (K1), six medium (K2–K7) and five low (K8–K12).
All are fixed before the release, each with a regression test written first, and are pending re-verification. The
review verified J1–J3, J5, J6, J8, J10 and J11 from 0.7.0.
- **K1 (high) and K3:** every git call goes through one helper (`fsutil.git_run`). It:
 - drops inherited `GIT_*` variables and system and user configuration (except for signing);
 - passes `--no-optional-locks`, so git never rewrites the index;
 - overrides the settings a repository could use to run a program (`core.fsmonitor`, `core.hooksPath`,
 `core.sshCommand`, `diff.external`, `credential.helper`, the pager);
 - forbids every transport (`protocol.allow=never`, `GIT_NO_LAZY_FETCH`), so a partial clone never fetches.
 - The MCP server no longer offers `authorize_list`: signature verification writes temporary files.
- **L1 (high), found by the re-verification of the K1 fix:**
 - `git status` could run a clean filter selected by the repository's `.gitattributes` and configuration. This was
 reproduced in a test;
 - no check runs `git status` any more. The report envelope records the commit, with `dirty: "not checked"` (the
 envelope is informational, never part of a verdict);
 - committed files are read with `git cat-file blob`, which applies no textconv or filters.
- **M1–M3** (re-verification of e7a6344, which verified K1 and L1; no high or critical finding remains):
 - over MCP, a refused signature verification is UNKNOWN (`*.verification_unavailable`), never a failed
 authorization;
 - a failed `git diff` is unknown review coverage, not coverage;
 - the protocol allow-list is empty (`GIT_ALLOW_PROTOCOL=""`), so no custom helper is permitted.
- **L2:** the MCP server never verifies signatures, because verification writes temporary files. Rules that need a
 signature report UNKNOWN there ("run `steward check` in a terminal").
- **L3:** no transport on any git version, whatever the repository configures: every protocol is denied by name
 (`protocol.<name>.allow=never`), and `GIT_ALLOW_PROTOCOL` names no real protocol.
- **K2:**
 - the artifact registry, DVC pointers and Git-listed files must resolve inside the repository;
 - MCP `runs` checks the ledger path, and returns only run IDs, labels, contracts, times, statuses and output
 hashes. It returns no commands or parameters.
- **K4:**
 - the DVC parser reads only `outs:` entries, without comments;
 - the pointer's hash is part of the verdict's inputs;
 - SHA-256, MD5 and size come from one read, and a file that changes while it is read is INCOMPLETE.
- **K5:** registry strings are TOML-escaped (newlines and control characters included), and the registry is written
 atomically after a read-back check.
- **K6:** MCP frames are limited to 1 MiB and must be UTF-8. An oversized, undecodable or too-deeply-nested frame
 gets an error reply, and the session continues.
- **K7:** R-43 counts module-level bindings inside `if` / `try` / `for` / `with` blocks, and treats a rebound
 `object` as unresolvable.
- **K8:** a dropped annex object is INCOMPLETE under `--final`, with its retrieval note.
- **K9:** a contract with no required split fails R-47 (`R-47.no_required_splits`).
- **K10:** read errors on split, metadata and results files name the file.
- **K11:** MCP checks argument types exactly. Request IDs must be strings or integers, arguments must be an object,
 an unknown rule is an error, and tolerances accept what the CLI accepts.
- **K12:** `steward storage audit` does not read the artifact registry.
- **R-50 `storage.artifacts`:**
 - large files kept out of git are registered (`development/artifacts.toml`, schema `steward.artifacts/0.1`) with
 SHA-256, size, a retrieval note and the tool;
 - a present file that differs is FAIL;
 - a DVC pointer (`PATH.dvc`) whose MD5 differs is FAIL;
 - a git-annex symlink's key is read without the content, and a key that differs is FAIL;
 - an absent artifact is named with its retrieval note, and is INCOMPLETE only with `--final`;
 - an entry without a retrieval note is INCOMPLETE;
 - a git-tracked file above `[storage] large_mb` that is not registered is INCOMPLETE;
 - artifacts are hashed by streaming, never held in memory.
- **`steward storage record PATH --retrieval TEXT [--tool dvc|datalad|manual]`**, **`verify`** and **`audit`**. The
 audit is read-only: it reports directory sizes against `[storage.caps]` and the largest untracked files. It never
 deletes, and no rule gates on it.
- **`steward mcp`:** an optional MCP server over stdio.
 - standard library only;
 - it implements the JSON-RPC subset: `initialize`, `notifications/initialized`, `ping`, `tools/list` and
 `tools/call`;
 - it has twelve read-only tools, each running the CLI's own command, so its results equal the CLI's;
 - no tool signs, prepares, approves, freezes, seals, unseals, waives, spends, runs a command or writes a file, and a
 test enumerates the surface;
 - path arguments must resolve inside the repository.
- **Skills:** `using-steward` names the later rules, `storage` and `mcp`. `change-impact` mentions R-50.

## 0.7.0 (2026-11-23): benchmark checks
Pre-release, not on PyPI. An independent pre-release review (Codex, at c2019ad) found no high or critical issue.
Its eleven findings (J1–J11) are fixed below, and I2 and I1 are fixed again through J1 and J7. These fixes are
pending the next re-verification; I3 is verified.
Per development/design/RELEASE_v0.7_SPEC.md. Reports say a benchmark is *checked for declared-rule violations*,
never that it is fair or leakage-free.
- **R-45 `benchmark.splits`:**
 - sample IDs repeated within a split or shared across splits;
 - with `[splits] metadata` (a CSV, one row per sample), groups shared across splits;
 - with `temporal = true`, train after dev / validation, or either after test;
 - unparseable times, and samples absent from the metadata, are INCOMPLETE.
- **R-46 `benchmark.datasets`:** a dataset whose `source` is a repository file must match its `sha256`.
- **R-47 `benchmark.results`:**
 - a results matrix `{split: {method: {metric: number}}}`, complete for every metric, method (the baselines and
 `candidate`) and required split;
 - values read exactly;
 - thresholds evaluated exactly and reported, never gating.
- **R-48 `benchmark.comparison`:** `[comparison] output` must come from a finished run whose recorded inputs include
 every split file with its current hash. For a confirmatory contract, the seed and resamples must be recorded.
- **R-49 `benchmark.leakage`:**
 - each of the seven undetectable leakage types is declared, as `checked` with evidence, or `not_applicable` with a
 reason;
 - undeclared types are UNKNOWN for confirmatory contracts (or with `[benchmark] require_leakage = true`), and
 advisory otherwise;
 - an unknown type key fails.
- **Commands:**
 - `steward check benchmark`;
 - `steward benchmark splits CONTRACT` and `steward benchmark results CONTRACT`.
- **Fixes for the pre-release review** (development/assessment/2026-11-23-review-v0.7-c2019ad.md: no high finding;
 J1–J11 fixed before release, each with a regression test written first; pending re-verification):
 - **J1:** split files and metadata are read once, through the check's snapshot, for the decision and the digest;
 - **J2:** metadata with duplicate columns, duplicate sample rows or short rows is FAIL (`R-45.metadata_invalid`).
 A blank group cell is INCOMPLETE (`R-45.blank_group`);
 - **J3:**
 - times are exact (numbers as decimals; dates as aware date-times), and NaN or infinite values are unparsed;
 - `temporal = true` without a `time_key` is INCOMPLETE;
 - digits-only times are numbers. Write dates as `YYYY-MM-DD`;
 - **J4:**
 - `[results] splits` cannot be empty;
 - a baseline may not be named `candidate`;
 - repeated JSON keys in a results file are refused;
 - **J5:** non-finite cells fail, and TOML `nan` is a failure, not an internal error. Thresholds use the literal
 written in the contract, and an unevaluable threshold is reported without changing the verdict;
 - **J6:**
 - `steward run` records each declared output's state before the command (`outputs_before`), and R-48 credits only
 a run that wrote the output (absent before, or bytes or modification time changed);
 - a run labelled for another contract does not count;
 - the best qualifying run decides;
 - a missing split file is INCOMPLETE;
 - **J7:** R-43 refuses a base class bound more than once in the module;
 - **J8:** leakage sentinels belong to R-49, so an advisory `unknown` no longer blocks through R-02;
 - **J9:**
 - missing and unreadable split files are named;
 - `steward benchmark splits` reports time ranges;
 - `steward benchmark results` shows the cell values and exits 65 on a malformed file;
 - **J10:** every benchmark path (split files, metadata, dataset sources, results, comparison output, leakage evidence)
 must resolve inside the repository;
 - **J11:** the freezing companion binds every split file and the metadata, and its preparation example includes
 `--expires`.
- **Contract additions:** additive and optional (`steward.contract/0.1` stays valid). The template documents them.
- **The `benchmark-contract` skill:**
 - it covers the new fields;
 - its leakage walk-through and its freezing steps move to companion files (`leakage.md`, `freezing.md`), loaded
 only when needed;
 - the skill body stays within its word cap.
- **The worked example:**
 - declares its sample metadata (donor overlap is now checked) and its leakage table;
 - it has no trained model, so it declares no results. Results and comparison provenance are shown in the tests,
 not in invented example numbers.

## 0.6.3 (2026-11-23): fixes for the 0.6.2 known issues
Pre-release, not on PyPI. Fixes H1–H7 (the 0.6.2 known issues) and I1–I3 (found by the re-verification of the H
fixes, which found no high or critical issue). H3, H4, H5 and H7 are verified by Codex. H1, H2, H6 and I1–I3 were
fixed after that review, each with a regression test, and are pending the next re-verification.
Each fix has a regression test written first and seen failing.
- **H1:** R-43 refuses a test in a `Test*` class with `__init__` or `__new__` (pytest does not collect it); nested
 `Test*` classes are accepted.
- **H2:** R-40 reads each claim source once per check and decides every claim, direct or through the registry,
 from that one snapshot.
- **H3:** a derived registry value needs provenance for every source behind it: a listed run must have recorded
 each one with its current hash (`R-40.not_from_runs` otherwise).
- **H4:** an out-of-range number is never evidence, even when two tokens are identical; a difference beyond the
 decimal range is `out of range`, not an internal error; out-of-range TOML registry values, claim values and claim
 tolerances report `R-40.out_of_range`.
 - **Verdict precedence (documented):** a difference found makes `diff run` *not repeatable* (exit 1), even when other
 values are not comparable or out of range. *Incomplete* (exit 2) is reported only when no difference is found.
- **H5:** display-lock digests must be SHA-256 (64 lowercase hex characters); others are
 `R-11.lock_entry_invalid` and earn no coverage.
- **H6:** an infinite claim tolerance is `R-40.invalid_tolerance`; NaN fails claim-map validation.
- **H7:** runs with no recorded metrics show precision `none`, not `binary64`.

**Fixes for the re-verification of b4190ac** (development/assessment/2026-11-23-reverification-b4190ac.md: H3, H4,
H5 and H7 verified; no high finding), each with a regression test written first. These were fixed after that
review and are pending the next re-verification:
- **I1:** R-43 finds constructors inherited from base classes in the same file. A base class imported from
 another module cannot be inspected, so a reference through it is refused (a possible false refusal, never a false
 pass).
- **I2:** one snapshot per check. `Ctx.read` reads each file once, and every rule (R-10, R-40 and the others) and the
 verdict's input digest use those bytes.
- **I3:** every negative or non-finite claim tolerance (`-inf`, `inf`, `nan`, `-1`) is `R-40.invalid_tolerance`. The
 claims schema no longer states a minimum; the rule enforces it.

## 0.6.2 (2026-11-23): release review gate, runtime fingerprints, git hooks, red-team rounds 2 – 6
Pre-release, not on PyPI. Six rounds of independent red-team review (Codex) since 0.6.1; every high and critical
finding is verified fixed. The last review (development/assessment/2026-11-23-reverification-7a67d8b.md) found the
known issues below. The release was made with them on Muiz's decision: "i want you to move on to the release now, with known issues for future release if codex has any identified".

### Known issues in 0.6.2
To be fixed in 0.6.3, each with a regression test written first. None is high or critical.

| ID | Severity | Issue | Until fixed |
|---|---|---|---|
| H1 | Medium | R-43 accepts a plain test reference pytest cannot collect (a `Test*` class with `__init__`) | name only tests in classes without a constructor, or confirm with `pytest --collect-only` |
| H2 | Medium | R-40 can pass two claims that rely on different revisions of one source file, if the file is saved during the check | do not write claim sources while `steward check` runs |
| H3 | Medium | R-40 does not check that the runs recorded the source files behind a *derived* registry value | claim the underlying values, or check their sources by direct pointers |
| H4 | Low | out-of-range numbers: two identical unrepresentable tokens compare equal; `±9e{MAX_EMAX}` with a tolerance raises; a mixed diff exits 1, not 2; extreme TOML registry or claim values raise | keep metrics within ordinary floating-point range |
| H5 | Low | R-11 credits integrity for lock digests that are not SHA-256 strings | regenerate locks with `steward paper displays --record` |
| H6 | Low | a claim `tolerance = inf` is reported as a value mismatch, not an invalid tolerance | use finite tolerances |
| H7 | Low | `diff run` labels runs with no recorded metrics as legacy `binary64` | read the label as "no exact metrics" |

**Fixes for the re-verification of 3e8cd37** (development/assessment/2026-11-23-reverification-3e8cd37.md), each
with a regression test written first and seen failing. Three are design narrowings, so each class cannot recur:
- **G2 (narrowed):** R-43 accepts only plain test references (`path::test_x`, `path::TestC::test_x`); a `[parameter]`
 suffix is refused. pytest's ID escaping is no longer reproduced. The E5 and D8 regression tests now expect
 parameter references to be refused.
- **G3 (narrowed):** a number whose exponent is beyond the decimal limits, or whose exact difference would need more
 than 10^6 digits, is `out of range`: `diff run` reports it as such (incomplete, exit 2), and R-40 reports
 `R-40.out_of_range` (UNKNOWN). Exact inequality with no tolerance still needs no arithmetic.
- **G7 (narrowed):** R-40 reads the claim map once, and each claim source once. Validation, exact numbers, the value
 and every evidence hash come from the same bytes.
- **G1:** claims through paper registry pointers read the source exactly (JSON, TOML, CSV cells); a derived value is
 labelled `R-40.derived_binary64`.
- **G4:** a lock entry without recorded fingerprints is `R-11.lock_entry_invalid` (FAIL) and earns no coverage; a
 malformed lock no longer raises.
- **G5:** `--tol` requires `POINTER=SPEC`; `=SPEC` names the root.
- **G6:** claim tolerances are validated as written (a tiny negative is refused even for equal values); messages show
 the exact numbers compared, in plain notation.
- **G8:** the text output of `diff run` names each run's metrics precision.

**Fixes for the re-verification of 328a17f** (development/assessment/2026-11-23-reverification-328a17f.md), each
with a regression test written first and seen failing:
- **F1:** a run keeps its metrics file's text (`metrics_text`), and fractional numbers are read as the exact decimals
 written, in `diff run` and in R-40 claim sources and claim values. Records written before this keep binary-float
 values; `diff run` reports `metrics_precision` (`exact` or `binary64`) for each run.
- **F2:** R-11 earns integrity coverage only when a display fingerprint was compared with the lock
 (`R-11.fingerprints_compared`); a missing lock earns none, a stale lock (compared, failing) keeps it.
- **F3:** R-43 refuses explicit parameter IDs that pytest would escape (non-ASCII or non-printable); reference the
 test without `[...]`.
- **F4:** `--tol POINTER=SPEC` splits at the last `=`, so a pointer may contain `=`.

**Fixes for the re-verification of 9bc2d9b** (development/assessment/2026-11-23-reverification-9bc2d9b.md), each
with a regression test written first and seen failing:
- **E1:** the relative-tolerance scale is taken context-free, so the caller's Decimal precision cannot round it.
- **E2:** extreme finite tolerances (up to the Decimal exponent limits) are decided by order of magnitude, never
 by materialising an out-of-range product; no internal error.
- **E3:** integer claim values and tolerances stay integers through validation (`steward.claims/0.1` schema
 regenerated), so R-40 compares them exactly.
- **E4:** an empty display manifest reports `R-11.nothing_to_check` and earns no integrity coverage.
- **E5:** R-43 accepts a test reference only if pytest would collect it with default naming: `test*` functions,
 `Test*` classes, and a parameter ID computed from literal `parametrize` arguments (`ids=`, `pytest.param(id=)`).
 IDs that depend on runtime values are refused; reference the test without `[...]`.
- **E6:** `--tol '=abs:X'` names the JSON root (`""`); `/` stays the property with an empty key.

**Fixes for the re-verification of 90d0622** (development/assessment/2026-11-23-reverification-90d0622.md). Each
has a regression test written first and seen failing:
- **D7 (high) / B3:** single use is decided when the authorization is consumed, under the ledger lock. Concurrent
 uses of one approval run the protected operation once.
- **B4:** git runs for verification and review drop every inherited `GIT_*` variable (`GIT_DIR`, `GIT_WORK_TREE`,
 `GIT_OBJECT_DIRECTORY`, `GIT_CONFIG_*`) and ignore user configuration, except when signing.
- **D1 / B1:** flattened metrics give each JSON node exactly one pointer (RFC 6901, `""` is the root); structure is
 typed, so no key such as `p#type` can impersonate it.
- **D2 / A1:** a positive repeatability verdict needs at least one compared metric value or output hash; structure
 alone is incomplete.
- **D3:** tolerances keep the decimal the user wrote (`abs:1e400` accepted); the boundary is decided without
 rounding; floats compare as the decimal they were written as. R-40 claim values use the same comparison.
- **D4 / B5:** R-42 fails when CITATION.cff or the claim map changed since the manifest, requires the configured
 claim map, and checks it with or without distributions.
- **D5:** a present PDF reader that cannot read the file reports `R-28.pdf_unreadable`.
- **D6 / A6 / B7:** coverage credits R-42 only when distributions were audited, and R-27 only when it traced
 something.
- **D8:** R-43 needs a named implementer (independence is shown, not assumed), a test that exists in the named file
 (parsed, not run), and a recorded re-verifier.

**Fixes for the v0.6.1 re-verification** (development/assessment/2026-11-23-reverification-v0.6.1.md). Each has a
regression test written first:
- **B4 / C1:** steward verifies the tag's SSH signature itself. It reads the tag object as raw bytes (replacement
 objects disabled) and runs the pinned `ssh-keygen -Y find-principals / verify`; only SSH signatures are accepted.
 `git verify-tag` and git's configuration are no longer involved.
 - *Note:* two concrete attacks (a forged PGP block judged by a repository `gpg.program`; hostile repository gpg
 settings) were already refused at v0.6.1. This is hardening.
- **B3 / A3:**
 - revocations and consumed nonces are the union of the pinned copy, the baseline's own `[policy]` paths and the
 working-tree paths, each read at the baseline and in the working tree;
 - a broken authorization ledger refuses rather than reading as empty;
 - spend, amend, unseal, confirmatory freeze and waivers require a pinned trust root (R-34 and R-38 report UNKNOWN
 for unpinned).
 - *Demonstrated before the fix:* repointing `revoked` or `ledger` in `steward.toml` re-enabled an approval.
- **B2 / A2:** an `unknown-price` budget needs a finite `calls=N`, and is refused before any reservation.
- **B1 / A1:** comparison keeps arrays, objects and empty containers; distinguishes missing metrics from falsey
 values; compares in exact decimal arithmetic (no overflow on huge integers); a key on one side only is a difference.
- **B5:**
 - R-42 fails when the claim map (R-40) does not pass;
 - the manifest records the claim map's hash;
 - `cffconvert --validate` runs when installed.
- **B6 / A5:** a missing PDF reader is reported as such (`R-28.pdf_reader_missing`, with an install hint), not as a
 missing PDF. The README states the PDF-reader prerequisite.
- **B7 / A6:** the coverage statement names the integrity rules that ran. R-28's reason says when fonts and bounds
 were not assessed.

**Runtime fingerprint and hooks:**
- **R-44 `release.fingerprint`** (`[release] fingerprint = ["src/pkg/**/*.py"]`):
 - an AST fingerprint per module (comments, whitespace and docstrings ignored);
 - `steward release fingerprint --record` writes the baseline;
 - a code change fails until reviewed and acknowledged with `steward release ack MODULE --reason TEXT` (an
 append-only ledger; one acknowledgement covers one fingerprint).
- **`steward hooks install [--force]`:**
 - pre-commit blocks on FAIL;
 - pre-push refuses force-pushes to `[release] protected` branches, and pushes when the gate is not eligible;
 - existing hooks are kept unless `--force`.

 Hooks can be skipped with `--no-verify`; CI with branch protection is the enforcement point.

**Release review gate:**
- **R-43 `release.review`:** an independent red-team review gate for releases.
 - It needs a review of the release commit (later changes that touch only documentation are still covered), a
 reviewer different from the implementer, and every high or critical finding verified with a regression test or
 accepted with a signed `waive` (`scope finding=ID`).
 - **Optional** (`[release] review_required = false` by default). When off, every report carries a "Recommended:"
 line before a public release.
- **Findings register** `development/assessment/findings.toml` (schema `steward.findings/0.1`).
- **New core skill `red-team-review`:** roles (reviewer, implementer, owner), the brief, the register, the
 re-verification.
- The name is fixed: **Bio-STEWARD**, Scientific Toolkit for Engineering, Workflow Assurance, Reproducibility, and
 Development.

## 0.6.1 (2026-11-23): first red-team fixes, release integrity
**Security and correctness fixes** (development/assessment/; each has a regression test):
- **C1:** signature verification is pinned to the system `ssh-keygen`. A repository's `gpg.ssh.program` can no longer
 fake a valid signature.
- **A3:** a pinned trust root:
 - sources: `STEWARD_TRUST_BASELINE` / `STEWARD_TRUST_SIGNERS` (CI), or `steward authorize pin` (a per-user
 `trust.toml` with signer keys by value);
 - an unpinned trust root makes R-33 UNKNOWN, never PASS;
 - R-33 reports the trust source, the baseline commit and the signer fingerprints;
 - `steward authorize anchor integrity`.
- **A1:** `steward diff run` needs two finished runs. Missing or non-comparable evidence is INCOMPLETE (exit 2);
 types are preserved (`true` ≠ `1`); NaN and inf are refused; tolerances must be finite and non-negative.
- **A2:** the spend guard decides and reserves inside one ledger lock (`Ledger.transaction`), so concurrent workers
 cannot share the last allocation. A spend authorization must name `models=` (and optionally `task=`), and calls
 outside its scope are refused.
- **A5, C2:**
 - files the example and the tests need are re-included despite global `*.pdf` / `*.lock` ignores;
 - `tools/example_setup.sh` regenerates the example;
 - `tools/ci_local.sh` tests a clean `git archive` export;
 - a test fails when a needed file is git-ignored.
- **A6:** reports show which kits were checked and which are not configured, plus a next action for every blocking
 result.
- **A4:** an explicit source-archive boundary (no `development/`), plus `CITATION.cff`.

**Release integrity (v0.6.1 slice):**
- `steward release manifest` (artifacts, locks, citation, claim-map status);
- `steward release audit` (every member of every wheel and sdist; development files, secrets and private terms
 refused);
- R-42 `release.integrity`;
- CI builds, audits and installs the wheel in a clean environment.

## 0.6.0 (unreleased; pre-release `0.6.0.dev0`): evidence
- **`steward run --metrics FILE`:** small JSON metrics are recorded by value. Run records now hash every repository
 file named in the command (`code`).
- **`steward diff run A B [--tol POINTER=abs:X|rel:X] [--default-tol …]`:** repeatability within declared tolerances.
 Environment, code, input and parameter differences are listed; the result never says "reproducible".
- **`steward diff impact`:** result files are classed stale, changed or current from their run records, with
 downstream paper values and displays, and a coverage line.
- **R-40 `evidence.claims`:** a claim map (`development/claims.toml`) ties each headline number to the runs that
 produced it. It fails claims with no run, from failed runs, whose source was rewritten after the run, or whose
 number differs.
- **R-41 `prior_work.links`:** claimed differences must cite existing contracts.

## 0.5.0 (unreleased; pre-release `0.5.0.dev0`): research integrity
- **`steward freeze NAME`:** snapshots protocol files, cohort ID lists (as hashed sets) and confirmatory parameters.
 Confirmatory contracts need a signed, single-use `freeze.confirmatory` and a decision reference; `--dry-run`
 prints the hash to approve.
- **`steward amend propose | apply`:** anyone proposes, recording the diff and the reason. Only a signed, single-use
 `amend` naming the proposal hash applies it, and it is refused if files changed after the proposal.
- **`steward seal | unseal DATASET`:** datasets are declared in `development/datasets.toml` with roles
 `development`, `sealed`, `spent`, `census-only`. `steward run` refuses sealed inputs with exit 77, matched by path or
 by content hash (copies under other names). An unseal needs a signed `unseal`, and the role becomes `spent`.
- **`steward integrity status`;** `steward run --contract ID`.
- **Rules:**

 | Rule | Checks |
 |---|---|
 | R-35 `integrity.frozen` | Drift, cohort changes as counts only, parameters, pending proposals |
 | R-36 `integrity.datasets` | Roles vs the record; sealed contents unchanged |
 | R-37 `integrity.sealed_use` | Run inputs and paper values reading sealed data |
 | R-38 `integrity.decisions` | Authorizations and decision references; DECISIONS.md append-only against the baseline |
 | R-39 `integrity.contract_frozen` | A confirmatory contract is frozen before its first run |

## 0.4.3 (unreleased; pre-release `0.4.3.dev0`): PresentationKit slices
- **Source adapters:** rules R-24 – R-29 now apply to Beamer, Quarto / reveal.js, PPTX and Keynote (through its
 exported PDF).
- **PDF layout checks:** minimum font size (normalised to a 960 pt wide slide; `typography.min_font_pt`) and text
 outside the slide.
- **`steward talk values NAME --write`** (Quarto `_variables.yml`); **`steward talk export NAME`** (Keynote → PDF,
 macOS).
- **PPTX:** explicit font sizes, off-slide shapes, notes, and pictures traced to displays by hash.
- **Optional extra** `[talk]` (pypdf, python-pptx).

## 0.4.2 (unreleased; pre-release `0.4.2.dev0`): spend guard
- **`steward.spend.guard` / `record`** (library) and **`steward spend check | record | status`** (CLI).
 - Refusals:
 - past the repository cap (`[spend] cap`);
 - beyond the signed budget (`USD 20 calls=200`) or its call ceiling;
 - without a verified `spend` authorization, or after its expiry;
 - at an unknown price, unless authorized as `unknown-price calls=N`;
 - always when `STEWARD_NO_PAID_CALLS=1`.
 - Estimates and actual usage are recorded apart, with price sources; the provider's bill is authoritative.
- **R-34 `spend.ledger`:** each call's authorization verifies (judged at the time of the call); the committed total is
 within the cap; actual usage without an estimate is listed.
- **`no-paid-tests` skill:** how the guard is used.

## 0.4.1 (unreleased; pre-release `0.4.1.dev0`): signed authorizations
- **`steward authorize prepare | sign | verify | list | keys | anchor`.**
 - The payload (`steward-authorization/1`) names the exact object (a SHA-256), action, scope, budget, expiry,
 policy baseline and nonce. It is signed as an annotated git tag with the human's SSH key.
 - **Verification:**
 - signers are read from `allowed_signers` **at the baseline ref**;
 - `git verify-tag` checks the signature;
 - strict payload;
 - repository, action, recomputed object, expiry;
 - the baseline must be an ancestor;
 - revocation list at the baseline;
 - single-use nonces are consumed in `development/authorizations.jsonl`.
- **R-33 `policy.baseline`:** policy files that differ from the baseline FAIL unless a verified `policy.change`
 names their bundle hash. Signer key types are reported; `sk-*` keys count as hardware-backed.
- **Ledger anchors:** `steward authorize anchor runs` → signed `steward/anchor/<ledger>/<seq>` tags. R-31 then detects
 a truncated tail or a rewritten ledger (FAIL).
- **`task-lifecycle` skill:** the approval flow; agents never sign for the human.

## 0.4.0 (unreleased; pre-release `0.4.0.dev0`): `steward run`
- **`steward run [limits] [--slot] [--input/--output/--param/--seed/--estimate-min] -- CMD`:**
 - watchdog over the whole process tree (wall time, memory, hang, free disk): SIGTERM, a 5 s grace, then SIGKILL;
 exit 124;
 - concurrency slots (exit 75, or `--wait`);
 - output copied to a log;
 - `--recover` marks orphaned runs as interrupted.
- **Run records** in a hash-chained ledger (`development/runs.jsonl`): command, git state and diff hash, inputs,
 parameters, seed, environment (Python, platform, CPU, thread variables, lock-file hashes), limits, estimate vs
 actual, outcome, peak memory, output and log hashes.
- **Ledgers:** append-only, hash-chained, `flock`-serialised, fsynced. `steward ledger recover` quarantines a torn
 tail; nothing is deleted.
- **Rules:**
 - R-31 `ledger.integrity`: edits, gaps and broken chains → FAIL; torn tail → INCOMPLETE; a missing anchor is a
 stated limit (deviation V6);
 - R-32 `run.records`: unfinished runs → INCOMPLETE; failed and killed runs are retained and listed; outputs
 changed since their run are listed.
- **Dependency:** psutil (D7).
- **Documented limit, tested:** processes that leave the tree (double fork with `setsid`) are not supervised.

## 0.3.0 (unreleased; pre-release `0.3.0.dev0`): PresentationKit
- **`[talk.<name>]` in `steward.toml/0.2`.** The talk plan `talk.toml` (schema `steward.talk/0.1`) records:
 - stage, confirmed by a human;
 - purpose, audience, duration and feedback mode;
 - outline;
 - claims with status and evidence;
 - style overrides.
- **Taxonomy and patterns as data:**
 - six stages with claim ceilings;
 - twelve purposes and four feedback modes;
 - six structural patterns, with feedback roles and limitations added by stage.
- **Rules R-21 – R-29:**

 | Rule | Checks |
 |---|---|
 | R-21 | Plan valid |
 | R-22 | Stage confirmed |
 | R-23 | Claim ceiling: validated or published claims need evidence |
 | R-24 | Slide numbers from the paper's values registry |
 | R-25 | Limitations from the evaluation stage on |
 | R-26 | Structure matches the feedback intent |
 | R-27 | Figures from declared, current displays |
 | R-28 | Slide budget, frame overflow, palette contrast |
 | R-29 | Strong wording listed for review |
- **Commands:**
 - `steward init --talk NAME`;
 - `steward talk plan [NAME] [--write-outline]`;
 - `steward talk prefs [NAME] [--compact] [--set KEY VALUE --layer …]`: layered style preferences (talk → project →
 context → global), with provenance; written only by the explicit `--set`.
- **Skills (talk kit):** `presentation-planning`, `presentation-building`, `presentation-review`.
- **The example** gains a Beamer progress update (stage `development`, feedback `targeted`) that shares the paper's
 values and displays.

## 0.2.3 (unreleased; pre-release `0.2.3.dev0`): venue rules, citations, submission manifest
- **R-13 `paper.venue`:** machine-checkable venue rules, INCOMPLETE in draft mode and FAIL in final mode:
 - page limits on the built PDF (total; main text up to `main_ends_at`);
 - abstract and title word counts;
 - required sections and declarations;
 - double-blind anonymity scan of sources, PDF text and PDF author metadata, from a private list (the report never
 prints the terms);
 - figure formats and raster resolution (Pillow).

 Missing sources, unspecified rules and missing tools → UNKNOWN.
- **R-14 `paper.citations`** (LaTeX/BibTeX):
 - a dependency-free `.bib` reader;
 - missing entries, duplicate keys, duplicate DOIs and malformed DOI / PMID / arXiv identifiers → FAIL;
 - unused entries and entries without identifiers are listed;
 - verification counts are reported. Existence is not verified in this version.
- **`steward paper manifest [NAME]`:** a submission record listing every file with its size and SHA-256, plus the git
 state.
- **DOCX** (secondary): placeholders (R-09) and required headings (R-13) via pandoc; other checks report UNKNOWN or
 N/A.
- **Skills:** `manuscript-drafting`, and `manuscript-review` (objective results kept apart from recommendations;
 response-to-reviewers procedure).

## 0.2.2 (unreleased; pre-release `0.2.2.dev0`): displays
- **Display manifest** `paper/displays.toml` (schema `steward.displays/0.1`). Each figure or table declares its
 script, inputs, parameters, output and label.
- **`steward paper displays [NAME] [--record]`** writes `displays.lock` with script, input and output hashes after a
 build.
- **R-11 `paper.displays`:**
 - stale displays (script, inputs, parameters or output changed since recorded);
 - missing scripts, outputs or inputs;
 - displays not cited or not included;
 - an unrecorded build;
 - figures included with no manifest entry (draft: INCOMPLETE; final: FAIL).
- **Skill `figures-and-tables`.**
- **Generated files are excluded** from the bare-number scan: the values file and display outputs.
- **Growth guard for skill budgets:**
 - every bundle budget names its decision, which is checked against DECISIONS.md;
 - per-skill descriptions are capped at 35 words;
 - a warning at 90 %;
 - the core budget is 300 words.
- **The example** builds a table and a TikZ figure from the split files with `analysis/make_displays.py`.

## 0.2.1 (unreleased; pre-release `0.2.1.dev0`): values registry
- **Values registry** `paper/values.toml` (schema `steward.values/0.1`). Each value comes from one source:
 - a JSON pointer into a `.json` or `.toml` file;
 - a CSV cell;
 - a row count or unique count;
 - or `derive` (arithmetic on other keys).

 `[[assert]]` declares relations that must hold between values.
- **`steward paper values [NAME] [--write]`:** prints every value, and writes `values.tex` (`\val{key}`),
 `_variables.yml` (Quarto) or `values.json`.
- **R-10 `paper.values`:**
 - values recompute from their sources; the generated file is current; every key used in the text exists;
 - unregistered bare numbers in the LaTeX body are listed (heuristic) and block in final mode, unless marked
 `% literal-ok`;
 - sentinels and missing sources give INCOMPLETE or UNKNOWN, never a guessed value.
- **R-15 `paper.consistency`:** declared assertions hold (with optional tolerance).
- **Skill bundles (H2):** `steward init --skills DIR --kits core,paper`, with per-bundle description budgets in
 `skills/BUNDLES.toml`.
- **Skill `number-crosscheck`.**
- **The example paper** takes every number from the registry: donors, samples and splits from the data files;
 bootstrap settings and threshold from the contract.

## 0.2.0 (unreleased; pre-release `0.2.0.dev0`): PaperKit, first slice
- **Config:** schema `steward.toml/0.2` with `[paper.<name>]` tables; 0.1 configs are still accepted.
- **Rules:**
 - R-08 `paper.spec_valid`: paper spec and venue profile;
 - R-09 `paper.placeholders`: draft vs final mode; comments scanned in final mode;
 - R-12 `paper.build`: LaTeX log, covering undefined references or citations, duplicate labels, errors, reruns and
 overfull boxes.
- **R-07 v2:** private terms inside PDF text (Poppler `pdftotext`, or `pypdf`); unreadable PDFs → UNKNOWN.
- **CLI:** `steward check --final`; `steward init --paper [NAME]` (LaTeX skeleton, spec, venue profile, bib).
- **Skills:** `paper-kit`, `submission-readiness`.
- **Optional extra** `[paper]` (pypdf, Pillow).
- **Example:** a synthetic LaTeX preprint built reproducibly (`SOURCE_DATE_EPOCH`).

## 0.1.1 – 0.1.3 (unreleased; developed together, pre-release `0.1.3.dev0`)
- Skills added:
 - `signature-and-attribution`, `negative-results` (0.1.1);
 - `run-estimate`, `no-paid-tests` (0.1.2);
 - `change-impact`, advisory (0.1.3).
- Every skill starts with a one-line statement of why it was loaded (DESIGN_v0.5 §3.3).
- All skill descriptions were shortened to stay within the always-loaded budget: 248 of 250 words for nine skills.
- The language lint also flags advice to skip verification, or to trade it for tokens or time (invariant A7).

## 0.1.0 (unreleased)
- `steward init`: scaffold `steward.toml`, development templates, `.gitignore` and AGENTS.md blocks, optional skills.
 It never overwrites.
- `steward check`:
 - rules R-01 … R-07: config, benchmark contracts, prior-work records, private-term denylist;
 - five statuses with all counts always shown, and gate decisions kept separate from the summary;
 - `--summary` gives compact output that lists every non-PASS result;
 - `--output` saves the full JSON report.
- `steward report`: Markdown, text or summary rendering of a saved report; `--rule` / `--subject` fetch one result's
 evidence.
- Four Agent Skills: `using-steward`, `task-lifecycle`, `benchmark-contract`, `prior-work-grounding`.
- `--summary` and `report --rule/--subject` (F1); footprint budgets (F2); gate presets in the config template (F3).
- Synthetic example: `examples/toy-expression-benchmark`.
- JSON Schemas for the config, contract, prior-work record and report.
- Tooling: language lint, footprint budgets, schema regeneration check.
