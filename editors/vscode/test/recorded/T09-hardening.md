# T09 hardening verification

2026-11-26 · Sprint 2026-11-27-vscode-0.1 · macOS arm64 · VS Code test build 1.148.0 · steward 0.20.6

| Check | Observed result |
| --- | --- |
| G1 branch scope guard and working-tree review | Exit 0. All task changes are under `editors/vscode/`. |
| `npm ci --ignore-scripts && npm run check` | Exit 0. Lint, bundle and test compilation passed. Mocha reported `150 passing (9s)`. |
| `npm run cli:install && npm run fixtures -- --verify` | Exit 0. Eight reports and the schema matched the pinned CLI. GEO had 13 PASS and toy had 28 PASS. |
| `npm run test:host` | Exit 1. VS Code 1.148.0 exited with `SIGABRT` in all eight profiles before reporting Mocha results. The macOS crash report places the abort in AppKit application registration. |
| `npm audit --omit=dev` | Exit 0, `found 0 vulnerabilities`. The full install audit reported nine existing development-tool advisories (one low, seven moderate, one high). |
| Project report confinement probe | With the installed CLI and a minimal VS Code API stub, an external saved report behind a symlinked parent was skipped. Running a check failed before touching that file. |

The pinned CLI was installed from the public v0.20.6 release tag. The first install needed `UV_NO_CACHE=1` because the sandbox could not write to uv's shared cache. The exact install-and-verify command then passed. No dependencies were added.

The host suite contains the Restricted Mode CLI spy, a workspace-setting override fixture, report-path and plain-text rendering checks, and the two example runs with TCP/UDP calls blocked in the extension host. The network guard allows local IPC and covers Node sockets in the extension-host process. It leaves VS Code's other processes, direct DNS APIs, and the external CLI's networking outside that test. Unit coverage passed for the five spoken status labels, workspace executable rejection, traversal, oversized and malformed output, process-group timeout and cancellation, and denied commands.

## Timings

Three sequential runs per fixture. The CLI timings measure the installed program's complete process lifetime while it writes the JSON report. The parsing and view-model timings start after reading the report and include JSON validation and building the Overview, Results, and status bar models in Node. Schema compilation happened once before the measurements.

| Example | CLI check (ms) | Validate and build view models (ms) |
| --- | --- | --- |
| GEO | 258.6, 253.2, 252.1 | 2.6, 0.5, 0.3 |
| Toy | 231.0, 212.7, 215.1 | 0.6, 0.4, 0.4 |

The production bundle was 258,259 bytes against the 1 MB limit. The 300 ms activation-to-sidebar threshold and the host-side Run Check timings remain unverified because of the startup abort.

## Keyboard and screen-reader pass pending

Desktop automation could not access Code. The unit tests exercised the accessibility label text. The keyboard flow and spoken output still require verification in a running editor.

1. In a fresh Restricted Mode window, open **Bio-STEWARD: Show Overview** from the Command Palette. Use Tab and Enter to reach **Manage Workspace Trust**. Verify the status is announced as “Bio-STEWARD: Restricted Mode.”
2. In a trusted GEO fixture, run **Bio-STEWARD: Run Check** from the Command Palette. Open **Show Overview** and navigate with the arrow keys. Verify the gate is announced as “ELIGIBLE” with the blocking count. Use **Focus Status Bar** and arrow keys to reach the Bio-STEWARD item and verify “fresh” is announced. Edit a fixture input and verify the same item announces “stale.”
3. Focus **Results** and use the arrow keys to navigate the five groups. Verify the screen reader announces FAIL, INCOMPLETE, UNKNOWN, PASS and NOT APPLICABLE in words. With the seeded GEO fault, open **Problems**, navigate to the Bio-STEWARD diagnostic, and open **Explain Rule** from a result's keyboard context menu. Use Tab to reach **Copy CLI command**.
4. Record the editor and screen reader versions and the observed focus and announcements. Linux, WSL, and Remote-SSH also remain unverified.

## Verifier's run outside the sandbox (2026-11-26)

The implementer's sandbox could not start VS Code (the SIGABRT above), so the host suite had never run. Run on the
host machine by the verifier (Claude Code, `claude-opus-5-5`):

- The network test failed at first: it counted every connection attempt in the shared extension host. Stack traces
  showed the two extra attempts were TLS connections from VS Code's own built-in networking (`@vscode/proxy-agent`,
  `undici` in the app bundle), not from the extension. The guard now attributes each attempt by its caller frames:
  the extension's bundle must make none, the test's probe must be rejected once, and VS Code's built-ins are counted
  and logged. Result on both examples: **extension 0, probe 1, VS Code built-ins 2.**
- Restricted Mode (N1 of the feasibility record): the suite passes. The configured CLI is never invoked in an
  untrusted workspace, also through direct commands.
- **Activation to sidebar: 72.8 ms (GEO) and 72.9 ms (toy)** against the 300 ms limit (PERF-2). Run Check takes
  287 ms and 286 ms in the host.
- `npm run test:host`: exit 0 in seven of eight runs. One run had one failure in the T08 suite that did not
  reproduce in six further runs. It is recorded as a suspected timing-dependent test for the T11 review.
- Still open: the keyboard and screen-reader pass (a person, using the steps above); Linux, WSL, Remote-SSH.
