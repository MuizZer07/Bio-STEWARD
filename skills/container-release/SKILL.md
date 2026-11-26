---
name: container-release
description: Ship container images after auditing build contexts and compose files, then record and verify the bundle. Use before shipping images.
---

# A container release, step by step

Start by saying in one line that you are using this skill and why.


For a project that ships container images (with a registry, or as `docker save` archives without one). Each step
names the check that confirms it. Estimate each heavy step first (the `run-estimate` skill) and run it under
`steward run` limits; image builds and saves are memory- and disk-heavy.

1. **Declare the contexts and the dev-only paths** in `steward.toml`:
   ```toml
   [containers]
   contexts = ["services/api", "services/web"]
   dev_only = ["/Volumes/scratch"]          # disks or folders no image may reach
   max_unignored_mb = 500
   compose = ["compose.yml"]
   ship_with_image = ["services/api/models/weights.bin"]
   [containers.urls]
   web = ["API_URL"]                         # keys each service must set (never a localhost fallback)
   [containers.user_data]
   web = ["/srv/uploads"]                    # container paths that must be on named volumes
   ```
2. **Audit the build contexts and the compose files:** `steward check containers` (R-64, R-65; R-65 needs the
   `[containers]` extra). Fix a FAIL with `.dockerignore`, a named volume or a missing key, not by removing the
   declaration.
3. **Build** each image under limits: `steward run --wall … --mem … --slot heavy -- docker build …`.
4. **Smoke-test** each image the way it will run (`docker compose up`, then the project's own smoke checks).
5. **Package** the images per architecture: `docker save IMAGE | gzip > bundle/NAME-ARCH.tar.gz`.
6. **Record the release:** `steward release manifest --version X.Y.Z --image TAG=sha256:…@linux/amd64 …
   --archives bundle`. The manifest lists each image (tag, digest, platform) and each archive (hash, size, the tags
   it holds).
7. **Verify before sending:** `steward release verify bundle` re-hashes every archive and lists changed, missing and
   extra archives and images. Send only a bundle that verifies.

## Credentials a private package ships on purpose
The release audit refuses secret-like files. When the owner decides a private package ships a credential, declare it,
and record the decision first:
```toml
[[release.shipped_secret]]
path     = "app/config/service.env"
reason   = "private deployment; credentials rotated per customer"
decision = "2026-11-20: ship the service credentials"   # the decisions-log heading
```
The audit then reports it (`shipped_secret`, R-42 `R-42.shipped_secret`) instead of refusing it. An undeclared
file, or a declaration whose decision is not in the log, is still refused.
