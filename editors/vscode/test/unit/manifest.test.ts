// Unit suite (plain Node, mocha). T01 holds the manifest's safety-relevant declarations; T02 onwards add the model,
// the builders, the allow-list and freshness here.
import { strict as assert } from 'node:assert';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { PANELS, panelTitle } from '../../src/model/panels';

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
    assert.deepEqual(manifest.bioSteward, { minimumCli: '0.20.6', testedWithCli: '0.22.0' });
  });

  // F5 numbered the builds before the first public release 0.0.x; the roadmap to v1.0 made 0.3.0 the MVP, which is
  // sideloaded, not published, until the Marketplace step after v1.0.
  it('is version 0.3.0, the MVP, with a CHANGELOG entry for it (E05)', () => {
    assert.equal(manifest.version, '0.3.0');
    const changelog = readFileSync(join(root, 'CHANGELOG.md'), 'utf8');
    assert.match(changelog, /^## 0\.3\.0 \(/m);
    const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
    assert.equal(lock.version, manifest.version);
    assert.equal(lock.packages[''].version, manifest.version);
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
      // E03: urgent notification toasts setting; machine-scoped so a repository cannot mute urgent alerts.
      'bioSteward.notifications.toasts': [true, 'machine'],
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
    for (const heading of ['### Today', '### Where am I?', '### Approvals', '### Tasks', '### Tokens', '### Decisions',
      '### Milestones and Drift', '### Overview', '### Results', '### Agent Skills', '### Sprint']) {
      assert.ok(help.includes(heading), heading);
    }
    assert.match(readFileSync(join(root, '.vscodeignore'), 'utf8'), /^!media\/help\/panels\.md$/m);
  });

  it('puts Today first, names its sources in its help, and gives the Where am I? page its help and brief buttons (U02)', () => {
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
    const today = help.slice(help.indexOf('### Today'), help.indexOf('### Where am I?'));
    for (const source of ['the session handoff', '`steward timeline`', '`steward audit progress`']) assert.ok(today.includes(source), source);
  });

  it('has the Tasks and Tokens panels, Tasks read from the files, and window buttons only in trusted workspaces (U03)', () => {
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
    const tasks = help.slice(help.indexOf('### Tasks'), help.indexOf('### Sprint'));
    assert.match(tasks, /\*read from\s+the file\*/);
    const tokens = help.slice(help.indexOf('### Tokens'), help.indexOf('## Direction'));
    for (const key of ['bioSteward.tokens.claudeLogs', 'bioSteward.tokens.codexLogs', 'bioSteward.tokens.geminiLogs', '`steward task start ID`']) {
      assert.ok(tokens.includes(key), key);
    }
  });

  it('has the Approvals panel after Today as a webview of cards, its links only in trusted workspaces (U04b)', () => {
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
    const approvals = help.slice(help.indexOf('### Approvals'), help.indexOf('## Quality')).replace(/\s+/g, ' ');
    for (const words of ['`steward authorize pending --all-projects`', '**View exactly what you are approving**', '**✍ Sign**',
      '**✓ Signed**', '*read from the file*', 'type the action\'s name', '`steward authorize sign-pending --repo ROOT`',
      'asks *Sign …? [y/N]* before each']) {
      assert.ok(approvals.includes(words), words);
    }
  });

  it('has the Decisions and Drift panels, with their commands only in trusted workspaces (U05)', () => {
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
    const decisions = help.slice(help.indexOf('### Decisions'), help.indexOf('## Agents')).replace(/\s+/g, ' ');
    for (const words of ['**Open DECISIONS.md**', '`[integrity] decisions`', '`development/DECISIONS.md`', '**Record Decision…** opens the log at the end and starts a dated entry.']) {
      assert.ok(decisions.includes(words), words);
    }
    const drift = help.slice(help.indexOf('### Milestones and Drift'), help.indexOf('### Decisions')).replace(/\s+/g, ' ');
    for (const words of ['**Newest first:** the latest due date comes first', "**in the CLI's own words**", '*on track*', '*at risk*', '*late*', '*due (record its outcome)*']) {
      assert.ok(drift.includes(words), words);
    }
  });

  // E01 (RELEASE_vscode_0.3.0_SPEC): the ten panels by job, a refresh button in every title bar, no "reduced" left,
  // and every empty state and help section opening with the panel's sentence on how it helps.
  it('groups the ten panels as Now, Quality, Work, Direction and Agents, in that order (E01)', () => {
    const views: { id: string; name: string }[] = manifest.contributes.views.bioSteward;
    const panels = Object.values(PANELS);
    assert.deepEqual(views.map((v) => v.id), panels.map((p) => p.view));
    assert.deepEqual(views.map((v) => v.name), panels.map(panelTitle));
    const groups = panels.map((p) => p.group).filter((g, i, all) => all.indexOf(g) === i);
    assert.deepEqual(groups, ['Now', 'Quality', 'Work', 'Direction', 'Agents']);
  });

  it('has a refresh button in the title bar of every panel, only in trusted workspaces (E01)', () => {
    const titles: { command: string; when: string; group?: string }[] = manifest.contributes.menus['view/title'];
    const commands: { command: string; icon?: string; enablement?: string }[] = manifest.contributes.commands;
    for (const panel of Object.values(PANELS)) {
      const entry = titles.find((m) => m.command === panel.refresh && m.when === `view == ${panel.view} && isWorkspaceTrusted`);
      assert.ok(entry, panel.view);
      assert.match(entry.group ?? '', /^navigation@/, panel.view);
      const command = commands.find((c) => c.command === panel.refresh);
      assert.equal(command?.icon, '$(refresh)', panel.refresh);
      assert.equal(command?.enablement, 'isWorkspaceTrusted', panel.refresh);
    }
  });

  it('says "reduced" nowhere: manifest, bundled help, README and sources (E01)', () => {
    const files = [join(root, 'package.json'), join(root, 'media', 'help', 'panels.md'), join(root, 'README.md'),
      ...readdirSync(join(root, 'src'), { recursive: true, encoding: 'utf8' }).filter((f) => f.endsWith('.ts')).map((f) => join(root, 'src', f))];
    for (const file of files) assert.doesNotMatch(readFileSync(file, 'utf8'), /reduced/i, file);
  });

  it('opens every empty state and every help section with the panel\'s sentence on how it helps (E01)', () => {
    const welcome: { view: string; contents: string }[] = manifest.contributes.viewsWelcome;
    const help = readFileSync(join(root, 'media', 'help', 'panels.md'), 'utf8');
    for (const panel of Object.values(PANELS)) {
      for (const entry of welcome.filter((w) => w.view === panel.view)) {
        assert.ok(entry.contents.startsWith(`${panel.helps}\n`), `${panel.view}: ${entry.contents}`);
      }
      const at = help.indexOf(`### ${panel.name}\n`);
      assert.ok(at >= 0, panel.name);
      assert.ok(help.slice(at).startsWith(`### ${panel.name}\n\n${panel.helps}\n`), panel.name);
    }
    assert.ok(welcome.some((w) => w.view === PANELS.today.view));
  });

  it('declares the notifications bell, read/unread actions, toasts setting, Upgrade CLI, and keeps help current (E03)', () => {
    const commands: { command: string; enablement?: string }[] = manifest.contributes.commands;
    for (const command of [
      'bioSteward.notifications.openBell',
      'bioSteward.notifications.markRead',
      'bioSteward.notifications.markUnread',
      'bioSteward.notifications.markAllRead',
      'bioSteward.notifications.openDetails',
      'bioSteward.upgradeCli',
    ]) {
      assert.equal(commands.find((c) => c.command === command)?.enablement, 'isWorkspaceTrusted', command);
    }
    const contextMenus: { command: string; when: string }[] = manifest.contributes.menus['view/item/context'];
    assert.ok(contextMenus.some((m) => m.command === 'bioSteward.notifications.markRead' && m.when.includes('notification-unread')));
    assert.ok(contextMenus.some((m) => m.command === 'bioSteward.notifications.markUnread' && m.when.includes('notification-read')));
    assert.ok(contextMenus.some((m) => m.command === 'bioSteward.notifications.markAllRead' && m.when.includes('today-notifications')));
    assert.ok(contextMenus.some((m) => m.command === 'bioSteward.upgradeCli' && m.when.includes('viewItem == upgrade')));
    const titleMenus: { command: string; when: string }[] = manifest.contributes.menus['view/title'];
    assert.ok(titleMenus.some((m) => m.command === 'bioSteward.upgradeCli' && m.when.includes('bioSteward.upgradeAvailable')));
    assert.ok(titleMenus.some((m) => m.command === 'bioSteward.notifications.markAllRead' && m.when.includes('bioSteward.today')));

    const help = readFileSync(join(root, 'media', 'help', 'panels.md'), 'utf8').replace(/\s+/g, ' ');
    for (const phrase of [
      '`steward notifications --format json`',
      '**Mark Read**',
      '**Mark Unread**',
      '**Mark All Read**',
      '`bioSteward.notifications.toasts`',
      '**Upgrade CLI**',
      '`steward upgrade --check --format json`',
      '`steward upgrade --to VERSION`',
    ]) {
      assert.ok(help.includes(phrase), phrase);
    }
  });
});
