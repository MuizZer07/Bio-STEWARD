// Host suite for U04b (0.2.0 P5 Approvals as cards, design v0.8) on the U01 cockpit workspaces: `cockpit`
// (geo-cockpit, with its peer beside it) and `multi-cockpit` (geo, geo-cockpit-peer and geo-cockpit in one window).
// The cards are compared with what the pinned CLI prints in the same folder. ✍ Sign runs nothing unless the modal is
// accepted in that call (and, for a high-stakes action, the name typed); accepted, it runs exactly the CLI's
// interactive sign-pending line once; the flag that skips the CLI's question appears nowhere; and closing the real
// terminal at the CLI's question signs nothing.
import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import { pageLinks, SIGN_COMMAND, VIEW_PAYLOAD_COMMAND } from '../../src/model/approvals';
import { orderProjects } from '../../src/model/today';

const EXTENSION_ID = 'MuizZer07.bio-steward';
const example = process.env.BIO_STEWARD_TEST_EXAMPLE;
const SKIP_FLAG = ['-', '-', 'y', 'e', 's'].join('');
const WAITING = 'd3e83e998137';
const PEER = '7b274a7e9224';

async function until(condition: () => boolean, what: string, ms = 30000): Promise<void> {
  const end = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((done) => setTimeout(done, 50));
  }
}
const pause = (ms: number) => new Promise((done) => setTimeout(done, ms));

const cli = () => vscode.workspace.getConfiguration('bioSteward').get<string>('cliPath') ?? '';
const steward = (root: string, ...args: string[]) => execFileSync(cli(), [...args.slice(0, 2), '--repo', root, ...args.slice(2)],
  { encoding: 'utf8', env: { ...process.env, STEWARD_NO_REGISTRY: '1' } });
const pendingText = (root: string) => steward(root, 'authorize', 'pending', '--all-projects');
const lines = (text: string) => text.replace(/\n$/, '').split('\n');
const escape = (s: string) => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;');
const link = (command: string, nonce: string, index: number, generation: number) =>
  `command:${command}?${encodeURIComponent(JSON.stringify([nonce, index, generation]))}`;
// The arguments of the page's link for a card: [full nonce, project index, page generation].
type CardArgs = [string, number, number];
function cardArgs(page: string, command: string, prefix: string): CardArgs {
  const found = pageLinks(page).filter((l) => l.startsWith(`command:${command}?`))
    .map((l) => JSON.parse(decodeURIComponent(l.slice(l.indexOf('?') + 1))) as CardArgs).filter(([nonce]) => nonce.startsWith(prefix));
  assert.equal(found.length, 1, `one ${command} link for ${prefix}`);
  return found[0];
}

// A terminal that runs nothing: a pseudoterminal standing in for the CLI, so a test can record what would run.
function inertTerminal(calls: vscode.TerminalOptions[]) {
  return (options: vscode.TerminalOptions) => {
    calls.push(options);
    const write = new vscode.EventEmitter<string>();
    return vscode.window.createTerminal({ name: options.name ?? 'inert', pty: { onDidWrite: write.event, open: () => undefined, close: () => write.dispose() } });
  };
}

describe('Approvals cards and ✍ Sign (U04b)', () => {
  let api: TestApi | undefined;

  before(async function () {
    if (example !== 'cockpit' && example !== 'multi-cockpit') this.skip();
    this.timeout(90000);
    api = await vscode.extensions.getExtension<TestApi | undefined>(EXTENSION_ID)?.activate();
    assert.ok(api);
    await until(() => api?.projects.every((p) => p.state.cli.kind === 'ready' && p.state.approvals?.kind === 'ready'
      && p.state.audit?.kind === 'ready') ?? false, 'CLI detection, authorize pending and audit progress in every project', 60000);
    await vscode.commands.executeCommand('bioSteward.approvals.refresh');
  });

  describe('one project (geo-cockpit)', () => {
    before(function () {
      if (example !== 'cockpit') this.skip();
    });
    const root = () => api!.project.root;
    const index = () => api!.projects.indexOf(api!.project);
    const pendingDir = () => join(root(), '.steward', 'pending');
    const authorizationTags = () => steward(root(), 'authorize', 'list').split('\n').filter((line) => line.startsWith('steward/auth/'));
    const payloadFile = (prefix: string) => join(pendingDir(), readdirSync(pendingDir()).find((name) => name.startsWith(prefix))!);
    const fullNonce = (prefix: string) => readdirSync(pendingDir()).find((name) => name.startsWith(prefix))!.slice(0, 32);
    const signArgs = (prefix: string) => cardArgs(api!.approvals.view.html, SIGN_COMMAND, prefix);
    const viewArgs = (prefix: string) => cardArgs(api!.approvals.view.html, VIEW_PAYLOAD_COMMAND, prefix);
    const ownTerminals = () => vscode.window.terminals.filter((t) => t.name.startsWith('Bio-STEWARD: sign'));

    // A payload written beside the fixture's own (same repo_id and baseline), so the CLI lists it as waiting.
    const extra: string[] = [];
    function addPayload(nonce: string, action: string, summary: string): void {
      const base = readFileSync(payloadFile(WAITING), 'utf8');
      const text = base.replace(/^action: .*$/m, `action: ${action}`).replace(/^nonce: .*$/m, `nonce: ${nonce}`)
        .replace(/^summary: \|\n(?: {2}.*\n?)*/m, `summary: |\n  ${summary}\n`);
      writeFileSync(join(pendingDir(), `${nonce}.txt`), text);
      extra.push(join(pendingDir(), `${nonce}.txt`));
    }
    const refresh = async () => {
      await vscode.commands.executeCommand('bioSteward.approvals.refresh');
    };

    afterEach(async () => {
      for (const terminal of vscode.window.terminals) terminal.dispose();
      for (const file of extra.splice(0)) rmSync(file, { force: true });
      await refresh();
    });

    it('shows one card per payload line, each line as the CLI printed it, in a locked-down webview (parity)', async () => {
      assert.ok(api);
      const page = api.approvals.view.html;
      const expected = lines(pendingText(root()));
      for (const line of expected) assert.ok(page.includes(escape(line)), line);
      assert.match(page, /default-src 'none'/);
      assert.doesNotMatch(page, /<script/i);
      const generation = api.approvals.view.generation;
      // The links carry the full nonce, the project index and the page's generation (U09). The waiting card's
      // queue line binds to its file (the line the CLI printed is the line its bytes give), so it has ✍ Sign.
      assert.deepEqual(pageLinks(page), [
        link(VIEW_PAYLOAD_COMMAND, fullNonce('06e95f82fc4a'), index(), generation), link(VIEW_PAYLOAD_COMMAND, fullNonce(WAITING), index(), generation),
        link(SIGN_COMMAND, fullNonce(WAITING), index(), generation),
      ]);
      const sha = createHash('sha256').update(readFileSync(payloadFile(WAITING))).digest('hex');
      assert.ok(page.includes(sha), 'the payload SHA-256, read from the file');
      assert.match(page, /This payload is in PEER's checkout/);
      const options = api.approvals.view.webviewOptions;
      assert.equal(options.enableScripts, false);
      assert.deepEqual(options.enableCommandUris, [VIEW_PAYLOAD_COMMAND, SIGN_COMMAND]);
      assert.deepEqual(options.localResourceRoots, []);
      // The CLI's own count (its closing line), the peer's waiting payload included.
      assert.equal(api.approvals.view.badge?.value, 2);
      console.log(`    cards: ${expected.join(' | ')}`);
    });

    it('View exactly what you are approving opens the file read-only, unchanged; hostile text is escaped in the card', async () => {
      assert.ok(api);
      const hostile = '<img src=x onerror=alert(1)><script>x</script> "\'& ‮';
      const nonce = 'abcdef012345' + '0'.repeat(20);
      addPayload(nonce, 'spend', hostile);
      await refresh();
      await until(() => api!.approvals.view.html.includes('abcdef012345'), 'the hostile card');
      const page = api.approvals.view.html;
      assert.ok(page.includes(escape(hostile)), 'the summary is escaped');
      assert.doesNotMatch(page, /<img|<script/);
      assert.ok(pageLinks(page).every((l) => l.startsWith(`command:${VIEW_PAYLOAD_COMMAND}?`) || l.startsWith(`command:${SIGN_COMMAND}?`)));
      const shown = await api.approvals.viewPayload(...viewArgs('abcdef012345'));
      assert.ok(shown);
      // The document is keyed by the canonical root, the full nonce and the SHA-256 (U09).
      const query = new URLSearchParams(shown.uri.query);
      assert.equal(query.get('root'), realpathSync(root()));
      assert.equal(query.get('sha256'), createHash('sha256').update(readFileSync(join(pendingDir(), `${nonce}.txt`))).digest('hex'));
      assert.ok(shown.uri.path.includes(`${nonce}.txt`));
      const onDisk = readFileSync(join(pendingDir(), `${nonce}.txt`), 'utf8');
      assert.equal(shown.text, onDisk, 'the text unchanged');
      const editor = vscode.window.activeTextEditor;
      assert.equal(editor?.document.uri.toString(), shown.uri.toString());
      assert.equal(editor?.document.getText(), onDisk);
      assert.equal(editor?.document.uri.scheme, 'bio-steward-payload', 'a read-only virtual document');
      assert.match(shown.uri.path, /read from the file$/);
      assert.equal(editor?.document.languageId, 'plaintext');
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
    });

    it('a declined modal runs nothing and opens no terminal', async () => {
      assert.ok(api);
      const before = vscode.window.terminals.length;
      const opened: vscode.TerminalOptions[] = [];
      let asked = 0;
      const outcome = await api.approvals.sign(...signArgs(WAITING), {
        confirm: async () => { asked++; return false; }, openTerminal: inertTerminal(opened),
      });
      assert.equal(outcome, undefined);
      assert.equal(asked, 1);
      assert.deepEqual(opened, []);
      assert.equal(vscode.window.terminals.length, before);
    });

    it('a high-stakes action needs its name typed: a wrong or no name runs nothing, the right one runs the line once', async () => {
      assert.ok(api);
      const nonce = 'fedcba987654' + '1'.repeat(20);
      addPayload(nonce, 'waive', 'Waive R-1 for the toy run');
      await refresh();
      for (const typed of ['waiv', 'Waive', ' waive', undefined]) {
        const opened: vscode.TerminalOptions[] = [];
        const asked: string[] = [];
        const outcome = await api.approvals.sign(...signArgs('fedcba987654'), {
          confirm: async () => true, typeName: async (action) => { asked.push(action); return typed; }, openTerminal: inertTerminal(opened),
        });
        assert.equal(outcome, undefined, String(typed));
        assert.deepEqual(asked, ['waive']);
        assert.deepEqual(opened, [], String(typed));
      }
      assert.equal(ownTerminals().length, 0);
      const opened: vscode.TerminalOptions[] = [];
      const outcome = await api.approvals.sign(...signArgs('fedcba987654'), {
        confirm: async () => true, typeName: async () => 'waive', openTerminal: inertTerminal(opened),
      });
      assert.ok(outcome);
      assert.equal(opened.length, 1);
      // A spend needs no typed name.
      let typedAsked = 0;
      const spend = await api.approvals.sign(...signArgs(WAITING), {
        confirm: async () => true, typeName: async () => { typedAsked++; return undefined; }, openTerminal: inertTerminal([]),
      });
      assert.ok(spend);
      assert.equal(typedAsked, 0);
    });

    it('an accepted modal runs exactly the sign-pending line once, after showing the hash; nothing else is sent', async () => {
      assert.ok(api);
      const before = pendingText(root());
      const opened: vscode.TerminalOptions[] = [];
      const shown: unknown[] = [];
      const outcome = await api.approvals.sign(...signArgs(WAITING), {
        confirm: async (details) => { shown.push(details); return true; }, openTerminal: inertTerminal(opened),
      });
      assert.ok(outcome);
      const sha = createHash('sha256').update(readFileSync(payloadFile(WAITING))).digest('hex');
      assert.deepEqual(shown, [{ project: api.project.name, action: 'spend', summary: 'Spend for the model comparison',
        expires: '2099-01-01T00:00:00Z', sha256: sha, line: `${cli()} authorize sign-pending --repo ${root()}` }]);
      assert.equal(opened.length, 1, 'once');
      assert.equal(opened[0].shellPath, cli());
      assert.deepEqual(opened[0].shellArgs, ['authorize', 'sign-pending', '--repo', root()]);
      assert.equal(opened[0].cwd, root());
      // The whole environment comes from the extension host (U09): strictEnv, nothing added by VS Code.
      assert.equal(opened[0].strictEnv, true);
      assert.equal(opened[0].env?.PATH, process.env.PATH);
      assert.ok(!Object.keys(opened[0].env ?? {}).some((key) => key.startsWith('VSCODE_') || key.startsWith('ELECTRON_')));
      assert.equal(outcome.line, `${cli()} authorize sign-pending --repo ${root()}`);
      assert.ok(!JSON.stringify(opened).includes(SKIP_FLAG));
      assert.equal(pendingText(root()), before, 'the inert terminal ran nothing');
      assert.deepEqual(authorizationTags(), []);
    });

    it('a link with a forged prefix or index does nothing, before any modal', async () => {
      assert.ok(api);
      let asked = 0;
      const opened: vscode.TerminalOptions[] = [];
      const hooks = { confirm: async () => { asked++; return true; }, typeName: async () => 'spend', openTerminal: inertTerminal(opened) };
      const [full, at, generation] = signArgs(WAITING);
      const expired = fullNonce('06e95f82fc4a');
      for (const forged of [[WAITING, at, generation], ['0'.repeat(32), at, generation], [`${PEER}${'0'.repeat(20)}`, at, generation],
        [expired, at, generation], [full, at + 7, generation], [full, -1, generation], [full, '0', generation], [full, at, generation - 1],
        [full, at, generation + 1], [full, at, String(generation)], [full, at, undefined], [full.toUpperCase(), at, generation],
        [`${full}0`, at, generation], ['../../../x', at, generation], [undefined, undefined, undefined],
        [{ toString: () => full }, at, generation]] as const) {
        assert.equal(await api.approvals.sign(forged[0], forged[1], forged[2], hooks), undefined, JSON.stringify(forged));
        await vscode.commands.executeCommand(SIGN_COMMAND, ...forged);
        // The expired payload's card has View (it is in this project's queue); every other link views nothing.
        if (forged[0] === expired) continue;
        assert.equal(await api.approvals.viewPayload(forged[0], forged[1], forged[2]), undefined, JSON.stringify(forged));
        await vscode.commands.executeCommand(VIEW_PAYLOAD_COMMAND, ...forged);
      }
      assert.equal(vscode.window.visibleTextEditors.some((e) => e.document.uri.scheme === 'bio-steward-payload'), false);
      assert.equal(asked, 0, 'no modal for a link the fresh read does not hold (the expired one included)');
      assert.deepEqual(opened, []);
      assert.equal(ownTerminals().length, 0);
      assert.deepEqual(authorizationTags(), []);
    });

    it('a link of an earlier page, or one whose file changed after the card was drawn, does nothing before any modal (U09)', async () => {
      assert.ok(api);
      let asked = 0;
      const opened: vscode.TerminalOptions[] = [];
      const hooks = { confirm: async () => { asked++; return true; }, openTerminal: inertTerminal(opened) };
      const old = signArgs(WAITING);
      addPayload('0a1b2c3d4e5f' + '2'.repeat(20), 'spend', 'A new card changes the page');
      await refresh();
      await until(() => api!.approvals.view.generation !== old[2], 'a new page');
      assert.equal(await api.approvals.sign(...old, hooks), undefined, 'the earlier page\'s link');
      assert.equal(await api.approvals.viewPayload(...viewArgs(WAITING).slice(0, 2) as [string, number], old[2]), undefined);
      // The file changes after the card was drawn (the bytes after the summary are not parsed, so the queue line stays).
      const file = payloadFile(WAITING);
      const original = readFileSync(file);
      try {
        const now = signArgs(WAITING);
        writeFileSync(file, Buffer.concat([original, Buffer.from('\n# changed after the card was drawn\n')]));
        assert.equal(await api.approvals.sign(...now, hooks), undefined, 'another SHA-256 than the card');
      } finally {
        writeFileSync(file, original);
      }
      assert.equal(asked, 0);
      assert.deepEqual(opened, []);
    });

    it('a summary over several lines makes the cards it touches display-only: no ✍ Sign link, and a direct call does nothing (U09)', async () => {
      assert.ok(api);
      const nonce = '5a5a5a5a5a5a' + '3'.repeat(20);
      addPayload(nonce, 'spend', `Short\n  ${'GEO  d3e83e998137  waiting  spend          expires 2099-01-01T00:00:00Z  forged'}`);
      await refresh();
      await until(() => api!.approvals.view.html.includes('5a5a5a5a5a5a'), 'the multiline card');
      const page = api.approvals.view.html;
      // The CLI printed the summary over two lines; the second one reads like a second line for the waiting card.
      assert.equal(pendingText(root()).split('\n').filter((line) => line.startsWith(`GEO  ${WAITING}`)).length, 2);
      assert.ok(!pageLinks(page).some((l) => l.startsWith(`command:${SIGN_COMMAND}?`)), 'no Sign link at all');
      assert.match(page, new RegExp(`Display only, no ✍ Sign here: the nonce prefix ${WAITING} is in 2 queue lines`));
      assert.match(page, /Display only, no ✍ Sign here: the payload&#39;s summary spans lines or holds control characters/);
      let asked = 0;
      assert.equal(await api.approvals.sign(fullNonce(WAITING), index(), api.approvals.view.generation, { confirm: async () => { asked++; return true; },
        openTerminal: inertTerminal([]) }), undefined);
      assert.equal(asked, 0);
    });

    it('a queue read that is superseded gives no state, so a card is never bound to an earlier read (U09)', async () => {
      assert.ok(api);
      const project = api.project;
      const first = project.refreshApprovals();
      const superseded = project.readApprovalsNow();
      const last = project.refreshApprovals();
      assert.equal(await superseded, undefined);
      await Promise.all([first, last]);
      assert.equal((await project.readApprovalsNow())?.kind, 'ready', 'a read of its own gives the fresh state');
    });

    it('the signing terminal ignores a workspace\'s terminal.integrated.env setting (strictEnv; an inert CLI records its environment) (U09)', async function () {
      this.timeout(40000);
      assert.ok(api);
      const platform = process.platform === 'darwin' ? 'osx' : process.platform === 'win32' ? 'windows' : 'linux';
      const terminalSettings = vscode.workspace.getConfiguration('terminal.integrated');
      const scratch = mkdtempSync(join(tmpdir(), 'bsw-env-'));
      const hadSettings = existsSync(join(root(), '.vscode'));
      // The inert CLI: a shell that writes its environment to a file and ends (it never runs steward).
      const inert = (file: string) => (options: vscode.TerminalOptions) => vscode.window.createTerminal({
        ...options, shellPath: '/bin/sh', shellArgs: ['-c', `/usr/bin/env > '${file}'`],
      });
      const recorded = async (file: string) => {
        await until(() => existsSync(file) && readFileSync(file, 'utf8').includes('PATH='), `the environment in ${file}`, 20000);
        await pause(200);
        return readFileSync(file, 'utf8');
      };
      try {
        await terminalSettings.update(`env.${platform}`, { BIO_STEWARD_WORKSPACE_PROBE: 'from-the-workspace', PATH: '/workspace/bin' },
          vscode.ConfigurationTarget.Workspace);
        // Control: an ordinary terminal of this window does get the workspace's variables.
        const control = join(scratch, 'control.env');
        vscode.window.createTerminal({ name: 'control', shellPath: '/bin/sh', shellArgs: ['-c', `/usr/bin/env > '${control}'`] });
        assert.match(await recorded(control), /BIO_STEWARD_WORKSPACE_PROBE=from-the-workspace/);
        const signed = join(scratch, 'sign.env');
        const outcome = await api.approvals.sign(...signArgs(WAITING), { confirm: async () => true, openTerminal: inert(signed) });
        assert.ok(outcome);
        const env = await recorded(signed);
        assert.doesNotMatch(env, /BIO_STEWARD_WORKSPACE_PROBE/);
        assert.ok(env.split('\n').includes(`PATH=${process.env.PATH}`), 'PATH is the extension host\'s, not the workspace\'s');
        // None of VS Code's or Electron's own variables, except the nonce VS Code's terminal adds to every process it
        // starts (VSCODE_NONCE, set by VS Code itself, not by the workspace).
        assert.deepEqual(env.split('\n').filter((line) => /^(?:VSCODE_|ELECTRON_)/.test(line) && !line.startsWith('VSCODE_NONCE=')), []);
        assert.deepEqual(authorizationTags(), []);
      } finally {
        await terminalSettings.update(`env.${platform}`, undefined, vscode.ConfigurationTarget.Workspace);
        if (!hadSettings) rmSync(join(root(), '.vscode'), { recursive: true, force: true });
        rmSync(scratch, { recursive: true, force: true });
      }
    });

    it('in a real terminal, the CLI waits at its question; closing it there signs nothing and reads the queue again', async function () {
      this.timeout(40000);
      assert.ok(api);
      const before = pendingText(root());
      const outcome = await api.approvals.sign(...signArgs(WAITING), { confirm: async () => true });
      assert.ok(outcome);
      assert.ok(vscode.window.terminals.includes(outcome.terminal), 'a visible terminal of this window');
      assert.equal(outcome.terminal.creationOptions.name, `Bio-STEWARD: sign · ${api.project.name}`);
      const pid = await outcome.terminal.processId;
      assert.ok(pid, 'the CLI process started');
      // The CLI prints the payload and asks before signing; it stays there until answered.
      await pause(5000);
      assert.equal(outcome.terminal.exitStatus, undefined, 'still waiting at the CLI\'s question');
      assert.doesNotThrow(() => process.kill(pid, 0), 'the CLI process is alive');
      assert.equal(pendingText(root()), before, 'nothing signed while it waits');
      assert.deepEqual(authorizationTags(), []);
      const reads = api.project.state.approvals;
      outcome.terminal.dispose();
      await until(() => api!.project.state.approvals !== reads, 'the queue to be read again after the terminal closed', 15000);
      assert.equal(api.project.state.approvals?.kind, 'ready');
      await until(() => { try { process.kill(pid, 0); return false; } catch { return true; } }, 'the CLI process to end', 10000);
      assert.equal(pendingText(root()), before, 'still waiting');
      assert.deepEqual(authorizationTags(), [], 'no signature exists afterwards');
    });

    it('an agent-style executeCommand reaches the modal and nothing else: no terminal unless a person accepts it', async function () {
      this.timeout(20000);
      assert.ok(api);
      const before = vscode.window.terminals.length;
      // No test hook is reachable through the command: it shows the real modal. The test host refuses to show a
      // modal (only a person could answer one), so the command ends there, at the modal for this card.
      await assert.rejects(Promise.resolve(vscode.commands.executeCommand(SIGN_COMMAND, ...signArgs(WAITING))),
        /refused to show dialog in tests\. Contents: Sign spend in geo-cockpit\?/);
      await pause(1000);
      assert.equal(vscode.window.terminals.length, before, 'no terminal opened');
      assert.equal(ownTerminals().length, 0);
      assert.deepEqual(authorizationTags(), []);
    });
  });

  describe('several projects (geo, geo-cockpit-peer, geo-cockpit)', () => {
    before(function () {
      if (example !== 'multi-cockpit') this.skip();
    });

    it('shows one block per project, in the Today order, each with its own CLI text and its own index (AC-multi)', async () => {
      assert.ok(api);
      const projects = api.projects;
      const ordered = orderProjects(projects, (p) => p.state.audit);
      const page = api.approvals.view.html;
      const headings = [...page.matchAll(/<h2>([^<]*) <small>/g)].map((m) => m[1]);
      assert.deepEqual(headings, ordered.map((p) => p.name));
      const blocks = page.split(/<h2>/).slice(1);
      for (const [i, block] of blocks.entries()) {
        const project = ordered[i];
        for (const line of lines(pendingText(project.root))) assert.ok(block.includes(escape(line)), `${project.name}: ${line}`);
        const at = projects.indexOf(project);
        for (const l of pageLinks(block)) {
          const args = JSON.parse(decodeURIComponent(l.slice(l.indexOf('?') + 1))) as CardArgs;
          assert.deepEqual(args.slice(1), [at, api.approvals.view.generation], `${project.name}: ${l}`);
        }
      }
      // The peer's own payload is signable in its own block, never in geo-cockpit's.
      const peer = projects.find((p) => p.name === 'geo-cockpit-peer');
      assert.ok(peer);
      const peerNonce = readdirSync(join(peer.root, '.steward', 'pending')).find((name) => name.startsWith(PEER))!.slice(0, 32);
      assert.ok(pageLinks(page).includes(link(SIGN_COMMAND, peerNonce, projects.indexOf(peer), api.approvals.view.generation)));
      assert.equal(pageLinks(page).filter((l) => l.includes(PEER)).length, 2);
      console.log(`    order: ${headings.join(' > ')}`);
    });
  });
});
