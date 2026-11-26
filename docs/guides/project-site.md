# Publish your project's documentation

Bio-STEWARD can build a documentation site for your own project from the records it already keeps.

```bash
steward docs init --pages      # mkdocs.yml, docs/index.md, and a GitHub Pages workflow (never overwrites)
steward docs build             # docs/project/*.md from the records
pip install mkdocs-material && mkdocs build --strict
```

Configure it in `steward.toml`:
```toml
[docs]
title   = "My benchmark"
publish = ["overview", "contracts", "runs", "values", "releases"]   # add "decisions", "exchange" or "timeline" to opt in
```

- **What each page shows:** the project and its governed areas; each benchmark contract (datasets, splits,
  baselines, metrics, thresholds); the run ledger (status, duration, limits, exit code); the paper's values registry
  (name, source, how); the release manifest (artifacts, bundles, images). Decisions and exchange items are opt-in,
  and show only dates, titles, IDs and states.
- **Where it comes from:** every page names its records by path and hash. Change the records and build again; never
  edit the generated pages.
- **Privacy first:** every page passes your term lists and the local-path check before anything is written. One
  failing page writes nothing.
- **Kept current:** R-69 `docs.current` reports a site older than its records.
- **Hosting:** GitHub Pages is free for public repositories; GitLab Pages or a plain folder work too.

Ask your agent: *"Build the project's documentation site and tell me what changed."*

## Generate the project README block

Run `steward docs readme` to append a generated block to the root `README.md`. To choose its position, add
these two lines on their own before running the command.

```markdown
<!-- steward:readme:start -->
<!-- steward:readme:end -->
```

Keep your own prose outside the markers. Commit the README and its generated images in
`docs/steward-readme/`. The local SVGs adapt to light and dark themes. The block shows the version in the
release manifest, the number of study records, the number of open tasks under `[tasks]`, the configured checks,
a project lifecycle diagram, and the study cards. Open tasks are recorded task IDs with a configured status
outside the closed statuses and archive.

To include a gate snapshot, run `steward check --output .steward/readme-check.json` before generating the block.
The badge describes the default gate in that saved report. Refresh the snapshot whenever you want to publish
a new gate result. A site that already uses `[docs]` can set `readme_report` to a different repo-relative report path.

Run `steward check docs` to check the generated README block and SVGs against the records with R-69.
This works without a documentation site. The generator scans the block and images for private terms and
local paths before writing them.

For a PyPI long description, use `steward docs readme --pypi` and insert the printed Markdown into the
file your package uses for its long description. This format uses text in place of images and can be
rendered without access to the repository. The command leaves files alone.

<!-- 2026-11-25 · STW-010 implementation · Codex CLI 0.171.0 · OpenAI · model ID unknown · No live publication. -->
