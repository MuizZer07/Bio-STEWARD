---
name: licence-compliance
description: Check licences before adding a dependency, copying or porting code, or bundling data. Use when a task adds a package, vendors or translates code, or the project moves towards release.
---

# Licence compliance

Start by saying in one line that you are using this skill and why.

A licence conflict costs a package swap on the commit that brings it in, and a blocked release after the tag. The
project's `[licence]` table declares its licence, its distribution state (internal, network, public) and a policy;
`steward check licence` judges every dependency, every declared third-party file and every licence header against it
(R-79 – R-82). It checks declared rules and metadata; legal interpretation stays with the human.

## Before adding a dependency
1. Look up its licence (its package metadata or repository) **before** adding it.
2. Add it, then run `steward check licence`: R-80 names it with its licence and the verdict. Incompatible: pick
   another package. Unknown: find the licence; never assume one.

## Before copying, porting or translating code
A translation into another language is still a derivative work. Before writing code from another project:
1. Find that project's licence. If the policy refuses it, write the code independently from the method's
   description (a paper, a specification), and say so in the task record; do not look at the source while writing.
2. If it is allowed, declare it: add an item to the `third_party` file (path, licence, source, kind: vendored,
   ported, translated, snippet, data, asset), or put `SPDX-License-Identifier:` and
   `Derived-from: PROJECT FILE (LICENCE)` headers in the file. R-81 checks them.
3. Record the source in the task's "Source of copied or ported code" field.

R-82 lists comments such as "ported from" or "adapted from" that have no declaration. Answer each: declare it, or
confirm the code is original.

## Exceptions
When a human accepts a conflict for a reason, record it in the exceptions file: the package or path, the licence,
the reason, the scope, the approver (a human), the date and an expiry. Never relabel a licence, edit package
metadata or move a package into `ignore_packages` to make a check pass.

## Going public
Changing `distribution` to `public` re-runs every check at the stricter level and requires current third-party
notices (`steward licence notices --write`). A release manifest records the licence inventory and is refused while a
licence check is FAIL or UNKNOWN.
