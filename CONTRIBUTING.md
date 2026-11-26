# Contributing to Bio-STEWARD

Thank you for helping. Bio-STEWARD keeps a deterministic record of what an agent-driven research project decided, ran,
froze and claimed. Contributions keep to the same standard: small, tested, and honest about what they do not check.

## Before you start
- **Questions and ideas:** open a discussion or an issue with the "feature" template. Say which project need it serves
  (a benchmark, a paper, a release) and what a PASS would and would not mean.
- **Bugs:** use the "bug" template. A false PASS (a check that passes when it should not) is the most important kind of
  bug; say so in the title.
- **Security problems:** do not open an issue; follow [SECURITY.md](SECURITY.md).

## How changes are made
1. **A failing test first.** Every fix or rule comes with the test that fails without it (`tests/`).
2. **One concern per pull request**, with the changelog entry under `## Unreleased` in [CHANGELOG.md](CHANGELOG.md).
3. **Generic only.** Nothing project-specific, no personal details, no local paths (`python tools/scrub_check.py`).
4. **Plain language.** The text lint must pass (`python tools/lint_language.py`); claims say what is checked, never
   that something "is correct" or "is valid".
5. **Generated files stay generated.** After changing rules or models: `python tools/build_rule_reference.py` and
   `python tools/regenerate_schemas.py`.
6. **Run the suite:** `python -m pip install -e ".[dev]"`, then `python -m pytest -q` (and `tools/ci_local.sh` for
   Linux, with Docker).

AI coding agents are welcome as tools; the person opening the pull request is responsible for it, has run it, and
says which parts an agent wrote. An agent never approves, merges or signs.

## What to expect (response promise)
Bio-STEWARD has one maintainer. Issues and pull requests get a first response within **7 days** (security reports
within **3 days**). A reported false PASS is triaged first. Decisions are recorded in `development/DECISIONS.md`.
Other people may triage when the maintainer names them there.

## Licence
By contributing you agree that your contribution is licensed under the [MIT licence](LICENSE).
