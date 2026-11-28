// Agent Skills (S7): the view (folder listing and R-60 drift) and Install Agent Skills… (`steward init --skills
// DIR … --kits …`, previewed with `--dry-run`, confirmed with the exact command line, never overwriting).
//
// CLI 0.20.6 has no skills inventory (C8), so the folders are listed from disk: only the folders R-60 names and the
// known harness folders (PERF-7), each confined to the project (T5). Nothing here edits a file; installing is the
// CLI's `init`, which never overwrites and never edits steward.toml.
import { lstat, realpath } from 'node:fs/promises';
import { resolve } from 'node:path';
import * as vscode from 'vscode';
import { skillsInstallCommands, type SkillsInstallOptions } from '../cli/commands';
import {
  normalisePath, planLines, printedSkillsTable, skillFolders, skillsNodes, skillsResult, type FolderListing,
} from '../model/skills';
import type { ViewNode } from '../model/views';
import type { Project } from '../project';
import { canInitialize } from '../projects';
import { listSkillFolders, skillsPlanBlock } from '../skillFolders';
import { escapeHtml } from './explain';
import { NodeTree } from './tree';

export const SKILLS_VIEW = 'bioSteward.skills';
export const INSTALL_SKILLS_COMMAND = 'bioSteward.installSkills';
export const APPLY_SKILLS_COMMAND = 'bioSteward.applySkillsInstall';
export const CHECK_SKILLS_COMMAND = 'bioSteward.checkSkills';
export const REFRESH_SKILLS_COMMAND = 'bioSteward.refreshSkills';

const KITS = ['core', 'paper', 'talk'] as const;

export class SkillsView implements vscode.Disposable {
  readonly tree = new NodeTree();
  readonly #view: vscode.TreeView<ViewNode>;
  #generation = 0;
  #last: Project | undefined;

  constructor() {
    this.#view = vscode.window.createTreeView(SKILLS_VIEW, { treeDataProvider: this.tree, showCollapseAll: true });
  }

  // Resolves once the tree shows the newest update: when a later update supersedes this one while the folders are
  // listed, it waits for that one too, so a caller never reads the tree of an older update (T11-06).
  update(project: Project | undefined, description?: string): Promise<void> {
    const generation = ++this.#generation;
    const render = this.#render(generation, project, description);
    this.#latest = render;
    const settle = async (): Promise<void> => {
      let current = render;
      await current;
      while (this.#latest !== current) {
        current = this.#latest;
        await current;
      }
    };
    return settle();
  }

  #latest: Promise<void> = Promise.resolve();

  // How many times the tree was set (for the tests).
  renders = 0;

  async #render(generation: number, project: Project | undefined, description?: string): Promise<void> {
    this.#last = project;
    this.#view.description = description;
    if (!project?.state.trusted) {
      this.tree.set([]);
      this.renders++;
      return;
    }
    const { state } = project;
    let listings: FolderListing[] = [];
    try {
      listings = await listSkillFolders(project.root, skillFolders(skillsResult(state)?.result));
    } catch {
      // The project folder itself is unreadable: no folders to show.
    }
    if (generation === this.#generation) {
      this.tree.set(skillsNodes(state, listings), project.root);
      this.renders++;
    }
  }

  refresh(): Promise<void> {
    return this.update(this.#last, this.#view.description);
  }

  dispose(): void {
    this.#generation++;
    this.#view.dispose();
    this.tree.dispose();
  }
}

// ── Install Agent Skills… ──────────────────────────────────────────────────────────────────────────────────────

function validFolder(value: string): string | undefined {
  const path = normalisePath(value.trim());
  if (!path || path === '.' || path.startsWith('-') || path.startsWith('/') || /^[A-Za-z]:/.test(path) ||
      path.split('/').some((part) => part === '..' || part === '') || /[\0\r\n]/.test(path)) {
    return undefined;
  }
  return path;
}

export async function pickSkillsInstall(project: Project): Promise<SkillsInstallOptions | undefined> {
  const named = skillFolders(skillsResult(project.state)?.result);
  const exists = async (path: string) => lstat(resolve(project.root, path)).then(() => true, () => false);
  const items = await Promise.all(named.map(async (folder) => ({
    label: folder.path,
    description: [folder.role === 'found' ? undefined : `${folder.role} in [skills]`,
      await exists(folder.path) ? 'exists' : undefined].filter(Boolean).join(' · ') || undefined,
    picked: folder.role === 'canonical',
  })));
  const other = { label: 'Another folder…', description: 'a folder inside the project', picked: false };
  const selected = await vscode.window.showQuickPick([...items, other], {
    title: 'Bio-STEWARD: Agent Skills folders', canPickMany: true,
    placeHolder: 'Select the harness folders to receive the skills',
  });
  if (!selected?.length) return;
  const skills = selected.filter((item) => item !== other).map(({ label }) => label);
  if (selected.includes(other)) {
    const typed = await vscode.window.showInputBox({
      title: 'Bio-STEWARD: Skills folder', prompt: 'A folder inside the project, such as .agents/skills',
      validateInput: (value) => validFolder(value) ? undefined : 'Enter a relative folder inside the project.',
    });
    const path = typed === undefined ? undefined : validFolder(typed);
    if (!path) return;
    if (!skills.includes(path)) skills.push(path);
  }
  if (skills.length > 1) {
    const primary = await vscode.window.showQuickPick(skills.map((label) => ({ label })), {
      title: 'Bio-STEWARD: Primary skills folder', placeHolder: 'This folder holds the skills. The other folders link to it.',
    });
    if (!primary) return;
    skills.splice(skills.indexOf(primary.label), 1);
    skills.unshift(primary.label);
  }
  const kits = await vscode.window.showQuickPick(KITS.map((label) => ({ label })), {
    title: 'Bio-STEWARD: Skill kits', canPickMany: true, placeHolder: 'Select kits, or continue with the CLI default (core)',
  });
  if (!kits) return;
  return { skills, kits: kits.map(({ label }) => label) };
}

export function shellLine(cli: string, args: readonly string[]): string {
  return [cli, ...args].map((part) => /^[\w./:=,-]+$/.test(part) ? part : "'" + part.replaceAll("'", "'\\''") + "'").join(' ');
}

export function skillsPreviewHtml(stdout: string, blocked: string | undefined): string {
  const updates = planLines(stdout).filter((line) => line.action === 'would update').map((line) => line.path);
  const table = printedSkillsTable(stdout);
  const notes = [
    ...(updates.length ? [`This plan also updates: ${updates.join(', ')} (as the CLI lists it below).`] : []),
    ...(table ? ['steward.toml is never edited. After installing, add the [skills] table the CLI prints, so R-60 can check drift.'] : []),
  ];
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'">
<title>Bio-STEWARD Skills Preview</title>
</head>
<body>
<h1>Install Agent Skills: preview</h1>
${blocked ? `<p>${escapeHtml(blocked)}</p>` : `<p><a href="command:${APPLY_SKILLS_COMMAND}">Review command and confirm…</a></p>`}
${notes.map((note) => `<p>${escapeHtml(note)}</p>`).join('\n')}
<pre><span>${escapeHtml(stdout)}</span></pre>
</body>
</html>`;
}

type Confirm = (cli: string, args: readonly string[]) => Promise<boolean>;

async function confirmInstall(cli: string, args: readonly string[]): Promise<boolean> {
  const answer = await vscode.window.showWarningMessage('Install Agent Skills into this project?', {
    modal: true, detail: shellLine(cli, args),
  }, 'Install');
  return answer === 'Install';
}

interface Preview {
  project: Project;
  root: string;
  commands: ReturnType<typeof skillsInstallCommands>;
  stdout: string;
  blocked?: string;
}

export class SkillsInstall implements vscode.Disposable {
  #panel: vscode.WebviewPanel | undefined;
  #preview: Preview | undefined;
  #applying = false;

  // Called after a successful install with the CLI's output.
  constructor(private readonly onInstalled: (project: Project, stdout: string) => Promise<void>) {}

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

  async preview(project: Project, options: SkillsInstallOptions): Promise<boolean> {
    if (this.#applying || !project.state.trusted) return false;
    this.dispose();
    if (await canInitialize(project.root)) {
      void vscode.window.showWarningMessage('Bio-STEWARD: This folder has no steward.toml. Run Initialize Project… first.');
      return false;
    }
    const root = await realpath(project.root);
    const commands = skillsInstallCommands(options);
    const result = await project.runInit(commands.preview);
    if (result.kind !== 'completed' || result.exitCode !== 0) {
      void vscode.window.showWarningMessage('Bio-STEWARD: Could not preview the skills install. See the Bio-STEWARD log.');
      return false;
    }
    const blocked = await skillsPlanBlock(root, result.stdout);
    const panel = vscode.window.createWebviewPanel('bioSteward.skillsPreview', 'Bio-STEWARD: Skills Preview', vscode.ViewColumn.Active, {
      enableCommandUris: [APPLY_SKILLS_COMMAND], enableScripts: false, localResourceRoots: [],
    });
    this.#panel = panel;
    this.#preview = { project, root, commands, stdout: result.stdout, blocked };
    panel.onDidDispose(() => {
      if (this.#panel === panel) {
        this.#panel = undefined;
        this.#preview = undefined;
      }
    });
    panel.webview.html = skillsPreviewHtml(result.stdout, blocked);
    return true;
  }

  async apply(confirm: Confirm = confirmInstall): Promise<boolean> {
    const preview = this.#preview;
    if (!preview || preview.blocked || this.#applying) return false;
    this.#applying = true;
    const { project, root, commands, stdout } = preview;
    try {
      let changed = false;
      const result = await project.runInit(commands.apply, { confirm: async (cli, args) => {
        if (!await confirm(cli, args) || this.#preview !== preview) return false;
        // The plan is made again after the confirmation: what runs is what was shown.
        const latest = await project.runInit(commands.preview, { recheck: true });
        changed = latest.kind !== 'completed' || latest.exitCode !== 0 || latest.stdout !== stdout ||
          Boolean(await skillsPlanBlock(root, stdout));
        return !changed && this.#preview === preview;
      } });
      if (changed) {
        this.dispose();
        void vscode.window.showWarningMessage('Bio-STEWARD: The skills plan changed. Run Install Agent Skills… again to review it.');
        return false;
      }
      if (result.kind === 'unconfirmed' || result.kind === 'cancelled') return false;
      if (result.kind !== 'completed' || result.exitCode !== 0) {
        this.dispose();
        void vscode.window.showWarningMessage('Bio-STEWARD: The skills install did not finish. See the Bio-STEWARD log.');
        return false;
      }
      this.dispose();
      await this.onInstalled(project, result.stdout);
      return true;
    } finally {
      this.#applying = false;
    }
  }

  dispose(): void {
    this.#panel?.dispose();
    this.#panel = undefined;
    this.#preview = undefined;
  }
}
