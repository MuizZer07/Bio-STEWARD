# Adopting the toolkit into an existing repository

Companion to the `using-steward` skill (constitution, Article V).

1. **Install it as a development tool, pinned to a tag,** never as a runtime dependency. Use a separate requirements
   file, or `uv tool install` / `pipx install` from the tag's archive.
2. **Initialise without overwriting:** `steward init --dry-run` first, then `steward init`. It never replaces an
   existing file.
3. **Map what exists.** For each local rule, script or test the toolkit can replace, add a row to `parity.md`
   (`templates/parity.md`): the local item and the rule or skill that replaces it.
4. **Run both side by side** on the same tree. Record the command and its result in the parity row. Parity means both
   found the same problems, not that the new rule reads well.
5. **Remove the local item** only after its row is checked, in its own commit.
6. **Keep local** what has no generic replacement, with the reason in `parity.md`.
7. **Ask the toolkit for what is missing** through the exchange protocol: an item in your own `exchange/outbox/`, a
   one-line notice, nothing written into the toolkit's repository.
