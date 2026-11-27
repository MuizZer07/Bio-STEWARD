import { strict as assert } from 'node:assert';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, renameSync, rmSync, statSync, symlinkSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { commands, isAllowed, type Invocation } from '../../src/cli/commands';
import { signingArgs, signingCommand, signingEnvironment } from '../../src/cli/signing';
import {
  actionIcon, approvalsHtml, approvalsSummary, bindCard, cardUri, needsTypedName, pageLinks, parsePayload, parsePendingText,
  printedLine, queueCode, SIGN_BUTTON, SIGN_COMMAND, signDialog, signedTag, typedNamePrompt, VIEW_PAYLOAD_COMMAND,
  type ApprovalsBlock, type ApprovalsState, type Binding, type PayloadFields, type PayloadRead,
} from '../../src/model/approvals';
import { parseToml } from '../../src/model/toml';
import { PAYLOAD_LIMIT_BYTES, payloadRead, pendingNames, readPendingPayload } from '../../src/pendingPayload';

// P5 Approvals as cards (task U04b, design v0.8): the text of `steward authorize pending --all-projects` of CLI
// 0.20.6 (the U01 corpus), one card per payload line, the payload read from `.steward/pending/<nonce>.txt`, and the
// signing command ✍ Sign runs in a terminal after the modal.

const extensionRoot = join(__dirname, '..', '..', '..');
const fixtures = join(extensionRoot, 'test', 'fixtures', 'cockpit', 'authorize-pending');
const text = (name: string) => readFileSync(join(fixtures, `${name}.txt`), 'utf8');
type Ready = Extract<ApprovalsState, { kind: 'ready' }>;
const ready = (stdout: string): Ready => {
  const state = parsePendingText(stdout);
  assert.equal(state.kind, 'ready', stdout.slice(0, 80));
  return state as Ready;
};
const lines = (name: string) => text(name).replace(/\n$/, '').split('\n');
// The CLI's flag that skips its question, assembled so this file is not itself a match for the source scan below.
const SKIP_FLAG = ['-', '-', 'y', 'e', 's'].join('');
const escape = (s: string) => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;');
const FULL = 'd3e83e998137' + 'a'.repeat(20);
const BOUND: Binding = { kind: 'bound', line: { text: '', kind: 'payload' }, fields: {} as PayloadFields };
const bound = (nonce: string, sha256: string): PayloadRead => ({ kind: 'read', nonce, sha256, binding: BOUND });

// A payload in the format CLI 0.20.6 `authorize.prepare` writes.
function payloadText(nonce: string, summary = 'Spend for the model comparison', action = 'spend'): string {
  return ['steward-authorization/1', `repo_id: ${'0'.repeat(8)}-0000-4000-8000-${'0'.repeat(12)}`, `action: ${action}`,
    'object: models/compare', 'scope: run=compare', 'budget: 10 USD', 'expires: 2099-01-01T00:00:00Z',
    `baseline: ${'1'.repeat(40)}`, `nonce: ${nonce}`, 'summary: |', ...summary.split('\n').map((l) => `  ${l}`), ''].join('\n');
}

function files(dir: string, ext: RegExp): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path, ext) : ext.test(name) ? [path] : [];
  });
}

function block(stdout: string, payloads: [string, PayloadRead][] = [], index = 0): ApprovalsBlock {
  return { root: '/w/geo-cockpit', name: 'geo-cockpit', index, approvals: ready(stdout), payloads: new Map(payloads) };
}

describe('Approvals (U04b, reduced form, cards)', () => {
  describe('steward authorize pending --all-projects', () => {
    it('keeps every line of each U01 fixture unchanged, and reads each payload line\'s fields as printed', () => {
      for (const name of ['geo', 'geo-cockpit', 'geo-cockpit-all-projects']) {
        const state = ready(text(name));
        assert.deepEqual(state.lines.map((line) => line.text), lines(name), name);
        assert.equal(state.text, text(name));
      }
      assert.equal(ready(text('geo')).waiting, 0);
      const all = ready(text('geo-cockpit-all-projects'));
      assert.equal(all.waiting, 2);
      assert.deepEqual(all.lines.map((l) => [l.kind, l.code, l.nonce, l.state, l.action, l.expires, l.summary]), [
        ['payload', 'GEO', '06e95f82fc4a', 'expired', 'spend', '2000-01-02T00:00:00Z', 'Spend for the first rerun'],
        ['payload', 'GEO', 'd3e83e998137', 'waiting', 'spend', '2099-01-01T00:00:00Z', 'Spend for the model comparison'],
        ['skipped', undefined, undefined, undefined, undefined, undefined, undefined],
        ['payload', 'PEER', '7b274a7e9224', 'waiting', 'spend', '2099-01-01T00:00:00Z', 'Spend for the peer rerun'],
        ['summary', undefined, undefined, undefined, undefined, undefined, undefined],
      ]);
      // An action longer than the CLI's 14-character column, and an empty summary.
      const long = ready('GEO  0123456789ab  waiting  freeze.confirmatory expires 2099-01-01T00:00:00Z  \n1 waiting\n');
      assert.deepEqual([long.lines[0].action, long.lines[0].summary], ['freeze.confirmatory', '']);
    });

    it('is unreadable, never guessed, without the CLI\'s closing line, or when too large', () => {
      for (const bad of ['', 'not the CLI\n', '1 waiting\nGEO  d3e83e998137  waiting  spend  expires 2099-01-01T00:00:00Z  x\n',
        `${'x'.repeat(300 * 1024)}\n0 waiting\n`, `${'line\n'.repeat(600)}0 waiting\n`]) {
        assert.deepEqual(parsePendingText(bad), { kind: 'unreadable' }, bad.slice(0, 40));
      }
      assert.equal(parsePendingText('0 waiting').kind, 'ready', 'without a final line break');
      assert.equal(approvalsSummary(ready(text('geo-cockpit'))), '1 waiting');
      assert.match(approvalsSummary({ kind: 'failed' }), /did not finish/);
    });
  });

  describe('the cards', () => {
    const sha = 'f'.repeat(64);
    const EXPIRED = '06e95f82fc4a' + 'b'.repeat(20);
    const html = (binding: PayloadRead = bound(FULL, sha)) => approvalsHtml({ kind: 'ready', blocks: [block(text('geo-cockpit-all-projects'), [
      ['d3e83e998137', binding],
      ['06e95f82fc4a', { kind: 'read', nonce: EXPIRED, sha256: 'e'.repeat(64) }],
    ], 3)] }, 7);

    it('has default-src \'none\', no script, and only the two card links, each carrying the full nonce, index and generation', () => {
      const page = html();
      assert.match(page, /<meta http-equiv="Content-Security-Policy" content="default-src 'none'">/);
      assert.doesNotMatch(page, /<script|<style|style=|<img|<iframe|<form|\son\w+=/i);
      const links = pageLinks(page);
      assert.deepEqual(links, [
        `command:${VIEW_PAYLOAD_COMMAND}?${encodeURIComponent(`["${EXPIRED}",3,7]`)}`,
        `command:${VIEW_PAYLOAD_COMMAND}?${encodeURIComponent(`["${FULL}",3,7]`)}`,
        `command:${SIGN_COMMAND}?${encodeURIComponent(`["${FULL}",3,7]`)}`,
      ]);
      assert.match(page, /Reduced form/);
    });

    it('shows each CLI line as printed, the summary, expiry, hash and the buttons (parity)', () => {
      const page = html();
      for (const line of lines('geo-cockpit-all-projects')) assert.ok(page.includes(escape(line)), line);
      assert.ok(page.includes(sha) && page.includes('read from the file'));
      assert.ok(page.includes('View exactly what you are approving') && page.includes('✍ Sign'));
      assert.ok(page.includes('expires 2099-01-01T00:00:00Z') && page.includes('Spend for the model comparison'));
      // The peer's payload is not in this project's queue: no View, no Sign, a pointer to its project.
      assert.match(page, /This payload is in PEER's checkout/);
      assert.match(page, /Expired: it can no longer be signed/);
      assert.equal(actionIcon('spend'), '💳');
      assert.equal(actionIcon('constructor'), '•');
      console.log(`      links: ${pageLinks(page).map(decodeURIComponent).join(' | ')}`);
    });

    it('a card whose queue line does not bind to the file read is display-only: View, no ✍ Sign, and the reason', () => {
      const page = html({ kind: 'read', nonce: FULL, sha256: sha, binding: { kind: 'display-only', reason: 'the nonce prefix d3e83e998137 is in 2 queue lines' } });
      assert.ok(!pageLinks(page).some((link) => link.startsWith(`command:${SIGN_COMMAND}?`)));
      assert.ok(pageLinks(page).includes(`command:${VIEW_PAYLOAD_COMMAND}?${encodeURIComponent(`["${FULL}",3,7]`)}`));
      assert.match(page, /Display only, no ✍ Sign here: the nonce prefix d3e83e998137 is in 2 queue lines/);
      assert.ok(!pageLinks(html({ kind: 'read', nonce: FULL, sha256: sha })).some((link) => link.includes(SIGN_COMMAND)), 'no binding, no Sign');
    });

    it('shows ✓ Signed with its tag for a signed request, and no Sign', () => {
      const signed = 'GEO  d3e83e998137  signed   spend          expires 2099-01-01T00:00:00Z  Spend\n0 waiting\n';
      const page = approvalsHtml({ kind: 'ready', blocks: [block(signed, [['d3e83e998137', { kind: 'read', nonce: FULL, sha256: sha }]])] });
      assert.ok(page.includes(`<b>✓ Signed</b> <code>steward/auth/${FULL}</code>`));
      assert.ok(!page.includes('✍ Sign'));
      assert.equal(signedTag('anchor', FULL), undefined);
    });

    it('escapes hostile summary text: it is shown, never rendered', () => {
      const hostile = '<img src=x onerror=alert(1)><script>x</script>"\'&<a href="command:evil">';
      const stdout = `GEO  d3e83e998137  waiting  spend          expires 2099-01-01T00:00:00Z  ${hostile}\n1 waiting\n`;
      const page = approvalsHtml({ kind: 'ready', blocks: [block(stdout, [['d3e83e998137', bound(FULL, sha)]])] });
      assert.ok(page.includes(escape(hostile)));
      assert.doesNotMatch(page, /<img|<script|<a href="command:evil/);
      assert.equal(pageLinks(page).filter((link) => !link.startsWith(`command:${VIEW_PAYLOAD_COMMAND}?`)
        && !link.startsWith(`command:${SIGN_COMMAND}?`)).length, 0);
    });

    it('with several projects: one block each, in the order given; untrusted and empty pages have no link', () => {
      const page = approvalsHtml({ kind: 'ready', blocks: [block(text('geo-cockpit'), [], 1),
        { ...block(text('geo'), [], 0), name: 'geo', root: '/w/geo' }] });
      assert.ok(page.indexOf('<h2>geo-cockpit') < page.indexOf('<h2>geo <'));
      for (const kind of ['untrusted', 'none'] as const) assert.deepEqual(pageLinks(approvalsHtml({ kind })), [], kind);
      assert.match(approvalsHtml({ kind: 'untrusted' }), /Restricted Mode/);
    });

    it('refuses to build a link from a prefix, a forged nonce, index or generation', () => {
      for (const [nonce, index, generation] of [['d3e83e998137', 0, 1], [FULL.toUpperCase(), 0, 1], [`${FULL}"`, 0, 1],
        [FULL, -1, 1], [FULL, 1.5, 1], [FULL, 0, -1], [FULL, 0, 0.5]] as const) {
        assert.throws(() => cardUri(SIGN_COMMAND, nonce, index, generation), /Invalid card reference/);
      }
    });

    it('asks for the typed name for exactly the high-stakes actions', () => {
      for (const action of ['unseal', 'freeze.confirmatory', 'policy.change', 'waive', 'pin.retire', 'amend']) assert.ok(needsTypedName(action));
      for (const action of ['spend', 'anchor', 'freeze', 'pin', 'Unseal']) assert.equal(needsTypedName(action), false, action);
    });
  });

  describe('the payload read (.steward/pending/<nonce>.txt)', () => {
    let root: string;
    const pending = () => join(root, '.steward', 'pending');
    beforeEach(() => {
      root = mkdtempSync(join(tmpdir(), 'bsw-pending-'));
      mkdirSync(pending(), { recursive: true });
    });
    afterEach(() => rmSync(root, { recursive: true, force: true }));

    it('reads the file the prefix names, unchanged, with its SHA-256', async () => {
      const hostile = 'action = spend\nsummary = <script>alert(1)</script>\u001b[2J\u0007 ‮ done\n';
      writeFileSync(join(pending(), `${FULL}.txt`), hostile);
      const read = await readPendingPayload(root, 'd3e83e998137');
      assert.equal(read.kind, 'read');
      if (read.kind !== 'read') return;
      assert.equal(read.text, hostile);
      assert.equal(read.nonce, FULL);
      assert.equal(read.sha256, createHash('sha256').update(hostile).digest('hex'));
      assert.deepEqual(await payloadRead(root, 'd3e83e998137'), { kind: 'read', nonce: FULL, sha256: read.sha256,
        binding: { kind: 'display-only', reason: 'no fresh steward authorize pending read' } });
      assert.equal((await readPendingPayload(root, FULL)).kind, 'read', 'the full nonce names it too');
      assert.equal((await readPendingPayload(root, 'd3e83e998137' + 'b'.repeat(20))).kind, 'unreadable', 'another nonce of that prefix');
      assert.equal(await payloadRead(root, '7b274a7e9224'), undefined, 'a peer\'s prefix is not in this queue');
    });

    it('refuses a link, a large file, non-UTF-8 text, an ambiguous or malformed prefix, and a linked queue folder', async () => {
      const outside = mkdtempSync(join(tmpdir(), 'bsw-outside-'));
      try {
        writeFileSync(join(outside, 'secret.txt'), 'secret');
        symlinkSync(join(outside, 'secret.txt'), join(pending(), `${FULL}.txt`));
        assert.match(JSON.stringify(await readPendingPayload(root, 'd3e83e998137')), /without following a link/);
        rmSync(join(pending(), `${FULL}.txt`));
        writeFileSync(join(pending(), `${FULL}.txt`), Buffer.alloc(PAYLOAD_LIMIT_BYTES + 1, 0x61));
        assert.match(JSON.stringify(await readPendingPayload(root, 'd3e83e998137')), /larger than/);
        writeFileSync(join(pending(), `${FULL}.txt`), Buffer.from([0xff, 0xfe, 0x00]));
        assert.match(JSON.stringify(await readPendingPayload(root, 'd3e83e998137')), /not UTF-8/);
        writeFileSync(join(pending(), `d3e83e998137${'c'.repeat(20)}.txt`), 'other');
        assert.match(JSON.stringify(await readPendingPayload(root, 'd3e83e998137')), /not in this project/);
        for (const bad of ['d3e83e99813', '../../secret', 'D3E83E998137']) {
          assert.match(JSON.stringify(await readPendingPayload(root, bad)), /not named by a nonce/, bad);
        }
        rmSync(join(root, '.steward'), { recursive: true });
        mkdirSync(join(outside, 'pending'));
        writeFileSync(join(outside, 'pending', `${FULL}.txt`), 'x');
        symlinkSync(outside, join(root, '.steward'));
        assert.match(JSON.stringify(await readPendingPayload(root, 'd3e83e998137')), /link or not a folder/);
        assert.ok(!(await pendingNames(root) instanceof Map));
      } finally {
        rmSync(outside, { recursive: true, force: true });
      }
    });
  });

  describe('the payload read keeps its boundary across the open (U09)', () => {
    let root: string;
    let outside: string;
    const steward = () => join(root, '.steward');
    beforeEach(() => {
      root = mkdtempSync(join(tmpdir(), 'bsw-race-'));
      outside = mkdtempSync(join(tmpdir(), 'bsw-race-outside-'));
      mkdirSync(join(steward(), 'pending'), { recursive: true });
      writeFileSync(join(steward(), 'pending', `${FULL}.txt`), 'inside');
      mkdirSync(join(outside, 'pending'));
      writeFileSync(join(outside, 'pending', `${FULL}.txt`), 'outside');
    });
    afterEach(() => {
      rmSync(root, { recursive: true, force: true });
      rmSync(outside, { recursive: true, force: true });
    });
    // `.steward` replaced by a link to another folder after the folder checks, so the open goes through the link.
    const swap = () => {
      renameSync(steward(), join(root, '.steward-real'));
      symlinkSync(outside, steward());
    };
    const back = () => {
      unlinkSync(steward());
      renameSync(join(root, '.steward-real'), steward());
    };

    it('refuses an ancestor replaced by a link between the checks and the open', async () => {
      const read = await readPendingPayload(root, FULL, { beforeOpen: swap });
      assert.deepEqual(read, { kind: 'unreadable', reason: 'changed, or was reached through a link, while it was read' });
    });

    it('refuses it also when the link is put back to the real folder before the checks after the read', async () => {
      const read = await readPendingPayload(root, FULL, { beforeOpen: swap, afterOpen: back });
      assert.deepEqual(read, { kind: 'unreadable', reason: 'changed, or was reached through a link, while it was read' });
      const plain = await readPendingPayload(root, FULL);
      assert.equal(plain.kind === 'read' && plain.text, 'inside', 'without a swap, the file inside is read');
    });
  });

  describe('one snapshot per card: the queue line must bind to the bytes read (U09)', () => {
    const line = (code: string, nonce: string, summary = 'Spend for the model comparison', state = 'waiting') =>
      `${code}  ${nonce.slice(0, 12)}  ${state.padEnd(8)} ${'spend'.padEnd(14)} expires 2099-01-01T00:00:00Z  ${summary}`;
    const queue = (...rows: string[]) => ready(`${rows.join('\n')}\n1 waiting\n`);

    it('reads a payload as CLI 0.20.6 parse does, and prints its line as _pending does', () => {
      const fields = parsePayload(payloadText(FULL));
      assert.ok(fields);
      assert.deepEqual([fields.action, fields.expires, fields.nonce, fields.summary],
        ['spend', '2099-01-01T00:00:00Z', FULL, 'Spend for the model comparison']);
      assert.equal(printedLine('GEO', fields, 'waiting'), line('GEO', FULL));
      assert.equal(parsePayload(payloadText(FULL).replace('steward-authorization/1', 'other/1')), undefined);
      assert.equal(parsePayload(payloadText(FULL, 'x', 'spend.more')), undefined, 'an action the CLI does not know');
      assert.equal(parsePayload(payloadText(FULL).replace('budget: 10 USD\n', '')), undefined, 'a missing field');
      assert.equal(parsePayload(`${payloadText(FULL)}`.replace('scope:', 'scope: a\nscope:')), undefined, 'a repeated field');
      // The summary is cut at 60 code points, as Python slices it.
      const long = '😀'.repeat(70);
      assert.equal(printedLine('GEO', parsePayload(payloadText(FULL, long))!, 'waiting'), line('GEO', FULL, '😀'.repeat(60)));
    });

    it('binds when exactly one line under this project\'s code holds the prefix and describes the bytes read', () => {
      const result = bindCard(queue(line('GEO', FULL), line('PEER', '7b274a7e9224' + 'c'.repeat(20))), 'GEO', FULL, payloadText(FULL));
      assert.equal(result.kind, 'bound');
      if (result.kind === 'bound') assert.deepEqual([result.fields.action, result.line.state], ['spend', 'waiting']);
    });

    it('fails closed on a duplicate prefix of a peer, another project\'s code, a changed file, a stale or failed read', () => {
      const cases: [ApprovalsState | undefined, string | undefined, string, RegExp][] = [
        [queue(line('GEO', FULL), line('PEER', FULL)), 'GEO', payloadText(FULL), /is in 2 queue lines/],
        [queue(line('GEO', FULL), line('GEO', FULL)), 'GEO', payloadText(FULL), /is in 2 queue lines/],
        [queue(line('PEER', FULL)), 'GEO', payloadText(FULL), /under PEER, not this project's GEO/],
        [queue(line('GEO', FULL)), undefined, payloadText(FULL), /queue code/],
        [queue(line('GEO', FULL)), 'GEO', payloadText(FULL, 'Spend for something else'), /does not describe the payload read now/],
        [queue(line('GEO', FULL)), 'GEO', payloadText('d3e83e998137' + 'b'.repeat(20)), /not one the CLI would list/],
        [queue(line('GEO', FULL)), 'GEO', 'not a payload', /not one the CLI would list/],
        [{ kind: 'failed' }, 'GEO', payloadText(FULL), /no fresh/],
        [undefined, 'GEO', payloadText(FULL), /no fresh/],
        [queue(line('GEO', 'aaaaaaaaaaaa' + 'a'.repeat(20))), 'GEO', payloadText(FULL), /is not in the queue/],
      ];
      for (const [state, code, payload, reason] of cases) {
        const result = bindCard(state, code, FULL, payload);
        assert.equal(result.kind, 'display-only', String(reason));
        if (result.kind === 'display-only') assert.match(result.reason, reason);
      }
    });

    it('fails closed on a summary over several lines, even when its second line looks like a payload line', () => {
      const forged = line('GEO', FULL, 'forged');
      const summary = `Short\n${forged}`;
      // What the CLI prints for it: the first 60 code points of the summary, line break included.
      const printed = `${line('GEO', FULL, Array.from(summary).slice(0, 60).join(''))}`;
      const state = ready(`${printed}\n1 waiting\n`);
      const result = bindCard(state, 'GEO', FULL, payloadText(FULL, summary));
      assert.equal(result.kind, 'display-only');
      // A summary with a terminal control character is refused too.
      const escape = bindCard(queue(line('GEO', FULL, 'a\u001b[2Jb')), 'GEO', FULL, payloadText(FULL, 'a\u001b[2Jb'));
      assert.deepEqual(escape, { kind: 'display-only', reason: 'the payload\'s summary spans lines or holds control characters' });
    });

    it('takes the queue code from [exchange] code, or "." without an exchange', () => {
      assert.equal(queueCode(parseToml('[steward]\nrepo_id = "x"\n')), '.');
      assert.equal(queueCode(parseToml('[exchange]\ncode = "GEO"\n')), 'GEO');
      assert.equal(queueCode(parseToml('[exchange]\ncode = "geo"\n')), undefined);
      assert.equal(queueCode(parseToml('exchange = 1\n')), undefined);
    });
  });

  describe('the signing command', () => {
    it('runs with the extension host\'s environment only, without VS Code\'s internal variables', () => {
      const env = signingEnvironment({ PATH: '/usr/bin', HOME: '/var/empty', SSH_AUTH_SOCK: '/tmp/agent', VSCODE_IPC_HOOK: 'x',
        ELECTRON_RUN_AS_NODE: '1', 'BAD\nKEY': 'x', NUL: 'a\0b', EMPTY: undefined });
      assert.deepEqual(env, { PATH: '/usr/bin', HOME: '/var/empty', SSH_AUTH_SOCK: '/tmp/agent', TERM: 'xterm-256color' });
      assert.ok(Object.isFrozen(env));
    });

    it('the modal says that the CLI\'s own prompt is the review of record', () => {
      const dialog = signDialog({ project: 'geo', action: 'spend', summary: 's', expires: 'e', sha256: 'ab'.repeat(32), line: 'l' });
      assert.match(dialog.detail.join('\n'), /The review of record is the CLI's own prompt in the terminal/);
      assert.match(dialog.detail.join('\n'), /not only this card/);
    });

    it('is the CLI\'s interactive sign-pending with --repo and nothing else', () => {
      assert.deepEqual(signingArgs('/w/geo'), ['authorize', 'sign-pending', '--repo', '/w/geo']);
      assert.deepEqual(signingCommand('/opt/bin/steward', '/w/geo'), {
        program: '/opt/bin/steward', args: ['authorize', 'sign-pending', '--repo', '/w/geo'],
        line: '/opt/bin/steward authorize sign-pending --repo /w/geo',
      });
      assert.equal(signingCommand('/opt/my tools/steward', "/w/it's here").line,
        "'/opt/my tools/steward' authorize sign-pending --repo '/w/it'\\''s here'");
    });

    it('refuses a relative path or any control character', () => {
      for (const [cli, root] of [['steward', '/w'], ['/bin/steward', 'w'], ['/bin/steward\n', '/w'], ['/bin/steward', '/w\r'],
        ['/bin/steward', '/w\u001b[A'], ['/bin/steward', '/w\t'], ['/bin/steward', '/w\u007f']]) {
        assert.throws(() => signingCommand(cli, root), /Invalid/, JSON.stringify([cli, root]));
      }
    });

    it('the modal names the action, summary, expiry, hash and exact command, and says the CLI asks and the key completes it', () => {
      const line = signingCommand('/opt/bin/steward', '/w/geo').line;
      const dialog = signDialog({ project: 'geo', action: 'spend', summary: 'Spend for the model comparison',
        expires: '2099-01-01T00:00:00Z', sha256: 'ab'.repeat(32), line });
      assert.equal(dialog.title, 'Sign spend in geo?');
      assert.deepEqual(dialog.detail.slice(0, 4), ['Action: spend', 'Summary: Spend for the model comparison',
        'Expires: 2099-01-01T00:00:00Z', `Payload SHA-256 (read from the file): ${'ab'.repeat(32)}`]);
      assert.ok(dialog.detail.includes(`  ${line}`), 'the exact command line');
      assert.match(dialog.detail.join('\n'), /asks before each signature/);
      assert.match(dialog.detail.join('\n'), /Your key's own prompt completes each signature/);
      assert.equal(dialog.detail.join('\n').includes(SKIP_FLAG), false);
      assert.equal(SIGN_BUTTON, 'Sign in a Terminal');
      assert.deepEqual(typedNamePrompt('unseal'), { title: 'Bio-STEWARD: confirm unseal',
        prompt: 'unseal is a high-stakes action. Type its name to continue.', mismatch: 'Type unseal exactly' });
    });

    it('is never an allow-listed invocation: the runner refuses it, and the builders only read the queue', () => {
      const pendingRead = commands.authorizePending();
      assert.deepEqual(pendingRead.args, ['authorize', 'pending', '--all-projects']);
      assert.ok(isAllowed(pendingRead));
      for (const args of [['authorize', 'sign-pending'], ['authorize', 'sign-pending', '--all-projects'], ['authorize', 'sign', FULL]]) {
        const forged: Invocation = { args, repoIndex: 2, paths: [], confirmation: true };
        assert.equal(isAllowed(forged), false, args.join(' '));
      }
      for (const builder of Object.values(commands) as ((...a: never[]) => Invocation)[]) {
        let built: Invocation | undefined;
        try {
          built = builder();
        } catch {
          continue;
        }
        if (built?.args?.[0] === 'authorize') assert.deepEqual(built.args.slice(0, 2), ['authorize', 'pending']);
      }
    });

    it('the source and bundle never hold the skip flag; nothing types into a terminal; one path builds and runs the command', () => {
      const sources = files(join(extensionRoot, 'src'), /\.ts$/);
      const bundle = join(extensionRoot, 'dist', 'extension.js');
      assert.ok(sources.length > 20);
      for (const file of [...sources, ...(existsSync(bundle) ? [bundle] : [])]) {
        assert.equal(readFileSync(file, 'utf8').includes(SKIP_FLAG), false, file);
      }
      const rel = (file: string) => file.slice(extensionRoot.length);
      const holding = (pattern: RegExp) => sources.filter((file) => pattern.test(readFileSync(file, 'utf8'))).map(rel).sort();
      assert.deepEqual(holding(/\.sendText\(/), [], 'the old "type without Enter" path is gone');
      assert.deepEqual(holding(/createTerminal\(/), ['/src/ui/approvals.ts']);
      assert.deepEqual(holding(/signingCommand\(/), ['/src/cli/signing.ts', '/src/ui/approvals.ts']);
      assert.deepEqual(holding(/shellPath/), ['/src/ui/approvals.ts']);
      // Only the signing module, and the panel's words about it, name the signing command; the allow-list does not.
      assert.deepEqual(holding(/sign-pending/), ['/src/cli/signing.ts', '/src/model/approvals.ts', '/src/ui/approvals.ts']);
    });
  });
});
