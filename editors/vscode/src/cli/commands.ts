export const CHECK_AREAS = Object.freeze([
  'agents', 'benchmark', 'boundary', 'branches', 'changelog', 'compare', 'config', 'containers',
  'contract', 'data', 'dependencies', 'docs', 'evidence', 'files', 'frozen', 'governance',
  'integrity', 'licence', 'milestones', 'models', 'paper', 'pins', 'policy', 'prior-work',
  'privacy', 'release', 'repro', 'research', 'run', 'session', 'skills', 'spend', 'sprints',
  'stages', 'storage', 'studies', 'talk', 'tasks',
] as const);

export type Area = typeof CHECK_AREAS[number];
export type Rule = `R-${number}`;

export function isArea(value: unknown): value is Area {
  return typeof value === 'string' && (CHECK_AREAS as readonly string[]).includes(value);
}
// `log`: an agent's session log named by a machine setting (P4): an existing regular file anywhere on this machine,
// passed to `tokens report` only, which reads usage counts from it. With a `boundary` (the file or folder the
// setting named, canonical), the runner checks again just before the CLI starts that the file is still inside it and
// reached without a link (U09).
type PathUse = 'input' | 'output' | 'projectInput' | 'projectDestination' | 'log';

export interface Invocation {
  readonly args: readonly string[];
  readonly repoIndex: number | undefined;
  readonly paths: readonly Readonly<{ index: number; use: PathUse; boundary?: string }>[];
  readonly confirmation: boolean;
}

const built = new WeakSet<Invocation>();

function command(prefix: readonly string[], repo = true) {
  const args = [...prefix];
  const paths: { index: number; use: PathUse; boundary?: string }[] = [];
  return {
    args,
    path(value: string, use: PathUse, boundary?: string) {
      paths.push(Object.freeze(boundary === undefined ? { index: args.length, use } : { index: args.length, use, boundary }));
      args.push(argument(value));
    },
    finish(confirmation = false): Invocation {
      const invocation = Object.freeze({
        args: Object.freeze(args),
        paths: Object.freeze(paths),
        repoIndex: repo ? prefix.length : undefined,
        confirmation,
      });
      built.add(invocation);
      return invocation;
    },
  };
}

export function isAllowed(invocation: Invocation): boolean {
  return built.has(invocation);
}

function argument(value: string): string {
  if (typeof value !== 'string' || !value.trim() || value.startsWith('-') || /[\0\r\n]/.test(value)) {
    throw new Error('Invalid CLI argument');
  }
  return value;
}

function choice<T extends string>(value: T, choices: readonly T[]): T {
  if (!choices.includes(value)) throw new Error('Unsupported CLI option');
  return value;
}

export function isRuleId(value: unknown): value is Rule {
  return typeof value === 'string' && /^R-\d{2}$/.test(value);
}

function ruleId(value: Rule): Rule {
  if (!isRuleId(value)) throw new Error('Invalid rule ID');
  return value;
}

// The CLI's task window identifier (CLI 0.20.6 `token_logs.identifier`).
function windowId(value: string): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$/.test(value)) throw new Error('Invalid task ID');
  return value;
}

// A sprint ID as the sprint files name it (`development/sprints/<id>.toml`).
function sprintId(value: string): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value)) throw new Error('Invalid sprint ID');
  return value;
}

export interface TokenLogs {
  claude?: readonly string[];
  codex?: readonly string[];
  gemini?: readonly string[];
  // Per file: the file or folder its setting named (src/tokenLogs.ts), kept to the moment the CLI starts.
  boundaries?: Readonly<Record<string, string>>;
}

function name(value: string): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(value)) throw new Error('Invalid scaffold name');
  return value;
}

type CheckOptions = {
  areas?: readonly Area[];
  rule?: Rule;
  gate?: string;
} & ({ mode: 'report'; output: string } | { mode: 'summary' } | { mode: 'digest' });

interface InitOptions {
  profile?: 'exploratory' | 'confirmatory';
  goals?: readonly ('agents' | 'benchmark' | 'licence' | 'paper' | 'reanalysis')[];
  agentsMd?: boolean;
  skills?: readonly string[];
  kits?: readonly ('core' | 'paper' | 'talk')[];
  paper?: true | string;
  talk?: string;
  project?: string;
  templates?: readonly ('contract' | 'prior-work')[];
  configOverlay?: string;
  preview?: 'text' | 'json';
}

export type GuidedInitOptions = Pick<InitOptions, 'profile' | 'goals' | 'skills' | 'kits'>;

export function guidedInitCommands(options: GuidedInitOptions) {
  return {
    preview: commands.init({ ...options, preview: 'text' }),
    apply: commands.init(options),
  };
}

export type SkillsInstallOptions = { skills: readonly string[]; kits?: GuidedInitOptions['kits'] };

// S7: `init --skills DIR … [--kits …]`, with its dry run. The first folder holds the copy, the others link to it.
export function skillsInstallCommands(options: SkillsInstallOptions) {
  if (!options.skills.length) throw new Error('No skills folder');
  const init = { skills: options.skills, kits: options.kits };
  return {
    preview: commands.init({ ...init, preview: 'text' }),
    apply: commands.init(init),
  };
}

export const commands = Object.freeze({
  version: () => command(['--version'], false).finish(),
  interface: () => jsonCommand(['interface'], false),
  check(options: CheckOptions): Invocation {
    const spec = command(['check']);
    switch (options.mode) {
      case 'report':
        spec.args.push('--format', 'json', '--output');
        spec.path(options.output, 'output');
        break;
      case 'summary':
        spec.args.push('--summary');
        break;
      case 'digest':
        spec.args.push('--digest-only', '--format', 'json');
        break;
      default:
        throw new Error('Unsupported check mode');
    }
    if (options.rule !== undefined) spec.args.push('--rule', ruleId(options.rule));
    if (options.gate !== undefined) spec.args.push('--gate', argument(options.gate));
    for (const area of options.areas ?? []) spec.args.push(choice(area, CHECK_AREAS));
    return spec.finish();
  },
  explain(rule: Rule, format: 'text' | 'json' = 'text'): Invocation {
    const spec = command(['explain']);
    spec.args.push(ruleId(rule));
    if (format === 'json') spec.args.push('--format', 'json');
    return spec.finish();
  },
  report(file: string, options: { format?: 'md' | 'text' | 'summary'; rule?: Rule } = {}): Invocation {
    const spec = command(['report']);
    if (options.format !== undefined) spec.args.push('--format', choice(options.format, ['md', 'text', 'summary']));
    if (options.rule !== undefined) spec.args.push('--rule', ruleId(options.rule));
    spec.path(file, 'input');
    return spec.finish();
  },
  timeline: () => legacyJsonCommand(['timeline']),
  skillsList: () => jsonCommand(['skills', 'list']),
  auditProgress: () => legacyJsonCommand(['audit', 'progress']),
  exchangeStatus: () => legacyJsonCommand(['exchange', 'status']),
  // E03: one feed of notifications (steward.notifications/0.1), read-only.
  notifications: () => jsonCommand(['notifications']),
  // E03: local upgrade check (steward.upgrade/0.1), read-only; never passes --online (no network call).
  // Upgrading itself (`upgrade --to VERSION`) runs only in a visible terminal after confirmation (src/cli/upgrade.ts).
  upgradeCheck(): Invocation {
    const spec = command(['upgrade']);
    spec.args.push('--check', '--format', 'json');
    return spec.finish();
  },
  nextBrief(): Invocation {
    const spec = command(['next']);
    spec.args.push('--brief');
    return spec.finish();
  },
  taskBrief(file: string): Invocation {
    const spec = command(['task', 'brief']);
    spec.path(file, 'projectInput');
    spec.args.push('--for', 'codex');
    return spec.finish();
  },
  // P5: the queue of payloads waiting for a signature, here and in the declared peers. Read-only (CLI
  // 0.20.6 prints text; it has no JSON form). Signing is never built here: see src/cli/signing.ts.
  authorizePending(): Invocation {
    const spec = command(['authorize', 'pending']);
    spec.args.push('--all-projects');
    return spec.finish();
  },
  // E04, the full forms (CLI 0.21 and later, found through `steward interface`). Each is read-only.
  next: () => jsonCommand(['next']),
  taskBoard: () => jsonCommand(['task', 'board']),
  decisions: () => jsonCommand(['decisions']),
  // The timeline as a versioned document: the milestones and the drift fields.
  timelineFull: () => jsonCommand(['timeline']),
  authorizePendingJson(): Invocation {
    const spec = command(['authorize', 'pending']);
    spec.args.push('--all-projects', '--format', 'json');
    return spec.finish();
  },
  sprintStatus(id: string): Invocation {
    const spec = command(['sprint', 'status']);
    spec.args.push(sprintId(id), '--format', 'json');
    return spec.finish();
  },
  // P4: read-only; the CLI reads the log files given and prints counts. With `versioned` (CLI 0.21 and later), the
  // versioned document, which names each task's windows and the record each came from (E04).
  tokensReport(logs: TokenLogs = {}, versioned = false): Invocation {
    const spec = command(['tokens', 'report']);
    spec.args.push(...(versioned ? ['--format', 'json'] : ['--json']));
    for (const agent of ['claude', 'codex', 'gemini'] as const) {
      for (const file of logs[agent] ?? []) {
        spec.args.push(`--${agent}`);
        spec.path(file, 'log', logs.boundaries?.[file]);
      }
    }
    return spec.finish();
  },
  // P4: open or close a task window in `.steward/task-tokens.jsonl`; each is a write, so each needs confirmation.
  taskStart: (id: string): Invocation => {
    const spec = command(['task', 'start']);
    spec.args.push(windowId(id));
    return spec.finish(true);
  },
  taskDone: (id: string): Invocation => {
    const spec = command(['task', 'done']);
    spec.args.push(windowId(id));
    return spec.finish(true);
  },
  init(options: InitOptions = {}): Invocation {
    const spec = command(['init']);
    if (options.profile !== undefined) {
      spec.args.push('--profile', choice(options.profile, ['exploratory', 'confirmatory']));
    }
    for (const goal of options.goals ?? []) {
      spec.args.push('--for', choice(goal, ['agents', 'benchmark', 'licence', 'paper', 'reanalysis']));
    }
    if (options.agentsMd === true) spec.args.push('--agents-md');
    for (const directory of options.skills ?? []) {
      spec.args.push('--skills');
      spec.path(directory, 'projectDestination');
    }
    if (options.kits?.length) {
      spec.args.push('--kits', options.kits.map((kit) => choice(kit, ['core', 'paper', 'talk'])).join(','));
    }
    if (options.paper !== undefined) {
      spec.args.push('--paper');
      if (options.paper !== true) spec.args.push(name(options.paper));
    }
    if (options.talk !== undefined) spec.args.push('--talk', name(options.talk));
    if (options.project !== undefined) spec.args.push('--project', argument(options.project));
    if (options.templates?.length) {
      spec.args.push('--templates', options.templates.map((template) => choice(template, ['contract', 'prior-work'])).join(','));
    }
    if (options.configOverlay !== undefined) {
      spec.args.push('--config-overlay');
      spec.path(options.configOverlay, 'projectInput');
    }
    if (options.preview !== undefined) {
      spec.args.push('--dry-run');
      if (choice(options.preview, ['text', 'json']) === 'json') spec.args.push('--format', 'json');
    }
    return spec.finish(options.preview === undefined);
  },
});

function jsonCommand(prefix: readonly string[], repo = true): Invocation {
  const spec = command(prefix, repo);
  spec.args.push('--format', 'json');
  return spec.finish();
}

function legacyJsonCommand(prefix: readonly string[]): Invocation {
  const spec = command(prefix);
  spec.args.push('--json');
  return spec.finish();
}
