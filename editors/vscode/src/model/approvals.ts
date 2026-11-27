// P5 Approvals, reduced form (RELEASE_vscode_0.2.0_SPEC §3), as cards (DESIGN_vscode_extension_v0.8, which
// overrides v0.3 §2.2 and spec §3 P5): the text of `steward authorize pending --all-projects` (CLI 0.20.6) for
// every open project, one card per payload line, and the card page's HTML. No `vscode` import.
//
// The text is never reworded. The extension reads it only to place each line: a payload line gives a card (its
// project code, the first 12 characters of the nonce, its state, action, expiry and summary, each as printed), and
// the CLI's last line ("N waiting; …") gives the project's count. The payload's SHA-256 and **View exactly what you
// are approving** come from `.steward/pending/<nonce>.txt` (src/pendingPayload.ts), the one payload read of the
// reduced form, labelled "read from the file". The full form needs `authorize pending --format json` (STW-050).
//
// The page has `default-src 'none'`, no scripts and no local resources. Its only links are two command URIs (view a
// payload, sign), and each carries only the card's full nonce, the project index and the page's render generation
// (U09). The handler in src/ui/approvals.ts accepts a link only for a card of the page now shown, then binds it again
// to a fresh `authorize pending` read and a fresh payload read (bindCard below), and fails closed on any doubt.
import type { TomlTable } from './toml';

export type ApprovalsState =
  | { readonly kind: 'none' }
  | { readonly kind: 'loading' }
  | { readonly kind: 'ready'; readonly text: string; readonly lines: readonly PendingLine[]; readonly waiting?: number }
  | { readonly kind: 'not-configured' }
  | { readonly kind: 'unreadable' }
  | { readonly kind: 'failed'; readonly message?: string };

export type PendingLineKind = 'payload' | 'skipped' | 'summary' | 'other';

export interface PendingLine {
  // The line as the CLI printed it, without its line break.
  readonly text: string;
  readonly kind: PendingLineKind;
  // A payload line: the project code, the first 12 characters of the nonce, the state, the action, the expiry and
  // the summary (the CLI prints its first 60 characters), each as printed.
  readonly code?: string;
  readonly nonce?: string;
  readonly state?: string;
  readonly action?: string;
  readonly expires?: string;
  readonly summary?: string;
}

export const APPROVALS_REDUCED_NOTE = 'The text of steward authorize pending --all-projects, as the ' +
  'CLI printed it (CLI 0.20.6 has no JSON form for it), one card per payload line. The payload and its SHA-256 are ' +
  'read from the file .steward/pending/<nonce>.txt. Scope, budget, object hash and who asked come with ' +
  'authorize pending --format json in a newer CLI.';

// Text larger than this is not shown (the queue of one project is a few lines).
const MAX_TEXT = 256 * 1024;
const MAX_LINES = 500;

// CLI 0.20.6 `_pending`: f"{code}  {nonce[:12]}  {state:<8} {action:<14} expires {expires}  {summary[:60]}".
const PAYLOAD = /^(\S+) {2}([0-9a-f]{12}) {2}(waiting|signed|expired) +(\S+) +expires (\S+)(?: {2}(.*))?$/;
// `{code}: no local checkout for signing; skipped` and `{code}: {name}: not a steward project here; skipped`.
const SKIPPED = /^\S+: .*; skipped$/;
// `{n} waiting` and `{n} waiting; sign them with: steward authorize sign-pending[ --all-projects]`.
const SUMMARY = /^(\d+) waiting(?:; sign them with: .+)?$/;

export function parsePendingText(stdout: string): ApprovalsState {
  if (typeof stdout !== 'string' || stdout.length > MAX_TEXT) return { kind: 'unreadable' };
  const raw = stdout.replace(/\r?\n$/, '').split(/\r?\n/);
  if (raw.length > MAX_LINES) return { kind: 'unreadable' };
  const lines = raw.filter((text) => text.length > 0).map((text): PendingLine => {
    const payload = PAYLOAD.exec(text);
    if (payload) {
      return { text, kind: 'payload', code: payload[1], nonce: payload[2], state: payload[3], action: payload[4],
        expires: payload[5], summary: payload[6] ?? '' };
    }
    if (SUMMARY.test(text)) return { text, kind: 'summary' };
    if (SKIPPED.test(text)) return { text, kind: 'skipped' };
    return { text, kind: 'other' };
  });
  const summary = lines.filter((line) => line.kind === 'summary').at(-1);
  // Without the CLI's closing line, the text is not what 0.20.6 prints: never shown as a queue.
  if (!summary || lines.at(-1) !== summary) return { kind: 'unreadable' };
  return { kind: 'ready', text: stdout, lines, waiting: Number(SUMMARY.exec(summary.text)?.[1]) };
}

const PROBLEMS: Readonly<Record<Exclude<ApprovalsState['kind'], 'ready'>, string>> = Object.freeze({
  none: 'not read yet',
  loading: 'reading steward authorize pending…',
  'not-configured': 'not set up: the CLI found no steward.toml it accepts',
  unreadable: 'the output of steward authorize pending was unreadable',
  failed: 'steward authorize pending did not finish',
});

export function approvalsSummary(state: ApprovalsState | undefined): string {
  if (!state || state.kind !== 'ready') return PROBLEMS[state?.kind ?? 'none'];
  return `${state.waiting ?? 0} waiting`;
}

// The actions whose ✍ Sign also asks the person to type the action's name (design v0.8 §2.1).
export const TYPED_NAME_ACTIONS: readonly string[] = Object.freeze([
  'unseal', 'freeze.confirmatory', 'policy.change', 'waive', 'pin.retire', 'amend',
]);

export const needsTypedName = (action: string): boolean => TYPED_NAME_ACTIONS.includes(action);

// What ✍ Sign's modal dialog says (src/ui/approvals.ts shows it; scripts/figures.mjs draws it). Pure text.
export interface SignDetails {
  readonly project: string;
  readonly action: string;
  readonly summary: string;
  readonly expires: string;
  readonly sha256: string;
  readonly line: string;
}

export const SIGN_BUTTON = 'Sign in a Terminal';

export function signDialog(details: SignDetails): { readonly title: string; readonly detail: readonly string[] } {
  return {
    title: `Sign ${details.action} in ${details.project}?`,
    detail: [
      `Action: ${details.action}`,
      `Summary: ${details.summary}`,
      `Expires: ${details.expires}`,
      `Payload SHA-256 (read from the file): ${details.sha256}`,
      '',
      'Bio-STEWARD then runs this command in a new terminal:',
      `  ${details.line}`,
      '',
      'This dialog and the preview show what Bio-STEWARD read just now. The review of record is the CLI\'s own ' +
        'prompt in the terminal: it prints the bytes it will sign and asks before each signature, for each waiting ' +
        'payload of this project in turn, not only this card. Read them there, and answer y only for what you mean ' +
        'to approve. ' +
        'Your key\'s own prompt completes each signature.',
    ],
  };
}

// The box a high-stakes action adds after the modal: the person types the action's name.
export function typedNamePrompt(action: string): { readonly title: string; readonly prompt: string; readonly mismatch: string } {
  return {
    title: `Bio-STEWARD: confirm ${action}`,
    prompt: `${action} is a high-stakes action. Type its name to continue.`,
    mismatch: `Type ${action} exactly`,
  };
}

// One icon per action family (design v0.8 §1); unknown actions get a plain mark.
export function actionIcon(action: string): string {
  const family = action.split('.')[0];
  const icons: Readonly<Record<string, string>> = {
    spend: '💳', unseal: '🔓', amend: '✏️', freeze: '❄️', waive: '⚐', policy: '⚖️', anchor: '⚓', pin: '📌',
  };
  return Object.hasOwn(icons, family) ? icons[family] : '•';
}

export const isPrefix = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{12}$/.test(value);
export const isNonce = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{32}$/.test(value);

// ── One snapshot per card (U09, U08's third high finding) ─────────────────────────────────────────────────────
//
// A card's action, expiry, summary and SHA-256 all come from one read of the payload file (one buffer). The queue
// line of a fresh `authorize pending` read only has to agree with that buffer: the line the CLI would print for it
// must be in the text exactly once, under this project's own code, and no other line may carry the same nonce
// prefix. Anything else (a summary over several lines, a line the reduced form cannot place, a duplicate prefix of a
// peer, a file changed in between) leaves the card display-only.

// CLI 0.20.6 `authorize.HEADER`, `FIELDS` and `ACTIONS`.
const PAYLOAD_HEADER = 'steward-authorization/1';
const PAYLOAD_FIELDS = ['repo_id', 'action', 'object', 'scope', 'budget', 'expires', 'baseline', 'nonce'] as const;
const PAYLOAD_ACTIONS: readonly string[] = ['spend', 'amend', 'unseal', 'freeze.confirmatory', 'waive', 'policy.change', 'anchor', 'pin.retire'];

export type PayloadFields = Readonly<Record<typeof PAYLOAD_FIELDS[number] | 'summary', string>>;

// Python's str.splitlines() boundaries and str.strip() whitespace, as far as a payload's fields need them.
const LINE_BREAKS = new RegExp(`\r\n|[${[0x0a, 0x0d, 0x0b, 0x0c, 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029].map((c) => `\\u${c.toString(16).padStart(4, '0')}`).join('')}]`, 'u');
// Python's whitespace: JavaScript's \s without U+FEFF, and with U+001C – U+001F and U+0085.
const isPySpace = (c: string) => {
  const point = c.codePointAt(0) ?? 0;
  return (point >= 0x1c && point <= 0x1f) || point === 0x85 || (point !== 0xfeff && /\s/u.test(c));
};
function pyStrip(text: string): string {
  const points = Array.from(text);
  let start = 0;
  let end = points.length;
  while (start < end && isPySpace(points[start])) start++;
  while (end > start && isPySpace(points[end - 1])) end--;
  return points.slice(start, end).join('');
}

// The payload's fields as CLI 0.20.6 `authorize.parse` reads them, or undefined where it would refuse the text.
export function parsePayload(text: string): PayloadFields | undefined {
  const body = text.split('-----BEGIN SSH SIGNATURE-----')[0].split('-----BEGIN PGP SIGNATURE-----')[0];
  const lines = body.split(LINE_BREAKS);
  if (lines.at(-1) === '' && LINE_BREAKS.test(body.slice(-2))) lines.pop();
  if (!lines.length || pyStrip(lines[0]) !== PAYLOAD_HEADER) return undefined;
  const out: Record<string, string> = {};
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith('summary: |')) {
      out.summary = pyStrip(lines.slice(i + 1).filter((l) => l.startsWith('  ')).map((l) => l.slice(2)).join('\n'));
      break;
    }
    const at = line.indexOf(': ');
    if (at < 0) return undefined;
    const key = line.slice(0, at);
    if (!(PAYLOAD_FIELDS as readonly string[]).includes(key) || Object.hasOwn(out, key)) return undefined;
    out[key] = pyStrip(line.slice(at + 2));
  }
  if (PAYLOAD_FIELDS.some((field) => !Object.hasOwn(out, field)) || !PAYLOAD_ACTIONS.includes(out.action)) return undefined;
  out.summary ??= '';
  return Object.freeze(out as PayloadFields);
}

// Python's `s[:n]` and `f"{s:<n}"` count code points, not UTF-16 units.
const firstCodePoints = (text: string, n: number) => Array.from(text).slice(0, n).join('');
const padCodePoints = (text: string, n: number) => text + ' '.repeat(Math.max(0, n - Array.from(text).length));

// The line CLI 0.20.6 `_pending` prints for a payload with these fields in this state.
export function printedLine(code: string, fields: PayloadFields, state: string): string {
  return `${code}  ${fields.nonce.slice(0, 12)}  ${padCodePoints(state, 8)} ${padCodePoints(fields.action, 14)} ` +
    `expires ${fields.expires}  ${firstCodePoints(fields.summary, 60)}`;
}

// The code the CLI prints for this project's own payloads: `[exchange] code`, or "." without an exchange.
export function queueCode(toml: TomlTable): string | undefined {
  const exchange = toml.exchange;
  if (exchange === undefined) return '.';
  if (typeof exchange !== 'object' || exchange === null || Array.isArray(exchange)) return undefined;
  const code = (exchange as TomlTable).code;
  return typeof code === 'string' && /^[A-Z]{2,6}$/.test(code) ? code : undefined;
}

export type Binding =
  | { readonly kind: 'bound'; readonly line: PendingLine; readonly fields: PayloadFields }
  | { readonly kind: 'display-only'; readonly reason: string };

const CONTROL = /\p{Cc}/u;

// Whether a queue read and one payload read describe the same card, for this project only.
export function bindCard(state: ApprovalsState | undefined, code: string | undefined, nonce: string, text: string): Binding {
  const refuse = (reason: string): Binding => ({ kind: 'display-only', reason });
  if (state?.kind !== 'ready') return refuse('no fresh steward authorize pending read');
  if (code === undefined) return refuse('steward.toml does not give this project\'s queue code');
  if (state.lines.some((line) => line.kind === 'other')) return refuse('the queue text holds a line the reduced form cannot place (a summary over several lines?)');
  const prefix = nonce.slice(0, 12);
  const same = state.lines.filter((line) => line.kind === 'payload' && line.nonce === prefix);
  if (same.length !== 1) return refuse(same.length ? `the nonce prefix ${prefix} is in ${same.length} queue lines` : `${prefix} is not in the queue`);
  const [line] = same;
  if (line.code !== code) return refuse(`the queue line of ${prefix} is under ${line.code ?? '?'}, not this project's ${code}`);
  const fields = parsePayload(text);
  if (!fields || fields.nonce !== nonce) return refuse('the payload file is not one the CLI would list under this name');
  const shown = firstCodePoints(fields.summary, 60);
  if (shown.includes('\n') || CONTROL.test(shown) || CONTROL.test(fields.action) || CONTROL.test(fields.expires)) {
    return refuse('the payload\'s summary spans lines or holds control characters');
  }
  if (printedLine(code, fields, line.state ?? '') !== line.text) return refuse('the queue line does not describe the payload read now');
  return { kind: 'bound', line, fields };
}

// What the extension read of `.steward/pending/<nonce>.txt` for one card (src/pendingPayload.ts), and whether the
// queue line binds to it (a card without a `bound` binding has no ✍ Sign).
export type PayloadRead =
  | { readonly kind: 'read'; readonly nonce: string; readonly sha256: string; readonly binding?: Binding }
  | { readonly kind: 'unreadable'; readonly reason: string };

// The signed tag a payload gets, from its full nonce (CLI 0.20.6 `tag_name`); an anchor's tag is named from its
// payload's scope, which the reduced form does not read, so it is not shown.
export function signedTag(action: string, nonce: string): string | undefined {
  return action === 'anchor' ? undefined : `steward/auth/${nonce}`;
}

export interface ApprovalsBlock {
  readonly root: string;
  readonly name: string;
  // The project's index in the open projects, the only project reference a link carries.
  readonly index: number;
  readonly approvals: ApprovalsState | undefined;
  // Per 12-character prefix: the payload files of this project's own `.steward/pending/`. A prefix not here is a
  // peer's payload (or a file the extension cannot read): its card has no View and no Sign.
  readonly payloads: ReadonlyMap<string, PayloadRead>;
}

export type ApprovalsPage =
  | { readonly kind: 'untrusted' }
  | { readonly kind: 'none' }
  | { readonly kind: 'ready'; readonly blocks: readonly ApprovalsBlock[] };

export const VIEW_PAYLOAD_COMMAND = 'bioSteward.approvals.viewPayload';
export const SIGN_COMMAND = 'bioSteward.approvals.sign';
export const CARD_COMMANDS: readonly string[] = Object.freeze([VIEW_PAYLOAD_COMMAND, SIGN_COMMAND]);

export function escapeHtml(text: string): string {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

// A command URI with exactly the three arguments a card may carry: the full nonce, the project index and the
// generation of the page it is on.
export function cardUri(command: typeof VIEW_PAYLOAD_COMMAND | typeof SIGN_COMMAND, nonce: string, index: number, generation: number): string {
  if (!isNonce(nonce) || !Number.isSafeInteger(index) || index < 0 || !Number.isSafeInteger(generation) || generation < 0) {
    throw new Error('Invalid card reference');
  }
  return `command:${command}?${encodeURIComponent(JSON.stringify([nonce, index, generation]))}`;
}

function card(line: PendingLine, block: ApprovalsBlock, generation: number): string {
  const action = line.action ?? '';
  const read = line.nonce ? block.payloads.get(line.nonce) : undefined;
  const bound = read?.kind === 'read' && read.binding?.kind === 'bound';
  const parts = [
    `<h3>${actionIcon(action)} ${escapeHtml(action)} <small>· ${escapeHtml(line.code ?? '')} ${escapeHtml(line.nonce ?? '')} · ` +
      `${escapeHtml(line.state ?? '')}</small></h3>`,
    `<p>${escapeHtml(line.summary ?? '')}</p>`,
    `<p>expires ${escapeHtml(line.expires ?? '')}</p>`,
  ];
  if (read?.kind === 'read') parts.push(`<p>Payload SHA-256 <i>(read from the file)</i>:<br><code>${escapeHtml(read.sha256)}</code></p>`);
  if (read?.kind === 'read') {
    parts.push(`<p><a href="${escapeHtml(cardUri(VIEW_PAYLOAD_COMMAND, read.nonce, block.index, generation))}">View exactly what you are approving</a></p>`);
  }
  if (line.state === 'waiting') {
    if (read?.kind === 'read' && bound) {
      parts.push(`<p><a href="${escapeHtml(cardUri(SIGN_COMMAND, read.nonce, block.index, generation))}"><b>✍ Sign</b></a></p>`);
    } else if (read?.kind === 'read') {
      const reason = read.binding?.kind === 'display-only' ? read.binding.reason : 'the queue line was not checked against the file';
      parts.push(`<p>Display only, no ✍ Sign here: ${escapeHtml(reason)}. Read the payload, then run steward authorize sign-pending yourself.</p>`);
    } else if (read?.kind === 'unreadable') parts.push(`<p>Not signable here: the payload file ${escapeHtml(read.reason)}.</p>`);
    else parts.push(`<p>This payload is in ${escapeHtml(line.code ?? '')}'s checkout. Open that project to view and sign it.</p>`);
  } else if (line.state === 'signed') {
    const tag = read?.kind === 'read' ? signedTag(action, read.nonce) : undefined;
    parts.push(`<p><b>✓ Signed</b>${tag ? ` <code>${escapeHtml(tag)}</code>` : ' (steward authorize list shows its tag)'}</p>`);
  } else {
    parts.push('<p>⏱ Expired: it can no longer be signed.</p>');
  }
  parts.push(`<p><small>As printed: <code>${escapeHtml(line.text)}</code></small></p>`);
  return `<section>\n${parts.join('\n')}\n</section>`;
}

function blockHtml(block: ApprovalsBlock, heading: boolean, generation: number): string {
  const state = block.approvals;
  const out: string[] = heading ? [`<h2>${escapeHtml(block.name)} <small>· ${escapeHtml(approvalsSummary(state))}</small></h2>`] : [];
  if (!state || state.kind !== 'ready') return [...out, `<p>${escapeHtml(approvalsSummary(state))}</p>`].join('\n');
  for (const line of state.lines) {
    if (line.kind === 'payload') out.push(card(line, block, generation));
    else out.push(`<p>${escapeHtml(line.text)}</p>`);
  }
  return out.join('\n<hr>\n');
}

// The whole page. Every CLI and file text is escaped; the only links are the cards' two command URIs, each naming
// the page's generation.
export function approvalsHtml(page: ApprovalsPage, generation = 0): string {
  let body: string;
  if (page.kind === 'untrusted') {
    body = '<p>This workspace is not trusted, so Bio-STEWARD reads and runs nothing (Restricted Mode).</p>';
  } else if (page.kind === 'none' || !page.blocks.length) {
    body = '<p>Open a folder that holds a steward.toml to see what waits for your signature.</p>';
  } else {
    body = [`<p><small><b>Reduced form.</b> ${escapeHtml(APPROVALS_REDUCED_NOTE)}</small></p>`,
      ...page.blocks.map((block) => blockHtml(block, page.blocks.length > 1, generation))].join('\n<hr>\n');
  }
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'">
<title>Bio-STEWARD Approvals</title>
</head>
<body>
${body}
</body>
</html>`;
}

// The links a page holds, for the tests and the handler's own check.
export function pageLinks(html: string): string[] {
  return [...html.matchAll(/href="([^"]*)"/g)].map((match) => match[1].replaceAll('&amp;', '&'));
}
