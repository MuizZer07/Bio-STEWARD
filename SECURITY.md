# Security policy

## What counts
Anything that lets a project pass a check it should fail (a false PASS), lets an agent act without a required human
approval, reads or writes outside the project without being asked, deletes data it should keep, or publishes private
information. Signed approvals, sealed data, storage cleanup, hooks and the exchange are the most sensitive parts.

## How to report
Use GitHub's **private vulnerability reporting** for this repository (Security → Report a vulnerability), which is
enabled with the public release. Do not open a public issue. Include the version (`steward --version`), the smallest synthetic project that shows it, and what you
expected. Never include real data or credentials.

## What happens
- A first response within **3 days**; a fix or a documented mitigation for a confirmed issue in the next release.
- The fix comes with a regression test, and the changelog names the issue once a fixed release is out.
- Supported versions: the latest release only, while the toolkit is in beta (0.x).

## Known limits
The changelog's "Known issues" tables list what is not yet fixed, with what to do until it is.
