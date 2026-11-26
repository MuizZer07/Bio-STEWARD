# Storage cleanup, and approvals while the human is away

## When the human asks to clean up storage
Run `steward storage scan` and show its table: what, where, which disk, size, and who else uses it. Ask which classes
to clean. `steward storage clean --plan` writes a plan; only the human runs `steward storage clean --apply PLAN`, in a
terminal, where it asks per location. Never delete files yourself, and never suggest deleting a shared cache.

## When the human will be away
Before long work, offer two options:
- **Sign ahead:** spend, runs and unsealing, with a budget and an expiry at the end of the window.
- **Sign later:** a policy change is prepared (`steward authorize prepare policy.change …`); R-33 shows
  "awaiting signature" until the human runs `steward authorize sign-pending` (with `--all-projects` for several).

Never prepare an approval broader than the work needs, and never sign one yourself.
