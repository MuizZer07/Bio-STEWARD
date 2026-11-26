# Progress Audit

Say **"Progress Audit"** to your agent (with the `progress-audit` skill installed: `steward init --skills
.agents/skills --kits core,manage`). It gathers the evidence, judges how far the project is and how useful it is to the
projects that use it, recommends what to improve, and offers to plan a sprint.

## The evidence (read-only)
```bash
steward audit progress          # or --json
```
1. **Where we are:** version, branch, latest tag, the known issues the changelog lists.
2. **Use by other projects:** for each consumer (from the exchange): what it filed (by kind and by the version it
   tested), what is open, how long filing took to ship, the state of each release notice, the version it uses and the
   areas it configures (when it is checked out on this machine).
3. **Pending:** open exchange items, waiting signatures, milestones and their state, sprints with open tasks.
4. **Reach:** what a new adopter finds (licence, citation, guide, quick start, examples) and what is missing
   (community files, a GitHub Action, pre-commit hooks).

Nothing is changed. Progress comes from the records, never from an estimate.

## What the skill does with it
- Answers where we are, whether it is used, whether it helps, what is pending, and what limits its reach, each with the
  numbers it rests on.
- Ranks three to seven improvements by reach for the effort, separating fixes from growth.
- Asks "Design a sprint from this?" and, on a yes, drafts one (`steward sprint plan`), lists the signatures its
  tasks need, and offers to sign ahead or sign later ([guide](signing-ahead.md)). It never starts the sprint, signs or
  merges.
