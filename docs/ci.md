# Bio-STEWARD in CI, and the approval key

Step by step, for a project that adopts the toolkit. `OWNER/REPO` is the toolkit's repository and `vX.Y.Z` the tag
you pin; replace both. Each step says what happens when it is missing.

## 1. Install in CI
The toolkit is public on GitHub; pin a release tag:
```bash
pipx install "git+https://github.com/MuizZer07/Bio-STEWARD.git@vX.Y.Z"
```

### From a private fork or mirror
A private repository needs a token to install from. Use a fine-grained personal access token, never a classic one.

1. **Create the token** (GitHub → Settings → Developer settings → Fine-grained tokens):
   - resource owner: the account or organisation that owns `OWNER/REPO`;
   - repository access: only `OWNER/REPO`;
   - permissions: **Contents: read-only**, nothing else;
   - an expiry date (for example 90 days). Write it in your task board, so you rotate the token before it expires.
2. **Store it** as a secret of the adopting repository (Settings → Secrets and variables → Actions), for example
   `STEWARD_INSTALL_TOKEN`. Never commit it, and never print it in a log.
3. **Use it** only in the install line:
   ```bash
   pipx install "git+https://x-access-token:${STEWARD_INSTALL_TOKEN}@github.com/OWNER/REPO.git@vX.Y.Z"
   ```
4. **A missing or expired secret fails the job.** The install fails, so the check never runs; make the workflow fail
   rather than continue (the default for a failed step). Never let a missing token turn into a skipped gate.
5. **To rotate:** create the new token, replace the secret's value, run the workflow once, then delete the old token.


## 2. A workflow
```yaml
name: steward
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # full history: baseline ancestry, append-only checks and release tags need it
          fetch-tags: true      # authorization and anchor tags
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install the toolkit (isolated, pinned to a tag)
        env:
          STEWARD_INSTALL_TOKEN: ${{ secrets.STEWARD_INSTALL_TOKEN }}
        run: pipx install "git+https://x-access-token:${STEWARD_INSTALL_TOKEN}@github.com/OWNER/REPO.git@vX.Y.Z"
      - name: Check the gate
        env:   # only when [policy] is used (section 3): the trust root comes from secrets, not from the repository
          STEWARD_TRUST_BASELINE: ${{ secrets.STEWARD_TRUST_BASELINE }}
          STEWARD_TRUST_SIGNERS: ${{ secrets.STEWARD_TRUST_SIGNERS }}
        run: steward check --gate default --summary --output steward-report.json
```
The tool is installed apart from the project's own environment (pipx), so it is never a runtime dependency. The
exit code is the gate's: a step that ignores it ignores the gate. A FAIL outside the gate's rules leaves the exit
code at 0; add `--fail-on fail` (any FAIL) or `--fail-on incomplete` (anything not passing) when a step must stop on
those too.

## 3. The approval key (signed authorizations)
Only a human holds this key. It signs approvals (spend past a budget, amending a frozen design, unsealing held-out
data, policy changes); an agent never holds or uses it.

1. **Create a key used only for approvals.** A hardware key is recommended (`ed25519-sk`, with a PIN and touch):
   ```bash
   ssh-keygen -t ed25519-sk -O verify-required -C "approvals" -f ~/.ssh/steward_approvals
   ```
   Without a hardware key, use `-t ed25519` with a passphrase. A key that signs without a prompt makes an approval only
   a recorded decision; R-33 lists each signer's key type.
2. **Let git sign tags with it** (in your own git configuration, not the repository's):
   ```bash
   git config --global gpg.format ssh
   git config --global user.signingkey ~/.ssh/steward_approvals.pub
   ```
3. **Add the public key to `allowed_signers`** (default `development/allowed_signers`), one line:
   `PRINCIPAL namespaces="git" <contents of steward_approvals.pub>`, where `PRINCIPAL` is the name or address you
   sign as. Commit it on the policy baseline branch, and have it reviewed.
4. **Declare the policy** in `steward.toml`: `[policy]` (`baseline`, `allowed_signers`). Until steps 1 – 5 are done,
   `state = "pending"` keeps R-33 INCOMPLETE with these steps, instead of blocking other rules.
5. **Pin the trust root** on your own machine: `steward authorize pin`. It records the reviewed baseline commit
   outside the repository; set `state = "active"` (or remove `state`) afterwards.
6. **One round, to see it work:**
   ```bash
   steward authorize prepare spend --object development/budget.toml \
     --expires 2026-12-31T00:00:00Z --summary "first test approval"
   steward authorize sign <nonce>            # you, in your own terminal: the key prompt is the approval
   steward authorize verify <tag> --object development/budget.toml
   ```
7. **The CI trust root:** store the reviewed baseline commit SHA as `STEWARD_TRUST_BASELINE`, and the
   `allowed_signers` line (or a file path) as `STEWARD_TRUST_SIGNERS`, both as secrets (section 2). Without them, CI
   reads the trust root from the working tree and R-33 reports UNKNOWN: a checkout can edit its own policy.

## What this does not do
- A token or a pin protects what goes through `steward`; a push with hooks skipped, or a change to CI settings, is
  outside it. Branch protection on the default branch stays the enforcement point.
- A signature shows that someone with the key signed; it does not show that they read the payload.

## Discover JSON output

```mermaid
flowchart LR
    D(["steward interface --format json"]):::cmd --> C["commands: argv for JSON,<br/>schema ID"]
    D --> S["schema_files: ID → file<br/>(bundled in the wheel)"]
    D --> E["exit_codes, error_schema<br/>(78: not configured)"]
    C --> R(["steward CMD --format json"]):::cmd
    R --> V["validate against the schema;<br/>read the exit status"]
    S --> V
    E --> V
    classDef cmd fill:#1f6feb,color:#fff,stroke:#1f6feb
```

Run `steward interface --format json` from any directory. It returns a
`steward.interface/1` document with these fields.

| Field | How to use it |
|---|---|
| `interface_version` | Select the discovery format the client understands. |
| `commands` | Find the arguments to request JSON on stdout and the schema ID to expect. Supply any required command arguments separately. Empty `argv` means the command emits JSON by default. The `legacy_argv` field lists the older JSON option where available. |
| `schema_files` | Resolve a bundled schema ID to its file name. The source tree has these files in `schemas/`. The installed wheel has them in `steward/_bundled/schemas/`, which Python callers can locate with `steward.resources.schemas_dir()`. |
| `exit_codes` | Interpret exit codes defined by Steward. Commands that launch a child can also propagate the child's exit code. |
| `error_schema` | The schema ID of the error document that a command prints with `--format json` when it exits 78. |

Terminal users, CI and agents can use `--format json` with `audit progress`,
`benchmark results`, `benchmark splits`, `diff impact`, `diff run`, `diff runs`,
`exchange status`, `licence inventory`, `pins status`, `research list`,
`storage audit`, `storage scan`, `storage verify`, `study list`, `timeline`
and `tokens report`. For example, `steward timeline --format json` emits a
`steward.timeline/0.1` document. Choose one output flag per invocation. Existing
`--json` invocations retain their output bytes. In the tagged exchange status
document, `items` contains the rows that the legacy flag emits as an array.

**List order (0.22.0).** The text views print the newest entry first (by date, then by ID, highest first; an
entry without a date last). The JSON documents keep the order they had before: each schema's `description` names
the order of its lists, so a script or editor sorts as it needs. For example, `steward.timeline/0.1` lists
milestones by due date, earliest first, while `steward timeline` prints the latest due first.

Read the exit status alongside stdout. Some commands return a complete document
and a nonzero exit status when the document describes a negative outcome.
Usage and input errors can report a diagnostic on stderr and leave stdout empty.
Discovery and the default read commands use local data. To query configured
remote peers explicitly, use `steward exchange status --fetch --format json`.

## More JSON documents (0.21.0)

| Command | Schema | What it holds |
|---|---|---|
| `steward explain R-42 --format json` | `steward.explain/0.1` | The rule's name, version, area, what it checks, why, what a PASS does not mean, its fix, and every result code with its own fix where one exists. `steward explain --all --format json` lists every rule. |
| `steward check --digest-only --against report.json --format json` | `steward.digest/0.1` | The present digest of the report's inputs, and `current`. No rule is evaluated. |
| `steward init --dry-run --format json` | `steward.init_plan/0.1` | What `init` would create, skip, update or print, the `steward.toml` tables it would append, and the next commands. Nothing is written. |
| `steward skills list --format json` | `steward.skills/0.1` | The bundled skills by bundle, with their descriptions. In a project with `[skills]`, the canonical folder, the skills in it and the state of each copy (the codes of R-60). |
| `steward next --format json` | `steward.next/0.1` | The resume pointer (the handoff's next steps and open decisions), the nearest milestone with its blockers, what waits on the human and on agents, and the tidy counts. Each item names its source record and one command. `--now TIME` evaluates at another time. |
| `steward tidy --format json` | `steward.tidy/0.1` | Stale tasks, contradicting statuses, stale pages, exchange items, leftovers and memory entries, with the thresholds used. Read-only. |
| `steward notifications --format json` | `steward.notifications/0.1` | One feed, newest first: each item's `id`, `time`, `kind`, `source`, `title`, `command` and `urgent`. `--against REPORT` adds the gates that turned not eligible since that report. No network call. |
| `steward decisions --format json` | `steward.decisions/0.1` | Dated decisions and open questions with their options, each linked to a local file and line. |
| `steward upgrade --check --format json` | `steward.upgrade/0.1` | The installed and newest known versions, their source, the install method and the exact install command. Local release notices only, unless `--online`. See [Upgrade the CLI](guides/upgrade.md). |
| `steward issues inbox --format json` | `steward.issues_inbox/0.1` | Received toolkit defect reports grouped by fingerprint. See [Report a toolkit defect](guides/report-a-defect.md). |
| `steward timeline --format json` | `steward.timeline/0.1` | Milestones plus date, scope and order drift and changes with or without a matching decision. |

### Status and record views

| Command | Schema | What it holds |
|---|---|---|
| `steward task board --format json` | `steward.task_board/0.1` | The board path, when configured, and task IDs, paths, statuses and closed and archived flags. Without `[tasks]`, it searches `development/tasks/**/*.md`. |
| `steward authorize pending --format json` | `steward.authorize_pending/0.1` | Queued payloads with their full nonce, action, scope, budget, expiry, object hash and SHA-256 of the exact payload bytes. `--all-projects` includes local peers and reports skipped peers. Current payloads carry a repository ID, so `requester` is null. |
| `steward authorize list --format json` | `steward.authorize_list/0.1` | Authorization and anchor tags with verification results. |
| `steward authorize keys --format json` | `steward.authorize_keys/0.1` | The baseline and its allowed signer principals and key types. |
| `steward sprint status ID --format json` | `steward.sprint_status/0.1` | The sprint window, dispatch mode and ordered task list with ledger state, limits, checks and recorded branch and commit. |
| `steward session start --format json` | `steward.session_start/0.1` | Constitution version and the configured handoff path, text and last commit details. The text is null when the handoff is absent. |
| `steward study show ID --format json` | `steward.study_show/0.1` | The study record, its path and its check status. |
| `steward integrity status --format json` | `steward.integrity_status/0.1` | Frozen snapshots, proposed amendments and recorded dataset roles. |
| `steward spend status --format json` | `steward.spend_status/0.1` | Call counts and recorded costs against the project cap. |
| `steward release status --format json` | `steward.release_status/0.1` | Public release status and unpublished tags from local Git records. |
| `steward channel status --format json` | `steward.channel_status/0.1` | Declared tools and their last recorded channel, tag and switch time. |
| `steward paper values --format json` | `steward.paper_values/0.1` | Computed registry values and per-value errors. |
| `steward paper displays --format json` | `steward.paper_displays/0.1` | Display IDs, labels, outputs and missing files. |
| `steward paper citations --format json` | `steward.paper_citations/0.1` | Local verification count, mismatches, unverified citations and bibliography problems. |
| `steward talk plan --format json` | `steward.talk_plan/0.1` | Stage, missing fields and the suggested pattern and slide count when the required fields are present. |
| `steward talk prefs --format json` | `steward.talk_prefs/0.1` | Resolved preferences and the source layer for each value. |

The pending queue's `object` identifies what is being authorized.
`payload_sha256` fingerprints the complete request for that authorization, including its scope and expiry.
The paper and talk JSON views are read-only. Use their text mode for `--write`, `--record`, `--fetch`,
`--write-outline` and `--set`. For token reports from configured local logs, see [Track tokens per task](guides/tokens.md).

### Is a saved report still current?

`steward check` writes the files it read into the report (`verdict.inputs`) beside
the `inputs_digest`, and a digest of the repository's file list (`verdict.tree_digest`).
`steward check --digest-only --against FILE` reads those again, hashes the same
files with the function the check uses, and lists the file names again. It
evaluates no rule.

```bash
steward check --output .steward/report.json
steward check --digest-only --against .steward/report.json --format json
```

`current` is `true` only when every listed input has the same bytes, no file was
added or removed, and the report was written by this version of Steward. The
`changed` list names the inputs that differ or cannot be read. Write the report
with `--output`: the check leaves that file out of the file list, and so does
`--digest-only` for the file given with `--against`. A report written before
0.21.0 lists no inputs; `--digest-only` exits 65 for it. Settings outside the
repository, such as the installed tools a rule calls, are not in the digest.

### Area and scope

Each result in a report names its `area`, the first area that lists its rule
(R-02 and R-03 are in `contract` and `benchmark` and name `contract`). The
report's `verdict.scope` says what the run covered: `full` is `true` for a run of
every area, `areas` lists the areas of a scoped run, and `rule` names the rule of
`steward check --rule R-xx`.

### Locations in result details

A detail that points into a file uses these keys.

| Key | Meaning |
|---|---|
| `path` | The file, relative to the repository root, with `/` separators. |
| `line` | A 1-based line of `path`. |
| `column` | With `line`: the 1-based character column on that line. With `row` (a table record, as in R-75 and R-83): the table's column. |
| `end_line` | The last line of a span that starts at `line`. |

A `line` without a `path` is not a location: R-28 names a PDF page that way.
`row` counts records of a table, which is not the same as a line when a cell
holds a line break. R-07, R-09 and R-57 gained locations in 0.21.0.

### Not configured (exit 78)

A command that needs a project exits 78 when no `steward.toml` is found, in this
folder or a parent. With `--format json` it also prints a `steward.error/0.1`
document on stdout (`code` is `not_configured`, with a `hint`). The prose on
stderr is unchanged. Before 0.21.0 the same case exited 64.

The same document, with `code` set to `invalid_input` and `exit` 65, is printed
when `steward notifications --against FILE --format json` is given a file that is
not a check report.

### Documents without a `--format` option

`steward interface --format json` also lists two commands that write JSON by
default: `paper manifest` (`steward.submission_manifest/0.1`) and `shards plan`
(`steward.shards/0.1`). Both schemas are in `schemas/`, like every other
schema the interface names.

2026-11-27 · W05 status reference · Codex CLI 0.171.0 · OpenAI · exact model ID unknown · verified with worked-example fixtures.
