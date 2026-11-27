// Several projects in one window (S2; AC-1.4). A project is a workspace folder whose root holds steward.toml, as
// `steward --repo FOLDER` reads it. Each has its own runner, report, watcher, timeline and Problems batch. The
// views and the status bar show the *active* project: the one holding the active editor's file, else the one last
// chosen (Bio-STEWARD: Select Project…), else the first. With no folder holding steward.toml, the first folder is
// the one project, so the CLI's own "not set up" answer is shown, as before.
import { lstat } from 'node:fs/promises';
import { join } from 'node:path';
import * as vscode from 'vscode';
import { isWithin } from './cli/paths';

export interface Folder {
  readonly uri: vscode.Uri;
  readonly name: string;
}

export async function canInitialize(root: string): Promise<boolean> {
  try {
    await lstat(join(root, 'steward.toml'));
    return false;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'ENOENT';
  }
}

export function localFolders(folders: readonly Folder[]): Folder[] {
  return folders.filter(({ uri }) => uri.scheme === 'file' || uri.scheme === 'vscode-remote');
}

// The folders that are projects, in workspace order.
export async function projectFolders(folders: readonly Folder[]): Promise<Folder[]> {
  const local = localFolders(folders);
  const projects: Folder[] = [];
  for (const folder of local) {
    try {
      if ((await lstat(join(folder.uri.fsPath, 'steward.toml'))).isFile()) projects.push(folder);
    } catch {
      // Not a project folder.
    }
  }
  return projects.length ? projects : local.slice(0, 1);
}

// The project whose root holds `path`; the deepest root wins when roots are nested.
export function projectFor<T extends { readonly root: string }>(projects: readonly T[], path: string): T | undefined {
  let best: T | undefined;
  for (const project of projects) {
    if (isWithin(project.root, path) && (!best || project.root.length > best.root.length)) best = project;
  }
  return best;
}

export class ActiveProject<T extends { readonly root: string }> implements vscode.Disposable {
  #active: T | undefined;
  readonly #changed = new vscode.EventEmitter<T>();
  readonly onDidChange = this.#changed.event;

  constructor(readonly projects: readonly T[]) {
    this.#active = projects[0];
  }

  get active(): T | undefined {
    return this.#active;
  }

  select(project: T | undefined): void {
    if (!project || project === this.#active || !this.projects.includes(project)) return;
    this.#active = project;
    this.#changed.fire(project);
  }

  // Follow the active editor (AC-1.4): a file in a project makes that project active; anything else keeps it.
  follow(uri: vscode.Uri | undefined): void {
    if (!uri || uri.scheme !== 'file') return;
    this.select(projectFor(this.projects, uri.fsPath));
  }

  dispose(): void {
    this.#changed.dispose();
  }
}
