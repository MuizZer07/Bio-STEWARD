# Bio-STEWARD in VS Code

The Bio-STEWARD extension for VS Code shows what `steward check` says about your repository where you write the
code: the gate verdict in the status bar, every result in a tree, the files they name in **Problems**, and the rule
behind each one a click away. It uses the `steward` program you installed; it decides nothing itself.

!!! note "Version 0.3.0, sideloaded"
    This is extension 0.3.0, the MVP, tested with CLI 0.22.0. It is installed from a `.vsix` file and is not on the
    VS Code Marketplace or Open VSX: it goes there after v1.0, when both the CLI and the extension are stable.

<p align="center"><img src="https://raw.githubusercontent.com/MuizZer07/Bio-STEWARD/main/editors/vscode/media/readme/overview.png" alt="The Overview and the status bar for the GEO example with a seeded fault: gate default NOT ELIGIBLE, 2 blocking results" width="92%"></p>

| | |
|---|---|
| 🧠 **No AI inside** | no model calls and no tokens; it works with any agent, or none |
| 📡 **No network, no telemetry** | the extension makes no network requests; reports stay on your machine |
| 🛡️ **The CLI decides** | every status, count and gate is read off the report |
| 🔒 **Restricted Mode runs nothing** | in an untrusted workspace no CLI command runs |
| ✍️ **It never signs for you** | no command signs, approves, publishes or spends by itself. **✍ Sign** in the Approvals panel asks you first, then starts the CLI's own signing in a terminal, where the CLI asks again and your key completes it |

**New in 0.3.0**

| | |
|---|---|
| 🗂️ **Panels by job** | ten panels in five groups: Now, Quality, Work, Direction, Agents ([the cockpit](#the-cockpit)) |
| ⟳ **Refresh in every panel** | runs that panel's CLI commands again at once, with a progress bar |
| ⬆️ **Newest first** | every list puts the latest entry on top; milestones the latest due first |
| 🔔 **Notifications bell** | unread count in the status bar; read once seen; toasts only for urgent items |
| 🧾 **Full forms on CLI 0.22** | Today from `steward next`, the task board, decisions, drift, approval details, sprint commits |
| 🔢 **Token counts that work** | windows from the sprint and run records; tokens by model with the estimated cost; **Use this folder** |
| 👉 **Every item opens something** | Markdown in preview, files in the editor, records as details pages; **Hand to Agent** |
| ⬆ **Upgrade CLI** | the exact command in a modal, then the CLI's own upgrade in a visible terminal |

## How it works

```mermaid
flowchart LR
  V["VS Code<br/>Bio-STEWARD views"] -->|Run Check| R["allow-listed runner<br/>no shell · --repo · timeout"]
  R -->|steward check --format json| C["your steward CLI<br/>bio-steward ≥ 0.20.6"]
  C -->|writes| F[("report JSON")]
  F -->|read| S{"schema check<br/>steward.report/0.1"}
  S -->|readable| V
  S -->|"oversized or invalid"| U["unreadable:<br/>nothing shown"]
```

The extension runs a short, fixed list of `steward` commands, each built from typed arguments and started without a
shell. It reads the report, checks it against the report schema it carries, and draws the views from it. Every
number on screen is a number in the report.

## 1. Install

| Step | Do |
|---|---|
| 1. The CLI | `uv tool install "git+https://github.com/MuizZer07/Bio-STEWARD.git@v0.22.0"` (or `pipx install …` with the same address). The package is `bio-steward`; its `--version` must read 0.20.6 or newer (this extension is tested with 0.22.0) |
| 2. The extension | in VS Code, **Extensions: Install from VSIX…** and pick `bio-steward-0.3.0.vsix` (built from `editors/vscode` with `npm run package`; the same commit gives the same bytes) |
| 3. A project | open a folder with a `steward.toml`. Without one, the **Set up a Bio-STEWARD project** walkthrough runs `steward init` for you, after showing the CLI's dry run |
| 4. Trust | trust the workspace when VS Code asks. In Restricted Mode the extension runs nothing |

The extension finds `steward` on `PATH`, then in the pipx and uv tool folders. To use another program, set
`bioSteward.cliPath` in your **user** settings; a workspace cannot set it, and a repository's own `.venv` is never
picked.

| Works in | Does not work in |
|---|---|
| VS Code 1.100 or newer on macOS and Linux; Remote-SSH (cluster nodes), WSL, dev containers | vscode.dev and github.dev (no local processes); Windows without WSL |

## 2. Your first check, step by step

```mermaid
sequenceDiagram
  actor You
  participant VS as VS Code
  participant CLI as steward
  You->>VS: open the project folder
  VS-->>You: status bar: default ? · no report
  You->>VS: Run Check (▷)
  VS->>CLI: steward check --format json --output …
  CLI-->>VS: report
  VS-->>You: default ✗ NOT ELIGIBLE · 2 blocking · fresh
  You->>VS: open the problem in Problems
  You->>VS: Explain Rule (the code R-83.excel_date)
  VS->>CLI: steward explain R-83
  You->>You: fix the file
  VS-->>You: … · stale (no check is run)
  You->>VS: Run Check
  VS-->>You: default ✓ ELIGIBLE · fresh
```

1. **Open the folder.** The extension activates when the workspace holds a `steward.toml`. The status bar shows the
   gate named in `bioSteward.gate` (`default` unless you change it).
2. **Run Check** (the ▷ button on the Overview or Results view, or the command palette). The CLI runs
   `steward check --format json --output .steward/report.json`, or writes to the extension's storage (see
   [Where the report goes](#where-the-report-goes)).
3. **Read the verdict.** The Overview lists each gate with its blocking and waived lists, the five counts, the worst
   status and the coverage statement.
4. **Go to the file.** A FAIL with a file appears in **Problems** at the reported line (or line 1). In the GEO
   example with a seeded fault, R-83 reports `'7-Sep' looks like a spreadsheet date` in `results/top_genes.tsv`.
5. **Explain the rule.** Select the problem's code, or **Explain Rule…** from a result's context menu. The text is
   `steward explain R-83`, shown as the CLI prints it.
6. **Fix and check again.** As soon as you save, the report reads *stale*; no check runs on its own unless you turn
   on `bioSteward.check.onSave` (then a check runs 2 s after the last save, one at a time per project, never for a
   save under `.steward/` or `.git/`). **Run Check** makes it *fresh* again.

## 3. What each view shows

<p align="center"><img src="https://raw.githubusercontent.com/MuizZer07/Bio-STEWARD/main/editors/vscode/media/readme/results.png" alt="The Results view grouped by status for the toy benchmark with seeded faults" width="92%"></p>

| View | Shows | Read off |
|---|---|---|
| ⛉ Status bar | one gate: ELIGIBLE or NOT ELIGIBLE, the blocking count, freshness; the countdown to the next milestone; the notifications bell with unread count | `gates[]`, `summary`; `steward timeline --json`; `steward notifications --format json` |
| Overview | the CLI (and **Upgrade CLI** when a newer local release notice exists); the report (freshness, project, profile, time); gates with blocking and waived lists; counts; worst status; coverage | the report's `verdict`; `steward upgrade --check --format json` |
| Results | every result by status, gate or file, with its details and the gates it blocks | `results[]` |
| Problems | FAIL → error, INCOMPLETE → warning, UNKNOWN → information (or warning, by setting) | results that name a file |
| Explain | the CLI's text for a rule | `steward explain R-83` |
| Agent Skills | skill folders on disk, R-60's codes (linked, copy, drift…), install with a dry run first | R-60 and the folders |
| Sprint | a running sprint's tasks, newest first, their states (derived ones labelled), times, done-commands with exit codes; with steward 0.21 or newer also each task's step, its commits (newest first), changed and uncommitted files and logs | the sprint file and its ledger (no git); `steward sprint status --format json`, where the CLI reads git |

Each panel has a **?** button that opens a plain-language explanation of it, bundled with the extension, and a
**refresh** button (⟳) that runs that panel's CLI commands again at once, with a progress bar in the panel. The
cockpit panels (Today, Approvals, Tasks, Tokens, Milestones and Drift, Decisions) have
[their own section](#the-cockpit).

Click a file row to open it. Markdown opens in preview, with **Open as Text** and **Copy Path** on the row.
Other files open in the editor and offer **Reveal in Explorer**. Record rows open read-only details with the CLI
source and next step. The inline buttons and context menu carry out the actions for that record.

Statuses always carry a word: ✓ PASS · ✗ FAIL · ◐ INCOMPLETE · ? UNKNOWN · – NOT APPLICABLE. Colour is never the only
signal.

<p align="center"><img src="https://raw.githubusercontent.com/MuizZer07/Bio-STEWARD/main/editors/vscode/media/readme/status-bar.png" alt="Eight status-bar states, from eligible and fresh to Restricted Mode" width="92%"></p>

## 4. Fresh, stale, unknown

```mermaid
stateDiagram-v2
  direction LR
  [*] --> unknown: a report found at start-up
  [*] --> fresh: Run Check
  [*] --> unknown: Run Check, and a file changed during the run
  fresh --> stale: a project file changed · the CLI changed · a newer scoped run
  stale --> fresh: Run Check (a full run)
  unknown --> fresh: Run Check (a full run)
```

| Word | Means |
|---|---|
| **fresh** | the extension made this report and no project file changed since |
| **stale** | something changed since; run the check again |
| **unknown** | the extension cannot tell (a report it did not make, or a change during the run) |

File changes only ever downgrade. Changes under `.steward/` and git's own bookkeeping do not count; a moved branch
does. The word *current* is not used: this version of the extension cannot show that a report still matches the
files.

**The CLI version.** The extension is tested with CLI 0.22.0 and works from 0.20.6 on. It reads the interface a CLI
publishes (`steward interface`) to choose each panel's form, and says "CLI newer than tested" in the log for a newer
one. When a newer release notice is on this machine, **Upgrade CLI** offers the upgrade (see
[Today](#today-and-where-am-i)). Explain, Agent Skills,
Initialize Project and freshness work the same way on every version; their richer forms (structured explanations, a
skills inventory, an init file list, *current* shown by a digest), which CLI 0.22.0 can give, come in a later release
of the extension.

**A scoped run never changes a gate badge.** **Run Check for Area…** (`steward check data`) and **Run Check for
Rule…** (`steward check --rule R-83`) are partial runs: their gates read NOT EVALUATED BY THIS RUN, the full verdict
stays in the status bar marked *stale*, and their report never replaces the shared one.

## The cockpit

The check panels above answer "may this project move on?". The cockpit panels answer the questions of a working
day: *what waits, and for whom? what do I sign? which tasks are open, and what did they cost? which target needs
attention?*

**Panels by job.** The ten panels sit in one Bio-STEWARD container, grouped by the job they help with; each panel's
header names its group (*Work · Tasks*, for example).

<p align="center"><img src="https://raw.githubusercontent.com/MuizZer07/Bio-STEWARD/main/editors/vscode/media/readme/panels.png" alt="The ten panels grouped as Now, Quality, Work, Direction and Agents, each with the sentence its empty state and ? help open with, and a refresh and ? button in every title bar" width="92%"></p>

| Group | Panels | The question it answers |
|---|---|---|
| **Now** | Today, Approvals | What needs me, and what changed since I looked? |
| **Quality** | Overview, Results | Is this project's work checkable and eligible to move on? |
| **Work** | Tasks, Sprint, Tokens | What are my agents doing, what did it cost, and what's next? |
| **Direction** | Milestones and Drift, Decisions | Am I on plan, and why did we decide what we did? |
| **Agents** | Agent Skills (with **Copy as Agent Brief**) | Do my agents work by this project's rules? |

**Newest first.** Every list puts the newest entry on top: by its latest change, then by its ID, highest first
(`T10` before `T9`). Milestones come with the latest due date first, while the status-bar countdown still names the
nearest. The dates and IDs are the CLI's (or a file's); the order is only how the list is shown.

Each panel's first row names its source, and each row says where it comes from. Nothing is guessed to fill a gap.

With steward 0.21 or newer every panel shows its **full form**, read from the versioned documents the CLI publishes
(`steward interface` lists them). An older CLI still works: each panel then reads what that CLI offers, and a row says
what needs a newer one.

| Panel | Answers | Reads (steward 0.21 or newer) | With an older CLI |
|---|---|---|---|
| **Today** | what waits, and for whom? | `steward notifications --format json` and `steward next --format json`: resume pointer, next milestone and its blockers, waiting on you, waiting on agents, needs tidying, each row with its next step | `steward audit progress --json`, `steward timeline --json`, the session handoff |
| **Where am I?** | where did I leave off? | the same, as one page | the same, as one page |
| **Approvals** | what waits for my signature? | `steward authorize pending --all-projects` (text) and the payload files, plus scope, budget, object, who asked and hashes from `authorize pending --format json` | the text and the payload files |
| **Tasks** | which tasks are open, and what changed last? | `steward task board --format json`: each task's status in the CLI's words, closed, archived | the task files' `Status:` lines, as written |
| **Sprint** | what are my agents doing now? | the sprint file and ledger, plus each task's step, commits, changed files and logs from `steward sprint status --format json` | the sprint file and ledger |
| **Tokens** | what did each task cost? | `steward tokens report --format json`: each task's windows from the records, its total, its tokens by model, the estimated cost where given | `steward tokens report --json` |
| **Milestones and Drift** | am I on plan? | `steward timeline --format json`: each milestone's state, then moved dates, scope, order and changes without a decision | `steward timeline --json`: each milestone's state |
| **Decisions** | why did we decide what we did? | the log `steward.toml` names, plus the open questions and every decision, newest first, from `steward decisions --format json` | the log, opened as it is |

With several projects open, every panel shows one block per project and never mixes their rows. Projects come in
the Today order: the most waiting on you first, then the most waiting on agents (from `steward next`; with an older
CLI, more signatures waiting first, then open exchange items, your own open requests, then sprints with open
tasks). That is a plain order of counts, not a judgement.

### Today and Where am I?

<p align="center"><img src="https://raw.githubusercontent.com/MuizZer07/Bio-STEWARD/main/editors/vscode/media/readme/today.png" alt="The Today panel and the status-bar bell on CLI 0.22: Notifications at the top, two unread and one read item dimmed below, then Resume, the next milestone, seven items waiting on you newest first, nothing waiting on agents, and what needs tidying" width="88%"></p>

**Today** is the first panel of the Bio-STEWARD sidebar. At its top, **Notifications** lists the items of
`steward notifications --format json` (CLI upgrades, exchange items, sprint task updates, approvals waiting, gates
turned not eligible, milestones at risk or late), unread first and read dimmed underneath, newest first in each. Below
it, with steward 0.21 or newer, Today reads `steward next`: **Resume**
(your last handoff, its age, and its next lines), **Next milestone** with what blocks it, **Waiting on you** and
**Waiting on agents** (newest first, each row with its next step, the exact CLI command), **Needs tidying**, and the
CLI's notes. With an older CLI, from the top: **Resume** opens your last session handoff as
written; **Next milestone** is the status bar's countdown; then the lists of the "Pending" part of
`steward audit progress`, item by item: signatures waiting (only you can give those), exchange items open here, this
project's own requests still open, sprints with open tasks, and every milestone. Items with IDs come highest ID
first, milestones the latest due first; signatures keep the CLI's order, as it gives them no date.

**Notifications bell and read state.** The status bar carries a **bell** showing the unread count across open
projects. Read state is kept locally on this machine, keyed by each notification's ID and content hash, so the same
item stays read until the CLI reports a change to it. Opening the bell or expanding **Notifications** in Today marks
every item it showed as read and drops the count; each item also has **Mark Read** / **Mark Unread**, the list has
**Mark All Read**, and clicking an item opens its read-only Markdown details page. System toasts appear only for the
three urgent kinds (a gate turned not eligible, an approval waiting, or a sprint task failed) and can be turned off
with `bioSteward.notifications.toasts`.

**Upgrade CLI.** When `steward upgrade --check --format json` finds a newer version from a local release notice (no
network call by the extension), the bell shows it and Overview offers **Upgrade CLI**. Clicking it shows the exact
`steward upgrade --repo ROOT --to VERSION` command and the CLI's detected installer command in a modal dialog; on
confirmation, a visible terminal runs `steward upgrade --to VERSION` with a clean environment, where the CLI asks
`[y/N]` before running its installer. When the terminal closes, the extension re-detects the CLI and runs its
contract check.

**Where am I?** is the same information as one page, for a project you come back to. It opens by itself once when
you reopen a project after more than 3 days (`bioSteward.whereAmI.showOnReopen`, `bioSteward.whereAmI.reopenAfterDays`),
or from the Today title bar. **Copy as Agent Brief** puts that page on the clipboard for a new agent session, with
the handoff cut to its first 40 lines. Making it runs only read commands.

### Approvals: what waits for your signature

<p align="center"><img src="https://raw.githubusercontent.com/MuizZer07/Bio-STEWARD/main/editors/vscode/media/readme/approvals.png" alt="The Approvals panel: an expired card, a waiting card with View exactly what you are approving and a Sign button, a skipped peer, and a peer's waiting card without buttons" width="88%"></p>

An agent can prepare a request for your signature (`steward authorize prepare`) but never sign it. The Approvals
panel turns each line of `steward authorize pending --all-projects` into a **card**: the action and its icon, the
project, the payload's short ID and its state (*waiting*, *signed*, *expired*), the summary and expiry as the CLI
printed them, and the payload's SHA-256, worked out from the payload file `.steward/pending/<nonce>.txt`. The line
itself is shown underneath, exactly as printed. The cards keep the CLI's order, the newest prepared payload first.
With steward 0.21 or newer each card also shows the payload's scope, budget, object, who asked, the peer, the
baseline, the CLI's payload hash and the tag a signature makes, from `steward authorize pending --format json`. The
title of a card opens a read-only details page.

- **View exactly what you are approving** opens that payload file read-only, unchanged. It is read inside the
  project only, never through a link, up to 1 MiB.
- **✍ Sign** appears on a waiting card of this project whose queue line matches its file. A peer project's card has
  no buttons: open that project to sign it.
- A card is **display only** (View, no ✍ Sign, and the reason) when its queue line cannot be tied to its file without
  doubt: a summary over several lines, another line with the same short ID (a peer's, for example), a line under
  another project's code, or a file that no longer gives the line the CLI printed.

### What ✍ Sign does, step by step

<p align="center"><img src="https://raw.githubusercontent.com/MuizZer07/Bio-STEWARD/main/editors/vscode/media/readme/sign-flow.png" alt="Six steps of Sign, the modal dialog with the action, summary, expiry, payload hash and exact command, and the box that asks for the action's name for high-stakes actions" width="96%"></p>

```mermaid
sequenceDiagram
  actor You
  participant P as Approvals panel
  participant CLI as steward (in a terminal)
  participant K as your key
  You->>P: ✍ Sign on a waiting card
  P->>P: read the file, steward authorize pending, the file again (same bytes? one line that matches them?)
  P-->>You: modal dialog: action, summary, expiry, SHA-256 (one read), the exact command
  You->>P: Sign in a Terminal (or Cancel: nothing runs)
  opt unseal, freeze.confirmatory, policy.change, waive, pin.retire, amend
    P-->>You: type the action's name
    You->>P: unseal (anything else: nothing runs)
  end
  P->>CLI: a new terminal runs steward authorize sign-pending --repo ROOT
  CLI-->>You: the exact bytes of each waiting payload, then "Sign …? [y/N]"
  You->>CLI: y (or n)
  CLI->>K: sign
  K-->>You: its own prompt: passphrase, agent confirmation or touch
  P->>P: terminal closed: read the queue again; the card turns ✓ Signed
```

1. **The card is checked again.** The button carries only the payload's nonce, the project's place in the window and
   the page it is on. Bio-STEWARD reads the payload file, the queue and the file again, and goes on only if the card
   is on the page now shown, the file still has the SHA-256 the card shows, and exactly one queue line, in this
   project, is the line the CLI prints for those bytes.
2. **A modal dialog asks you.** It shows the action, the summary, the expiry and the payload's SHA-256, all from that
   one read of the file, and the exact command it will run. It says plainly that the dialog is a snapshot and **the
   CLI's own prompt in the terminal is the review of record**. Only a person can answer it: **Sign in a Terminal** or
   **Cancel**. Cancel runs nothing and opens no terminal.
3. **For a high-stakes action you type its name.** For `unseal`, `freeze.confirmatory`, `policy.change`, `waive`,
   `pin.retire` and `amend`, a box asks you to type the action's name exactly. Any other text stops here.
4. **The CLI still shows the bytes and asks.** A new terminal runs the CLI's own
   `steward authorize sign-pending --repo ROOT`, with your environment as VS Code started; a workspace's
   `terminal.integrated.env.*` settings and other extensions' additions do not reach it. The CLI prints the exact bytes of each waiting payload of this project and asks *Sign …? [y/N]*
   before each signature. Answer no to anything you do not mean to approve; closing the terminal at that question
   signs nothing.
5. **Your key's prompt completes it.** The key's own confirmation (a passphrase, an SSH agent that asks, a hardware
   touch) completes each signature. When the terminal closes, the panel reads the queue again and the card turns
   **✓ Signed** if the CLI says so.

The extension never signs, never reads a key, and never adds the CLI's flag that skips its question. A command an
agent sends reaches the same dialog, which only a person can accept. `sign-pending` asks about each waiting payload
of the project in turn; signing one card alone needs a later CLI.

Which program signs is the CLI's business. CLI 0.20.7 signs with the pinned `ssh-keygen` whatever the repository's
git configuration says. With 0.20.6, `git tag -s` takes its signing program and key from your git configuration,
the repository's own `.git/config` included; use 0.20.7 or later for signing.

### Tasks, Tokens, Milestones and Drift, Decisions

<p align="center"><img src="https://raw.githubusercontent.com/MuizZer07/Bio-STEWARD/main/editors/vscode/media/readme/cockpit.png" alt="The Tasks, Tokens, Decisions, and Milestones and Drift panels in their full forms on CLI 0.22: the task board, tokens per task and model with the estimated cost, open questions and decisions newest first, and moved dates, scope, order and changes without a decision" width="88%"></p>

| Panel | In plain words |
|---|---|
| **Tasks** | every task of the project. With steward 0.21 or newer, the rows come from `steward task board`: `ID · file`, the status in the CLI's words, open first, then **Closed** and **Archived**. With an older CLI: every task file (the `[tasks]` table of `steward.toml`, or `development/tasks/**/*.md`), with the line that holds its `**Status:**` label **exactly as written**, marked *read from the file*. Open tasks first; closed ones under **Closed**, a display grouping by the rule of the CLI's R-57; in each, the file changed last comes first, then the highest ID. A file without a Status line shows nothing beside it. Files are found as the CLI lists them (no link, never `.git`); click to open the file, which is checked again first |
| **Tokens** | how many tokens your agents used **per task** and per model, newest first, read by `steward tokens report` from the agents' own log files on this machine. **Windows come from the records**: each sprint task's run (its sprint ledger), each `steward run`, the agents ledger, and the windows you start by hand (**Start Task Window…** and **Done Task Window…** run `steward task start ID` and `steward task done ID` after showing you the exact command). **Logs in one click**: where a log setting (`bioSteward.tokens.claudeLogs`, `…codexLogs`, `…geminiLogs`) is empty, the panel names that agent's usual folder for this project and offers **Use this folder**, which writes the setting in your user settings; nothing is read before you click. Each task shows its total, then its tokens by model (input, output, cache read, cache write), with the estimated cost where the CLI gives one, and says which windows and logs it covers. An empty panel says in one sentence which input is missing. **Total** is the sum of the tasks' totals. The logs are shared by every open project and the CLI matches them by time, not by project, so the **all activity** row is marked *shared* |
| **Decisions** | where the owner's decisions are written: the log `steward.toml` names (`[integrity] decisions`), or the CLI's default `development/DECISIONS.md`. **Open DECISIONS.md** opens it as it is (the first log that exists; a row says when that is not the first one configured, which the CLI's single-path commands use). With steward 0.21 or newer, **Open decisions** lists the questions still open with their options, and **Decisions** every dated decision, newest first; click one to open its log. The extension never writes a decision; you do, in your own words |
| **Milestones and Drift** | each milestone of `development/milestones.toml` with its state **in the CLI's own words** (*on track*, *at risk*, *late*, *due (record its outcome)*, *ready*, *met*, *moved*, *dropped*) and its days left or ago, the latest due date first. Click a row to open the milestones file. With steward 0.21 or newer, the drift follows: **Moved dates** (from the first due date to the current one, and whether a decision records it), **Scope**, **Order** and **Changes without a decision**. Dates change only in the milestones file, with a decision |

## 5. Working with agents

| You want | Use |
|---|---|
| your agent to see what failed | **Copy Summary for Agent**: the CLI's `steward check --summary` text with its re-check command. Use **Hand to Agent** on a result for `steward check --rule … --summary`, on a task for `steward task brief --for codex` or on a milestone for `steward next --brief`. Each copy is capped at 16 KiB and reports its size |
| a new agent session to pick up where the last one stopped | **Copy as Agent Brief** (Today): the Where am I? page, with the handoff's first 40 lines |
| to know what a task cost | run it as a sprint task (its window is recorded) or open a task window by hand, and choose **Use this folder** for your agent once (Tokens) |
| you and your agents to read one verdict | `bioSteward.report.location = auto` (the default) writes `.steward/report.json` when git ignores it, as `steward init` sets up |
| the next sprint task started | the Sprint view's **Copy Order Command** puts `steward sprint go ID TASK` on the clipboard; you run it |

Nothing the extension copies is typed into a terminal for you.

## Where the report goes

| `bioSteward.report.location` | File |
|---|---|
| `auto` (default) | `.steward/report.json` when git ignores it; otherwise the extension's own storage |
| `repository` | `.steward/report.json` |
| `extension` | the extension's storage only; nothing is written to the repository |

`auto` asks git one read-only question, `git check-ignore`, with the repository's fsmonitor and hooks forced off and
only `PATH`, `HOME` and `GIT_CONFIG_NOSYSTEM=1` in its environment. It is the only git command the extension runs.

Each check writes its report to a new file of its own; only a check that ends with a verdict (exit 0 – 3) and a
valid report replaces the saved one, in one step. A cancelled or failed check leaves the saved report as it was.

## Safety and its limits

| The extension | How |
|---|---|
| runs only listed commands | typed builders, no shell, `--repo` set, a timeout, one run at a time, the whole process tree stopped on cancel |
| shows nothing it cannot read | a report that fails the schema, or is too large, shows as *unreadable*, never as a partial dashboard |
| keeps paths inside the project | a path in a report that leaves the project (or a link that does) is not opened |
| renders report text as text | reasons and messages are never rendered as HTML or markdown links |
| runs git once, confined | only `git check-ignore`; a repository's own filter, fsmonitor and hook programs never run (tested). The Sprint view runs no git |
| keeps webview links few | Explain, Init Preview and Skills Preview each enable one command link. Two of them, **Review command and confirm…** in the previews, lead to a write: a documented exception that only opens a confirmation showing the exact command. The Approvals panel enables two: **View exactly what you are approving** and **✍ Sign**. Every webview has no scripts |
| never signs | no command signs, approves, unseals, spends or publishes by itself. **✍ Sign** opens a modal dialog first; only after you accept does a terminal run `steward authorize sign-pending --repo ROOT`, which asks again, and your key completes it |

The extension cannot stop an agent that has a shell from running the CLI, or anything else, itself. A signing key
is protected by the key's own confirmation (a passphrase, an SSH agent that asks, a hardware touch) and by the
[constitution](https://github.com/MuizZer07/Bio-STEWARD/blob/main/CONSTITUTION.md), not by the extension.

## Troubleshooting

| The view says | Do |
|---|---|
| No steward CLI was found | install `bio-steward`, or set `bioSteward.cliPath` in your user settings; **Re-detect CLI** |
| The CLI found is older than this extension supports | upgrade `bio-steward` to 0.20.6 or newer |
| This workspace is not trusted | **Manage Workspace Trust**; in Restricted Mode nothing runs |
| This folder has no steward.toml | **Initialize** opens the setup walkthrough |
| The output of the last run was unreadable | **Show Log** for the CLI's error output; run the check in a terminal to compare |
| The CLI found no steward.toml it accepts here | fix `steward.toml`; `steward check` in a terminal names the problem |

The **Bio-STEWARD** output channel (**Show Log**) holds the CLI found, the check commands the extension ran with
their exit codes, and the CLI's error output.

## More

- The extension's [README](https://github.com/MuizZer07/Bio-STEWARD/blob/main/editors/vscode/README.md): every
  command and setting.
- Its [changelog](https://github.com/MuizZer07/Bio-STEWARD/blob/main/editors/vscode/CHANGELOG.md).
- Cite Bio-STEWARD: [doi:10.5281/zenodo.24548977](https://doi.org/10.5281/zenodo.24548977).
