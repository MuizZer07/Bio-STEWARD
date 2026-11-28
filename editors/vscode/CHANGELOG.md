# Changelog: Bio-STEWARD for VS Code

The extension has its own version numbers and tags (`vscode-vX.Y.Z`). The builds before the roadmap to v1.0 were
numbered 0.0.x. Since then each extension version names the CLI it was tested with and is built as a `.vsix` that is
sideloaded in the adopting projects; it goes to the Marketplace only after v1.0. Newest first.

## 0.3.0 (the MVP, 2026-11-27)

The first version on the roadmap to v1.0 (sprint 2026-11-28-s1, tasks E01 – E05): every panel in its full form on
CLI 0.22, grouped by job, with a refresh button, newest first, a notifications bell, Upgrade CLI and token counts that
work. Tested with `bio-steward` 0.22.0 (`testedWithCli`); it still works from 0.20.6 on (`minimumCli`), where each
panel shows what that CLI offers and says what needs a newer one. Not published: install the `.vsix`.

### Added
- **The notifications bell** (E03): a status-bar bell with the unread count, and **Notifications** at the top of
  Today, from `steward notifications --format json`. Opening the bell or the list marks what it showed as read; **Mark
  Read**, **Mark Unread** and **Mark All Read** do it by hand. Read items stay, dimmed, under the unread ones, newest
  first. Read state is kept on this machine only, by each item's ID and content hash, so an item is news again only
  when the CLI reports a change to it. Toasts only for the three urgent kinds (a gate turned not eligible, an approval
  waiting, a sprint task failed); `bioSteward.notifications.toasts` turns them off.
- **Upgrade CLI** (E03): when `steward upgrade --check --format json` finds a newer release notice on this machine
  (the extension asks nothing of the network), the bell and Overview offer it. A modal shows the exact
  `steward upgrade --repo ROOT --to VERSION` and the CLI's installer command; on your confirmation a visible terminal
  runs it, and the CLI asks before installing. When the terminal closes, the extension detects the new CLI and runs
  its contract check.
- **The full forms** (E04), from the documents CLI 0.21 / 0.22 publish (`steward interface` lists them):
  - **Today** and **Where am I?** from `steward next`: Resume, the next milestone and what blocks it, what waits on you
    and on your agents with each row's next step, what needs tidying.
  - **Tasks** from `steward task board`: the status in the CLI's words; Closed and Archived groups.
  - **Approvals** cards add scope, budget, object, who asked, peer, baseline, the CLI's payload hash and the signed
    tag from `authorize pending --format json`.
  - **Decisions** adds the open questions with their options and every decision, newest first.
  - **Milestones and Drift** adds moved dates, scope, order and changes without a decision.
  - **Sprint** adds each task's step, commits (newest first), changed files, uncommitted files and logs from
    `sprint status --format json`.
- **Token counts that work** (E04): windows come from the records (the sprint ledger, runs, the agents ledger, and the
  hand-made windows). Each task shows its total, its tokens by model (input, output, cache read, cache write) and the
  estimated cost where the CLI gives one, and says which windows and logs it covers. Where a log setting is empty, the
  panel names that agent's usual folder for the project and offers **Use this folder**, which writes only that user
  setting; nothing is read before the click. An empty panel says in one sentence which input is missing, with the
  button that fixes it.
- **Every item does something** (E02): Markdown opens in preview (with **Open as Text** and **Copy Path**), other
  files in the editor (with **Reveal in Explorer**), and a record that is not a file opens a read-only details page:
  what it is, where it comes from, what it means and the next step. Row actions per panel, among them **Hand to
  Agent**, which copies `steward check --rule … --summary`, `steward task brief … --for codex` or `steward next
  --brief`, at most 16 KiB, and says its size.
- **A refresh button (⟳) in every panel's title bar** (E01): it runs that panel's CLI commands again at once, past the
  debounce and the Sprint pacing, with a progress bar in the panel.
- Figures for the guide and this README: the panels by job, Today with the bell, and the cockpit in its full forms.

### Changed
- **Panels by job** (E01): the ten panels sit in one container, in five groups, each header named with its group:
  *Now* (Today, Approvals), *Quality* (Overview, Results), *Work* (Tasks, Sprint, Tokens), *Direction* (Milestones and
  Drift, Decisions), *Agents* (Agent Skills). Each empty state and each `?` help opens with one sentence on how the
  panel helps when developing with agents.
- **Newest first in every list** (E01): tasks by the latest change, then the ID, highest first; decisions,
  notifications, exchange items, sprints and their tasks, runs and token windows likewise; milestones the latest due
  first, while the status-bar countdown still names the nearest. The order is made from the CLI's dates and IDs.
- **"Reduced" is gone** from every string (E01). Where the installed CLI cannot give something, the row says what is
  missing and how to get it ("… needs steward 0.21 or newer: Upgrade CLI").
- `testedWithCli` is 0.22.0. Feature detection reads the interface CLI 0.21+ publishes (`interface_version` and its
  `commands` map).
- The version is 0.3.0: the roadmap to v1.0 made this release the MVP (the 0.0.x numbering was for the builds before
  it).

### Development
- `npm run cli:install` installs the pinned CLI from the release tag `v<testedWithCli>` of the enclosing repository
  (`git archive`) when it has it, and otherwise from PyPI, then the public tag; `--source local|pypi|tag` chooses one,
  and the output names the source used. `npm run fixtures` reads the same tag. The tests no longer clone the public
  repository.
- New fixtures from CLI 0.22.0: the full-form documents, a recorded sprint with stand-in agent logs for the token
  totals.

## 0.0.5 (pilot build, 2026-11-27)

### Fixed after the independent review (U09)
- **✍ Sign's terminal** gets its whole environment from the extension (`strictEnv`): a workspace's
  `terminal.integrated.env.*` settings and other extensions' environment collections no longer reach the CLI.
- **Cards are bound to one snapshot.** A card link carries the full nonce, the project index and the page's
  generation; a link of an earlier page does nothing. The handler reads the file, a fresh `authorize pending` (a
  superseded or failed read refuses) and the file again; the card's, both reads' SHA-256 must agree, and ✍ Sign needs
  exactly one queue line for the prefix, under this project's code, equal to the line the CLI prints for those bytes.
  Otherwise the card is display-only and says why (a summary over several lines, a peer's duplicate prefix, a changed
  file). The modal's action, expiry and summary come from the same read as its SHA-256.
- The modal says plainly that **the CLI's own prompt is the review of record**. Preview documents are named by the
  project's canonical folder, the full nonce and the SHA-256, so two projects of the same name never share one.
- The **payload read** checks, after the read, that `.steward`, `.steward/pending` and the file are still the same
  entries and none is a link (Node has no directory-relative open).
- **Tokens:** each log keeps the file or folder its setting named; just before the CLI starts, the file must still be
  inside it and reached without a link. The **all activity** row is marked *shared* (the logs are the machine's).
- **Tasks and Decisions** find files as the CLI lists them (no link on the way to a glob's folder, never `.git`), match
  globs as Python does (`**` stops at a line break, `?` is one code point), name a glob unmatched only when it matches
  no file, say when the search stopped at its limit, and check a file again when a row or **Open DECISIONS.md** opens
  it. A row says when **Open DECISIONS.md** opens a log other than the first one configured.
- **Tasks** shows the physical line that holds the `**Status:**` label, unchanged; the open / closed grouping uses
  R-57's rule (the value as the CLI's pattern reads it, normalised against `statuses`, then checked against `closed`)
  and is labelled a display grouping.

The cockpit, in its reduced forms: the panels of extension 0.2.0 built from what CLI 0.20.6 already prints (sprint
2026-11-27-vscode-0.2, U01 – U05, U04b, U07). Each reduced panel says "Reduced form" on its first row and names its
source on every row; its full form waits for the newer "cockpit" CLI. Tested with `bio-steward` 0.20.6.

### Added
- **Today** (reduced): what waits, and for whom, from `steward audit progress --json`, `steward timeline --json` and
  the session handoff: **Resume**, the next milestone, signatures waiting, exchange items open here, this project's
  own requests still open, sprints with open tasks and every milestone, each item as the CLI wrote it. With several
  projects open, one block per project, ordered by the counts audit progress reports.
- **Where am I?** (reduced): the same as one page, each part labelled with its source; shown once when a project is
  reopened after 3 days (`bioSteward.whereAmI.showOnReopen`, `bioSteward.whereAmI.reopenAfterDays`). **Copy as Agent
  Brief** copies it with the handoff cut to 40 lines.
- **Tasks** (reduced): every task file (the `[tasks]` table, or `development/tasks/**/*.md`) with its `Status:` line
  exactly as written, labelled *read from the file*; open first, closed ones in their own group. A file without a
  Status line shows nothing.
- **Tokens**: `steward tokens report --json` per task window and model, with a total, over the agent logs you select
  in your user settings (`bioSteward.tokens.claudeLogs`, `codexLogs`, `geminiLogs`). **Start / Done Task Window…**
  runs `steward task start` / `task done` after you confirm the exact command.
- **Approvals** (reduced, design v0.8): one card per payload line of `steward authorize pending --all-projects`, with
  the payload's SHA-256 read from `.steward/pending/<nonce>.txt` and the line as printed. **View exactly what you are
  approving** opens the payload file read-only, unchanged. **✍ Sign** re-reads the queue, shows a modal dialog
  (action, summary, expiry, hash, the exact command), asks you to type the action's name for unseal,
  freeze.confirmatory, policy.change, waive, pin.retire and amend, and only then runs the CLI's own
  `steward authorize sign-pending --repo ROOT` in a new terminal. The CLI prints the bytes and asks before each
  signature; the key's own prompt completes it. A peer's card has no buttons.
- **Decisions** (reduced): **Open DECISIONS.md** opens the log `steward.toml` names (or the CLI's default) as it is.
  The extension never creates or writes a decision.
- **Drift** (reduced): each milestone's state from `steward timeline --json` in the CLI's own words, with its days
  left or ago; nothing computed.
- A **?** help for each new panel, in `media/help/panels.md`, with a table of every panel, what it answers and what
  it reads.
- Four figures drawn by `npm run figures` from the panels' view models and the cockpit fixtures: Today, Approvals,
  the ✍ Sign steps with the modal dialog, and Tasks / Tokens / Decisions / Drift. The README and the guide
  (`docs/guides/vscode.md`, "The cockpit") show them.
- Fixtures for the reduced forms (`test/fixtures/cockpit/`), generated from CLI 0.20.6 (U01).

### Changed
- The modal dialog's and the typed-name box's words live in the view model (`signDialog`, `typedNamePrompt`), so the
  figure draws exactly what the dialog says; the dialog itself is unchanged.
- The "how it works" figure lists the new panels and says the extension never signs: your key does, in a terminal.

### Security
- Signing is the only new write path, and the extension does not sign: no code path runs the signing command
  without the modal accepted in that call, no text is typed into a terminal, the CLI's flag that skips its question
  is never built, and no key is read. The card links carry only the full nonce, a project index and the page's
  generation, and are checked against the page now shown, a fresh read of the queue and two reads of the file (U09). The Approvals webview has no scripts and enables exactly two
  command links. In Restricted Mode no new panel reads or runs anything.

## 0.0.4 (pilot build, 2026-11-26)

### Changed
- The publisher is `MuizZer07`, matching the GitHub account, so the extension ID is `muizzer07.bio-steward`
  (Muiz's decision, before any publication). Uninstall `repertoire0f1ife.bio-steward` (0.0.2, 0.0.3) before installing
  this build; VS Code treats the two IDs as different extensions.

## 0.0.3 (pilot build, 2026-11-26)

The first pilot finding, and help for each panel.

### Changed
- The setup guide ("Set up a Bio-STEWARD project") is offered only when no open folder is a Bio-STEWARD project.
  **Initialize Project** in a folder that already has a `steward.toml` now says so and offers **Run Check** and
  **Show Overview**, instead of asking for another folder.

### Added
- A **?** button on each panel (Overview, Results, Agent Skills, Sprint) opens a plain-language explanation of that
  panel: what it shows, what its words mean and when to use it. The help ships with the extension
  (`media/help/panels.md`), so it works offline.

## 0.0.2 (pilot build, 2026-11-26)

The build for the pilot in the adopting projects: everything below, after the independent review (T11) and its
fix pass (T12). Tested with `bio-steward` 0.20.6.

### Added
- Freshness (S1): *fresh* right after a run, *stale* within about a second of a project file change (no check is
  run), *unknown* when the extension cannot tell (a report found at start-up, a change during the run). File
  watchers only downgrade; `.steward/` and git's bookkeeping are not watched. A CLI version change makes the
  report stale. Problems are tagged "from a stale report" / "from a freshness-unknown report".
- Several projects in one window (S2): every workspace folder with a `steward.toml` is a project with its own
  runs, report, watcher, countdown and Problems; the views and the status bar follow the active editor's project;
  **Select Project…**.
- Countdown (S3): the next milestone in the status bar, from `steward timeline --json`, with what blocks it in the
  tooltip and every milestone on click (**Show Milestones**).
- Resume (S4): **Resume: Show the Last Session Handoff** opens the `[session] handoff` file as a read-only document,
  its text unchanged.
- `bioSteward.report.location = auto` follows VX5 (S10): `.steward/report.json` when git ignores it, otherwise the
  extension's storage. Decided by one read-only `git check-ignore` with `core.fsmonitor`, hooks and the untracked
  cache forced off, on its own allow-list. It is the only git command the extension runs.
- At start-up, the report last written at the report location is shown, marked *unknown*.
- Copy for agent (S5): **Copy Summary for Agent** puts the CLI's own `steward check --summary` text on the clipboard,
  unchanged, followed by the command that re-checks it and the text's size in bytes. From a result's context menu
  it copies `steward check --rule R-xx --summary` instead. Nothing is written and nothing goes to a terminal.
- Agent Skills (S7): an **Agent Skills** view lists the skill folders R-60 names and the known harness folders
  (`.agents/skills`, `.claude/skills`) as they are on disk (a folder, a link and its target, a pointer file, or
  missing), with the folders each holds, and the R-60 `skills.copies` result with its codes (linked, copy, drift, …)
  as the CLI reports them. **Install Agent Skills…** picks the folders (the first holds the copy, the others link)
  and kits, shows the `steward init --skills … --dry-run` plan unchanged, and runs it after a confirmation that
  shows the exact command; a plan that would create nothing new, or reach outside the project, is blocked. The CLI
  never edits `steward.toml`, so the view says to add the `[skills]` table it prints (**Copy Table**).
  **Check Skills** re-checks R-60 as a partial run.
- Scoped re-check (S8): **Run Check for Area…** (`steward check AREA …`) and **Run Check for Rule…**
  (`steward check --rule R-xx`, also from a result's context menu). The report is a partial run: its gates read
  NOT EVALUATED BY THIS RUN, the status bar keeps the last full verdict, marked stale, and the report is written to
  the extension's storage, never to the shared `.steward/report.json`. A scope the CLI rejects (exit 64) is
  reported and changes nothing.
- Live sprint view, minimal (S9; design v0.4 VX22): a **Sprint** view shows each running sprint of the active
  project, read only from its sprint file and its ledger (`development/sprints/<id>.toml` / `.jsonl`), never git:
  every task in the dispatcher's order with its state in the CLI's words (READY · ORDER NEEDED, RUNNING 12 min,
  DONE, …; the states the view derives, such as READY and BLOCKED, are labelled as derived), the minutes used of
  its wall limit, its branch, and, once it ends, each done-command with its exit code and the commit the ledger
  records; then the last ten events. Commits and changed files during a task come in a later release, from the
  CLI. The status bar shows `▶ T01 12 min · 1/12` while a task runs. Three notifications: a task finished (done
  or failed), a task waits for an order, the watchdog stopped a task (`steward run exited 124`). **Copy Order
  Command** puts `steward sprint go ID TASK` on the clipboard; the view orders, starts and writes nothing, calls no
  model, and reads again at most once a second when a watched file changes. A ledger line that is not an entry is
  shown as *unreadable*, and every surface then marks the states *incomplete* (no notification is sent from
  them); the hash chain is the CLI's to verify. In Restricted Mode it reads nothing.
- `bioSteward.check.onSave` (off by default): a save runs **Run Check** for its project 2 s after the last save, one
  run at a time per project; a save under `.steward/` or `.git/` never does; trusted workspaces only.
- The Marketplace icon (`icon.png`, 128 px): the view container's shield.
- The README rewritten around five figures (the Overview and status bar, Results, the status bar state by state,
  how the extension works, freshness) and the guide page `docs/guides/vscode.md` in the doc site.
- `npm run figures` draws those figures from the extension's own view model and the fixture reports, so each shows
  what the extension draws for that report; they are drawings, not screenshots, and say so. `-- --verify` compares
  the committed SVGs, and the unit suite runs that comparison. The PNGs are made with `rsvg-convert` when it is on
  `PATH`.

### Changed
- With a CLI newer than 0.20.6, the extension says so ("CLI newer than tested") but works as it does on 0.20.6:
  Explain, Agent Skills, Initialize Project and freshness do not yet use the newer CLI. Their richer forms arrive
  in a later release, once the CLI offers them (requests C1 – C8).
- Each check writes its report to a private file; only a check that exits 0 – 3 with a valid report replaces the
  saved report (atomically), only a newer check's report replaces an older one, and a cancelled or failed check
  leaves the saved report as it was (T11-05).
- The sprint file is validated as the pinned CLI validates it (window order, cycles, `max_parallel` 1 – 16, unknown
  fields, adapters, done-commands), and ledger entries before they are folded. The TOML reader refuses a trailing
  comma in an inline table, a table redefined after a dotted key and invalid calendar dates, and bounds nesting
  (T11-04). A timeline gate without a readable verdict is shown as *unavailable* (T11-09).
- `npm run package` gives the same `.vsix` bytes for the same commit: it sets `SOURCE_DATE_EPOCH` to the commit
  time of `HEAD`, which `vsce` uses for every zip entry. `npm run package -- --twice` builds twice and fails if the
  two differ. It still never publishes.

### Security
- Hardening (T09): a host test shows Restricted Mode makes no CLI call, also through direct commands; workspace
  values of machine settings are ignored; a saved report reached through a link that leaves its folder is not read;
  report text is rendered as plain text; a host test with networking blocked shows the extension makes no network
  connection (VS Code's own built-in connections are counted apart). Activation to an interactive sidebar took
  about 73 ms on macOS arm64.
- The independent review's fixes (T12): the live sprint view's three git reads (`status`, `log`, `diff`) are
  removed, because `git status` could start a filter program defined in the repository's own config (T11-01) and
  object reads could fetch (T11-02). `git check-ignore` now runs with `PATH`, `HOME` and `GIT_CONFIG_NOSYSTEM=1`
  only; a test shows a repository's `filter.*.clean` and `filter.*.process` programs never run during it. Sprint
  files are read through one descriptor, without following links or blocking, up to a size limit, as valid UTF-8,
  with bounded work per refresh (T11-03). The two confirmation-gated **Review command and confirm…** links of Init
  Preview and Skills Preview are a documented exception to the read-only webview-link rule; a host test shows each
  of the three webviews enables exactly its one command and escapes CLI and repository text (T11-08).

## 0.0.1 (alpha.1)

### Added
- The extension's scaffold: manifest (workspace trust limited, activation on `steward.toml`, the settings),
  toolchain, `npm run cli:install` for the pinned CLI (`bio-steward` 0.20.6), and the unit and host test suites.
- `npm run fixtures`: the test corpus (reports of both worked examples and their seeded faults) and the copy of the
  report schema, generated from the pinned CLI and its release tag; `--verify` checks the committed copies.
- The verdict views (M3, M4): the Overview and Results trees in a Bio-STEWARD view container, and the status bar
  for the gate set by `bioSteward.gate`, built by pure view models from the validated report. A scoped run never
  changes a gate badge. Commands **Run Check**, **Show Overview**, **Group Results By…** and **Re-detect CLI**;
  explicit empty states (Restricted Mode, CLI not found, no report, unreadable output, …). Unit tests check every
  displayed number against every fixture report; host tests run the pinned CLI on a fresh copy of the GEO example.
- File findings in Problems (M5), with reported locations, gate tags and related evidence. The Explain view (M6)
  opens from a problem code, a result's context menu or **Explain Rule…**, and shows the CLI's explanation.
