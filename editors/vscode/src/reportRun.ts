// One `steward check --format json --output FILE` request, from its private output file to a published report
// (T12, T11-05). No VS Code API here, so the unit tests drive it with stand-in runs.
//
// - Each request writes to its own new file (`.report-<uuid>.json`) in the folder of the report it may replace, so
//   overlapping requests never read, delete or replace each other's output, and the saved report is never
//   removed before a run.
// - Only a completed run whose exit is 0 – 3 (a verdict: PASS, FAIL, INCOMPLETE, UNKNOWN) carries a report; the file
//   is then read and validated. Any other exit, a cancellation or a failure publishes nothing.
// - Publishing is in request order: a request older than one already published is dropped ("outdated"). For a
//   full check the private file atomically replaces the saved report (a rename in the same folder), and only then
//   is the new state shown; a scoped check never replaces it.
// - The private file is removed whatever the outcome.
import { randomUUID } from 'node:crypto';
import { mkdir, rename, rm } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import type { ValidateFunction } from 'ajv';
import { readJson } from './cli/output';
import { confinedPath } from './cli/paths';
import type { RunResult } from './cli/runner';

export const REPORT_EXITS: readonly number[] = Object.freeze([0, 1, 2, 3]);

export type ReportRun<T> =
  | { readonly kind: 'published'; readonly value: T; readonly exitCode: number }
  | { readonly kind: 'outdated' }
  | { readonly kind: 'path' }
  | { readonly kind: 'run'; readonly result: Exclude<RunResult, { kind: 'completed' }> }
  | { readonly kind: 'exit'; readonly exitCode: number; readonly stderr: string }
  | { readonly kind: 'unreadable'; readonly exitCode: number };

// Request order for one kind of report (full or scoped) of one project.
export class PublishOrder {
  #issued = 0;
  #published = 0;
  #lock: Promise<unknown> = Promise.resolve();

  ticket(): number {
    return ++this.#issued;
  }

  // Runs `publish` for `ticket` unless a later ticket has already published; one at a time.
  publish(ticket: number, publish: () => Promise<void>): Promise<boolean> {
    const step = this.#lock.then(async () => {
      if (ticket < this.#published) return false;
      await publish();
      this.#published = ticket;
      return true;
    });
    this.#lock = step.catch(() => undefined);
    return step;
  }
}

export interface ReportRequest<T> {
  // The folder the report may be written in (the project root or the extension's storage).
  readonly boundary: string;
  // The saved report a successful full check replaces; for a scoped check, the folder its private file goes in.
  readonly destination: { readonly replace: string } | { readonly folder: string };
  readonly order: PublishOrder;
  readonly validate: ValidateFunction<T>;
  // Runs the check with `--output <private file>`.
  readonly execute: (output: string) => Promise<RunResult>;
  // Shows the report; called in request order, after the saved report was replaced.
  readonly show: (value: T) => void;
}

export async function runReportRequest<T>(request: ReportRequest<T>): Promise<ReportRun<T>> {
  const ticket = request.order.ticket();
  const folder = 'replace' in request.destination ? dirname(request.destination.replace) : request.destination.folder;
  const output = join(folder, `.report-${randomUUID()}.json`);
  if (!await confinedPath(request.boundary, output, true)) return { kind: 'path' };
  if ('replace' in request.destination && !await confinedPath(request.boundary, request.destination.replace, true)) return { kind: 'path' };
  try {
    await mkdir(folder, { recursive: true });
    // Made by mkdir: confined again, so a link put in its place is never written through.
    if (!await confinedPath(request.boundary, output, true)) return { kind: 'path' };
    const result = await request.execute(output);
    if (result.kind !== 'completed') return { kind: 'run', result };
    if (!REPORT_EXITS.includes(result.exitCode)) return { kind: 'exit', exitCode: result.exitCode, stderr: result.stderr };
    const read = await readJson<T>(output, request.validate);
    if (read.kind !== 'valid') return { kind: 'unreadable', exitCode: result.exitCode };
    const { value } = read;
    const published = await request.order.publish(ticket, async () => {
      if ('replace' in request.destination) {
        const target = await confinedPath(request.boundary, request.destination.replace, true);
        if (!target) throw new Error('the report path is outside its allowed directory');
        await rename(output, target);
      }
      request.show(value);
    });
    return published ? { kind: 'published', value, exitCode: result.exitCode } : { kind: 'outdated' };
  } finally {
    await rm(output, { force: true });
  }
}
