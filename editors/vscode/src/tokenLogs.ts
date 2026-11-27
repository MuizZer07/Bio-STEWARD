// P4 Tokens: the agent log files the extension passes to `steward tokens report`, from three machine settings
// (`bioSteward.tokens.claudeLogs`, `…codexLogs`, `…geminiLogs`). Without `vscode`, so the unit tests run it on
// real folders.
//
// Each entry is an absolute path: a log file, or a folder whose `.jsonl` and `.json` files (down to MAX_DEPTH
// folders below it) are taken, newest first, at most MAX_LOG_FILES per agent. Links are not followed inside a
// folder. Nothing is opened here: the CLI reads the files. Entries that give no file are named, not dropped silently.
//
// Each file keeps its boundary: the canonical file or folder the setting named (U09). The runner checks again, just
// before the CLI starts, that the file is still inside it and reached without a link (src/cli/paths.ts
// `boundedLog`), so a file or folder replaced after the selection cannot redirect the read.
import { lstat, readdir, realpath, stat } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import { TOKEN_AGENTS, type LogSelection, type TokenAgent } from './model/tokens';

export const MAX_LOG_FILES = 50;
const MAX_DEPTH = 3;
const MAX_WALKED = 20_000;

async function folderLogs(folder: string): Promise<{ path: string; mtime: number }[]> {
  const out: { path: string; mtime: number }[] = [];
  const stack: { path: string; depth: number }[] = [{ path: folder, depth: 0 }];
  let budget = MAX_WALKED;
  while (stack.length && budget > 0) {
    const { path, depth } = stack.pop()!;
    const entries = await readdir(path, { withFileTypes: true }).catch(() => []);
    for (const entry of entries) {
      if (--budget <= 0) break;
      const child = join(path, entry.name);
      if (entry.isDirectory() && depth < MAX_DEPTH) stack.push({ path: child, depth: depth + 1 });
      else if (entry.isFile() && /\.jsonl?$/.test(entry.name)) {
        const info = await lstat(child).catch(() => undefined);
        if (info?.isFile()) out.push({ path: child, mtime: info.mtimeMs });
      }
    }
  }
  return out;
}

export async function selectLogs(settings: Readonly<Record<TokenAgent, readonly unknown[] | undefined>>): Promise<LogSelection> {
  const files: Record<TokenAgent, string[]> = { claude: [], codex: [], gemini: [] };
  const problems: string[] = [];
  const capped: Partial<Record<TokenAgent, number>> = {};
  const boundaries: Record<string, string> = {};
  for (const agent of TOKEN_AGENTS) {
    const found: { path: string; mtime: number; boundary: string }[] = [];
    for (const entry of settings[agent] ?? []) {
      if (typeof entry !== 'string' || !entry.trim()) continue;
      if (!isAbsolute(entry) || entry.includes('\0')) {
        problems.push(`${agent}: not an absolute path: ${entry}`);
        continue;
      }
      const resolved = await realpath(entry).catch(() => undefined);
      const info = resolved && await stat(resolved).catch(() => undefined);
      if (!resolved || !info) problems.push(`${agent}: not found: ${entry}`);
      else if (info.isFile()) found.push({ path: resolved, mtime: info.mtimeMs, boundary: resolved });
      else if (info.isDirectory()) {
        const logs = await folderLogs(resolved);
        if (!logs.length) problems.push(`${agent}: no .jsonl or .json files in ${entry}`);
        found.push(...logs.map((log) => ({ ...log, boundary: resolved })));
      } else problems.push(`${agent}: not a file or folder: ${entry}`);
    }
    const unique = [...new Map(found.map((file) => [file.path, file])).values()]
      .sort((a, b) => b.mtime - a.mtime || (a.path < b.path ? -1 : 1));
    files[agent] = unique.slice(0, MAX_LOG_FILES).map((file) => file.path);
    for (const file of unique.slice(0, MAX_LOG_FILES)) boundaries[file.path] ??= file.boundary;
    if (unique.length > MAX_LOG_FILES) capped[agent] = unique.length - MAX_LOG_FILES;
  }
  return { files, problems, capped, boundaries };
}
