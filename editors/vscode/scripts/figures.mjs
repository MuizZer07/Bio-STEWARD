// The README and guide figures (T10; the cockpit panels' four added in U07), drawn from the extension's own view
// models (out/src/model/*.js) applied to the committed fixture reports and the cockpit corpus, so every label, glyph
// and number in a figure is what the extension shows for that input. They are drawings of the views, not screenshots, and each says so in its caption.
//
//   npm run figures                 write media/readme/*.svg, and *.png when rsvg-convert is on PATH
//   npm run figures -- --verify     exit 1 if a committed SVG differs from what the view model draws now
//
// The SVG text is deterministic (no dates, no random IDs). The PNGs are rasterised from it by rsvg-convert at 2x;
// their bytes depend on the rsvg and font versions, so only the SVGs are verified.
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(import.meta.url);
const compiled = join(here, 'out', 'src', 'model', 'views.js');
if (!existsSync(compiled)) {
  console.error('out/src/model/views.js is missing: run `npm run compile:tests` first (`npm run figures` does).');
  process.exit(2);
}
const views = require(compiled);
// The cockpit panels' view models (0.2.0) and the signing command's builder; none imports `vscode`.
const model = (name) => require(join(here, 'out', 'src', 'model', `${name}.js`));
const today = model('today');
const timeline = model('timeline');
const tokens = model('tokens');
const tasks = model('tasks');
const drift = model('drift');
const decisions = model('decisions');
const approvals = model('approvals');
const full = model('full');
const notifications = model('notifications');
const panelsModel = model('panels');
const signing = require(join(here, 'out', 'src', 'cli', 'signing.js'));
const outDir = join(here, 'media', 'readme');
const verify = process.argv.includes('--verify');

const report = (name) => JSON.parse(readFileSync(join(here, 'test', 'fixtures', 'reports', `${name}.json`), 'utf8'));
const READY = { kind: 'ready', version: '0.22.0', mode: 'full', newerThanTested: false };
const ready = (extra = {}) => ({ ...views.initialState(true), cli: READY, ...extra });

// ── Drawing ─────────────────────────────────────────────────────────────────────────────────────────────────

// VS Code's Dark Modern colours for the parts drawn here.
const C = {
  bg: '#1f1f1f', side: '#181818', bar: '#181818', border: '#2b2b2b', text: '#cccccc', dim: '#9d9d9d',
  head: '#bbbbbb', status: '#181818', statusText: '#cccccc', error: '#c72e0f', accent: '#0078d4',
  passed: '#89d185', failed: '#f48771', warning: '#cca700', info: '#75beff', disabled: '#8b8b8b',
  caption: '#8b949e', box: '#252526', boxLine: '#3c3c3c',
};
const FONT = "-apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif";
const MONO = "'SF Mono', Menlo, Consolas, monospace";

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
// A rough width for 13 px text, only to cut a row with an ellipsis as VS Code does.
const fit = (s, px) => {
  const max = Math.floor(px / 6.9);
  return s.length > max ? `${s.slice(0, Math.max(0, max - 1))}…` : s;
};

// Stand-ins for the codicons the view model names: the same glyph and tone the extension pairs with each status.
const ICON = {
  pass: '✓', error: '✗', warning: '◐', question: '?', 'circle-slash': '–', info: 'i', file: '▫', history: '↺',
  filter: '≡', play: '▷', repo: '▣', 'sync~spin': '↻',
  // The cockpit panels (0.2.0).
  watch: '◷', edit: '✎', mail: '✉', 'comment-discussion': '❝', rocket: '↗', milestone: '◆', folder: '▣', book: '▤',
  bell: '!', 'arrow-right': '→', tasklist: '☰', 'file-text': '▫', gear: '⚙', graph: 'Σ', pulse: '∿',
  'symbol-numeric': '#', 'loading~spin': '↻',
  // The full forms, notifications and Tokens of 0.3.0.
  law: '§', calendar: '▦', 'list-unordered': '≔', 'arrow-swap': '⇄', 'git-commit': '◉', clock: '◷',
  'folder-opened': '▣', lightbulb: '✦', trash: '⌫', 'arrow-circle-up': '⇧', 'debug-pause': '‖', 'bell-dot': '!',
};
// The Approvals cards' action icons (approvals.actionIcon) are colour emoji, which rsvg-convert cannot draw; the
// drawing uses a plain stand-in for each.
const EMOJI = { '💳': '¤', '🔓': '⊙', '✏️': '✎', '❄️': '❄', '⚐': '⚐', '⚖️': '⚖', '⚓': '⚓', '📌': '⊥' };

// The caption wraps at word boundaries to the figure's width.
function captionLines(caption, width) {
  const max = Math.floor((width - 32) / 6.2);
  const lines = [''];
  for (const word of caption.split(' ')) {
    const last = lines[lines.length - 1];
    if (last && (last + ' ' + word).length > max) lines.push(word);
    else lines[lines.length - 1] = last ? `${last} ${word}` : word;
  }
  return lines;
}

function svg(width, height, body, caption) {
  const lines = captionLines(caption, width);
  const h = height + 18 + lines.length * 16;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${h}" viewBox="0 0 ${width} ${h}" font-family="${esc(FONT)}" font-size="13">
<rect width="${width}" height="${h}" rx="10" fill="${C.bg}"/>
${body}
${lines.map((l, i) => `<text x="16" y="${height + 22 + i * 16}" font-size="11.5" fill="${C.caption}">${esc(l)}</text>`).join('\n')}
</svg>
`;
}

// One tree as VS Code draws it: twistie, icon, label, then the description dimmed.
function treeRows(nodes, { x, y, width, depth = 0, expand = () => false }, out = []) {
  for (const node of nodes) {
    const open = node.children?.length && (node.expanded || expand(node));
    const ix = x + 8 + depth * 14;
    const twist = node.children?.length ? (open ? '⌄' : '›') : '';
    const icon = node.icon ? ICON[node.icon.codicon] ?? '•' : '';
    const tone = node.icon?.tone ? C[node.icon.tone] : C.dim;
    const ry = y + out.length * 22;
    let row = '';
    if (twist) row += `<text x="${ix}" y="${ry + 15}" fill="${C.dim}" font-size="12">${twist}</text>`;
    let tx = ix + 14;
    if (icon) {
      row += `<text x="${tx + 1}" y="${ry + 15.5}" fill="${tone}" font-weight="700" font-size="12.5">${esc(icon)}</text>`;
      tx += 18;
    }
    const room = x + width - tx - 10;
    const label = fit(node.label, room);
    const desc = node.description ? fit(node.description, Math.max(0, room - label.length * 6.9 - 8)) : '';
    row += `<text x="${tx}" y="${ry + 15}" fill="${node.dimmed ? C.disabled : C.text}">${esc(label)}${desc ? `<tspan dx="7" fill="${C.dim}">${esc(desc)}</tspan>` : ''}</text>`;
    out.push(row);
    if (open) treeRows(node.children, { x, y, width, depth: depth + 1, expand }, out);
  }
  return out;
}

function panel({ x, y, width, title, nodes, expand, actions = '▷' }) {
  const rows = treeRows(nodes, { x, y: y + 26, width, expand });
  const height = 26 + rows.length * 22 + 8;
  return {
    height,
    body: `<rect x="${x}" y="${y}" width="${width}" height="${height}" fill="${C.side}"/>
<text x="${x + 8}" y="${y + 17}" fill="${C.head}" font-size="11" font-weight="700">⌄  ${esc(title)}</text>
<text x="${x + width - 12}" y="${y + 17}" fill="${C.dim}" font-size="12" text-anchor="end">${esc(actions)}</text>
${rows.join('\n')}`,
  };
}

function statusItem(x, y, view, { width } = {}) {
  const text = view.text.replace('$(shield)', '⛉').replace('$(sync~spin)', '↻').replace('$(watch)', '⌚')
    .replace('$(bell-dot)', '(!)').replace('$(bell)', '( )');
  const w = width ?? Math.ceil(text.length * 6.6 + 20);
  const fill = view.tone === 'error' ? C.error : view.tone === 'warning' ? '#5a4500' : 'none';
  return `<rect x="${x}" y="${y}" width="${w}" height="22" fill="${fill}"/>
<text x="${x + 10}" y="${y + 15}" fill="#ffffff" font-size="12">${esc(text)}</text>`;
}

function activityBar(height) {
  return `<rect x="0" y="0" width="48" height="${height}" rx="10" fill="${C.bar}"/>
<rect x="0" y="16" width="2" height="30" fill="${C.text}"/>
<g transform="translate(12 19) scale(1)" fill="none" stroke="${C.text}" stroke-width="1.5" stroke-linejoin="round">
<path d="M12 2.5 4.5 5.5v6c0 4.6 3.1 8.6 7.5 10 4.4-1.4 7.5-5.4 7.5-10v-6L12 2.5Z"/><path d="m8.5 12 2.5 2.5 4.5-5" stroke-linecap="round"/></g>`;
}

// ── Figures ─────────────────────────────────────────────────────────────────────────────────────────────────

function overview() {
  const state = views.withReport(ready(), report('geo-fail-date-symbol'));
  const width = 760;
  const p = panel({ x: 48, y: 30, width: width - 48, title: 'QUALITY · OVERVIEW', nodes: views.overviewNodes(state), actions: '⛁  ↺  ▷  ⟳' });
  const sb = views.statusBarView(state, 'default');
  const h = 30 + p.height + 22;
  const body = `${activityBar(h)}
<text x="58" y="20" fill="${C.head}" font-size="11" font-weight="700">BIO-STEWARD</text>
${p.body}
<rect x="0" y="${30 + p.height}" width="${width}" height="22" fill="${C.status}"/>
${statusItem(56, 30 + p.height, sb)}`;
  return svg(width, h, body,
    'Drawing of the Overview and the status bar, rendered by the extension\'s view model from the fixture report of the GEO example with a seeded fault (not a screenshot).');
}

function results() {
  const state = views.withReport(ready(), report('toy-unknown-contract'));
  const width = 760;
  const expand = (node) => node.kind === 'result' && node.id.startsWith('status:FAIL');
  const p = panel({ x: 0, y: 0, width, title: 'QUALITY · RESULTS', nodes: views.resultsNodes(state, 'status'), expand, actions: '☰  ▷  ⟳' });
  return svg(width, p.height, p.body.replace(`width="${width}" height="${p.height}" fill="${C.side}"`, `width="${width}" height="${p.height}" rx="10" fill="${C.side}"`),
    'Drawing of the Results view grouped by status, rendered by the extension\'s view model from the toy benchmark\'s fixture report with seeded faults (not a screenshot).');
}

function statusBar() {
  const fail = report('geo-fail-date-symbol');
  const failState = views.withReport(ready(), fail);
  const cases = [
    ['Right after a full run, every required result passed', views.withReport(ready(), report('geo'))],
    ['A required result failed: the count of blocking results', failState],
    ['A project file changed since the run (no check is run)', { ...failState, full: { ...failState.full, freshness: 'stale' } }],
    ['A newer scoped run (check --rule R-83): verdict kept, stale',
      views.withReport(failState, report('geo-scoped-rule'), { scope: 'check --rule R-83' })],
    ['A report found on disk at start-up', views.withReport(ready(), fail, { freshness: 'unknown' })],
    ['No report yet', ready()],
    ['No steward program found', { ...views.initialState(true), cli: { kind: 'missing' } }],
    ['An untrusted workspace: nothing runs', views.initialState(false)],
  ];
  const width = 800;
  const fx = 440;
  const fw = width - fx - 16;
  const rows = cases.map(([why, state], i) => {
    const y = 14 + i * 34;
    return `<text x="16" y="${y + 15}" fill="${C.text}" font-size="12.5">${esc(why)}</text>
<rect x="${fx}" y="${y}" width="${fw}" height="22" rx="3" fill="${C.status}" stroke="${C.border}"/>
${statusItem(fx, y, views.statusBarView(state, 'default'), { width: fw })}`;
  });
  const h = 14 + cases.length * 34;
  return svg(width, h, rows.join('\n'),
    'The status bar for the gate set in bioSteward.gate, as the extension\'s view model renders it for each state (drawn, not a screenshot).');
}

function box(x, y, w, h, title, lines, tone = C.boxLine) {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="${C.box}" stroke="${tone}" stroke-width="1.5"/>
<text x="${x + 14}" y="${y + 24}" fill="#ffffff" font-weight="700" font-size="14">${esc(title)}</text>
${lines.map((l, i) => `<text x="${x + 14}" y="${y + 46 + i * 18}" fill="${C.dim}" font-size="12.5">${esc(l)}</text>`).join('\n')}`;
}

function arrowLabel(x, y, label, anchor = 'middle') {
  return label ? `<text x="${x}" y="${y}" fill="${C.info}" font-size="11.5" text-anchor="${anchor}" font-family="${esc(MONO)}">${esc(label)}</text>` : '';
}

// A straight arrow; a vertical one carries its label beside it.
function arrow(x1, y1, x2, y2, label, dy = -8) {
  const vertical = x1 === x2;
  const at = vertical ? arrowLabel(x1 + 8, (y1 + y2) / 2 + 4, label, 'start') : arrowLabel((x1 + x2) / 2, (y1 + y2) / 2 + dy, label);
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${C.info}" stroke-width="1.6" marker-end="url(#a)"/>
${at}`;
}

// An arrow along a path of points, labelled at the middle of its longest leg.
function elbow(points, label) {
  const legs = points.slice(1).map((p, i) => [points[i], p]);
  const [[ax, ay], [bx, by]] = legs.reduce((a, b) => (Math.hypot(b[1][0] - b[0][0], b[1][1] - b[0][1]) > Math.hypot(a[1][0] - a[0][0], a[1][1] - a[0][1]) ? b : a));
  return `<polyline points="${points.map((p) => p.join(',')).join(' ')}" fill="none" stroke="${C.info}" stroke-width="1.6" marker-end="url(#a)"/>
${arrowLabel((ax + bx) / 2, (ay + by) / 2 - 6, label)}`;
}

const MARKER = `<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="${C.info}"/></marker></defs>`;

function howItWorks() {
  const width = 960;
  const body = `${MARKER}
${box(20, 20, 250, 128, 'VS Code: Bio-STEWARD', ['Today · Approvals · Tasks · Tokens', 'Overview · Results · Problems · Sprint', 'Decisions · Drift · Agent Skills', 'status bar: gate, freshness, countdown'], C.accent)}
${box(370, 20, 220, 128, 'Allow-listed runner', ['one typed builder per command;', 'no shell; --repo; timeout;', 'cancel kills the process tree'])}
${box(690, 20, 250, 128, 'Your steward CLI', ['bio-steward 0.20.6 or newer,', 'installed by you (pipx, uv, pip);', 'it decides every status and gate'], C.passed)}
${box(20, 216, 250, 128, 'Validation', ['JSON checked against the bundled', 'steward.report/0.1 schema, with', 'size and path limits; otherwise', '"unreadable", never a partial view'])}
${box(690, 216, 250, 128, 'Report file', ['.steward/report.json when git', 'ignores it (you and your agents', 'read one report); otherwise the', 'extension\'s own storage'])}
${box(370, 216, 220, 128, 'Never', ['no network requests, no AI,', 'no telemetry; it never signs:', 'your key does, in a terminal;', 'Restricted Mode runs nothing'], C.failed)}
${arrow(270, 84, 368, 84, 'Run Check')}
${arrow(590, 84, 688, 84, 'steward check')}
${arrow(815, 148, 815, 214, 'writes')}
${elbow([[815, 344], [815, 372], [145, 372], [145, 346]], 'read')}
${arrow(145, 216, 145, 150, 'shown')}`;
  return svg(width, 386, body,
    'How the extension works: it shows what the steward CLI you installed reports; it computes no verdict of its own.');
}

function freshness() {
  const width = 900;
  const state = (x, y, word, tone, lines) => `<rect x="${x}" y="${y}" width="220" height="96" rx="48" fill="${C.box}" stroke="${tone}" stroke-width="2"/>
<text x="${x + 110}" y="${y + 38}" fill="${tone}" font-weight="700" font-size="17" text-anchor="middle">${word}</text>
${lines.map((l, i) => `<text x="${x + 110}" y="${y + 60 + i * 16}" fill="${C.dim}" font-size="12" text-anchor="middle">${esc(l)}</text>`).join('\n')}`;
  const body = `${MARKER}
${state(40, 40, 'fresh', C.passed, ['no project file changed', 'since this run'])}
${state(640, 40, 'stale', C.warning, ['run check again'])}
${state(340, 230, 'unknown', C.info, ['the extension cannot tell'])}
${arrow(262, 74, 638, 74, 'a file changed · the CLI changed · a scoped run')}
${arrow(638, 112, 262, 112, 'Run Check (a full run)', 18)}
${elbow([[400, 230], [400, 190], [150, 190], [150, 138]], 'Run Check')}
<text x="660" y="270" fill="${C.dim}" font-size="12">unknown when:</text>
<text x="660" y="290" fill="${C.dim}" font-size="12">· a report found at start-up</text>
<text x="660" y="308" fill="${C.dim}" font-size="12">· a file changed during the run</text>
<text x="40" y="270" fill="${C.dim}" font-size="12">File changes only ever downgrade.</text>
<text x="40" y="290" fill="${C.dim}" font-size="12">.steward/ and git's bookkeeping do not count.</text>
<text x="40" y="308" fill="${C.dim}" font-size="12">"current" is never shown on CLI 0.20.6.</text>`;
  return svg(width, 340, body, 'Freshness of the report the views show: three words, and what moves between them.');
}

// ── The cockpit (0.2.0; panels grouped by job in 0.3.0) ─────────────────────────────────────────────────────
// Drawn from the U01 corpus (test/fixtures/cockpit/, the pinned CLI's outputs of the geo-cockpit workspace) through the
// panels' own view models, as the unit parity tests feed them.

const cockpit = (name) => readFileSync(join(here, 'test', 'fixtures', 'cockpit', name), 'utf8');
const corpus = JSON.parse(readFileSync(join(here, 'test', 'fixtures', 'manifest.json'), 'utf8')).cockpit;
const ROOT = '/home/you/geo-cockpit';

// Word wrap to a number of characters.
function wrap(text, max) {
  const lines = [''];
  for (const word of text.split(' ')) {
    const last = lines[lines.length - 1];
    if (last && (last + ' ' + word).length > max) lines.push(word);
    else lines[lines.length - 1] = last ? `${last} ${word}` : word;
  }
  return lines;
}

// The notifications of the figure: a sample document in the CLI's steward.notifications/0.1 shape, made from the
// fixture's own waiting items (its payload, its exchange request, its sprint) with the CLI's wording for each kind.
// The live document carries file times and paths of the machine it runs on, so no fixture of it is committed (S1
// E03); the figure says so in its caption.
function sampleNotifications() {
  const next = full.parseNext(cockpit('full/next/geo-cockpit.json'));
  const [payload, exchange, task] = next.waiting_on_human;
  return {
    schema: 'steward.notifications/0.1', tool_version: '0.22.0', now: '2026-11-27T12:00:00Z', days: 14, notes: [],
    items: [
      { id: `approval:${payload.id}`, kind: 'approval', time: '2026-11-27T09:12:00Z', source: payload.source,
        title: 'spend waits for a signature (expires 2099-01-01T00:00:00Z)', command: payload.command, urgent: true },
      { id: `exchange:${exchange.id}`, kind: 'exchange', time: '2026-11-26T16:40:00Z', source: exchange.source,
        title: exchange.title, command: exchange.command, urgent: false },
      { id: `task_waiting:${task.id}`, kind: 'task_waiting', time: '2026-11-25T08:30:00Z', source: task.source,
        title: task.title, command: task.command, urgent: false },
    ],
  };
}

function todayFigure() {
  const document = sampleNotifications();
  // The oldest item has been seen once (opened in the bell), so it is read: dimmed, under the unread ones.
  const read = notifications.markNotificationsRead({}, [{ root: ROOT, item: document.items[2] }]).state;
  const state = { kind: 'ready', document };
  const input = {
    root: ROOT, name: 'geo-cockpit', trusted: true, notifications: state, readNotifications: read,
    next: { kind: 'ready', doc: full.parseNext(cockpit('full/next/geo-cockpit.json')) },
  };
  const nodes = today.todayNodes([input]).map((node) => (node.kind === 'today-notifications' ? { ...node, expanded: true } : node));
  const expand = (node) => node.id.endsWith('/human') || node.kind === 'today-resume';
  const width = 760;
  const p = panel({ x: 0, y: 0, width, title: 'NOW · TODAY', nodes, expand, actions: '⌖  ⎘  ⟳  ?' });
  const entries = notifications.collectNotifications([{ root: ROOT, name: 'geo-cockpit', trusted: true, state }], read);
  const bell = notifications.bellStatusView(entries, { trusted: true, hasProjects: true, hasReady: true });
  const h = p.height + 22;
  const body = `<rect width="${width}" height="${h}" rx="10" fill="${C.side}"/>
${p.body}
<rect x="0" y="${p.height}" width="${width}" height="22" fill="${C.status}"/>
${statusItem(width - 70, p.height, bell)}`;
  return svg(width, h, body,
    'Drawing of the Today panel and the status-bar bell on CLI 0.22, rendered by their view models (not a screenshot): Notifications at the top, unread first and the item seen once dimmed below, then the fixture\'s steward next output (Resume, the next milestone, what waits on you, what needs tidying). The notifications are a sample document in the CLI\'s shape, made from the fixture\'s own waiting items.');
}

// The ten panels by job, with the sentence each empty state and ? help opens with.
function panelsFigure() {
  const width = 860;
  const out = [];
  let y = 24;
  out.push(`<text x="20" y="${y}" fill="${C.head}" font-size="11" font-weight="700">BIO-STEWARD · ONE CONTAINER, FIVE GROUPS, TEN PANELS</text>`);
  y += 16;
  const groups = [...new Set(Object.values(panelsModel.PANELS).map((p) => p.group))];
  for (const group of groups) {
    const rows = Object.values(panelsModel.PANELS).filter((p) => p.group === group);
    const top = y;
    y += 26;
    out.push(`<text x="36" y="${y}" fill="#ffffff" font-size="14" font-weight="700">${esc(group)}</text>`);
    for (const p of rows) {
      y += 22;
      out.push(`<text x="52" y="${y}" fill="${C.text}" font-size="12.5" font-weight="700">${esc(panelsModel.panelTitle(p))}</text>`);
      out.push(`<text x="${width - 36}" y="${y}" fill="${C.dim}" font-size="12" text-anchor="end">⟳ ?</text>`);
      wrap(p.helps, 80).forEach((line, i) => {
        if (i) y += 17;
        out.push(`<text x="270" y="${y}" fill="${C.dim}" font-size="12.5">${esc(line)}</text>`);
      });
    }
    y += 14;
    out.push(`<rect x="20" y="${top + 6}" width="${width - 40}" height="${y - top - 6}" rx="8" fill="none" stroke="${C.boxLine}" stroke-width="1.2"/>`);
    y += 4;
  }
  return svg(width, y + 6, `<rect width="${width}" height="${y + 6}" rx="10" fill="${C.side}"/>\n${out.join('\n')}`,
    'The ten panels grouped by the job they help with, each header named with its group, and the sentence each panel\'s empty state and ? help open with (from the extension\'s panel list). Every panel has a refresh button (⟳) and a ? help in its title bar.');
}

function cockpitFigure() {
  const width = 760;
  const decisionSettings = decisions.decisionsSettings('').settings;
  const logs = { files: { claude: ['claude-sprint.jsonl'], codex: [], gemini: [] }, problems: [], capped: {} };
  const timelineText = cockpit('full/timeline/geo-cockpit.json');
  const tokenNodes = tokens.tokensNodes([{ root: '/home/you/geo-sprint', name: 'geo-sprint', logs,
    tokens: { kind: 'ready', report: tokens.parseTokensReport(cockpit('full/tokens-report/geo-sprint.json')) } }]);
  const panels = [
    ['WORK · TASKS', tasks.tasksNodes([{ root: ROOT, name: 'geo-cockpit', board: { kind: 'ready', doc: full.parseBoard(cockpit('full/task-board/geo-cockpit.json')) } }]), '⟳  ?'],
    ['WORK · TOKENS', tokenNodes, '▷  ■  ⟳  ?'],
    ['DIRECTION · DECISIONS', decisions.decisionsNodes([{ root: ROOT, name: 'geo-cockpit',
      decisions: { kind: 'ready', settings: decisionSettings, logs: [{ path: 'development/DECISIONS.md', exists: true }], unmatched: [], more: 0 },
      doc: { kind: 'ready', doc: full.parseDecisions(cockpit('full/decisions/geo-cockpit.json')) } }]), '▤  ⟳  ?'],
    ['DIRECTION · MILESTONES AND DRIFT', drift.driftNodes([{ root: ROOT, name: 'geo-cockpit',
      timeline: { kind: 'ready', rows: timeline.parseTimeline(timelineText).milestones, drift: full.parseDrift(timelineText) } }]), '⟳  ?'],
  ];
  let y = 0;
  const bodies = [];
  for (const [title, nodes, actions, expand] of panels) {
    const p = panel({ x: 0, y, width, title, nodes, actions, expand });
    bodies.push(p.body);
    y += p.height + 6;
  }
  return svg(width, y, `<rect width="${width}" height="${y}" rx="10" fill="${C.side}"/>\n${bodies.join('\n')}`,
    'Drawing of the Tasks, Tokens, Decisions, and Milestones and Drift panels in their full forms on CLI 0.22, rendered by their view models from the fixture outputs of steward task board, steward tokens report (a recorded sprint with stand-in agent logs: the tasks with counts show their tokens by model, the others say why they have none), steward decisions and steward timeline (not a screenshot).');
}

const unescape = (s) => s.replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&quot;', '"').replaceAll('&#39;', "'").replaceAll('&amp;', '&');
const strip = (s) => unescape(s.replace(/<br>/g, '\n').replace(/<[^>]+>/g, ''));

// The Approvals webview: the page approvalsHtml builds, its cards drawn as boxes. The fixture workspace has no
// payload files, so the hash shown is a placeholder that says which file the panel hashes, and each card is drawn as
// bound (its queue line describes its file, which the panel checks with bindCard before it offers ✍ Sign).
function approvalsFigure() {
  const parsed = approvals.parsePendingText(cockpit('authorize-pending/geo-cockpit-all-projects.txt'));
  const lineOf = (nonce) => parsed.lines.find((line) => line.nonce === nonce.slice(0, 12));
  const payloads = new Map(Object.values(corpus.queue['geo-cockpit']).map((nonce) => [nonce.slice(0, 12),
    { kind: 'read', nonce, sha256: `‹the SHA-256 of .steward/pending/${nonce}.txt›`, binding: { kind: 'bound', line: lineOf(nonce), fields: {} } }]));
  const pending = full.parsePending(cockpit('full/authorize-pending/geo-cockpit-all-projects.json'));
  const html = approvals.approvalsHtml({ kind: 'ready', blocks: [{ root: ROOT, name: 'geo-cockpit', index: 0, approvals: parsed, payloads, pending }] });
  const body = html.slice(html.indexOf('<body>') + 7, html.indexOf('</body>')).trim();
  const width = 820;
  const out = [];
  let y = 20;
  const text = (x, s, { fill = C.text, size = 13, weight, mono, underline } = {}) => {
    out.push(`<text x="${x}" y="${y}" fill="${fill}" font-size="${size}"${weight ? ` font-weight="${weight}"` : ''}` +
      `${mono ? ` font-family="${esc(MONO)}"` : ''}${underline ? ' text-decoration="underline"' : ''}>${esc(s)}</text>`);
  };
  out.push(`<text x="20" y="${y + 4}" fill="${C.head}" font-size="11" font-weight="700">NOW · APPROVALS</text>`);
  out.push(`<text x="${width - 20}" y="${y + 4}" fill="${C.dim}" font-size="12" text-anchor="end">↺  ?</text>`);
  y += 30;
  for (const chunk of body.split('\n<hr>\n')) {
    if (chunk.startsWith('<section>')) {
      const top = y - 6;
      y += 18;
      for (const line of chunk.split('\n').slice(1, -1)) {
        if (line.startsWith('<h3>')) {
          const [head] = strip(line).split(' · ');
          const [icon, ...name] = head.split(' ');
          out.push(`<text x="40" y="${y}" fill="#ffffff" font-size="15" font-weight="700"><tspan fill="${C.warning}">${esc(EMOJI[icon] ?? icon)}</tspan> ${esc(name.join(' '))}<tspan dx="8" fill="${C.dim}" font-size="12" font-weight="400">· ${esc(strip(line).slice(head.length + 3))}</tspan></text>`);
          y += 26;
        } else if (line.includes('<a href')) {
          text(40, strip(line), { fill: line.includes('<b>') ? '#ffffff' : C.info, weight: line.includes('<b>') ? 700 : undefined, underline: !line.includes('<b>') });
          if (line.includes('<b>')) out.splice(out.length - 1, 0, `<rect x="36" y="${y - 15}" width="78" height="22" rx="4" fill="${C.accent}"/>`);
          y += 26;
        } else if (line.startsWith('<p><small>As printed')) {
          text(40, fit(strip(line), (width - 80) * 1.05), { fill: C.dim, size: 11, mono: true });
          y += 20;
        } else {
          const [first, ...rest] = strip(line).split('\n');
          text(40, first, { fill: line.includes('✓') ? C.passed : line.includes('Expired') ? C.warning : C.text, weight: line.includes('✓') ? 700 : undefined });
          y += 20;
          for (const more of rest) {
            text(40, fit(more, (width - 80) * 0.95), { fill: C.dim, size: 11.5, mono: true });
            y += 20;
          }
        }
      }
      out.push(`<rect x="24" y="${top}" width="${width - 48}" height="${y - top - 4}" rx="8" fill="none" stroke="${C.boxLine}" stroke-width="1.5"/>`);
      y += 18;
    } else {
      for (const line of wrap(strip(chunk), 108)) {
        text(24, line, { fill: C.dim, size: 12 });
        y += 18;
      }
      y += 12;
    }
  }
  return svg(width, y, `<rect width="${width}" height="${y}" rx="10" fill="${C.side}"/>\n${out.join('\n')}`,
    'Drawing of the Approvals panel: the page its view model builds from the fixture text of steward authorize pending --all-projects, one card per payload line, with the fields of authorize pending --format json (not a screenshot). The baselines and the CLI\'s payload hashes are normalised to zeros in the fixture, which has no payload files, so the hash read from the file is a placeholder naming the file the panel hashes; each action\'s colour icon is drawn as a plain mark (¤ for spend). The peer\'s payload has no buttons.');
}

// ✍ Sign, step by step, with the modal dialog and the typed-name box as the view model words them.
function signFlowFigure() {
  const width = 960;
  const line = parsedWaiting();
  const command = signing.signingCommand('/home/you/.local/bin/steward', ROOT);
  const dialog = approvals.signDialog({ project: 'geo-cockpit', action: line.action, summary: line.summary, expires: line.expires,
    sha256: '‹the SHA-256 of the payload file›', line: command.line });
  const typed = approvals.typedNamePrompt('unseal');
  const steps = [
    ['1  ✍ Sign', ['on a waiting card; its', 'link names the nonce,', 'project and page'], C.accent],
    ['2  Read again', ['the queue and the file:', 'only if the line binds', 'to the bytes shown'], C.boxLine],
    ['3  You confirm', ['a modal dialog (below);', `for ${approvals.TYPED_NAME_ACTIONS.length} high-stakes`, 'actions, type the name'], C.warning],
    ['4  A terminal', ['runs the CLI\'s own', 'authorize sign-pending', '--repo ROOT, no shell'], C.boxLine],
    ['5  The CLI asks', ['prints the exact bytes,', 'then Sign …? [y/N]', 'before each signature'], C.passed],
    ['6  Your key', ['its own prompt: a', 'passphrase, an agent', 'or a hardware touch'], C.passed],
  ];
  const bw = 146;
  const gap = (width - 40 - steps.length * bw) / (steps.length - 1);
  const parts = [MARKER];
  steps.forEach(([title, lines, tone], i) => {
    const x = 20 + i * (bw + gap);
    parts.push(`<rect x="${x}" y="20" width="${bw}" height="96" rx="8" fill="${C.box}" stroke="${tone}" stroke-width="1.5"/>
<text x="${x + 10}" y="42" fill="#ffffff" font-weight="700" font-size="12.5">${esc(title)}</text>
${lines.map((l, j) => `<text x="${x + 10}" y="${62 + j * 16}" fill="${C.dim}" font-size="11">${esc(l)}</text>`).join('\n')}`);
    if (i < steps.length - 1) parts.push(`<line x1="${x + bw + 2}" y1="68" x2="${x + bw + gap - 2}" y2="68" stroke="${C.info}" stroke-width="1.6" marker-end="url(#a)"/>`);
  });
  const x3 = 20 + 2 * (bw + gap) + bw / 2;
  parts.push(`<line x1="${x3}" y1="116" x2="${x3}" y2="140" stroke="${C.failed}" stroke-width="1.6"/>
<text x="${x3 + 8}" y="136" fill="${C.failed}" font-size="11.5">Cancel, or a different name: nothing runs and no terminal opens</text>
<text x="${width - 20}" y="160" fill="${C.dim}" font-size="11.5" text-anchor="end">When the terminal closes, the queue is read again and the card turns ✓ Signed if the CLI says so.</text>`);

  // The modal dialog.
  const mx = 20;
  const my = 180;
  const mw = 580;
  const detail = dialog.detail.flatMap((l) => (l.startsWith('  ') ? [l] : l ? wrap(l, 84) : ['']));
  const mh = 58 + detail.length * 17 + 46;
  parts.push(`<rect x="${mx}" y="${my}" width="${mw}" height="${mh}" rx="10" fill="${C.box}" stroke="${C.boxLine}" stroke-width="1.5"/>
<text x="${mx + 20}" y="${my + 30}" fill="${C.warning}" font-size="16">⚠</text>
<text x="${mx + 44}" y="${my + 30}" fill="#ffffff" font-weight="700" font-size="14">${esc(dialog.title)}</text>
${detail.map((l, j) => `<text x="${mx + 44}" y="${my + 56 + j * 17}" fill="${l.startsWith('  ') ? C.info : C.text}" font-size="${l.startsWith('  ') ? 10.5 : 12}"${l.startsWith('  ') ? ` font-family="${esc(MONO)}"` : ''}>${esc(l.trim())}</text>`).join('\n')}
<rect x="${mx + mw - 250}" y="${my + mh - 40}" width="150" height="26" rx="4" fill="${C.accent}"/>
<text x="${mx + mw - 175}" y="${my + mh - 22}" fill="#ffffff" font-size="12.5" text-anchor="middle">${esc(approvals.SIGN_BUTTON)}</text>
<rect x="${mx + mw - 90}" y="${my + mh - 40}" width="70" height="26" rx="4" fill="none" stroke="${C.boxLine}"/>
<text x="${mx + mw - 55}" y="${my + mh - 22}" fill="${C.text}" font-size="12.5" text-anchor="middle">Cancel</text>`);

  // The typed-name box, for a high-stakes action.
  const tx = 630;
  const tw = width - tx - 20;
  parts.push(`<rect x="${tx}" y="${my}" width="${tw}" height="172" rx="10" fill="${C.box}" stroke="${C.boxLine}" stroke-width="1.5"/>
<text x="${tx + 16}" y="${my + 26}" fill="#ffffff" font-weight="700" font-size="13">${esc(typed.title)}</text>
<rect x="${tx + 16}" y="${my + 40}" width="${tw - 32}" height="26" rx="3" fill="${C.bg}" stroke="${C.accent}"/>
<text x="${tx + 24}" y="${my + 58}" fill="${C.disabled}" font-size="12">unseal</text>
${wrap(typed.prompt, 40).map((l, j) => `<text x="${tx + 16}" y="${my + 86 + j * 16}" fill="${C.dim}" font-size="11.5">${esc(l)}</text>`).join('\n')}
<text x="${tx + 16}" y="${my + 140}" fill="${C.dim}" font-size="11">only for: ${esc(approvals.TYPED_NAME_ACTIONS.slice(0, 3).join(', '))},</text>
<text x="${tx + 16}" y="${my + 156}" fill="${C.dim}" font-size="11">${esc(approvals.TYPED_NAME_ACTIONS.slice(3).join(', '))}</text>`);
  const h = Math.max(my + mh, my + 172) + 6;
  return svg(width, h, parts.join('\n'),
    `How ✍ Sign works: the steps, the modal dialog as the view model words it for the fixture's waiting payload (${line.nonce}), and the box a high-stakes action adds (drawn, not a screenshot). The extension never signs and never reads a key.`);
}

function parsedWaiting() {
  const parsed = approvals.parsePendingText(cockpit('authorize-pending/geo-cockpit.txt'));
  return parsed.lines.find((l) => l.kind === 'payload' && l.state === 'waiting');
}

// The Marketplace icon (vsce wants a PNG of at least 128 px): the Bio-STEWARD logo, a shield with a green check over
// a faint DNA helix, on the logo's teal-to-indigo gradient (the same drawing as docs/assets/logo.svg).
function icon() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
<defs><linearGradient id="bsg" x1="0.15" y1="0" x2="0.85" y2="1"><stop offset="0" stop-color="#0f8a8c"/><stop offset="1" stop-color="#4b4fd8"/></linearGradient></defs>
<path d="M64 5 L114 21 V58 C114 91 93 113 64 124 C35 113 14 91 14 58 V21 Z" fill="url(#bsg)"/>
  <g fill="none" stroke="#ffffff" stroke-linecap="round" opacity="0.32">
    <path d="M46 22 C46 38 82 38 82 54 C82 70 46 70 46 86 C46 96 58 100 64 104" stroke-width="6"/>
    <path d="M82 22 C82 38 46 38 46 54 C46 70 82 70 82 86 C82 96 70 100 64 104" stroke-width="6"/>
    <path d="M51 30 H77 M51 54 H77 M51 78 H77" stroke-width="3.5"/>
  </g>
  <g fill="none" stroke-linecap="round" stroke-linejoin="round">
    <path d="M38 66 C44 72 50 78 56 85 C66 70 78 58 92 47" stroke="#ffffff" stroke-width="17"/>
    <path d="M38 66 C44 72 50 78 56 85 C66 70 78 58 92 47" stroke="#22c55e" stroke-width="10"/>
  </g>
</svg>
`;
}

// ── Write or verify ─────────────────────────────────────────────────────────────────────────────────────────

// name → [draw, SVG path, PNG path, zoom], paths relative to the extension folder.
const FIGURES = {
  'how-it-works': [howItWorks], overview: [overview], results: [results], 'status-bar': [statusBar], freshness: [freshness],
  panels: [panelsFigure], today: [todayFigure], cockpit: [cockpitFigure], approvals: [approvalsFigure], 'sign-flow': [signFlowFigure],
  icon: [icon, 'media/icon.svg', 'icon.png', 1],
};

mkdirSync(outDir, { recursive: true });
let differ = 0;
const rsvg = spawnSync('rsvg-convert', ['--version'], { encoding: 'utf8' }).status === 0;
for (const [name, [draw, svgPath = `media/readme/${name}.svg`, pngPath = `media/readme/${name}.png`, zoom = 2]] of Object.entries(FIGURES)) {
  const text = draw();
  const file = join(here, svgPath);
  if (verify) {
    const same = existsSync(file) && readFileSync(file, 'utf8') === text;
    if (!same) differ += 1;
    console.log(`${same ? 'same   ' : 'DIFFERS'} ${svgPath}`);
    continue;
  }
  writeFileSync(file, text);
  console.log(`wrote ${svgPath}`);
  if (rsvg) {
    const r = spawnSync('rsvg-convert', ['--zoom', String(zoom), '--format', 'png', '--output', join(here, pngPath), file]);
    if (r.status !== 0) {
      console.error(`rsvg-convert failed for ${name}: ${String(r.stderr)}`);
      process.exit(1);
    }
    console.log(`wrote ${pngPath}`);
  }
}
if (!verify && !rsvg) console.log('rsvg-convert is not on PATH, so the PNGs were not rewritten.');
if (differ) {
  console.error(`${differ} figure(s) differ from the view model: run \`npm run figures\` and review them.`);
  process.exit(1);
}
