// Freshness (S1): fresh after a run, stale after a file change, unknown when the extension cannot tell; file
// changes only downgrade (design v0.1 PERF-6), and "current" is never used on CLI 0.20.6.
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { downgrade, freshnessOfRun, isWatchedInput, withInputChanged, worse } from '../../src/model/freshness';
import type { Report } from '../../src/model/report';
import {
  initialState, statusBarView, withReport, withRunFailure, type Freshness, type ProjectState,
} from '../../src/model/views';

const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures', 'reports');
const geo = JSON.parse(readFileSync(join(fixtures, 'geo.json'), 'utf8')) as Report;
const scoped = JSON.parse(readFileSync(join(fixtures, 'geo-scoped-data.json'), 'utf8')) as Report;
const ready: ProjectState = {
  ...initialState(true),
  cli: { kind: 'ready', version: '0.20.6', mode: 'limited', newerThanTested: false },
};
const FRESHNESS: readonly Freshness[] = ['fresh', 'unknown', 'stale'];

describe('freshness (S1)', () => {
  it('watches project files, but not .steward/ (the CLI\'s state, the shared report) or git\'s own bookkeeping', () => {
    for (const path of ['steward.toml', 'paper/main.tex', 'results/top_genes.tsv', '.gitignore', '.vscode/settings.json',
      'dir\\file.txt', '.git/HEAD', '.git/refs/heads/main', '.git/packed-refs', '.stewardish/file']) {
      assert.equal(isWatchedInput(path), true, path);
    }
    for (const path of ['', '.', '..', '../outside/steward.toml', '/abs/path', '.steward', '.steward/report.json',
      '.steward\\report.json', '.steward/sprints/x/T01/steward.toml', '.git', '.git/index', '.git/index.lock',
      '.git/objects/ab/cdef', '.git/FETCH_HEAD', '.git/logs/HEAD']) {
      assert.equal(isWatchedInput(path), false, path);
    }
  });

  it('a run with a watcher and no change during it is fresh; otherwise unknown', () => {
    assert.equal(freshnessOfRun({ watching: true, changedDuringRun: false }), 'fresh');
    assert.equal(freshnessOfRun({ watching: true, changedDuringRun: true }), 'unknown');
    assert.equal(freshnessOfRun({ watching: false, changedDuringRun: false }), 'unknown');
  });

  it('only ever downgrades: stale over unknown over fresh', () => {
    for (const a of FRESHNESS) {
      for (const b of FRESHNESS) {
        const result = worse(a, b);
        assert.ok(FRESHNESS.indexOf(result) >= FRESHNESS.indexOf(a) && FRESHNESS.indexOf(result) >= FRESHNESS.indexOf(b));
        assert.ok(result === a || result === b);
      }
    }
    for (const start of FRESHNESS) {
      const state = withReport(ready, geo, { freshness: start });
      for (const to of FRESHNESS) {
        const after = downgrade(state, to);
        assert.equal(after.full?.freshness, worse(start, to), `${start} → ${to}`);
        if (worse(start, to) === start) assert.equal(after, state, 'no change gives the same state');
      }
    }
  });

  it('a file change turns fresh and unknown into stale, for the full and the partial report alike', () => {
    for (const start of FRESHNESS) {
      const state = withReport(withReport(ready, geo, { freshness: start }), scoped, { freshness: start });
      const after = withInputChanged(state);
      assert.equal(after.full?.freshness, 'stale');
      assert.equal(after.partial?.freshness, 'stale');
      assert.equal(after.full?.report, state.full?.report, 'the verdict is kept');
    }
    assert.equal(withInputChanged(ready), ready, 'nothing to downgrade without a report');
  });

  it('the status bar shows each state in words, and never "current"', () => {
    for (const freshness of FRESHNESS) {
      const view = statusBarView(withReport(ready, geo, { freshness }), 'default');
      assert.equal(view.text, `$(shield) default ✓ ELIGIBLE · ${freshness}`);
      assert.ok(view.tooltip.some((line) => line.toLowerCase().startsWith(freshness === 'unknown' ? 'freshness unknown' : freshness)));
      assert.doesNotMatch([view.text, ...view.tooltip].join('\n'), /\bcurrent\b/i);
    }
  });

  it('a failed run after a file change keeps the verdict, stale', () => {
    const state = withRunFailure(withInputChanged(withReport(ready, geo)), 'failed');
    assert.equal(state.full?.freshness, 'stale');
  });
});
