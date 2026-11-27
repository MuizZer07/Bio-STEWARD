// T08: Copy for agent (S5, TOK-2), the scoped re-check builders (S8) and the skills install builders (S7).
import { strict as assert } from 'node:assert';
import { CHECK_AREAS, commands, isAllowed, isArea, skillsInstallCommands } from '../../src/cli/commands';
import { agentText, recheckCommand } from '../../src/model/agent';

describe('Copy for agent (S5)', () => {
  it('is the CLI summary unchanged, then the re-check command and the summary size in bytes', () => {
    const summary = 'Summary: PASS 1 · FAIL 0\nGate default: ELIGIBLE (é)\n';
    const text = agentText(summary, undefined, '0.20.6');
    assert.ok(text.startsWith(summary), 'the summary comes first, unchanged');
    assert.equal(text.slice(summary.length),
      '\nRe-check: steward check --summary\n' +
      `(the text above is \`steward check --summary\` from steward 0.20.6, unchanged: ${Buffer.byteLength(summary)} bytes)\n`);
    assert.notEqual(Buffer.byteLength(summary), summary.length, 'bytes, not characters');
  });

  it('names the rule re-check for a rule summary, and ends a summary without a newline cleanly', () => {
    assert.equal(recheckCommand('R-60'), 'steward check --rule R-60 --summary');
    const text = agentText('R-60 FAIL', 'R-60', '0.20.6');
    assert.equal(text, 'R-60 FAIL\n\nRe-check: steward check --rule R-60 --summary\n' +
      '(the text above is `steward check --rule R-60 --summary` from steward 0.20.6, unchanged: 9 bytes)\n');
  });

  it('builds `check --summary` and `check --summary --rule R-xx` only, both read-only', () => {
    const full = commands.check({ mode: 'summary' });
    const rule = commands.check({ mode: 'summary', rule: 'R-60' });
    assert.deepEqual(full.args, ['check', '--summary']);
    assert.deepEqual(rule.args, ['check', '--summary', '--rule', 'R-60']);
    for (const invocation of [full, rule]) {
      assert.equal(invocation.confirmation, false);
      assert.ok(isAllowed(invocation));
    }
    assert.throws(() => commands.check({ mode: 'summary', rule: 'R-6; rm' as 'R-6' }), /Invalid rule ID/);
  });
});

describe('Scoped re-check (S8)', () => {
  it('builds `check AREA … --format json --output FILE` and `check --rule R-xx …`', () => {
    const area = commands.check({ mode: 'report', output: '/s/scoped-report.json', areas: ['skills', 'data'] });
    assert.deepEqual(area.args, ['check', '--format', 'json', '--output', '/s/scoped-report.json', 'skills', 'data']);
    assert.deepEqual(area.paths, [{ index: 4, use: 'output' }]);
    const rule = commands.check({ mode: 'report', output: '/s/scoped-report.json', rule: 'R-60' });
    assert.deepEqual(rule.args, ['check', '--format', 'json', '--output', '/s/scoped-report.json', '--rule', 'R-60']);
  });

  it('accepts only the areas of CLI 0.20.6', () => {
    assert.ok(CHECK_AREAS.every(isArea));
    for (const value of ['', 'skills ', '--all', 'nope', 7, undefined]) assert.equal(isArea(value), false, String(value));
    assert.throws(() => commands.check({ mode: 'report', output: 'x', areas: ['--all' as 'skills'] }), /Unsupported CLI option/);
  });
});

describe('Install Agent Skills builders (S7)', () => {
  it('previews with --dry-run and applies the same flags with confirmation; the first folder holds the copy', () => {
    const { preview, apply } = skillsInstallCommands({ skills: ['.agents/skills', '.claude/skills'], kits: ['core', 'paper'] });
    assert.deepEqual(apply.args, ['init', '--skills', '.agents/skills', '--skills', '.claude/skills', '--kits', 'core,paper']);
    assert.deepEqual(preview.args, [...apply.args, '--dry-run']);
    assert.equal(apply.confirmation, true);
    assert.equal(preview.confirmation, false);
    assert.deepEqual(apply.paths.map((p) => p.use), ['projectDestination', 'projectDestination']);
    assert.deepEqual(skillsInstallCommands({ skills: ['.agents/skills'] }).apply.args, ['init', '--skills', '.agents/skills']);
  });

  it('refuses no folder, a flag as a folder and unknown kits', () => {
    assert.throws(() => skillsInstallCommands({ skills: [] }), /No skills folder/);
    assert.throws(() => skillsInstallCommands({ skills: ['--paper'] }), /Invalid CLI argument/);
    assert.throws(() => skillsInstallCommands({ skills: ['.agents/skills'], kits: ['all' as 'core'] }), /Unsupported CLI option/);
  });
});
