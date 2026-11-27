import { spawn } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { isAbsolute } from 'node:path';
import { Invocation, isAllowed } from './commands';
import { gitEnvironment, isGitAllowed } from './git';
import { boundedLog, confinedPath, existingFile } from './paths';

export const MAX_OUTPUT_BYTES = 20 * 1024 * 1024;

type Failure = { kind: 'timeout' | 'cancelled' | 'superseded' | 'untrusted' | 'unconfirmed' | 'unreadable' };
type ProcessError = { kind: 'process-error'; message: string };
export type RunResult = Failure | ProcessError | {
  kind: 'completed';
  exitCode: number;
  stdout: string;
  stderr: string;
};

interface RunnerOptions {
  // The program: the steward CLI (default), or git for the one allow-listed git command (src/cli/git.ts). Each
  // runs only invocations from its own allow-list.
  program?: 'steward' | 'git';
  cli: string;
  // Runners with different flight names do not share single-flight (a git probe or the timeline never
  // supersedes a queued check). The default is the root's steward flight.
  flight?: string;
  root: string;
  storageRoot?: string;
  isTrusted: () => boolean;
  registry?: 'respect' | 'disable';
  timeoutMs?: number;
  maxOutputBytes?: number;
  logStderr?: (stderr: string) => void;
}

interface RunOptions {
  signal?: AbortSignal;
  confirm?: (cli: string, args: readonly string[]) => Promise<boolean>;
}

interface Request {
  start: () => Promise<RunResult>;
  settle: (result: RunResult) => void;
}

interface Flight {
  pending?: Request;
}

const flights = new Map<string, Flight>();

export class CliRunner {
  readonly #root: string;
  readonly #flight: string;
  readonly #storageRoot: string | undefined;
  readonly #timeoutMs: number;
  readonly #maxOutputBytes: number;

  constructor(private readonly options: RunnerOptions) {
    if (!isAbsolute(options.cli)) throw new Error('CLI path must be absolute');
    this.#root = realpathSync(options.root);
    this.#flight = JSON.stringify([options.program ?? 'steward', options.flight ?? '', this.#root]);
    this.#storageRoot = options.storageRoot && realpathSync(options.storageRoot);
    this.#timeoutMs = options.timeoutMs ?? 120_000;
    this.#maxOutputBytes = options.maxOutputBytes ?? MAX_OUTPUT_BYTES;
    for (const limit of [this.#timeoutMs, this.#maxOutputBytes]) {
      if (!Number.isSafeInteger(limit) || limit < 1 || limit > 2_147_483_647) throw new Error('Invalid runner limit');
    }
  }

  get cliPath(): string {
    return this.options.cli;
  }

  run(invocation: Invocation, options: RunOptions = {}): Promise<RunResult> {
    const allowed = (this.options.program ?? 'steward') === 'git' ? isGitAllowed(invocation) : isAllowed(invocation);
    if (!allowed) return Promise.resolve({ kind: 'process-error', message: 'Disallowed invocation' });
    if (!this.options.isTrusted()) return Promise.resolve({ kind: 'untrusted' });
    const { signal } = options;
    if (signal?.aborted) return Promise.resolve({ kind: 'cancelled' });

    return new Promise((resolve) => {
      const flight = flights.get(this.#flight);
      if (!flight) {
        const current: Flight = {};
        flights.set(this.#flight, current);
        void this.#drain(current, { start: () => this.#run(invocation, options), settle: resolve });
        return;
      }

      const abort = () => {
        if (flight.pending === pending) flight.pending = undefined;
        pending.settle({ kind: 'cancelled' });
      };
      const pending: Request = {
        start: () => {
          signal?.removeEventListener('abort', abort);
          return this.#run(invocation, options);
        },
        settle: (outcome) => {
          signal?.removeEventListener('abort', abort);
          resolve(outcome);
        },
      };
      flight.pending?.settle({ kind: 'superseded' });
      flight.pending = pending;
      signal?.addEventListener('abort', abort, { once: true });
    });
  }

  async #drain(flight: Flight, request: Request): Promise<void> {
    let current: Request | undefined = request;
    while (current) {
      try {
        current.settle(await current.start());
      } catch (error) {
        current.settle({ kind: 'process-error', message: error instanceof Error ? error.message : String(error) });
      }
      current = flight.pending;
      flight.pending = undefined;
    }
    flights.delete(this.#flight);
  }

  async #run(invocation: Invocation, { signal, confirm }: RunOptions): Promise<RunResult> {
    if (!this.options.isTrusted()) return { kind: 'untrusted' };
    if (signal?.aborted) return { kind: 'cancelled' };
    const args = [...invocation.args];
    for (const { index, use, boundary } of invocation.paths) {
      if (use === 'log') {
        const file = boundary === undefined ? await existingFile(args[index]) : await boundedLog(args[index], boundary);
        if (!file) {
          return { kind: 'process-error', message: boundary === undefined ? 'An agent log is not an absolute path to a readable file'
            : 'An agent log is no longer inside the file or folder its setting names, or is reached through a link' };
        }
        args[index] = file;
        continue;
      }
      const allowMissing = use === 'output' || use === 'projectDestination';
      const projectPath = await confinedPath(this.#root, args[index], allowMissing);
      const storagePath = !projectPath && this.#storageRoot && isAbsolute(args[index]) && (use === 'input' || use === 'output')
        ? await confinedPath(this.#storageRoot, args[index], allowMissing)
        : undefined;
      const path = projectPath || storagePath;
      if (!path) return { kind: 'process-error', message: 'CLI path is outside its allowed directory or inaccessible' };
      args[index] = path;
    }
    if (invocation.repoIndex !== undefined) args.splice(invocation.repoIndex, 0, '--repo', this.#root);
    Object.freeze(args);
    if (!this.options.isTrusted()) return { kind: 'untrusted' };
    if (signal?.aborted) return { kind: 'cancelled' };
    if (invocation.confirmation && !await confirm?.(this.options.cli, args)) return { kind: 'unconfirmed' };
    if (!this.options.isTrusted()) return { kind: 'untrusted' };
    if (signal?.aborted) return { kind: 'cancelled' };
    return this.#execute(args, signal);
  }

  #execute(args: readonly string[], signal?: AbortSignal): Promise<RunResult> {
    return new Promise((resolve) => {
      // execFile does not expose detached process groups. On supported hosts
      // (macOS, Linux and WSL), a negative PID signals the whole group.
      const child = spawn(this.options.cli, args, {
        cwd: this.#root,
        shell: false,
        detached: true,
        stdio: ['ignore', 'pipe', 'pipe'],
        // git: PATH, HOME and GIT_CONFIG_NOSYSTEM=1 only (src/cli/git.ts, T11-02).
        env: this.options.program === 'git'
          ? gitEnvironment(process.env)
          : this.options.registry === 'disable' ? { ...process.env, STEWARD_NO_REGISTRY: '1' } : process.env,
      });
      const stdout: Buffer[] = [];
      const stderr: Buffer[] = [];
      let bytes = 0;
      let failure: Failure | ProcessError | undefined;
      const stop = (reason: Failure) => {
        if (failure) return;
        failure = reason;
        if (child.pid !== undefined) {
          try {
            process.kill(-child.pid, 'SIGKILL');
          } catch (error) {
            if ((error as NodeJS.ErrnoException).code !== 'ESRCH') child.kill('SIGKILL');
          }
        }
        // A descendant that opened its own process group can still hold these pipes.
        child.stdout.destroy();
        child.stderr.destroy();
      };
      const capture = (destination: Buffer[]) => (chunk: Buffer) => {
        if (failure) return;
        bytes += chunk.byteLength;
        if (bytes > this.#maxOutputBytes) stop({ kind: 'unreadable' });
        else destination.push(chunk);
      };
      const abort = () => stop({ kind: 'cancelled' });
      const timer = setTimeout(() => stop({ kind: 'timeout' }), this.#timeoutMs);
      signal?.addEventListener('abort', abort, { once: true });
      child.stdout.on('data', capture(stdout));
      child.stderr.on('data', capture(stderr));
      child.on('error', (error) => {
        failure ??= { kind: 'process-error', message: error.message };
      });
      child.once('close', (exitCode, signalName) => {
        clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
        const stderrText = Buffer.concat(stderr).toString('utf8');
        if (stderrText) this.options.logStderr?.(stderrText);
        resolve(failure ?? (exitCode === null
          ? { kind: 'process-error', message: `CLI ended with ${signalName}` }
          : { kind: 'completed', exitCode, stdout: Buffer.concat(stdout).toString('utf8'), stderr: stderrText }));
      });
    });
  }
}
