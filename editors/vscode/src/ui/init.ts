import { lstat, realpath } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import * as vscode from 'vscode';
import { guidedInitCommands, type GuidedInitOptions } from '../cli/commands';
import { confinedPath } from '../cli/paths';
import { HARNESS_FOLDERS } from '../model/skills';
import type { Project } from '../project';
import { canInitialize } from '../projects';
import { escapeHtml } from './explain';

export const INIT_COMMAND = 'bioSteward.initialize';
export const INIT_WALKTHROUGH_COMMAND = 'bioSteward.openInitWalkthrough';
export const APPLY_INIT_COMMAND = 'bioSteward.applyInit';

const goals = ['reanalysis', 'benchmark', 'paper', 'agents', 'licence'] as const;
const profiles = [
  { label: 'exploratory', description: 'For early investigation and iteration.' },
  { label: 'confirmatory', description: 'For work with a predeclared plan and verification requirements.' },
] as const;
const harnesses = HARNESS_FOLDERS;
const kits = ['core', 'paper', 'talk'] as const;

export async function pickInitOptions(root: string): Promise<GuidedInitOptions | undefined> {
  const selectedGoals = await vscode.window.showQuickPick(goals.map((label) => ({ label })), {
    title: 'Bio-STEWARD: Project goals', canPickMany: true, placeHolder: 'Select any goals, or continue without a goal',
  });
  if (!selectedGoals) return;
  const profile = await vscode.window.showQuickPick(profiles, { title: 'Bio-STEWARD: Project profile' });
  if (!profile) return;

  const candidates = await Promise.all(harnesses.map(async (label) => {
    const detected = await lstat(join(root, label, '..')).then((entry) => entry.isDirectory(), () => false);
    return { label, description: detected ? 'Harness folder detected' : undefined };
  }));
  const selected = await vscode.window.showQuickPick(candidates, {
    title: 'Bio-STEWARD: Agent Skills folders', canPickMany: true, placeHolder: 'Select folders, or continue without skills',
  });
  if (!selected) return;
  const skills = selected.map(({ label }) => label);
  if (skills.length > 1) {
    const primary = await vscode.window.showQuickPick(selected, {
      title: 'Bio-STEWARD: Primary skills folder', placeHolder: 'This folder holds the skills. Other selected folders link to it.',
    });
    if (!primary) return;
    skills.splice(skills.indexOf(primary.label), 1);
    skills.unshift(primary.label);
  }

  const selectedKits = skills.length ? await vscode.window.showQuickPick(kits.map((label) => ({ label })), {
    title: 'Bio-STEWARD: Skill kits', canPickMany: true, placeHolder: 'Select kits, or continue with the CLI defaults',
  }) : [];
  if (!selectedKits) return;
  return {
    goals: selectedGoals.map(({ label }) => label),
    profile: profile.label,
    skills,
    kits: selectedKits.map(({ label }) => label),
  };
}

async function initRoot(project: Project): Promise<string | undefined> {
  if (!project.state.trusted || !await canInitialize(project.root)) return;
  const root = await realpath(project.root);
  // These files can be read by the CLI even when the plan leaves them untouched.
  for (const name of ['.gitignore', 'AGENTS.md']) {
    if (!await confinedPath(root, name, true)) return;
  }
  return root;
}

async function planBlockReason(root: string, stdout: string): Promise<string | undefined> {
  if (/^would update\s/m.test(stdout)) return 'This plan would change an existing file. Guided init preserves existing files.';
  const destinations = [...stdout.matchAll(/^would create {3}(.+?)(?: {2}\(.*\))?$/gm)].map((match) => match[1]);
  if (!destinations.includes('steward.toml')) return 'The CLI did not show a plan to create steward.toml.';
  for (const path of destinations) {
    const target = resolve(root, path);
    if (await confinedPath(root, path, true) !== target) {
      return 'A planned destination is outside the project, inaccessible, or redirected through a link.';
    }
    const missing = await lstat(target).then(() => false, (error: NodeJS.ErrnoException) => error.code === 'ENOENT');
    if (!missing) return 'A planned destination already exists or is inaccessible.';
  }
  return undefined;
}

export function previewHtml(stdout: string, blocked: string | undefined): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'">
<title>Bio-STEWARD Init Preview</title>
</head>
<body>
<h1>Initialization preview</h1>
${blocked ? `<p>${escapeHtml(blocked)}</p>` : `<p><a href="command:${APPLY_INIT_COMMAND}">Review command and confirm…</a></p>`}
<pre><span>${escapeHtml(stdout)}</span></pre>
</body>
</html>`;
}

type Confirm = (cli: string, args: readonly string[]) => Promise<boolean>;

async function confirmInit(cli: string, args: readonly string[]): Promise<boolean> {
  const command = [cli, ...args].map((part) =>
    /^[\w./:=,-]+$/.test(part) ? part : "'" + part.replaceAll("'", "'\\''") + "'").join(' ');
  const answer = await vscode.window.showWarningMessage('Initialize this Bio-STEWARD project?', {
    modal: true, detail: command,
  }, 'Initialize');
  return answer === 'Initialize';
}

interface Preview {
  project: Project;
  root: string;
  commands: ReturnType<typeof guidedInitCommands>;
  stdout: string;
  blocked?: string;
}

export class InitView implements vscode.Disposable {
  #panel: vscode.WebviewPanel | undefined;
  #preview: Preview | undefined;
  #applying = false;

  constructor(private readonly onInitialized: (root: string) => Promise<void>) {}

  get html(): string | undefined {
    return this.#panel?.webview.html;
  }

  // The webview's options (D2: exactly one enabled command URI, no scripts, no local resources), for the tests.
  get webviewOptions(): vscode.WebviewOptions | undefined {
    return this.#panel?.webview.options;
  }

  get applying(): boolean {
    return this.#applying;
  }

  async preview(project: Project, options: GuidedInitOptions): Promise<void> {
    if (this.#applying) return;
    this.dispose();
    const root = await initRoot(project);
    if (!root) {
      void vscode.window.showWarningMessage('Bio-STEWARD: Select an unconfigured project folder with accessible init paths.');
      return;
    }
    const commands = guidedInitCommands(options);
    const result = await project.runInit(commands.preview);
    if (result.kind !== 'completed' || result.exitCode !== 0) {
      void vscode.window.showWarningMessage('Bio-STEWARD: Could not preview initialization. See the Bio-STEWARD log.');
      return;
    }
    const blocked = await planBlockReason(root, result.stdout);
    const panel = vscode.window.createWebviewPanel('bioSteward.initPreview', 'Bio-STEWARD: Init Preview', vscode.ViewColumn.Active, {
      enableCommandUris: [APPLY_INIT_COMMAND], enableScripts: false, localResourceRoots: [],
    });
    this.#panel = panel;
    this.#preview = { project, root, commands, stdout: result.stdout, blocked };
    panel.onDidDispose(() => {
      this.#panel = undefined;
      this.#preview = undefined;
    });
    panel.webview.html = previewHtml(result.stdout, blocked);
  }

  async apply(confirm: Confirm = confirmInit): Promise<boolean> {
    const preview = this.#preview;
    if (!preview || preview.blocked || this.#applying) return false;
    this.#applying = true;
    const { project, root, commands, stdout } = preview;
    try {
      let changed = false;
      const result = await project.runInit(commands.apply, { confirm: async (cli, args) => {
        if (!await confirm(cli, args) || this.#preview !== preview) return false;
        const currentRoot = await initRoot(project);
        const latest = currentRoot === root ? await project.runInit(commands.preview, { recheck: true }) : undefined;
        changed = latest?.kind !== 'completed' || latest.exitCode !== 0 || latest.stdout !== stdout
          || Boolean(await planBlockReason(root, stdout));
        return !changed && this.#preview === preview;
      } });
      if (changed) {
        this.dispose();
        void vscode.window.showWarningMessage('Bio-STEWARD: The initialization plan changed. Run Initialize Project again to review it.');
        return false;
      }
      if (result.kind === 'unconfirmed' || result.kind === 'cancelled') return false;
      if (result.kind !== 'completed' || result.exitCode !== 0) {
        this.dispose();
        void vscode.window.showWarningMessage('Bio-STEWARD: Initialization did not finish. See the Bio-STEWARD log.');
        return false;
      }
      this.dispose();
      await this.onInitialized(project.root);
      return true;
    } finally {
      this.#applying = false;
    }
  }

  dispose(): void {
    this.#panel?.dispose();
  }
}
