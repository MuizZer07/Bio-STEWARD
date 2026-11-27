// Where the session handoff is (S4): `[session] handoff`, default development/HANDOFF.md.
import { strict as assert } from 'node:assert';
import { DEFAULT_HANDOFF, handoffSetting } from '../../src/model/handoff';

describe('the [session] handoff setting (S4)', () => {
  it('defaults to development/HANDOFF.md, as CLI 0.20.6 does', () => {
    assert.equal(DEFAULT_HANDOFF, 'development/HANDOFF.md');
    assert.deepEqual(handoffSetting(''), { kind: 'path', path: DEFAULT_HANDOFF, configured: false });
    assert.deepEqual(handoffSetting('[steward]\nproject = "x"\n\n[session]\nbudget_words = 600\n'),
      { kind: 'path', path: DEFAULT_HANDOFF, configured: false });
  });

  it('reads the forms a person writes', () => {
    const cases: [string, string][] = [
      ['[session]\nhandoff = "docs/HANDOFF.md"\n', 'docs/HANDOFF.md'],
      ['[ session ]  # comment\n  handoff="a b.md"   # trailing\n', 'a b.md'],
      ["[session]\nhandoff = 'C:\\no\\escapes.md'\n", 'C:\\no\\escapes.md'],
      ['[session]\nhandoff = "tab\\there \\u00e9.md"\n', 'tab\there é.md'],
      ['["session"]\n"handoff" = "quoted.md"\n', 'quoted.md'],
      ['session.handoff = "dotted.md"\n[steward]\nproject = "x"\n', 'dotted.md'],
      ['[steward]\nhandoff = "not this"\n[session]\nend_hint = "/exit"\nhandoff = "this.md"\n[other]\nhandoff = "nor this"\n', 'this.md'],
      ['[session.extra]\nhandoff = "not this"\n[session]\nhandoff = "this.md"\n', 'this.md'],
      ['[tool]\nsession = { handoff = "not this" }\n', DEFAULT_HANDOFF],
    ];
    for (const [toml, path] of cases) {
      const setting = handoffSetting(toml);
      assert.equal(setting.kind === 'path' && setting.path, path, toml);
    }
  });

  it('never guesses: other forms that name the key are unreadable', () => {
    for (const toml of [
      'session = { handoff = "inline.md" }\n',
      '[session]\nhandoff = """\nmulti.md"""\n',
      '[session]\nhandoff = 12\n',
      '[session]\nhandoff = "unterminated\n',
      '[session]\nhandoff = "bad \\q escape"\n',
      '[session]\nhandoff = "a.md" trailing\n',
      '[session]\nhandoff = "a.md"\nhandoff = "b.md"\n',
      '[[session]]\nhandoff = "a.md"\n',
      '[session]\nhandoff.x = "a.md"\n',
    ]) {
      assert.equal(handoffSetting(toml).kind, 'unreadable', toml);
    }
  });
});
