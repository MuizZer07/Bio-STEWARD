// The README and guide figures are drawn by scripts/figures.mjs from the view model and the fixture reports (T10).
// A change to a label, a glyph or a fixture that alters a figure fails here until `npm run figures` is run and the
// new drawing reviewed, so the README never shows a view the extension no longer draws.
import { strict as assert } from 'node:assert';
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';

const root = join(__dirname, '..', '..', '..');

describe('figures', () => {
  it('the committed SVG figures equal what the view model draws now', () => {
    const r = spawnSync(process.execPath, [join(root, 'scripts', 'figures.mjs'), '--verify'], { cwd: root, encoding: 'utf8' });
    assert.equal(r.status, 0, `${r.stdout}\n${r.stderr}`);
  });
});
