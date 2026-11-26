# Delegated work in patch mode

Companion to the `task-lifecycle` skill (constitution, Article VIII). Use it when another agent implements part of a
task in a sandbox that cannot write the repository or run its tests, and returns a unified diff.

1. **Ask for the patch in the first dispatch,** with the task ID, the files in scope, and the acceptance criteria it
   must meet. Generated files are excluded: they are regenerated here.
2. **Check that it applies:** `git apply --check patch.diff`. A patch that does not apply cleanly goes back with the
   error.
3. **Apply it on the task branch,** regenerate any generated files, and run the project's tests and
   `steward check`.
4. **Review it** as you would your own change: every acceptance criterion against evidence.
5. **Record it** in the task's work log: who produced the patch, the commands run, their results.

A patch that was never run is never merged, however plausible it looks. Unrun patches carry wrong results that only
a run and a review catch.
