# Bio-STEWARD panels, in plain words

Bio-STEWARD shows what the `steward` CLI found in your project. It does not check anything itself, it calls no AI
model and it uses no network. Every panel reads what the CLI prints (the report that **Run Check** produces, or
another of its outputs), or a file the CLI or you wrote. Nothing runs in a workspace you have not trusted.

The panels are grouped by the job they help with, in one Bio-STEWARD container:

| Group | Panel | Answers | Reads |
|---|---|---|---|
| **Now** | **Today** | what needs me, and what changed since I looked? | `steward notifications`, `steward next` (older CLI: `steward audit progress`, `steward timeline`, the session handoff) |
| **Now** | **Approvals** | what waits for my signature? | `steward authorize pending --all-projects` (text, and `--format json` for the details) |
| **Quality** | **Overview**, **Results** | is this project's work checkable, and may it move on? | the report of **Run Check** |
| **Work** | **Tasks** | which tasks are open, and what changed last? | `steward task board` (older CLI: the task files' `Status:` lines) |
| **Work** | **Sprint** | what are the agents doing now? | the sprint file and its ledger, and `steward sprint status` |
| **Work** | **Tokens** | what did each task cost? | `steward tokens report` |
| **Direction** | **Milestones and Drift** | am I on plan? | `steward timeline` |
| **Direction** | **Decisions** | why did we decide what we did? | `steward decisions` and the log `steward.toml` names |
| **Agents** | **Agent Skills** | do my agents work by this project's rules? | the skill folders and rule R-60 |

With steward 0.21 or newer each panel shows its **full form**, from the versioned documents the CLI publishes. With
an older CLI each panel shows what that CLI offers, and a row says what needs a newer one. This help belongs to
extension 0.3.0, tested with steward 0.22.0.

**Every panel has a refresh button** (⟳) in its title bar. It runs that panel's CLI commands again at once, without
waiting for the panel's own timers, and shows a progress bar in the panel while they run.

**Newest first.** Every list puts the newest entry on top: by its date (the latest change), then by its ID, highest
first (`T10` comes before `T9`). Milestones are listed with the latest due date first; the countdown in the status
bar still names the nearest one. The dates and IDs are the CLI's (or a file's); the order is only how the list is
shown.

Click a Markdown file to preview it or another file to open it in the editor. Markdown rows offer **Open as Text**
and **Copy Path**. Other file rows offer **Reveal in Explorer**. Click a record to open its read-only details, with
its source, what it means and what to do next. Hover a row to see its inline buttons. More actions are available in
the row's context menu.

**Hand to Agent** copies up to 16 KiB of CLI text and reports the number of bytes copied and any truncation.
Paste the brief into your agent when you are ready.

Statuses always come with a word:

| Mark | Word | Means |
|---|---|---|
| ✓ | PASS | the rule's check passed |
| ✗ | FAIL | the rule found a problem to fix |
| ◐ | INCOMPLETE | something the rule needs is missing (a record, a field, a file) |
| ? | UNKNOWN | the check could not decide (a tool is missing, a file cannot be read) |
| – | NOT APPLICABLE | the rule does not apply: its area is not set up in this project |

## Now

### Today

Today shows what waits for you and what your agents are on, so each session starts where the work is.

**What it is:** what is waiting, for this project or for every open project. It answers: where did I leave off,
what is due next, and what waits for you. Each row names its source; the first row, **Sources**, lists them.

- **Notifications** sits at the top of Today, fed by `steward notifications --format json` (CLI upgrades, open exchange
  items, sprint tasks finished, failed or waiting for an order, approvals waiting, gates turned not eligible, and
  milestones at risk or late). Only which items you have read is kept, locally on this machine, keyed by each item's
  ID and content hash, so the same item is not news twice and comes back as unread only when the CLI reports a change
  to it. Expanding **Notifications** (or opening the status-bar bell) marks every item it showed as read and drops the
  unread count. Read items stay in the list, dimmed, below unread ones, newest first in each group; they never count
  again and never toast again. Each row has **Mark Read** / **Mark Unread**, the list has **Mark All Read**, and
  clicking a row opens its read-only details page with the CLI's next command. System toasts appear only for the three
  urgent kinds (a gate turned not eligible, an approval waiting, or a sprint task failed); turn them off with
  `bioSteward.notifications.toasts`. *Source: `steward notifications`.*

**With steward 0.21 or newer** (the full form), every row comes from `steward next`:
- **Resume**: your last session handoff, how old it is, and whether it is committed; open it for its *Next* and *Open
  decisions* lines. Click it to read the handoff as written.
- **Next milestone**: the next milestone, its days and state, and what blocks it (rules, tasks, exchange items,
  signatures), each with the command that moves it.
- **Waiting on you** (signatures, decisions, exchange items, sprint tasks waiting for your order) and **Waiting on
  agents** (sprint tasks running, ordered, finished or failed). **Newest first:** by time, then the highest ID. Hover
  a row for its source and its next step, the exact CLI command.
- **Needs tidying**: how many stale tasks, stale pages, leftovers and the like `steward tidy` would list. Agents name
  them and ask before archiving anything.
- The CLI's notes (a peer it could not check, for example).
- With several projects open, the project with the most waiting on you comes first, then the most waiting on agents.

**With an older CLI**, Today is composed from these sources instead:

- **Resume** opens your last session handoff (`development/HANDOFF.md` unless `steward.toml` names another file),
  in the Markdown preview. **Open as Text** shows the source. *Source: the session handoff.*
- **Next milestone** is the countdown of the status bar: the soonest milestone without an outcome, its days and its
  state (on track, at risk, late, …). Click it for details, or use **Show What Blocks This Milestone**.
  *Source: `steward timeline`.*
- **Signatures waiting**, **Exchange items open here**, **This project's own requests still open**, **Sprints with
  open tasks** and **Milestones** are the lists of the "Pending" section of `steward audit progress`, item by item as
  the CLI wrote them. Items with IDs come highest ID first, milestones latest due first; signatures keep the CLI's
  order (it gives them no date). A signature is something only you can give: you sign in a terminal (`steward
  authorize pending` lists them). *Source: `steward audit progress`.*
- A signature row opens Approvals from its action. A sprint row opens Sprint or copies the order for the sole
  waiting task. Exchange rows offer **Open Exchange Item**, **Mark Read**, **Respond…** for a received item, and
  **Copy Pull Command** for an item on a peer. Read markers are local to this workspace. The response opens as an
  editable draft and the pull command is for you to run.
- With several projects open, each project has its own block, and their rows are never mixed. Projects are ordered by
  the counts audit progress reports: signatures waiting first, then exchange items open, then your own open requests,
  then sprints with open tasks (more comes first; ties keep the workspace order). This is a plain order of counts,
  not a judgement of urgency.

If `steward next` gives no readable answer, a row says so and the panel shows these sources. What waits on agents
and what needs tidying need steward 0.21 or newer: **Upgrade CLI**.

**Use it:** first thing in a session, to see what only you can do. Buttons: **Where am I?**, **Copy as Agent
Brief**, **Mark All Read**, **Refresh**.

### Where am I?

**What it is:** a one-page reset for a project you come back to. It is shown by itself, once, when you open a
project again after more than 3 days (the settings `bioSteward.whereAmI.showOnReopen`, on by default, and
`bioSteward.whereAmI.reopenAfterDays`). Run **Bio-STEWARD: Where am I?** any time. With several projects open, it
first lists them, in the Today order.

Each part of the page names where it comes from:

| Part | Source |
|---|---|
| Last open in VS Code | kept by the extension on this machine, never written to the repository |
| Where it stands (branch, versions, known issues) | `steward audit progress` |
| Gate | the last `steward check` report of this session, with its freshness |
| You left off | the session handoff, quoted as written |
| Next target | `steward timeline` |
| Waiting on you, waiting on others, sprints, milestones | `steward audit progress` (older CLI) |
| Waiting on you, waiting on agents, needs tidying, notes | `steward next` (steward 0.21 or newer), each with its next step |

**Copy as Agent Brief** copies the same page for a new agent session, with the handoff cut to its first 40 lines.
The page is read-only, and making it runs only read commands.

### Approvals

Approvals lists what your agents prepared that only you can sign, with the exact text you approve.

**What it is:** what waits for **your signature**, in this project and in the peers its `[exchange]` table names. An
agent can prepare a payload (`steward authorize prepare`) but never sign it: only you can, with your own key. The
panel is built from the text of `steward authorize pending --all-projects`, and each payload line becomes a
**card**, newest first as the CLI prints them. Every card also shows that line **exactly as the CLI printed it**.

Each card shows:
- the action, with an icon (💳 spend, 🔓 unseal, ✏️ amend, ❄️ freeze, ⚐ waive, ⚖️ policy change, ⚓ anchor, 📌 pin), the
  project code, the first 12 characters of the payload's nonce and its state;
- the summary and the expiry, as the CLI printed them;
- the payload's **SHA-256**, *read from the file* `.steward/pending/<nonce>.txt`;
- **View exactly what you are approving**, which opens that file read-only, its text unchanged, labelled *read from
  the file*. It is read inside the project only, never through a link, and only up to 1 MiB;
- **✍ Sign** on a *waiting* payload whose queue line matches its file; a signed one shows **✓ Signed** with its tag,
  an expired one says so.

Click the action name to open the approval's read-only Markdown details. For a peer payload, open its project to
review the exact payload and sign.

A card is **display only** (View, but no ✍ Sign, and the reason) when the queue line cannot be tied to the file
without doubt: a summary over several lines, another queue line with the same nonce prefix (a peer's, for example),
a line under another project's code, or a file that no longer gives the line the CLI printed. Read the payload, then
run `steward authorize sign-pending` yourself if you mean to sign it.

**What ✍ Sign does:**
1. Bio-STEWARD reads the payload file, `steward authorize pending` and the file again, and acts only if the card is
   on the page now shown, the file has the SHA-256 the card shows, and the queue line is the one the CLI prints for
   those bytes. The button's link carries only the nonce, the project's place in the window and the page it is on;
   it is never trusted.
2. A **modal** dialog, *Sign spend in geo?* for example, shows the action, the summary, the expiry and the payload's
   SHA-256 (all from that one read of the file) and the exact command it will run. The dialog is a snapshot: **the
   CLI's own prompt in the terminal is the review of record**. Only a person can answer it: **Sign in a Terminal** or
   **Cancel**.
   For unseal, freeze.confirmatory, policy.change, waive, pin.retire and amend a box then asks you to type the
   action's name (for example `unseal`); any other text stops here.
3. Only then does a new terminal open and **run** the CLI's own `steward authorize sign-pending --repo ROOT`, with
   your own environment as VS Code started (a workspace's `terminal.integrated.env.*` settings do not reach it). The
   CLI prints the exact bytes of each waiting payload of this project and asks *Sign …? [y/N]* before each signature,
   so you see the bytes and answer once more. Answer no to anything you do not mean to approve. Your key's own
   prompt (a passphrase, an agent confirmation or a hardware touch) completes each signature.
4. When the terminal closes, the queue is read again and the card turns **✓ Signed** if the CLI says so. Closing the
   terminal at the CLI's question signs nothing.

The extension never signs, never reads a key, and never adds the CLI's flag that skips its question. Declining the
dialog, or typing a different name, runs nothing and opens no terminal. A command run by an agent reaches the same
dialog and nothing else. With several projects open, each has its own block, in the Today order. The panel's badge
counts the waiting payloads.

**With steward 0.21 or newer**, each card also shows the payload's scope, budget, object, who asked, the peer, the
baseline, the payload's SHA-256 as the CLI computed it and its signed tag, from `steward authorize pending
--all-projects --format json` (matched to the card by project and nonce). These are shown only; ✍ Sign still binds
to the queue line and the file as above. Signing one card alone (`authorize sign NONCE --expect-sha256 HASH`, a request to the CLI)
comes later; until then the CLI asks about each waiting payload in turn.

**Use it:** at the end of the day, to look at each request and sign what you mean to approve.

## Quality

### Overview

Overview shows whether your agents' work passes this project's checks and may move on.

**What it is:** the verdict for this project, on one screen.

- **steward 0.22.0 · full mode** names the CLI the extension found and what it can do with it. *Full* means the CLI
  publishes its machine interface (`steward interface`); *limited* is an older CLI without it (0.20.x).
- **Upgrade CLI** appears when `steward upgrade --check --format json` finds a newer version from a local release
  notice (no network call by the extension). Clicking it shows the exact `steward upgrade --repo ROOT --to VERSION`
  command and the installer the CLI detected in a modal dialog. Only after you confirm does a visible terminal run
  `steward upgrade --to VERSION`, where the CLI asks `[y/N]` before running the installer. When the terminal closes,
  Bio-STEWARD re-detects the CLI and runs its contract check (interface, notifications, upgrade check and report
  schema).
- **Report** says how fresh the verdict is. *fresh* means made just now and nothing has changed since. *stale* means
  a project file changed: run the check again. *unknown* means the extension cannot tell (for example, a report from
  an earlier session).
- **Gate** is the question "may this project move on (merge, release, submit)?". **ELIGIBLE** means every result
  the gate requires passed or does not apply. **NOT ELIGIBLE** lists the **blocking** results; fix those first.
  **Waived** lists results someone signed off on.
- **Counts** and **Worst status** sum up every result.
- **Coverage** says which areas are set up and which were not checked. A green gate covers only what was checked; it
  never means the science is right.

**Use it:** after each agent turn, glance at the gate. Click a gate or blocking result for its details. Use
**Explain Rule**, **Open the Finding File**, **Hand to Agent** or **Run Check for Rule** on a result.
Buttons: **Run Check**, **Resume** (your last session handoff), **Copy for Agent** (a short summary to paste to your
agent) and **Refresh**, which runs `steward check` again.

### Results

Results lists every check result, so you can hand one problem at a time to an agent.

**What it is:** every individual result, one row per rule and subject. Group the rows by **status** (problems
first), by **gate**, or by **file**.

- Open a row for the rule's reason, its details (the codes it reported), the files it looked at, and the gates it
  blocks.
- **Explain Rule** describes the rule. **Hand to Agent** copies its `steward check --rule … --summary` output,
  **Run Check for Rule** evaluates it again, and **Open the Finding File** opens the file at the reported location.
- A result that names a file also appears in VS Code's **Problems** panel (FAIL as an error, INCOMPLETE as a
  warning), at the file and the line when the CLI gives one.
- **Refresh** runs `steward check` again.

**Use it:** to work through the problems one by one, or to hand a single rule to your agent.

## Work

### Tasks

Tasks lists every task your agents work on, the latest change first.

**What it is:** every task of the project, not only sprint tasks.

**With steward 0.21 or newer** (the full form), the rows come from `steward task board --format json`, and the first
row says **Tasks · steward task board**. Each row is `ID · file name` with the task's status **in the CLI's words**
(the status without its qualifier; `(none)` when the file has none), *closed* or *archived* as the CLI decides it.
Open tasks come first, then **Closed (n)** and **Archived (n)**; in each, the task file changed last comes first,
then the highest ID. If the board gives no readable answer, a row says so and the panel lists the files as below.

**With an older CLI**, the panel reads the files themselves and says so on its first row, **Task files**:

- Each row is a task file, by name. Next to it is the line that holds its `**Status:**` label, **exactly as written**,
  marked *read from the file*: not checked, not reworded. A file without a Status line shows nothing there.
- **Newest first:** the file changed last comes first (its modification time), then the highest ID (the file's
  `**ID:**` line, or its name).
- Files are found as the CLI lists them: never through a link and never in `.git`. Clicking a row checks the file
  again before it opens.
- Which files count as tasks comes from the `[tasks]` table of `steward.toml` (its `specs`, minus its `archive` and
  the board). Without that table, the CLI's default is used: `development/tasks/**/*.md`.
- Open tasks come first. **Closed (n)** is a *display grouping*, not a CLI result: the files whose status is closed by
  the rule the CLI's R-57 uses (a status of `[tasks] statuses`, also with a qualifier such as `done (merged)` or
  `done — see the release notes`, that is one of `[tasks] closed`, `done` by default). Like R-57, it takes the value
  from the next line when the label stands alone. Without a `[tasks]` table R-57 does not apply, and the CLI's
  default statuses are used for the grouping only.
- The **Start Task Window…** list offers the IDs of the files' `**ID:**` lines, also read from the files; **Another
  task ID…** lets you type one.
- Click a row to preview the task Markdown. **Hand to Agent** uses `steward task brief --for codex`.
  The row menu offers **Start Task Window…**, **Done Task Window…** and **Dispatch with Codex…**. Dispatch shows
  the exact review command and asks before copying it for you to run.
- With several projects open, each has its own block, in the Today order.

A task's tokens and windows are in **Tokens**; what is stale is under **Needs tidying** in Today.

**Use it:** to see what is open across the project at a glance, and to open a task's file.

### Sprint

Sprint shows what each agent of a running sprint is doing and which of its checks passed.

**What it is:** a live view of a running sprint. A sprint is a list of agent tasks that `steward sprint` starts one
by one, when you give the order.

- Each task shows its state: *planned*, *ready* (waiting for your order), *running*, *checking*, *done*, *failed*,
  *held* or *skipped*. It also shows how long it has run against its time limit, and, when it ends, each acceptance
  command with its exit code. **The task is done only when those commands pass, never because the agent says so.**
- **Newest first:** the task whose ledger entry is the latest comes first, then the highest ID, as `steward sprint
  status` prints them. With several sprints, the one with the latest ledger entry comes first.
- A state marked *derived* was worked out from the plan (for example, "ready" because the tasks it waited for are
  done); the rest come straight from the sprint's ledger.
- Click a sprint, task, event or check for its details. **Show Run Log** opens the log referenced by the ledger.
  **Copy Order Command** and **Copy Hold Command** put a command on the clipboard for you to run. For a completed
  task, **Show Diff Range** displays a comparison command when the ledger contains both revisions.
- *incomplete* means a line of the ledger could not be read, so the view may be behind. It sends no "finished"
  notification from such a view.
- **With steward 0.21 or newer**, each task also shows what `steward sprint status --format json` reads from git:
  its current step (the last tool call in its log), its **Commits** (newest first), its **Changed files**, what is
  still **Uncommitted**, and its task and run logs. The view itself still runs no git: the CLI does, at most every 10
  seconds while the ledger changes.
- **Refresh** reads the sprint file and the ledger again at once (otherwise at most once a second), and asks the CLI
  for the status again.

**Use it:** while agents work, to see what is running, what waits for you, and what passed.

### Tokens

Tokens shows what each agent task cost, counted from the agents' own logs on this machine.

**What it is:** how many tokens your agents used, **per task** and per model, read by `steward tokens report` from
the agents' own log files on this machine (with steward 0.21 or newer, its versioned document, `--format json`).
Nothing leaves the machine, and the extension calls no model.

- **Two inputs.** A task's tokens are the usage logged in the agents' logs during that task's windows. When one is
  missing, the panel's first row says which, in one sentence, and clicking it opens the fix.
- **The logs, in one click.** The CLI reads only the logs it is given, from three user settings:
  `bioSteward.tokens.claudeLogs` (Claude Code), `bioSteward.tokens.codexLogs` (Codex) and
  `bioSteward.tokens.geminiLogs` (Gemini CLI). Where a setting is empty, the panel names that agent's usual folder for
  this project and offers **Use this folder**: `~/.claude/projects/<this project's path, with each character other
  than a letter or a digit as ->` for Claude Code, `~/.codex/sessions` for Codex, and `~/.gemini/tmp/<the SHA-256 of
  this project's path>` for Gemini CLI. The folder is worked out from names only: **nothing is read before you
  click**. The click writes that one setting in your user settings (machine scope; a repository cannot set it), then
  reads the report. You can also edit the settings yourself (**Agent log settings**); a folder gives its newest
  `.jsonl` and `.json` files, at most 50. These folders follow the agents' current log layouts, which may change.
- **Windows from the records.** With steward 0.22, each sprint task's run is a window (from its sprint ledger: from
  *running* to *done*, *failed* or skipped), and so is each `steward run` (the run ledger), with no step by you. The
  agents ledger and the windows you start and close by hand count too. A window is also the time between
  `steward task start ID` and `steward task done ID`: **Start Task Window…** and **Done Task Window…** (title bar, a Tokens
  row, or a Tasks row) run those commands: the extension first shows the exact command line and runs it only when you
  confirm. The CLI records the time in `.steward/task-tokens.jsonl`. Before any window exists, the CLI reports **all
  activity**.
- **Each task** shows its total, the estimated cost where the CLI gives one (when `[spend]` prices every model of
  the task), and the CLI's status (*available*, *partial*: some records were missing or matched more than one task,
  *unavailable*: no counts in its windows). Hover it for what the total covers: its windows and their records, and
  the logs read. Open it for its tokens **by model** (input, output, cache read, cache write, and the model's
  estimated cost where given), its **Windows** (newest first, each with its record), and the files read most.
- **Order:** newest first: the task whose latest window started last comes first, then the highest label.
- **Total** is the sum of the tasks' totals, each the CLI's, added up by the extension, with the estimated cost of
  the tasks the CLI priced; tasks without counts add nothing and are named.
- **Row actions.** **Show the Per-Model Split** opens the CLI's input, output, cache read, cache write and available
  cost; **Open the Task** previews the matching task file.
- **Sources** lists the logs the CLI read, by its own names ("claude log 1"): it never prints their paths. The rows
  show what the CLI prints: counts, model names and the relative paths of files the agents read.
- **Shared activity.** The logs are this machine's, the same for every open project, and the CLI matches records to a
  window by time, agent, model and session, not by project. Another project's work in the same period can count
  too; the **all activity** row is marked *shared*.
- A file is passed to the CLI only if, when the CLI starts, it is still inside the file or folder you named and
  reached without a link.

Totals per sprint and per day come with the token trends of a later release.

**Use it:** let the sprint record the windows (or start one when an agent picks up a task by hand), and see what
each task cost.

## Direction

### Milestones and Drift

Milestones and Drift shows whether the work your agents do keeps to the plan, the latest target first.

**What it is:** whether the project is keeping to its plan. Each row is a milestone of `development/milestones.toml`
with its state **in the CLI's own words**, as `steward timeline --json` gives it, and its days left or ago. The
extension computes nothing.

| State (the CLI's word) | Means |
|---|---|
| *on track* | open work remains (or the milestone tracks nothing), and the internal deadline (due minus its buffer) has not passed |
| *at risk* | work is still open after the internal deadline, or, in its last week, more than three pieces of open work a day remain |
| *late* | the due time has passed with work still open |
| *due (record its outcome)* | the due time has passed and no work is open: record what happened (met, moved, dropped) |
| *ready* | nothing is open and the due time is ahead |
| *met*, *moved*, *dropped* | the outcome recorded in `milestones.toml` |

- **Newest first:** the latest due date comes first. The countdown in the status bar still names the nearest
  milestone without an outcome.
- Click a row for its due date, internal deadline, open work and outcome. **Open the Milestones File** opens
  `development/milestones.toml`. **Show What Blocks This Milestone** displays the CLI's blocker details.
  **Hand Blockers to Agent** copies the project-wide text from `steward next --brief` (CLI 0.21 or newer).
- With several projects open, each has its own block, in the Today order, with a count of each state.
- Dates change only in `milestones.toml`, with a decision in the decisions log.

**With steward 0.21 or newer**, the panel reads `steward timeline --format json` and adds its drift fields after the
milestones, one group each, in the CLI's words:
- **Moved dates:** each milestone whose due date moved, from its first due date to the current one, by how many days
  and how many times, and whether a decision records the move (from the git history of `milestones.toml`). The
  latest due first.
- **Scope:** tasks no milestone names, tasks a milestone names that have no file, dropped tasks, and roadmap items
  with no task.
- **Order:** a later milestone whose work started while an earlier one is still open.
- **Changes without a decision:** plan changes in the history with no recorded decision, newest first.

A note says when the history is shallow or partial.

**Use it:** to see which target needs attention first.

### Decisions

Decisions keeps the owner's decisions one click away, so you and your agents work from the same record.

**What it is:** where the project's owner decisions are written down: its **decisions log**. The panel names the log
and opens it. With steward 0.21 or newer, it also lists what `steward decisions --format json` reads (see below).

- The row is the decisions log, as `steward.toml` names it: `[integrity] decisions` (a path, a list or globs). Without
  an `[integrity]` table, the CLI uses `DECISIONS.md` in the `[paths] records` folder, which is `development` unless
  you set it, so the default is `development/DECISIONS.md`. Several logs keep the configured order.
- **Open DECISIONS.md** (title bar or project row) previews the log. Click a file row to preview that log. With several logs, the first one that exists opens; when that is not the first one configured
  (the one the CLI's single-path commands use), a row says so.
- Logs are found as the CLI lists project files: never through a link and never in `.git`, and a log is checked
  again when it opens. A glob that matches nothing is named; if the search stops at its limit, a row says so.
- A log that is named but missing shows *not found*. The extension does not create it: `steward init` writes one,
  or you start it.
- **Record Decision…** opens the log at the end and starts a dated entry. Fill in the verbatim quote, decision and
  consequences. R-38 checks that earlier entries are preserved.
- With several projects open, each has its own block, in the Today order.

**With steward 0.21 or newer**, two groups follow the logs:
- **Open decisions (n):** the questions still open in the records (the index page and the handoff), each with its
  options.
- **Decisions (n):** every dated decision in the log, **newest first** (the latest date; on one date, the entry
  written later first), with its decision line; hover for the whole entry and its place (file and line). Click one to
  open its log.

**Record decision…** opens the log at a dated, started entry.

**Use it:** to read what was decided before you change a plan, and to write down a new decision.

## Agents

### Agent Skills

Agent Skills shows whether every agent in this project reads the same working rules.

Click a folder, skill or finding to see its details. The R-60 finding offers rule explanation, a scoped re-check
and a CLI brief for your agent.

**What it is:** Agent Skills are instruction files (`SKILL.md`) that coding agents such as Claude Code or Codex
read. They teach an agent this project's working rules: how to run checks, write a task, review a paper, keep a
benchmark honest. Bio-STEWARD ships a set of skills, and each agent tool looks for skills in its own folder, for
example `.claude/skills` for Claude Code and `.agents/skills` for others.

- The panel lists the skill folders it found in the project, and how each is set up. The first folder holds the
  real copy, and the others **link** to it, so every agent reads the same instructions.
- **drift** means a copy no longer matches the original: two agents would get different instructions. Fix it by
  replacing the copy with a link (the CLI's rule R-60 reports this).
- **Install Skills** puts the skills into the folders you choose. It previews what it will create first, and it never
  overwrites a file.
- **Copy as Agent Brief** (the agent brief of Where am I?) copies a bounded orientation for a new agent session.
- **Refresh** lists the skill folders again; **Check Skills** runs the CLI's R-60.

**Use it:** once per project, so your agents work by the same rules. Check it again if an agent behaves oddly.

## Status bar

The shield item shows one gate (`bioSteward.gate`, default `default`), whether it is ELIGIBLE, the number of
blocking results and the freshness. Click it to open the Overview. A second item counts down to the nearest
milestone of `steward timeline`. A third appears while a sprint runs. The **bell** item shows the unread notification
count from `steward notifications --format json` across open projects; clicking it opens the notifications list and
marks every item it showed as read.

## Where to read more
- The user guide: `docs/guides/vscode.md` in the Bio-STEWARD repository (and the project site).
- The extension's README: the **Details** tab of Bio-STEWARD in the Extensions panel.
- **Bio-STEWARD: Show Log** lists every CLI call the extension made.
