# Third-party notices for Bio-STEWARD for VS Code

The extension is licensed under MIT (see [LICENSE](LICENSE)). Its bundle (`dist/extension.js`) includes the
following packages, each under its own licence. The exact versions are in `package-lock.json`.

| Package | Version | Licence | Why |
|---|---|---|---|
| ajv | 8.20.0 | MIT | JSON Schema validation of the CLI's output |
| fast-deep-equal | 3.1.3 | MIT | dependency of ajv |
| fast-uri | 3.1.9 | BSD-3-Clause | dependency of ajv |
| json-schema-traverse | 1.0.0 | MIT | dependency of ajv |
| require-from-string | 2.0.2 | MIT | dependency of ajv |

The development tools (TypeScript, esbuild, ESLint, mocha, the VS Code test runner, `@vscode/vsce` and their
dependencies) build and test the extension and are not distributed with it.

The extension does not include the `steward` CLI. It runs the copy the user installed, which carries its own
notices (the repository's `THIRD_PARTY_NOTICES.md`).

Checks package metadata only; this is not legal advice.
