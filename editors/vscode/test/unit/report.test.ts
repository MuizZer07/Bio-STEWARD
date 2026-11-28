// The report types of src/model/report.ts against the schema copy: a property or a required key that differs
// fails here (the types are written out, not generated). The type-level half fails at compile time.
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  reportValidator, STATUSES, type Counts, type Coverage, type Envelope, type EvidenceItem, type Gate, type GateRef,
  type Report, type ResultItem, type Scope, type Verdict, type WaivedGateRef,
} from '../../src/model/report';

type RequiredKeys<T> = { [K in keyof T]-?: object extends Pick<T, K> ? never : K }[keyof T];
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
// Holds only when `Keys` lists exactly the properties of T, and `Required` exactly its required ones.
function shape<T>() {
  return <const Keys extends readonly (keyof T)[], const Required extends readonly RequiredKeys<T>[]>(
    keys: Keys & (Same<Keys[number], keyof T> extends true ? unknown : never),
    required: Required & (Same<Required[number], RequiredKeys<T>> extends true ? unknown : never),
  ) => ({ keys: [...keys].map(String).sort(), required: [...required].map(String).sort() });
}

type Areas = NonNullable<Coverage['areas']>;
type NotEvaluated = Coverage['not_evaluated'][number];
type Summary = Verdict['summary'];

const shapes: Record<string, { keys: string[]; required: string[] }> = {
  Report: shape<Report>()(['schema', 'envelope', 'verdict'], ['schema', 'envelope', 'verdict']),
  Envelope: shape<Envelope>()(['tool', 'tool_version', 'created', 'platform', 'git'],
    ['tool', 'tool_version', 'created', 'platform', 'git']),
  Verdict: shape<Verdict>()(
    ['repo_id', 'project', 'config_profile', 'inputs_digest', 'inputs', 'tree_digest', 'scope', 'results', 'summary',
      'gates', 'coverage'],
    ['repo_id', 'project', 'config_profile', 'inputs_digest', 'results', 'summary', 'gates', 'coverage']),
  Summary: shape<Summary>()(['counts', 'worst'], ['counts', 'worst']),
  Counts: shape<Counts>()(['PASS', 'FAIL', 'INCOMPLETE', 'UNKNOWN', 'NOT_APPLICABLE'],
    ['PASS', 'FAIL', 'INCOMPLETE', 'UNKNOWN', 'NOT_APPLICABLE']),
  Gate: shape<Gate>()(
    ['name', 'evaluated', 'eligible', 'reason', 'required_count', 'evaluated_count', 'pass_count',
      'not_applicable_count', 'blocking', 'waived'],
    ['name', 'evaluated', 'eligible', 'reason', 'required_count', 'evaluated_count', 'blocking', 'waived']),
  GateRef: shape<GateRef>()(['rule', 'subject', 'status'], ['rule', 'subject', 'status']),
  WaivedGateRef: shape<WaivedGateRef>()(['rule', 'subject', 'status', 'authorization'],
    ['rule', 'subject', 'status', 'authorization']),
  Scope: shape<Scope>()(['full', 'areas', 'rule'], ['full', 'areas']),
  ResultItem: shape<ResultItem>()(
    ['area', 'rule', 'name', 'rule_version', 'subject', 'status', 'reason', 'details', 'evidence'],
    ['rule', 'name', 'rule_version', 'subject', 'status', 'reason', 'details', 'evidence']),
  EvidenceItem: shape<EvidenceItem>()(['path', 'sha256'], ['path', 'sha256']),
  Coverage: shape<Coverage>()(['areas', 'not_evaluated', 'statement'], ['not_evaluated', 'statement']),
  Areas: shape<Areas>()(['configured', 'not_configured', 'nothing_recorded'], []),
  NotEvaluated: shape<NotEvaluated>()(['path', 'reason'], ['path', 'reason']),
};

interface SchemaObject {
  properties: Record<string, { enum?: string[] }>;
  required?: string[];
}

const schema = JSON.parse(readFileSync(join(__dirname, '..', '..', '..', 'src', 'schemas',
  'steward.report-0.1.schema.json'), 'utf8')) as SchemaObject & { $defs: Record<string, SchemaObject> };

describe('report model', () => {
  it('has a type for every object of the schema, with the same properties and required keys', () => {
    const objects: Record<string, SchemaObject> = { Report: schema, ...schema.$defs };
    assert.deepEqual(Object.keys(shapes).sort(), Object.keys(objects).sort());
    for (const [name, object] of Object.entries(objects)) {
      assert.deepEqual(shapes[name].keys, Object.keys(object.properties).sort(), `${name} properties`);
      assert.deepEqual(shapes[name].required, [...(object.required ?? [])].sort(), `${name} required`);
    }
  });

  it('lists the five statuses of the schema', () => {
    assert.deepEqual([...STATUSES], schema.$defs.ResultItem.properties.status.enum);
    assert.deepEqual([...STATUSES], schema.$defs.GateRef.properties.status.enum);
  });

  it('validates with the bundled schema copy', () => {
    const report = JSON.parse(readFileSync(join(__dirname, '..', '..', '..', 'test', 'fixtures', 'reports', 'geo.json'),
      'utf8')) as Report;
    assert.equal(reportValidator()(report), true);
    assert.equal(reportValidator()({ ...report, schema: 'steward.report/0.2' }), false);
    assert.equal(reportValidator()({ ...report, verdict: { ...report.verdict, gates: [{ name: 'default' }] } }), false);
  });
});
