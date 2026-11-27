// Unit suite (plain Node, mocha). T01 holds the manifest's safety-relevant declarations; T02 onwards add the model,
// the builders, the allow-list and freshness here.
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

interface Setting {
  scope?: string;
  default?: unknown;
}

const root = join(__dirname, '..', '..', '..');
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const settings: Record<string, Setting> = manifest.contributes.configuration.properties;

describe('manifest', () => {
  it('names the extension and the CLI it was tested with', () => {
    assert.equal(manifest.name, 'bio-steward');
    assert.equal(manifest.publisher, 'MuizZer07');
    assert.deepEqual(manifest.bioSteward, { minimumCli: '0.20.6', testedWithCli: '0.20.6' });
  });

  it('uses a 0.0.x version before the public release (F5)', () => {
    assert.match(manifest.version, /^0\.0\.\d+$/);
  });

  it('activates on a steward.toml in the workspace', () => {
    assert.deepEqual(manifest.activationEvents, ['workspaceContains:**/steward.toml']);
  });

  it('runs where the workspace is', () => {
    assert.deepEqual(manifest.extensionKind, ['workspace']);
  });

  it('is limited in untrusted workspaces, with a reason and the workspace settings it ignores there', () => {
    const trust = manifest.capabilities.untrustedWorkspaces;
    assert.equal(trust.supported, 'limited');
    assert.ok(trust.description.length > 0);
    const resourceSettings = Object.keys(settings).filter((k) => settings[k].scope === 'resource');
    assert.deepEqual([...trust.restrictedConfigurations].sort(), resourceSettings.sort());
  });

  it('declares that virtual workspaces are not supported', () => {
    assert.equal(manifest.capabilities.virtualWorkspaces.supported, false);
  });

  it('has the settings of design v0.1 §5.8 with their defaults and scopes', () => {
    const expected: Record<string, [unknown, string]> = {
      'bioSteward.cliPath': ['', 'machine'],
      'bioSteward.gate': ['default', 'resource'],
      'bioSteward.check.onSave': [false, 'resource'],
      'bioSteward.report.location': ['auto', 'resource'],
      'bioSteward.diagnostics.unknownSeverity': ['information', 'resource'],
      'bioSteward.timeoutSeconds': [120, 'machine'],
      'bioSteward.registry': ['respect', 'machine'],
      // 0.2.0 P2 (U02): Where am I? on reopening, on by default, with an off switch, after N days.
      'bioSteward.whereAmI.showOnReopen': [true, 'window'],
      'bioSteward.whereAmI.reopenAfterDays': [3, 'window'],
      // 0.2.0 P4 (U03): the agent logs `tokens report` reads; machine-scoped, so a repository cannot point them.
      'bioSteward.tokens.claudeLogs': [[], 'machine'],
      'bioSteward.tokens.codexLogs': [[], 'machine'],
      'bioSteward.tokens.geminiLogs': [[], 'machine'],
    };
    assert.deepEqual(Object.keys(settings).sort(), Object.keys(expected).sort());
    for (const [key, [def, scope]] of Object.entries(expected)) {
      assert.deepEqual(settings[key].default, def, `${key} default`);
      assert.equal(settings[key].scope, scope, `${key} scope`);
    }
  });

  it('has exactly one runtime dependency, pinned', () => {
    assert.deepEqual(Object.keys(manifest.dependencies), ['ajv']);
    for (const spec of Object.values({ ...manifest.dependencies, ...manifest.devDependencies })) {
      assert.match(String(spec), /^\d+\.\d+\.\d+$/, `exact version, got ${String(spec)}`);
    }
  });

  it('pins TypeScript to 6.0.x (F1)', () => {
    assert.match(manifest.devDependencies.typescript, /^6\.0\.\d+$/);
  });

  it('offers the setup guide only when no open folder is a Bio-STEWARD project (pilot finding, 0.0.3)', () => {
    const [walkthrough] = manifest.contributes.walkthroughs;
    assert.equal(walkthrough.when, 'isWorkspaceTrusted && !bioSteward.hasProject');
  });

  it('gives every panel a help button that opens the bundled plain-language help (0.0.3)', () => {
    const titles: { command: string; when: string }[] = manifest.contributes.menus['view/title'];
    for (const panel of ['today', 'approvals', 'overview', 'results', 'skills', 'sprint', 'tasks', 'tokens', 'decisions', 'drift']) {
      assert.ok(titles.some((m) => m.command === `bioSteward.help.${panel}` && m.when === `view == bioSteward.${panel}`), panel);
      assert.ok(manifest.contributes.commands.some((c: { command: string }) => c.command === `bioSteward.help.${panel}`), panel);
    }
    const help = readFileSync(join(root, 'media', 'help', 'panels.md'), 'utf8');
    for (const heading of ['## Today', '## Where am I?', '## Approvals', '## Tasks', '## Tokens', '## Decisions', '## Drift', '## Overview', '## Results', '## Agent Skills', '## Sprint']) {
      assert.ok(help.includes(heading), heading);
    }
    assert.match(readFileSync(join(root, '.vscodeignore'), 'utf8'), /^!media\/help\/panels\.md$/m);
  });

  it('puts Today first, labelled reduced in its help, and gives the Where am I? page its help and brief buttons (U02)', () => {
    assert.equal(manifest.contributes.views.bioSteward[0].id, 'bioSteward.today');
    const editor: { command: string; when: string }[] = manifest.contributes.menus['editor/title'];
    for (const command of ['bioSteward.whereAmI.copyBrief', 'bioSteward.help.whereAmI']) {
      assert.ok(editor.some((m) => m.command === command && m.when.startsWith('resourceScheme == bio-steward-where')), command);
    }
    const commands: { command: string; enablement?: string }[] = manifest.contributes.commands;
    for (const command of ['bioSteward.today.refresh', 'bioSteward.whereAmI', 'bioSteward.whereAmI.copyBrief']) {
      assert.equal(commands.find((c) => c.command === command)?.enablement, 'isWorkspaceTrusted', command);
    }
    const help = readFileSync(join(root, 'media', 'help', 'panels.md'), 'utf8');
    const today = help.slice(help.indexOf('## Today'), help.indexOf('## Where am I?'));
    assert.match(today, /\*\*reduced\*\* form/);
    for (const source of ['the session handoff', '`steward timeline`', '`steward audit progress`']) assert.ok(today.includes(source), source);
  });

  it('has the Tasks and Tokens panels, Tasks labelled reduced, and window buttons only in trusted workspaces (U03)', () => {
    const views: { id: string }[] = manifest.contributes.views.bioSteward;
    for (const id of ['bioSteward.tasks', 'bioSteward.tokens']) assert.ok(views.some((v) => v.id === id), id);
    const commands: { command: string; enablement?: string }[] = manifest.contributes.commands;
    for (const command of ['bioSteward.tasks.refresh', 'bioSteward.tokens.refresh', 'bioSteward.tokens.startWindow', 'bioSteward.tokens.doneWindow']) {
      assert.equal(commands.find((c) => c.command === command)?.enablement, 'isWorkspaceTrusted', command);
    }
    const menus: { command: string; when: string }[] = [...manifest.contributes.menus['view/title'], ...manifest.contributes.menus['view/item/context']];
    for (const menu of menus.filter((m) => m.command.startsWith('bioSteward.tokens.') && m.command.endsWith('Window'))) {
      assert.match(menu.when, /isWorkspaceTrusted/, menu.command);
    }
    const welcome: { view: string; when: string }[] = manifest.contributes.viewsWelcome;
    for (const [view, key] of [['bioSteward.tasks', 'tasksEmpty'], ['bioSteward.tokens', 'tokensEmpty']]) {
      assert.ok(welcome.some((w) => w.view === view && w.when === `bioSteward.${key} == 'untrusted'`), view);
    }
    const help = readFileSync(join(root, 'media', 'help', 'panels.md'), 'utf8');
    const tasks = help.slice(help.indexOf('## Tasks'), help.indexOf('## Tokens'));
    assert.match(tasks, /\*\*reduced\*\* form/);
    assert.match(tasks, /\*read from\s+the file\*/);
    const tokens = help.slice(help.indexOf('## Tokens'), help.indexOf('## Overview'));
    for (const key of ['bioSteward.tokens.claudeLogs', 'bioSteward.tokens.codexLogs', 'bioSteward.tokens.geminiLogs', '`steward task start ID`']) {
      assert.ok(tokens.includes(key), key);
    }
  });

  it('has the Approvals panel after Today as a webview of cards, labelled reduced, its links only in trusted workspaces (U04b)', () => {
    const view = manifest.contributes.views.bioSteward[1];
    assert.deepEqual([view.id, view.type], ['bioSteward.approvals', 'webview']);
    const commands: { command: string; title: string; enablement?: string }[] = manifest.contributes.commands;
    for (const command of ['bioSteward.approvals.refresh', 'bioSteward.approvals.viewPayload', 'bioSteward.approvals.sign']) {
      assert.equal(commands.find((c) => c.command === command)?.enablement, 'isWorkspaceTrusted', command);
    }
    assert.equal(commands.some((c) => c.command === 'bioSteward.approvals.reviewAndSign'), false, 'the old typing path is gone');
    const palette: { command: string; when: string }[] = manifest.contributes.menus.commandPalette;
    for (const command of ['bioSteward.approvals.viewPayload', 'bioSteward.approvals.sign']) {
      assert.ok(palette.some((m) => m.command === command && m.when === 'false'), `${command} is a card link, not a palette command`);
    }
    const menus: { command: string }[] = Object.values(manifest.contributes.menus).flat() as { command: string }[];
    assert.equal(menus.filter((m) => m.command === 'bioSteward.approvals.sign' || m.command === 'bioSteward.approvals.viewPayload').length, 2);
    const help = readFileSync(join(root, 'media', 'help', 'panels.md'), 'utf8');
    const approvals = help.slice(help.indexOf('## Approvals'), help.indexOf('## Tasks')).replace(/\s+/g, ' ');
    assert.match(approvals, /\*\*reduced\*\* form/);
    for (const words of ['`steward authorize pending --all-projects`', '**View exactly what you are approving**', '**✍ Sign**',
      '**✓ Signed**', '*read from the file*', 'type the action\'s name', '`steward authorize sign-pending --repo ROOT`',
      'asks *Sign …? [y/N]* before each']) {
      assert.ok(approvals.includes(words), words);
    }
  });

  it('has the Decisions and Drift panels, both labelled reduced, with their commands only in trusted workspaces (U05)', () => {
    const views: { id: string }[] = manifest.contributes.views.bioSteward;
    for (const id of ['bioSteward.decisions', 'bioSteward.drift']) assert.ok(views.some((v) => v.id === id), id);
    const commands: { command: string; title: string; enablement?: string }[] = manifest.contributes.commands;
    for (const command of ['bioSteward.decisions.open', 'bioSteward.decisions.refresh', 'bioSteward.drift.refresh']) {
      assert.equal(commands.find((c) => c.command === command)?.enablement, 'isWorkspaceTrusted', command);
    }
    assert.equal(commands.find((c) => c.command === 'bioSteward.decisions.open')?.title, 'Open DECISIONS.md');
    const menus: { command: string; when: string }[] = [...manifest.contributes.menus['view/title'], ...manifest.contributes.menus['view/item/context']];
    for (const menu of menus.filter((m) => /^bioSteward\.(decisions|drift)\./.test(m.command))) assert.match(menu.when, /isWorkspaceTrusted/, menu.command);
    const welcome: { view: string; when: string }[] = manifest.contributes.viewsWelcome;
    for (const [view, key] of [['bioSteward.decisions', 'decisionsEmpty'], ['bioSteward.drift', 'driftEmpty']]) {
      assert.ok(welcome.some((w) => w.view === view && w.when === `bioSteward.${key} == 'untrusted'`), view);
    }
    const help = readFileSync(join(root, 'media', 'help', 'panels.md'), 'utf8');
    const decisions = help.slice(help.indexOf('## Decisions'), help.indexOf('## Drift')).replace(/\s+/g, ' ');
    assert.match(decisions, /\*\*reduced\*\* form/);
    for (const words of ['**Open DECISIONS.md**', '`[integrity] decisions`', '`development/DECISIONS.md`', 'The extension never writes a decision.']) {
      assert.ok(decisions.includes(words), words);
    }
    const drift = help.slice(help.indexOf('## Drift'), help.indexOf('## Overview')).replace(/\s+/g, ' ');
    assert.match(drift, /\*\*reduced\*\* form/);
    for (const words of ['**the timeline states only**', "**in the CLI's own words**", '*on track*', '*at risk*', '*late*', '*due (record its outcome)*']) {
      assert.ok(drift.includes(words), words);
    }
  });
});
