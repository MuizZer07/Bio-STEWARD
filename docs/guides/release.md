# Release software and containers

- **Python packages:** build, then `steward release audit` (no development files, secrets or private terms in the
  distributions) and `steward release manifest --version X.Y.Z` (hashes of what ships). R-42 checks them;
  `steward check --final` requires them.
- **Asset bundles:** `steward release bundle NAME --paths …` writes a byte-identical zip, recorded by the manifest.
- **Containers:** follow the `container-release` skill: audit build contexts and compose files (R-64, R-65), build
  under limits, package, record images and archives, then `steward release verify bundle/`.
- **Upgrading a pinned dependency:** the `dependency-upgrade` skill and R-66.
- **Release notices:** `steward exchange announce vX.Y.Z` tells each declared consumer, with the changelog section,
  its known issues and upgrade notes ([multi-project governance](multi-project.md)).
- An independent review is recorded before a release (R-43; the `red-team-review` skill).

## Review waivers in gates

Run `steward check --summary` to see the finding ID and authorization tag for each signed waiver that applies
to a gate requiring R-43. In `steward check --format json`, the gate's `waived` entries include the rule, finding
ID as the subject, the status the waiver covers, and the `authorization` tag. Waivers are excluded from the
gate's blocking and passed counts. The gate still needs an unwaived passing rule and any configured minimum.
