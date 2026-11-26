---
# DRAFT, not ready for submission: JOSS asks for 750 – 1,750 words, sections on the state of the field, the software
# design, research impact and AI usage, and more than six months of public development (see the JOSS guidelines).
title: 'Bio-STEWARD: deterministic guardrails for agent-driven research in computational biology'
tags:
  - Python
  - computational biology
  - reproducibility
  - benchmarking
  - research integrity
  - AI coding agents
authors:
  - name: Muiz Khan
    orcid: 0000-0003-2039-7079
    affiliation: 1
affiliations:
  - name: Wayne State University
    index: 1
date: 24 November 2026
bibliography: paper.bib
---

# Summary

Researchers in computational biology increasingly write their analysis code with AI coding agents. Agents work fast,
but they also change benchmark splits, retune thresholds after seeing results, copy numbers into a manuscript by hand,
and touch held-out data, often without leaving a trace a reviewer can check. Bio-STEWARD is a command-line toolkit and
a set of agent skills that keeps a deterministic record of what a project decided, ran, froze and claimed, and refuses
what a human did not approve. It evaluates declared rules over the repository's files and reports one of five statuses
for each, with gates that decide when a project is ready for a commit, a confirmatory run, a submission or a release.

# Statement of need

Reproducibility guidance for computational research [@sandve2013] and the FAIR principles [@wilkinson2016] describe
what a trustworthy project records; leakage between training and evaluation data remains a frequent cause of
irreproducible machine-learning results [@kapoor2023]. When an agent writes most of the code, these practices need to
be checked mechanically and continuously, not remembered. Bio-STEWARD provides:

- **benchmark contracts** fixed before results, with identifier, group and temporal leakage checks;
- **paper and talk values traced to result files**: declared values come from their sources, and numbers typed into
  the text without one are reported;
- **frozen protocols, sealed held-out data and signed human approvals**, so an agent's change to them is refused or
  visible;
- **run supervision and records** (limits, a CPU-progress watchdog, a hash-chained run ledger);
- **release manifests and distribution audits** that keep private terms and local paths out of what is published;
- **project management across projects**: requests and release notices between repositories, milestones, supervised
  sprints of agent tasks, and a progress audit.

Each check states what a PASS does not mean. The toolkit never judges the science; it makes the record checkable.

# Acknowledgements

TBD.

# References
