# Clean up a project's storage

Caches, build folders, LaTeX by-products and scratch outputs grow quickly, on the startup disk and on external ones.
`steward storage` finds this project's temporary storage, tells you where it is and who else uses it, and deletes
only what you confirm, one location at a time.

## 1. Look first (read-only)
```bash
steward storage scan
```
Each line gives the class, the size, the path, the disk (startup or external, by its mount point) and whether it can
be cleaned. Lines below it name anyone else using the same place: another steward project on this machine, a running
process with a file open there, or an active `steward run`.

| Class | What | Cleaned by default |
|---|---|---|
| toolkit | `.steward/cache` | yes |
| python | `__pycache__`, `.pytest_cache`, `.mypy_cache`, `build/`, `*.egg-info`, … (untracked only) | yes |
| docs | `site/`, LaTeX by-products (`*.aux`, `*.fls`, …) | yes |
| declared | the folders you list in `[storage.clean] paths` (for example a scratch folder on an external disk) | yes |
| linked | the target of a link inside the project that leads outside it | only with `--class linked` (its contents) |
| shared | user-wide caches: pip, conda, Hugging Face, torch, DVC | never: listed so you can decide with their own tools |

```toml
[storage.clean]
paths = ["/Volumes/Lab/scratch/my-project", "outputs/tmp"]
registry = true   # list this checkout in the machine registry, so other projects see that they share a folder
```

## 2. Plan
```bash
steward storage clean --plan                 # toolkit, python, docs, declared
steward storage clean --plan --class linked  # also the targets of links
```
The plan (`.steward/cleanup/<time>.json`) records each location's identity. Nothing is deleted.

## 3. Apply, in your terminal
```bash
steward storage clean --apply .steward/cleanup/<time>.json
```
For each location it checks again, then asks. It skips a location when:
- it changed or was replaced since the plan, or its disk is not the one planned;
- git tracks files under it, the artifact registry records it, it is part of a sealed dataset, or it is under the
  project's records;
- a process has a file open there, or a steward run is active there;
- it is the repository, a home folder, a disk root or one of their parents.

A folder another project uses needs you to type `shared`. Deletion never follows a link. Each deletion is recorded in
`development/storage-cleanup.jsonl`; the report ends with the space freed on each disk.

An agent may run `scan` and `--plan` for you; only you run `--apply`.
