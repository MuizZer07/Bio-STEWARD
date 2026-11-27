# Bio-STEWARD panels, in plain words

Bio-STEWARD shows what the `steward` CLI found in your project. It does not check anything itself, it calls no AI
model and it uses no network. Every panel reads what the CLI prints (the report that **Run Check** produces, or
another of its outputs), or a file the CLI or you wrote. Nothing runs in a workspace you have not trusted.

| Panel | Answers | Reads |
|---|---|---|
| **Today** | what waits, and for whom? | `steward audit progress`, `steward timeline`, the session handoff |
| **Approvals** | what waits for my signature? | `steward authorize pending --all-projects` |
| **Tasks** | which tasks are open? | the task files' `Status:` lines |
| **Tokens** | what did each task cost? | `steward tokens report --json` |
| **Decisions** | where are the decisions written? | `steward.toml` (it opens the log) |
| **Drift** | which target needs attention? | `steward timeline --json` |
| **Overview**, **Results** | may the project move on, and why not? | the report of **Run Check** |
| **Agent Skills** | do my agents read the same rules? | the skill folders and rule R-60 |
| **Sprint** | what are the agents doing now? | the sprint file and its ledger |

Today, Approvals, Tasks, Decisions and Drift are **reduced** forms in this version: each shows only what the
installed CLI (0.20.6) already prints, and says so on its first row. Their full forms come with a newer CLI.

Statuses always come with a word:

| Mark | Word | Means |
|---|---|---|
| ✓ | PASS | the rule's check passed |
| ✗ | FAIL | the rule found a problem to fix |
| ◐ | INCOMPLETE | something the rule needs is missing (a record, a field, a file) |
| ? | UNKNOWN | the check could not decide (a tool is missing, a file cannot be read) |
| – | NOT APPLICABLE | the rule does not apply: its area is not set up in this project |

## Today

**What it is:** what is waiting, for this project or for every open project. It answers: where did I leave off,
what is due next, and what waits for you. This is the **reduced** form: it is built from what the installed CLI
(0.20.6) already prints, and each row names its source. The full form arrives with `steward next`, a newer CLI.

- **Resume** opens your last session handoff (`development/HANDOFF.md` unless `steward.toml` names another file),
  exactly as written. *Source: the session handoff.*
- **Next milestone** is the countdown of the status bar: the soonest milestone without an outcome, its days and its
  state (on track, at risk, late, …). Click it for every milestone. *Source: `steward timeline`.*
- **Signatures waiting**, **Exchange items open here**, **This project's own requests still open**, **Sprints with
  open tasks** and **Milestones** are the lists of the "Pending" section of `steward audit progress`, item by item as
  the CLI wrote them. A signature is something only you can give: you sign in a terminal (`steward authorize
  pending` lists them). *Source: `steward audit progress`.*
- With several projects open, each project has its own block, and their rows are never mixed. Projects are ordered by
  the counts audit progress reports: signatures waiting first, then exchange items open, then your own open requests,
  then sprints with open tasks (more comes first; ties keep the workspace order). This is a plain order of counts,
  not a judgement of urgency.

**Use it:** first thing in a session, to see what only you can do. Buttons: **Where am I?**, **Copy as Agent
Brief**, **Refresh Today**.

## Where am I?

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
| Waiting on you, waiting on others, sprints, milestones | `steward audit progress` |

"Since then", recent decisions, drift and "needs tidying" are not in the reduced form; they come with `steward next`.

**Copy as Agent Brief** copies the same page for a new agent session, with the handoff cut to its first 40 lines.
The page is read-only, and making it runs only read commands.

## Approvals

**What it is:** what waits for **your signature**, in this project and in the peers its `[exchange]` table names. An
agent can prepare a payload (`steward authorize prepare`) but never sign it: only you can, with your own key. This is
the **reduced** form: it is built from `steward authorize pending --all-projects` (CLI 0.20.6 has no JSON form for it
yet), and each payload line becomes a **card**. Every card also shows that line **exactly as the CLI printed it**.

Each card shows:
- the action, with an icon (💳 spend, 🔓 unseal, ✏️ amend, ❄️ freeze, ⚐ waive, ⚖️ policy change, ⚓ anchor, 📌 pin), the
  project code, the first 12 characters of the payload's nonce and its state;
- the summary and the expiry, as the CLI printed them;
- the payload's **SHA-256**, *read from the file* `.steward/pending/<nonce>.txt`;
- **View exactly what you are approving**, which opens that file read-only, its text unchanged, labelled *read from
  the file*. It is read inside the project only, never through a link, and only up to 1 MiB;
- **✍ Sign** on a *waiting* payload whose queue line matches its file; a signed one shows **✓ Signed** with its tag,
  an expired one says so.

A payload of a peer lives in the peer's checkout: its card has no buttons. Open that project to view and sign it.

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

Not in the reduced form: the scope, budget, object hash and who asked, read from the CLI. They come with
`authorize pending` as JSON in a newer CLI. Signing one card alone (`authorize sign NONCE --expect-sha256 HASH`, a
request to the CLI) comes later; until then the CLI asks about each waiting payload in turn.

**Use it:** at the end of the day, to look at each request and sign what you mean to approve.

## Tasks

**What it is:** every task file of the project, not only sprint tasks. This is the **reduced** form: the installed
CLI (0.20.6) does not print the task board yet, so the panel reads the files themselves and says so.

- Each row is a task file, by name. Next to it is the line that holds its `**Status:**` label, **exactly as written**,
  marked *read from the file*: not checked, not reworded. A file without a Status line shows nothing there.
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
- Click a row to open the file. Right-click it for **Start Task Window…**, which counts the tokens of that task
  (see Tokens).
- With several projects open, each has its own block, in the Today order.

Not in the reduced form: each task's window, owner and implementer, and "stale" marks. They come with the task
board as JSON in a newer CLI.

**Use it:** to see what is open across the project at a glance, and to open a task's file.

## Tokens

**What it is:** how many tokens your agents used, **per task window** and per model, read by `steward tokens
report --json` from the agents' own log files on this machine. Nothing leaves the machine, and the extension calls no
model.

- **Set it up once.** The CLI reads only the logs it is given. Add your agents' log files or folders to your user
  settings: `bioSteward.tokens.claudeLogs` (Claude Code, usually `~/.claude/projects/<this project's folder>`),
  `bioSteward.tokens.codexLogs` (Codex, `~/.codex/sessions`), `bioSteward.tokens.geminiLogs` (Gemini CLI,
  `~/.gemini/tmp/<this project's hash>`). A folder gives its newest `.jsonl` and `.json` files, at most 50. A
  repository cannot set these. Until one is set, the panel says **No agent logs selected**; click it to open the
  settings.
- **Task windows.** A window is the time between `steward task start ID` and `steward task done ID`. Tokens used in
  that time count for that task. **Start Task Window…** and **Done Task Window…** (title bar, a Tokens row, or a Tasks
  row) run those commands: the extension first shows the exact command line and runs it only when you confirm. The
  CLI records the time in `.steward/task-tokens.jsonl`. Before any window exists, the CLI reports **all activity**.
- Each task row shows its tokens and the CLI's status (*available*, *partial*: some records were missing or matched
  more than one task, *unavailable*: no counts in the window). Open it for each agent and model (input, output, cache
  read and write) and the files read most. Costs appear only when `[spend]` prices the model.
- **Total** is the sum of the rows, added up by the extension; rows without counts add nothing and are named.
- **Sources** lists the logs the CLI read, by its own names ("claude log 1"): it never prints their paths. The rows
  show what the CLI prints: counts, model names and the relative paths of files the agents read.
- **Shared activity.** The logs are this machine's, the same for every open project, and the CLI matches records to a
  window by time, agent, model and session, not by project. Another project's work in the same period can count
  too; the **all activity** row is marked *shared*.
- A file is passed to the CLI only if, when the CLI starts, it is still inside the file or folder you named and
  reached without a link.

Not yet: totals per sprint and per day (they need a newer CLI).

**Use it:** start a window when an agent picks up a task, close it when the task is done, and see what the task cost.

## Decisions

**What it is:** where the project's owner decisions are written down: its **decisions log**. This is the **reduced**
form: it names the log and opens it, nothing more. The installed CLI (0.20.6) has no command that lists the
decisions, so the panel does not read or list the entries.

- The row is the decisions log, as `steward.toml` names it: `[integrity] decisions` (a path, a list or globs). Without
  an `[integrity]` table, the CLI uses `DECISIONS.md` in the `[paths] records` folder, which is `development` unless
  you set it, so the default is `development/DECISIONS.md`.
- **Open DECISIONS.md** (title bar, or a project's row) opens the log in the editor, **as it is**. Click a row to
  open that log. With several logs, the first one that exists opens; when that is not the first one configured
  (the one the CLI's single-path commands use), a row says so.
- Logs are found as the CLI lists project files: never through a link and never in `.git`, and a log is checked
  again when it opens. A glob that matches nothing is named; if the search stops at its limit, a row says so.
- A log that is named but missing shows *not found*. The extension does not create it: `steward init` writes one,
  or you start it.
- The extension never writes a decision. You write it in the log, in your own words; the log is append-only (the
  rule R-38 checks that earlier entries are not changed).
- With several projects open, each has its own block, in the Today order.

Not in the reduced form: open decisions first, then the log, newest first and searchable, and **Record decision…**
(the log opened at a dated, started entry). They come with `steward decisions --format json` in a newer CLI.

**Use it:** to read what was decided before you change a plan, and to write down a new decision.

## Drift

**What it is:** whether the project is keeping to its plan. This is the **reduced** form: **the timeline states
only**. Each row is a milestone of `development/milestones.toml` with its state **in the CLI's own words**, as
`steward timeline --json` gives it, and its days left or ago. The extension computes nothing.

| State (the CLI's word) | Means |
|---|---|
| *on track* | open work remains (or the milestone tracks nothing), and the internal deadline (due minus its buffer) has not passed |
| *at risk* | work is still open after the internal deadline, or, in its last week, more than three pieces of open work a day remain |
| *late* | the due time has passed with work still open |
| *due (record its outcome)* | the due time has passed and no work is open: record what happened (met, moved, dropped) |
| *ready* | nothing is open and the due time is ahead |
| *met*, *moved*, *dropped* | the outcome recorded in `milestones.toml` |

- The rows keep the CLI's order (soonest due first). Hover a row for its due date, internal deadline, open work and
  what blocks it, as the CLI reports it. Click it to open `development/milestones.toml`.
- With several projects open, each has its own block, in the Today order, with a count of each state.
- Dates change only in `milestones.toml`, with a decision in the decisions log.

Not in the reduced form: drift itself (dates that moved and by how much, tasks outside any milestone, work started
out of order, changes without a decision). It comes with drift in `steward timeline --format json` in a newer CLI.

**Use it:** to see which target needs attention first.

## Overview

**What it is:** the verdict for this project, on one screen.

- **steward 0.20.6 · limited mode** names the CLI the extension found and what it can do with it. "Limited" is
  normal on 0.20.6: richer views arrive with a newer CLI.
- **Report** says how fresh the verdict is. *fresh* means made just now and nothing has changed since. *stale* means
  a project file changed: run the check again. *unknown* means the extension cannot tell (for example, a report from
  an earlier session).
- **Gate** is the question "may this project move on (merge, release, submit)?". **ELIGIBLE** means every result
  the gate requires passed or does not apply. **NOT ELIGIBLE** lists the **blocking** results; fix those first.
  **Waived** lists results someone signed off on.
- **Counts** and **Worst status** sum up every result.
- **Coverage** says which areas are set up and which were not checked. A green gate covers only what was checked; it
  never means the science is right.

**Use it:** after each agent turn, glance at the gate. Click a blocking result to see the file and the rule.
Buttons: **Run Check**, **Resume** (your last session handoff), and **Copy for Agent** (a short summary to paste to
your agent).

## Results

**What it is:** every individual result, one row per rule and subject. Group the rows by **status** (problems
first), by **gate**, or by **file**.

- Open a row for the rule's reason, its details (the codes it reported), the files it looked at, and the gates it
  blocks.
- Right-click a result: **Explain Rule** shows what the rule checks, why, what a PASS does *not* mean, and how to
  fix it. **Copy for Agent** copies just that rule's summary. **Run Check for Rule** re-checks only that rule.
- A result that names a file also appears in VS Code's **Problems** panel (FAIL as an error, INCOMPLETE as a
  warning), at the file and the line when the CLI gives one.

**Use it:** to work through the problems one by one, or to hand a single rule to your agent.

## Agent Skills

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

**Use it:** once per project, so your agents work by the same rules. Check it again if an agent behaves oddly.

## Sprint

**What it is:** a live view of a running sprint. A sprint is a list of agent tasks that `steward sprint` starts one
by one, when you give the order.

- Each task shows its state: *planned*, *ready* (waiting for your order), *running*, *checking*, *done*, *failed*,
  *held* or *skipped*. It also shows how long it has run against its time limit, and, when it ends, each acceptance
  command with its exit code. **The task is done only when those commands pass, never because the agent says so.**
- A state marked *derived* was worked out from the plan (for example, "ready" because the tasks it waited for are
  done); the rest come straight from the sprint's ledger.
- **Copy Order Command** copies `steward sprint go …` for a task that is waiting. You run it; the extension never
  starts an agent.
- *incomplete* means a line of the ledger could not be read, so the view may be behind. It sends no "finished"
  notification from such a view.

**Use it:** while agents work, to see what is running, what waits for you, and what passed.

## Status bar

The shield item shows one gate (`bioSteward.gate`, default `default`), whether it is ELIGIBLE, the number of
blocking results and the freshness. Click it to open the Overview. A second item counts down to the next milestone
of `steward timeline`. A third appears while a sprint runs.

## Where to read more
- The user guide: `docs/guides/vscode.md` in the Bio-STEWARD repository (and the project site).
- The extension's README: the **Details** tab of Bio-STEWARD in the Extensions panel.
- **Bio-STEWARD: Show Log** lists every CLI call the extension made.
