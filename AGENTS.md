# Instructions for agents working in this repository

Bio-STEWARD (Scientific Toolkit for Engineering, Workflow Assurance, Reproducibility, and Development) is a generic
research-and-development toolkit (Agent Skills, a small CLI, an
optional MCP server) for computational biology. Muiz (MuizZer07) is the owner and sole approver.

## Start here
1. [development/INDEX.md](development/INDEX.md): state, next step, open decisions.
2. [development/design/DESIGN_v0.3.md](development/design/DESIGN_v0.3.md) plus its deltas
   [DESIGN_v0.4.md](development/design/DESIGN_v0.4.md) and [DESIGN_v0.5.md](development/design/DESIGN_v0.5.md)
   (token efficiency, proposal): the current design. The v0.1 release specification is
   [RELEASE_v0.1_SPEC.md](development/design/RELEASE_v0.1_SPEC.md). Earlier versions are kept for history.
3. [development/design/DESIGN_BRIEF_v0.2.md](development/design/DESIGN_BRIEF_v0.2.md) and
   [development/design/PLAN_v0.1.md](development/design/PLAN_v0.1.md): the brief and the baseline plan.
4. [development/DECISIONS.md](development/DECISIONS.md): owner decisions, verbatim.

**This repository follows the [Bio-STEWARD constitution](CONSTITUTION.md)** (version 1), the top authority for every
project that adopts the toolkit, the toolkit included. The rules below are this repository's own scope and
applications of it; where they differ, the constitution wins.

## Hard rules
- **Authorised scope (2026-11-23):** toolkit **v0.1.x, pre-release**:
  - v0.1.0 per [RELEASE_v0.1_SPEC.md](development/design/RELEASE_v0.1_SPEC.md) plus DESIGN_v0.5 F1–F3;
  - the v0.1.1–v0.1.3 skills;
  - the paper kit (C16): its release specification and slices v0.2.0 (G4) and v0.2.1. LaTeX is first.
  - skill bundles per kit (H2);
  - PaperKit v0.2.2 and v0.2.3;
  - the presentation kit (C17): its release specification and implementation, including the slices for
    Quarto / reveal.js, PPTX, Keynote and PDF layout checks;
  - v0.4.0 – v0.4.2 (run safety, signed authorizations, spend guard);
  - v0.5.0 research integrity, per RELEASE_v0.5_SPEC (J1–J5);
  - v0.6 release integrity and evidence, per RELEASE_v0.6_SPEC (slices v0.6.0 – v0.6.2);
  - v0.6.3 (fixes for the known issues H1 – H7 of 0.6.2) and its release;
  - v0.7 benchmarking, per RELEASE_v0.7_SPEC (planned in DESIGN_v0.3 §3.3);
  - v0.8 storage and the optional MCP server, after the v0.7.0 release, starting with its release specification;
  - v0.8.1 (adopter requests, the constitution, the exchange protocol step 1) and its release;
  - v0.9.0: the items deferred from 0.8.1, exchange step 2, the configuration overlay, and further client requests,
    starting with its release specification.
  - v0.10.0 and later releases on the roadmap (hardening, then community capabilities that have a demand signal),
    each starting with its release specification (Muiz, 2026-11-23: "start working on the rest of the tasks guided
    in further releases as well e.g. 0.10.0 and so on").
  - the official VS Code extension (`editors/vscode/`) and the core additions it needs, per
    [DESIGN_vscode_extension](development/design/DESIGN_vscode_extension.md) and its
    deltas [v0.2](development/design/DESIGN_vscode_extension_v0.2.md) and
    [v0.3](development/design/DESIGN_vscode_extension_v0.3.md). The timeline is locked
    (`development/milestones.toml`). Unfrozen on 2026-11-26: extension 0.1.0 is built on CLI 0.20.6 per
    [RELEASE_vscode_0.1.0_SPEC](development/design/RELEASE_vscode_0.1.0_SPEC.md); **an extension task changes nothing
    outside `editors/vscode/`** (its rules G1 – G7), and each task starts on Muiz's `steward sprint go`. Later slices
    start with their release specifications. Marketplace accounts, tokens and publishing are Muiz's alone (Muiz,
    2026-11-26: "i like the initial timeline.. lets jump on it"; "we can start right now").

  Granted by Muiz, 2026-11-23 (v0.6.3 and v0.7: "You go ahead with next release with the fixes and our roadmap";
  v0.8: "yes, go ahead with v0.8 after the release"; 0.9.0: "Can we go for 0.9.0 with the deferred ones althogethar
  after 0.8.1 … lets release this and keep working towards our 0.9.0 goals").

  Rules for this scope:
  - No tags or publishing.
  - Anything beyond it (v0.2+, new capabilities, other spec changes) needs Muiz to name the step.
  - Spec deviations found while implementing are recorded and raised, not decided by the agent.
  - No migrations; adopter repositories are not touched.
- **Skill admission.**
  - A new skill must say, in its task or pull request, why no existing skill can absorb it.
  - Bundle description budgets (`skills/BUNDLES.toml`) change only with a recorded decision.
- **No authority for agents.** No agent approves its own work, grants a GO, authorises spending or merges.
- **Generic.** Nothing project-specific in the toolkit.
  - Adopters use it in their development process only, never as a runtime dependency.
  - Adopter names appear only in:
    - [development/ADOPTION.md](development/ADOPTION.md);
    - the historical planning files (PLAN_v0.1, DECISIONS);
    - Muiz's briefs, which are recorded verbatim (`design/DESIGN_BRIEF_*.md`).

    Never in README, skills, templates, code, examples or design documents.
- **Preserve history.**
  - New versions are new files (`DESIGN_v0.2.md`, …); earlier plans stay unchanged.
  - Decisions are appended, never rewritten.
- **Commits.** Author MuizZer07, with no co-author or AI attribution lines. Never force-push.
- **Private data.** No personal details, credentials, local paths or unpublished findings in documents that could
  become public.
- **Signing.** Sign substantive documents with: date, task / mode, harness and version, provider, exact model ID
  (unknown if not exposed), and limitations.
