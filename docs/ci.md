# Bio-STEWARD in CI, and the approval key

Step by step, for a project that adopts the toolkit. `OWNER/REPO` is the toolkit's repository and `vX.Y.Z` the tag
you pin; replace both. Each step says what happens when it is missing.

## 1. Install in CI while the toolkit repository is private
A private repository needs a token to install from. Use a fine-grained personal access token, never a classic one.

1. **Create the token** (GitHub → Settings → Developer settings → Fine-grained tokens):
   - resource owner: the account or organisation that owns `OWNER/REPO`;
   - repository access: only `OWNER/REPO`;
   - permissions: **Contents: read-only**, nothing else;
   - an expiry date (for example 90 days). Write it in your task board, so you rotate the token before it expires.
2. **Store it** as a secret of the adopting repository (Settings → Secrets and variables → Actions), for example
   `STEWARD_INSTALL_TOKEN`. Never commit it, and never print it in a log.
3. **Use it** only in the install line:
   ```bash
   pipx install "git+https://x-access-token:${STEWARD_INSTALL_TOKEN}@github.com/OWNER/REPO.git@vX.Y.Z"
   ```
4. **A missing or expired secret fails the job.** The install fails, so the check never runs; make the workflow fail
   rather than continue (the default for a failed step). Never let a missing token turn into a skipped gate.
5. **To rotate:** create the new token, replace the secret's value, run the workflow once, then delete the old token.

When the toolkit is public, drop the token: `pipx install "git+https://github.com/OWNER/REPO.git@vX.Y.Z"`.

## 2. A workflow
```yaml
name: steward
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # full history: baseline ancestry, append-only checks and release tags need it
          fetch-tags: true      # authorization and anchor tags
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install the toolkit (isolated, pinned to a tag)
        env:
          STEWARD_INSTALL_TOKEN: ${{ secrets.STEWARD_INSTALL_TOKEN }}
        run: pipx install "git+https://x-access-token:${STEWARD_INSTALL_TOKEN}@github.com/OWNER/REPO.git@vX.Y.Z"
      - name: Check the gate
        env:   # only when [policy] is used (section 3): the trust root comes from secrets, not from the repository
          STEWARD_TRUST_BASELINE: ${{ secrets.STEWARD_TRUST_BASELINE }}
          STEWARD_TRUST_SIGNERS: ${{ secrets.STEWARD_TRUST_SIGNERS }}
        run: steward check --gate default --summary --output steward-report.json
```
The tool is installed apart from the project's own environment (pipx), so it is never a runtime dependency. The
exit code is the gate's: a step that ignores it ignores the gate.

## 3. The approval key (signed authorizations)
Only a human holds this key. It signs approvals (spend past a budget, amending a frozen design, unsealing held-out
data, policy changes); an agent never holds or uses it.

1. **Create a key used only for approvals.** A hardware key is recommended (`ed25519-sk`, with a PIN and touch):
   ```bash
   ssh-keygen -t ed25519-sk -O verify-required -C "approvals" -f ~/.ssh/steward_approvals
   ```
   Without a hardware key, use `-t ed25519` with a passphrase. A key that signs without a prompt makes an approval only
   a recorded decision; R-33 lists each signer's key type.
2. **Let git sign tags with it** (in your own git configuration, not the repository's):
   ```bash
   git config --global gpg.format ssh
   git config --global user.signingkey ~/.ssh/steward_approvals.pub
   ```
3. **Add the public key to `allowed_signers`** (default `development/allowed_signers`), one line:
   `PRINCIPAL namespaces="git" <contents of steward_approvals.pub>`, where `PRINCIPAL` is the name or address you
   sign as. Commit it on the policy baseline branch, and have it reviewed.
4. **Declare the policy** in `steward.toml`: `[policy]` (`baseline`, `allowed_signers`). Until steps 1 – 5 are done,
   `state = "pending"` keeps R-33 INCOMPLETE with these steps, instead of blocking other rules.
5. **Pin the trust root** on your own machine: `steward authorize pin`. It records the reviewed baseline commit
   outside the repository; set `state = "active"` (or remove `state`) afterwards.
6. **One round, to see it work:**
   ```bash
   steward authorize prepare spend --object development/budget.toml \
     --expires 2026-12-31T00:00:00Z --summary "first test approval"
   steward authorize sign <nonce>            # you, in your own terminal: the key prompt is the approval
   steward authorize verify <tag> --object development/budget.toml
   ```
7. **The CI trust root:** store the reviewed baseline commit SHA as `STEWARD_TRUST_BASELINE`, and the
   `allowed_signers` line (or a file path) as `STEWARD_TRUST_SIGNERS`, both as secrets (section 2). Without them, CI
   reads the trust root from the working tree and R-33 reports UNKNOWN: a checkout can edit its own policy.

## What this does not do
- A token or a pin protects what goes through `steward`; a push with hooks skipped, or a change to CI settings, is
  outside it. Branch protection on the default branch stays the enforcement point.
- A signature shows that someone with the key signed; it does not show that they read the payload.
