// The `steward.report/0.1` document (`steward check --format json`) and its validator.
//
// The types mirror src/schemas/steward.report-0.1.schema.json, the byte-checked copy from the pinned release tag.
// They are written out rather than generated (no generator is a dependency); test/unit/report.test.ts fails when a
// property or a required key here differs from the schema.
import Ajv2020 from 'ajv/dist/2020';
import type { ValidateFunction } from 'ajv';
import schema from '../schemas/steward.report-0.1.schema.json';

export const STATUSES = ['PASS', 'FAIL', 'INCOMPLETE', 'UNKNOWN', 'NOT_APPLICABLE'] as const;
export type Status = typeof STATUSES[number];
export type Counts = Record<Status, number>;

export interface GateRef {
  rule: string;
  subject: string;
  status: Status;
}

export interface Gate {
  name: string;
  evaluated: boolean;
  eligible: boolean;
  reason: string;
  required_count: number;
  evaluated_count: number;
  pass_count?: number;
  not_applicable_count?: number;
  blocking: GateRef[];
  waived: WaivedGateRef[];
}

// A waived result of a gate, with the authorization that waived it (CLI 0.21 and later).
export interface WaivedGateRef extends GateRef {
  authorization: string;
}

// What a check covered (CLI 0.21 and later): the whole project, or some areas, or one rule.
export interface Scope {
  full: boolean;
  areas: string[];
  rule?: string | null;
}

export interface EvidenceItem {
  path: string;
  sha256: string;
}

export interface ResultItem {
  area?: string | null;
  rule: string;
  name: string;
  rule_version: number;
  subject: string;
  status: Status;
  reason: string;
  details: Record<string, unknown>[];
  evidence: EvidenceItem[];
}

export interface Coverage {
  areas?: { configured?: string[]; not_configured?: string[]; nothing_recorded?: string[] };
  not_evaluated: { path: string; reason: string }[];
  statement: string;
}

export interface Verdict {
  repo_id: string;
  project: string;
  config_profile: string;
  inputs_digest: string;
  inputs?: EvidenceItem[] | null;
  tree_digest?: string | null;
  scope?: Scope | null;
  results: ResultItem[];
  summary: { counts: Counts; worst: Status };
  gates: Gate[];
  coverage: Coverage;
}

export interface Envelope {
  tool: string;
  tool_version: string;
  created: string;
  platform: Record<string, string>;
  git: Record<string, unknown> | 'unknown';
}

export interface Report {
  schema: 'steward.report/0.1';
  envelope: Envelope;
  verdict: Verdict;
}

export const reportSchema: unknown = schema;

let compiled: ValidateFunction<Report> | undefined;

// Compiled once, on first use: the schema is draft 2020-12 and carries annotations (title, default) only.
export function reportValidator(): ValidateFunction<Report> {
  compiled ??= new Ajv2020({ strict: false, allErrors: false }).compile<Report>(schema);
  return compiled;
}
