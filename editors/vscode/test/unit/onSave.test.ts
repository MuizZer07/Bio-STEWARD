// T12, D3 (T11-10): bioSteward.check.onSave. Debounced, single-flight per project, never for a save under
// .steward/ or .git/. Trust and the setting are checked by the caller (src/extension.ts; host test in
// test/host/extension.test.ts). Short delays stand in for the 2 s debounce.
import { strict as assert } from 'node:assert';
import { join } from 'node:path';
import { DEBOUNCE_MS, SaveTrigger, triggersCheck } from '../../src/onSave';

const later = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe('bioSteward.check.onSave (D3)', () => {
  it('waits 2 s after the last save', () => assert.equal(DEBOUNCE_MS, 2000));

  it('a save under .steward/ or .git/, or outside the project, never triggers a check', () => {
    const root = join('/', 'work', 'project');
    for (const file of ['paper/main.tex', 'steward.toml', '.stewardish', 'src/.git-notes', '.github/workflows/ci.yml']) {
      assert.equal(triggersCheck(root, join(root, file)), true, file);
    }
    for (const file of ['.steward/report.json', '.steward/sprints/x/T1/a.txt', '.git/COMMIT_EDITMSG', '.git', '.steward']) {
      assert.equal(triggersCheck(root, join(root, file)), false, file);
    }
    assert.equal(triggersCheck(root, join('/', 'work', 'other', 'a.txt')), false);
    assert.equal(triggersCheck(root, root), false);
  });

  it('debounces: many saves inside the wait start one run, after the last save', async () => {
    const runs: number[] = [];
    const trigger = new SaveTrigger<string>(async () => {
      runs.push(Date.now());
    }, 60);
    const started = Date.now();
    for (let i = 0; i < 5; i++) {
      trigger.saved('a');
      await later(20);
    }
    await later(150);
    assert.equal(runs.length, 1);
    assert.ok(runs[0] - started >= 80 + 60 - 15, `ran ${runs[0] - started} ms after the first save`);
    trigger.dispose();
  });

  it('single-flight per project: saves during a run ask for one more run after it, never two at once', async () => {
    let active = 0;
    let most = 0;
    let runs = 0;
    const trigger = new SaveTrigger<string>(async () => {
      active++;
      most = Math.max(most, active);
      runs++;
      await later(100);
      active--;
    }, 20);
    trigger.saved('a');
    await later(50);
    assert.equal(active, 1);
    trigger.saved('a');
    trigger.saved('a');
    await later(40);
    assert.equal(active, 1, 'no second run while the first runs');
    await later(250);
    assert.equal(runs, 2, 'one more run for the saves during the first');
    assert.equal(most, 1);
    assert.equal(trigger.busy('a'), false);
    trigger.dispose();
  });

  it('projects are independent', async () => {
    const seen: string[] = [];
    const trigger = new SaveTrigger<string>(async (key) => {
      seen.push(key);
      await later(50);
    }, 10);
    trigger.saved('a');
    trigger.saved('b');
    await later(30);
    assert.deepEqual(seen.sort(), ['a', 'b']);
    await later(60);
    trigger.dispose();
  });

  it('a failing run does not stop later runs; dispose and forget drop a waiting run', async () => {
    let runs = 0;
    const trigger = new SaveTrigger<string>(async () => {
      runs++;
      throw new Error('check failed');
    }, 10);
    trigger.saved('a');
    await later(40);
    trigger.saved('a');
    await later(40);
    assert.equal(runs, 2);
    trigger.saved('a');
    trigger.forget('a');
    trigger.saved('b');
    trigger.dispose();
    trigger.saved('c');
    await later(40);
    assert.equal(runs, 2);
  });
});
