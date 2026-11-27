import { strict as assert } from 'node:assert';
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { projectFiles, resultAnchors, severityFor } from '../../src/model/findings';
import { STATUSES, type ResultItem } from '../../src/model/report';

describe('Problems mapping', () => {
  let scratch: string;
  let root: string;
  const finding: ResultItem = {
    rule: 'R-11', name: 'paper.displays', rule_version: 1, status: 'FAIL',
    reason: 'The file changed', subject: 'paper.tex', details: [], evidence: [],
  };

  before(async () => {
    scratch = await mkdtemp(join(tmpdir(), 'bsv-problems-'));
    root = join(scratch, 'project');
    await mkdir(join(root, 'directory'), { recursive: true });
    await writeFile(join(root, 'paper.tex'), 'first\nsecond\nthird\n');
    await writeFile(join(root, 'data.tsv'), 'first\n');
    await writeFile(join(scratch, 'outside'), 'outside the project');
    await symlink(join(scratch, 'outside'), join(root, 'external-link'));
    await symlink('paper.tex', join(root, 'internal-link'));
  });

  after(async () => rm(scratch, { recursive: true, force: true }));

  it('maps all five statuses and the UNKNOWN severity setting (AC-4.1)', () => {
    assert.deepEqual(STATUSES.map((s) => severityFor(s, 'information')), [
      undefined, 'error', 'warning', 'information', undefined,
    ]);
    assert.equal(severityFor('UNKNOWN', 'warning'), 'warning');
  });

  it('anchors detail paths and exact lines, coalescing identical locations and codes (AC-4.2)', async () => {
    const anchors = await resultAnchors({ ...finding, details: [
      { path: 'paper.tex', line: 3, code: 'R-11.stale' },
      { path: 'internal-link', line: 3, code: 'R-11.stale' },
      { path: 'paper.tex', line: 3, code: 'R-11.not_cited' },
      { path: join(root, 'paper.tex'), line: 1.5 },
      { path: 'data.tsv', row: 20, code: 'R-12.mismatch' },
    ] }, projectFiles(root));
    assert.deepEqual(anchors, [
      { path: 'paper.tex', line: 3, code: 'R-11.stale' },
      { path: 'paper.tex', line: 3, code: 'R-11.not_cited' },
      { path: 'paper.tex', line: 1, code: undefined },
      { path: 'data.tsv', line: 1, code: undefined },
    ]);
  });

  it('uses a file subject as a fallback and drops unsafe or non-file paths (T5)', async () => {
    const file = projectFiles(root);
    const anchors = await resultAnchors({ ...finding, details: [{ code: 'R-11.stale' }] }, file);
    assert.deepEqual(anchors, [{ path: 'paper.tex', line: 1, code: 'R-11.stale' }]);
    const unsafe = ['.', 'directory', 'repo-id', 'missing.txt', '../outside', join(scratch, 'outside'), 'external-link'];
    for (const path of unsafe) {
      assert.deepEqual(await resultAnchors({ ...finding, subject: path, details: [{ path, line: 3 }] }, file), [], path);
    }
  });
});
