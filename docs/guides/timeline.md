# Plan to a deadline: milestones and the timeline

A preprint, a conference submission, a release: each is a dated goal with work that must be done before it.
`steward timeline` shows how far each one is, from the project's own records.

## Declare the milestones
`development/milestones.toml`:

```toml
schema = "steward.milestones/0.1"

[[milestone]]
id = "ismb-2027"
title = "ISMB 2027 submission"
due = 2027-01-20T23:59:00-12:00     # the real deadline, with its time zone (anywhere on earth here)
kind = "submission"                 # submission | preprint | release | review | other
gate = "submission"                 # the gate that must be ELIGIBLE (for a paper: steward check --final)
tasks = ["BP-110", "BP-111"]        # board tasks (needs [tasks])
items = ["REQ-019"]             # exchange items it waits on
needs = ["policy.change"]           # signatures it will need
buffer_days = 3                     # your internal deadline: due minus the buffer
```

## Read the timeline
```bash
steward timeline          # soonest first
steward timeline --format json   # versioned milestones and drift
steward timeline --json   # legacy milestone output
steward timeline --now 2027-01-18T00:00:00Z   # as it will stand then (0.21.0), to reproduce "at risk"
```

Each milestone shows the days left and its progress:
- **gate:** ELIGIBLE or not, how many required rules pass, which block;
- **tasks:** done of total, and which are open (from the board);
- **items:** settled of total, and which are still waiting;
- **signatures:** which are needed, and which wait in the signing queue (`steward authorize sign-pending`).

Its state is **ready** (nothing open), **on track**, **at risk** (work open after the internal deadline, or more than
three pieces of open work a day in its last week), **late** (work open after the due time), or its recorded outcome.

`steward next` shows the nearest milestone with what blocks it, beside what waits on you
([Where you are, what is next, what is stale](next-and-tidy.md)).

## Read plan drift

`steward timeline --format json` includes a `drift` object in `steward.timeline/0.1`.

- `date` compares the first available committed due date with the current one, counts changes of deadline and
  identifies milestones with a recorded `moved` outcome. The day difference uses elapsed time.
- `scope` lists open or completed board tasks outside any milestone, milestone tasks that are missing, dropped or
  still unstarted, and roadmap table rows without a task reference. It reads the roadmap from the project's index.
- `order` lists started or completed tasks on a later milestone while the current records show work still open on an
  earlier milestone. Shared tasks are excluded from that pair.
- `changes` names the milestone or roadmap row, the fields changed, and the matching decision's file and line when
  available. A null `decision` marks a change without a matching record. A milestone's changed outcome can cite a
  dated decision heading exactly. Otherwise, a committed change looks for a dated log entry that mentions the
  milestone or roadmap row within one calendar day of the commit date.

The comparison uses local first-parent history and the working tree. Working-tree changes have a null commit and time.
`history` is `unavailable` when there is no local Git baseline, `shallow` for a shallow clone, or `partial`
when a snapshot could not be read. `notes` describes skipped snapshots. Drift is advisory information in the JSON
document. `--now` sets the time used to compute milestone states.

## Record the outcome
When a milestone passes, record what happened; R-70 (advisory) reports a past milestone without one:

```toml
[milestone.outcome]
state = "moved"                         # met | moved | dropped
decision = "2026-12-01: moved to the March deadline"
```

## On the documentation site
Add `"timeline"` to `[docs] publish` for a Milestones page: titles, kinds, due dates and recorded outcomes. Days
left and progress change every day, so they stay in `steward timeline`.
