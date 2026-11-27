// `bioSteward.check.onSave` (T12, decision D3 on T11-10): run `steward check` again after a file is saved. Off by
// default; trusted workspaces only (the caller checks trust and the setting). No VS Code API here, so the unit tests
// drive it with short delays.
//
// - Debounced: a run starts DEBOUNCE_MS after the last save in that project; more saves restart the wait.
// - Single-flight per project: while its check runs, saves only mark that one more run is wanted, which starts
//   (after the same wait) when the current run has ended. Never two runs of one project at once.
// - A save under `.steward/` (the CLI's own state and the report) or `.git/`, or outside the project, never
//   triggers a run.
import { isAbsolute, relative, sep } from 'node:path';

export const DEBOUNCE_MS = 2000;

// Whether saving `file` (absolute) may trigger a check of the project at `root`.
export function triggersCheck(root: string, file: string): boolean {
  const rel = relative(root, file);
  if (!rel || isAbsolute(rel) || rel === '..' || rel.startsWith(`..${sep}`)) return false;
  const first = rel.split(/[\\/]/)[0];
  return first !== '.steward' && first !== '.git';
}

interface Entry {
  timer: ReturnType<typeof setTimeout> | undefined;
  running: boolean;
  again: boolean;
}

export class SaveTrigger<K> {
  readonly #entries = new Map<K, Entry>();
  #disposed = false;

  constructor(private readonly run: (key: K) => Promise<unknown>, private readonly delayMs = DEBOUNCE_MS) {}

  // For the tests: whether a run is waiting or running for `key`.
  busy(key: K): boolean {
    const entry = this.#entries.get(key);
    return Boolean(entry && (entry.timer || entry.running));
  }

  saved(key: K): void {
    if (this.#disposed) return;
    const entry = this.#entries.get(key) ?? { timer: undefined, running: false, again: false };
    this.#entries.set(key, entry);
    if (entry.running) {
      entry.again = true;
      return;
    }
    this.#arm(key, entry);
  }

  #arm(key: K, entry: Entry): void {
    clearTimeout(entry.timer);
    entry.timer = setTimeout(() => {
      entry.timer = undefined;
      void this.#start(key, entry);
    }, this.delayMs);
  }

  async #start(key: K, entry: Entry): Promise<void> {
    if (this.#disposed) return;
    entry.running = true;
    entry.again = false;
    try {
      await this.run(key);
    } catch {
      // The run reports its own failures (the project state and the log).
    } finally {
      entry.running = false;
      if (entry.again && !this.#disposed) this.#arm(key, entry);
      else if (!entry.timer) this.#entries.delete(key);
    }
  }

  // A project that went away: its waiting run is dropped.
  forget(key: K): void {
    const entry = this.#entries.get(key);
    if (entry) {
      clearTimeout(entry.timer);
      entry.timer = undefined;
      entry.again = false;
    }
  }

  dispose(): void {
    this.#disposed = true;
    for (const entry of this.#entries.values()) clearTimeout(entry.timer);
    this.#entries.clear();
  }
}
