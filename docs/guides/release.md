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
