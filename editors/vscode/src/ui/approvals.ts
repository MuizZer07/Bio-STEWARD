// P5 Approvals, as cards (design v0.8, which overrides v0.3 §2.2 and RELEASE_vscode_0.2.0_SPEC §3 P5).
//
// The webview uses `default-src 'none'` and enables only the approval details, payload and sign command URIs.
// Details reads the queue line on the current page. The View and Sign links carry the full nonce, project index
// and page generation. Both handlers revalidate them:
//   - the link must name a card of the page now shown (same generation, same project root, same nonce);
//   - the payload file is read, `authorize pending` is read again (that very read must finish: a superseded or failed
//     read refuses), and the file is read once more; both reads and the card must have the same SHA-256;
//   - ✍ Sign also needs the fresh queue line to bind to the bytes read (model/approvals.ts `bindCard`): exactly one
//     line for that prefix, under this project's own code, printed as the CLI prints that payload. The modal's
//     action, expiry, summary and SHA-256 all come from that one read.
//
// ✍ Sign shows a modal confirmation; for the high-stakes actions the person also types the action's name. Only then,
// in the same call, a dedicated visible terminal runs the CLI's own interactive `steward authorize sign-pending --repo
// ROOT` (src/cli/signing.ts) with an environment the extension gives in full (`strictEnv`), so a workspace's terminal
// settings cannot reach it. The CLI prints the exact bytes and asks before each signature (its prompt is the review
// of record); the key's own prompt completes it. An agent's executeCommand reaches the same modal and nothing else:
// no code path runs the signing command without the modal accepted in that call.
import { realpath } from 'node:fs/promises';
import * as vscode from 'vscode';
import {
  APPROVAL_DETAILS_COMMAND, approvalsHtml, bindCard, CARD_COMMANDS, isNonce, needsTypedName, SIGN_BUTTON, SIGN_COMMAND, signDialog, typedNamePrompt,
  VIEW_PAYLOAD_COMMAND, type ApprovalsBlock, type ApprovalsPage, type ApprovalsState, type Binding, type PayloadRead,
  type SignDetails,
} from '../model/approvals';
import { orderProjects } from '../model/today';
import type { Project } from '../project';
import { payloadRead, readPendingPayload, readQueueCode, type PayloadText } from '../pendingPayload';
import type { DetailsView } from './preview';
import { signingCommand, signingEnvironment } from '../cli/signing';

export { APPROVAL_DETAILS_COMMAND, SIGN_COMMAND, VIEW_PAYLOAD_COMMAND };
export const APPROVALS_VIEW = 'bioSteward.approvals';
export const APPROVALS_REFRESH_COMMAND = 'bioSteward.approvals.refresh';
export const PAYLOAD_SCHEME = 'bio-steward-payload';

const waitingCount = (state: ApprovalsState | undefined) => (state?.kind === 'ready' ? state.waiting ?? 0 : 0);

// A card of the page now shown: the project root, the full nonce and the SHA-256 the card displays.
export interface RenderedCard {
  readonly root: string;
  readonly nonce: string;
  readonly sha256: string;
}

function renderedCards(page: ApprovalsPage): ReadonlyMap<string, RenderedCard> {
  const cards = new Map<string, RenderedCard>();
  if (page.kind !== 'ready') return cards;
  for (const block of page.blocks) {
    for (const read of block.payloads.values()) {
      if (read.kind === 'read') cards.set(`${block.index}/${read.nonce}`, { root: block.root, nonce: read.nonce, sha256: read.sha256 });
    }
  }
  return cards;
}

export class ApprovalsView implements vscode.WebviewViewProvider, vscode.Disposable {
  static readonly options: vscode.WebviewOptions = Object.freeze({
    enableScripts: false, enableCommandUris: CARD_COMMANDS, localResourceRoots: [],
  });

  #view: vscode.WebviewView | undefined;
  #html = approvalsHtml({ kind: 'none' });
  #badge: vscode.ViewBadge | undefined;
  #updates = 0;
  // The page now shown: its generation (named in every link it holds) and its cards, by `index/nonce`.
  #generation = 0;
  #page: ApprovalsPage = { kind: 'none' };
  #cards: ReadonlyMap<string, RenderedCard> = new Map();
  // What was read of each payload file, per approvals state (a new state is a new read).
  #reads = new WeakMap<ApprovalsState, ReadonlyMap<string, PayloadRead>>();
  readonly #registration = vscode.window.registerWebviewViewProvider(APPROVALS_VIEW, this);

  resolveWebviewView(view: vscode.WebviewView): void {
    this.#view = view;
    view.webview.options = ApprovalsView.options;
    view.webview.html = this.#html;
    view.badge = this.#badge;
    view.onDidDispose(() => {
      if (this.#view === view) this.#view = undefined;
    });
  }

  // The page's HTML and options (the tests read them even while the panel is hidden).
  get html(): string {
    return this.#html;
  }

  get webviewOptions(): vscode.WebviewOptions {
    return this.#view?.webview.options ?? ApprovalsView.options;
  }

  get badge(): vscode.ViewBadge | undefined {
    return this.#badge;
  }

  get generation(): number {
    return this.#generation;
  }

  // A card of the page now shown, or undefined: a link of an earlier page (or a forged one) names nothing.
  renderedCard(nonce: string, index: number, generation: number): RenderedCard | undefined {
    return generation === this.#generation ? this.#cards.get(`${index}/${nonce}`) : undefined;
  }

  showDetails(projects: readonly Project[], details: DetailsView, position: unknown, index: unknown,
    generation: unknown): Promise<vscode.Uri> | undefined {
    if (this.#page.kind !== 'ready' || this.#generation !== generation
      || typeof position !== 'number' || !Number.isSafeInteger(position) || position < 0) return;
    const block = this.#page.blocks.find((candidate) => candidate.index === index);
    if (!block || projects[block.index]?.root !== block.root) return;
    const line = block.approvals?.kind === 'ready' ? block.approvals.lines[position] : undefined;
    if (line?.kind !== 'payload') return;
    const read = line.nonce ? block.payloads.get(line.nonce) : undefined;
    const next = read?.kind !== 'read' ? 'Open the project that owns the payload to review it.'
      : line.state === 'waiting' && read.binding?.kind === 'bound' ? 'View exactly what you are approving, then use Sign on the card.'
        : 'Review the payload from the card.';
    return details.show(`${line.action ?? 'Approval'} · ${line.nonce ?? ''}`, 'steward authorize pending --all-projects',
      [line.text, read?.kind === 'read' ? `Payload SHA-256: ${read.sha256}` : ''].filter(Boolean).join('\n'), next);
  }

  // Every project, in the Today order (one block each, never mixed). The links carry each project's index in
  // `projects`, the order the session holds them in.
  async update(projects: readonly Project[], trusted: boolean): Promise<void> {
    const update = ++this.#updates;
    let page: ApprovalsPage;
    let waiting = 0;
    if (!trusted) page = { kind: 'untrusted' };
    else if (!projects.length) page = { kind: 'none' };
    else {
      const ordered = orderProjects(projects.filter((project) => project.state.trusted), (project) => project.state.audit);
      const blocks = await Promise.all(ordered.map(async (project): Promise<ApprovalsBlock> => ({
        root: project.root, name: project.name, index: projects.indexOf(project), approvals: project.state.approvals,
        pending: project.state.pending?.kind === 'ready' ? project.state.pending.doc : undefined,
        payloads: await this.#payloads(project.root, project.state.approvals),
      })));
      page = { kind: 'ready', blocks };
      waiting = ordered.reduce((sum, project) => sum + waitingCount(project.state.approvals), 0);
    }
    if (update !== this.#updates) return;
    // A new generation only when the page changes, so a link stays valid while the page it is on is shown.
    if (approvalsHtml(page, this.#generation) !== this.#html) {
      const generation = this.#generation + 1;
      this.#html = approvalsHtml(page, generation);
      this.#generation = generation;
      this.#cards = renderedCards(page);
      this.#page = page;
    }
    this.#badge = waiting ? { value: waiting, tooltip: `${waiting} waiting for your signature (steward authorize pending)` } : undefined;
    if (this.#view) {
      this.#view.webview.html = this.#html;
      this.#view.badge = this.#badge;
    }
  }

  async #payloads(root: string, state: ApprovalsState | undefined): Promise<ReadonlyMap<string, PayloadRead>> {
    if (state?.kind !== 'ready') return new Map();
    const known = this.#reads.get(state);
    if (known) return known;
    const reads = new Map<string, PayloadRead>();
    const code = await readQueueCode(root);
    for (const line of state.lines) {
      if (line.kind !== 'payload' || !line.nonce || reads.has(line.nonce)) continue;
      const read = await payloadRead(root, line.nonce, state, code);
      if (read) reads.set(line.nonce, read);
    }
    this.#reads.set(state, reads);
    return reads;
  }

  dispose(): void {
    this.#registration.dispose();
  }
}

// The read-only documents **View exactly what you are approving** opens: the payload text exactly as read.
export class PayloadDocuments implements vscode.TextDocumentContentProvider, vscode.Disposable {
  readonly #texts = new Map<string, string>();
  readonly #changed = new vscode.EventEmitter<vscode.Uri>();
  readonly onDidChange = this.#changed.event;
  readonly #registration = vscode.workspace.registerTextDocumentContentProvider(PAYLOAD_SCHEME, this);

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.#texts.get(uri.toString()) ?? '';
  }

  // The URI names the project and the payload file and says where the text comes from. Its query holds the
  // project's canonical root and the text's SHA-256, so two projects of the same name, or a payload that changed,
  // never share (or update) one document (U09).
  set(project: string, canonicalRoot: string, nonce: string, sha256: string, text: string): vscode.Uri {
    const uri = vscode.Uri.from({
      scheme: PAYLOAD_SCHEME, path: `/${project.replaceAll('/', '∕')}/.steward/pending/${nonce}.txt — read from the file`,
      query: new URLSearchParams({ root: canonicalRoot, sha256 }).toString(),
    });
    this.#texts.set(uri.toString(), text);
    this.#changed.fire(uri);
    return uri;
  }

  dispose(): void {
    this.#registration.dispose();
    this.#changed.dispose();
  }
}

// A card the link names, found again on the page now shown and in a fresh `authorize pending` read of that project,
// with its payload read now (twice, around the queue read).
interface Card {
  readonly project: Project;
  readonly canonicalRoot: string;
  readonly payload: Extract<PayloadText, { kind: 'read' }>;
  readonly binding: Binding;
}

async function findCard(projects: readonly Project[], view: ApprovalsView, nonce: unknown, index: unknown, generation: unknown,
  log?: (text: string) => void): Promise<Card | undefined> {
  if (!vscode.workspace.isTrusted || !isNonce(nonce) || typeof index !== 'number' || !Number.isSafeInteger(index)
    || index < 0 || index >= projects.length || typeof generation !== 'number' || !Number.isSafeInteger(generation)) {
    log?.('Approvals: a card link with an invalid nonce, project index or page generation was ignored');
    return undefined;
  }
  const project = projects[index];
  const nothing = (why: string): undefined => {
    log?.(`[${project.name}] Approvals: ${nonce.slice(0, 12)} ${why}; nothing done`);
    return undefined;
  };
  const rendered = view.renderedCard(nonce, index, generation);
  if (!rendered || rendered.root !== project.root) return nothing('is not a card of the page now shown');
  if (!project.state.trusted || !project.cliPath) return undefined;
  const before = await readPendingPayload(project.root, nonce);
  if (before.kind !== 'read') return nothing(`cannot be read: the payload file ${before.reason}`);
  if (before.sha256 !== rendered.sha256) return nothing('changed since the card was drawn (another SHA-256)');
  const fresh = await project.readApprovalsNow();
  if (fresh?.kind !== 'ready') return nothing('could not be checked: the fresh steward authorize pending read did not complete');
  const payload = await readPendingPayload(project.root, nonce);
  if (payload.kind !== 'read' || payload.sha256 !== before.sha256) return nothing('changed while the queue was read');
  const canonicalRoot = await realpath(project.root).catch(() => undefined);
  if (!canonicalRoot) return nothing('cannot be shown: the project folder cannot be read');
  const binding = bindCard(fresh, await readQueueCode(project.root), nonce, payload.text);
  if (binding.kind === 'display-only' && binding.reason.endsWith('is not in the queue')) {
    return nothing('is not in a fresh steward authorize pending read');
  }
  return { project, canonicalRoot, payload, binding };
}

// View exactly what you are approving: the payload, read now from the file, unchanged, in a read-only document.
export async function viewPayload(projects: readonly Project[], view: ApprovalsView, documents: PayloadDocuments, nonce: unknown,
  index: unknown, generation: unknown, log?: (text: string) => void): Promise<{ uri: vscode.Uri; text: string } | undefined> {
  const card = await findCard(projects, view, nonce, index, generation, log);
  if (!card) return undefined;
  const uri = documents.set(card.project.name, card.canonicalRoot, card.payload.nonce, card.payload.sha256, card.payload.text);
  const document = await vscode.workspace.openTextDocument(uri);
  await vscode.languages.setTextDocumentLanguage(document, 'plaintext');
  await vscode.window.showTextDocument(document, { preview: true });
  vscode.window.setStatusBarMessage(`Bio-STEWARD: read from the file .steward/pending/${card.payload.nonce}.txt (SHA-256 ${card.payload.sha256})`, 15000);
  return { uri, text: card.payload.text };
}

export type { SignDetails };

// The modal, the typed name and the terminal. Replaced only through the test API (Test mode).
export interface SigningHooks {
  confirm?: (details: SignDetails) => Promise<boolean>;
  typeName?: (action: string) => Promise<string | undefined>;
  openTerminal?: (options: vscode.TerminalOptions) => vscode.Terminal;
}

export interface SigningOutcome {
  readonly project: Project;
  readonly line: string;
  readonly terminal: vscode.Terminal;
}

export async function confirmSigning(details: SignDetails): Promise<boolean> {
  const dialog = signDialog(details);
  const answer = await vscode.window.showWarningMessage(dialog.title, { modal: true, detail: dialog.detail.join('\n') }, SIGN_BUTTON);
  return answer === SIGN_BUTTON;
}

export async function typeActionName(action: string): Promise<string | undefined> {
  const box = typedNamePrompt(action);
  return vscode.window.showInputBox({
    title: box.title,
    prompt: box.prompt,
    placeHolder: action,
    ignoreFocusOut: true,
    validateInput: (value) => (value === action ? undefined : box.mismatch),
  });
}

// ✍ Sign. Returns the terminal it opened, or undefined when nothing ran (a forged or stale link, a card the fresh
// queue does not bind, a declined modal, a wrong name, a changed payload).
export async function signCard(projects: readonly Project[], view: ApprovalsView, nonce: unknown, index: unknown,
  generation: unknown, hooks: SigningHooks = {}, log?: (text: string) => void): Promise<SigningOutcome | undefined> {
  const card = await findCard(projects, view, nonce, index, generation, log);
  if (!card) return undefined;
  const { project, payload, binding } = card;
  if (binding.kind !== 'bound') {
    log?.(`[${project.name}] Approvals: ${payload.nonce.slice(0, 12)} is display-only (${binding.reason}); nothing done`);
    return undefined;
  }
  if (binding.line.state !== 'waiting') return undefined;
  const cli = project.cliPath;
  if (!cli) return undefined;
  const command = signingCommand(cli, project.root);
  // Everything the modal says of the payload comes from the one read whose SHA-256 it shows.
  const { action, summary, expires } = binding.fields;
  const details: SignDetails = { project: project.name, action, summary, expires, sha256: payload.sha256, line: command.line };
  if (!await (hooks.confirm ?? confirmSigning)(details)) return undefined;
  if (needsTypedName(action) && await (hooks.typeName ?? typeActionName)(action) !== action) return undefined;
  // The world may have changed while the modal was open: run only if the project, its CLI and the bytes shown stand.
  if (!vscode.workspace.isTrusted || !project.state.trusted || project.cliPath !== cli) return undefined;
  const again = await readPendingPayload(project.root, payload.nonce);
  if (again.kind !== 'read' || again.sha256 !== payload.sha256) {
    void vscode.window.showWarningMessage('Bio-STEWARD: The payload changed after it was shown. Nothing was run; look at the card again.');
    return undefined;
  }
  const open = hooks.openTerminal ?? ((options: vscode.TerminalOptions) => vscode.window.createTerminal(options));
  // strictEnv: the environment is exactly this object; VS Code adds neither terminal.integrated.env.* nor any
  // extension's environment collection (U08's first high finding).
  const terminal = open({
    name: `Bio-STEWARD: sign · ${project.name}`, cwd: project.root, shellPath: command.program, shellArgs: [...command.args],
    env: { ...signingEnvironment(process.env) }, strictEnv: true, isTransient: true,
  });
  terminal.show(false);
  return { project, line: command.line, terminal };
}
