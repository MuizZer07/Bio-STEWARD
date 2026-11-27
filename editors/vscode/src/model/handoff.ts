// Where the session handoff is (S4): the `[session] handoff` setting of steward.toml, default
// `development/HANDOFF.md` (CLI 0.20.6, `SessionSection`). Pure: no `vscode` import.
//
// The extension has no TOML parser (one runtime dependency, design v0.1 §4.2). This reader understands the forms a
// person writes for this one key: a `[session]` table, or a dotted `session.handoff` key at the top level, with a
// basic ("…") or literal ('…') one-line string. Anything else that names the key (an inline table, a multi-line
// string, a duplicate) is "unreadable", never a guess.

export const DEFAULT_HANDOFF = 'development/HANDOFF.md';

export type HandoffSetting =
  | { readonly kind: 'path'; readonly path: string; readonly configured: boolean }
  | { readonly kind: 'unreadable'; readonly reason: string };

const BARE_KEY = /^[A-Za-z0-9_-]+$/;

// A dotted TOML key ("session", "session.handoff", `"session" . handoff`) as parts; undefined if not simple.
function keyParts(raw: string): string[] | undefined {
  const parts: string[] = [];
  for (const part of raw.split('.')) {
    const trimmed = part.trim();
    const quoted = /^"([A-Za-z0-9_-]+)"$|^'([A-Za-z0-9_-]+)'$/.exec(trimmed);
    if (quoted) parts.push(quoted[1] ?? quoted[2]);
    else if (BARE_KEY.test(trimmed)) parts.push(trimmed);
    else return undefined;
  }
  return parts;
}

const ESCAPES: Readonly<Record<string, string>> = Object.freeze({
  b: '\b', t: '\t', n: '\n', f: '\f', r: '\r', '"': '"', '\\': '\\',
});

// One string value followed by an optional comment; undefined when it is not one.
function stringValue(raw: string): string | undefined {
  const text = raw.trim();
  if (text.startsWith('"""') || text.startsWith("'''")) return undefined;
  if (text.startsWith("'")) {
    const end = text.indexOf("'", 1);
    if (end < 0 || !/^\s*(#.*)?$/.test(text.slice(end + 1))) return undefined;
    return text.slice(1, end);
  }
  if (!text.startsWith('"')) return undefined;
  let out = '';
  for (let i = 1; i < text.length; i++) {
    const char = text[i];
    if (char === '"') return /^\s*(#.*)?$/.test(text.slice(i + 1)) ? out : undefined;
    if (char !== '\\') {
      out += char;
      continue;
    }
    const next = text[++i];
    if (next === 'u' || next === 'U') {
      const length = next === 'u' ? 4 : 8;
      const hex = text.slice(i + 1, i + 1 + length);
      if (!new RegExp(`^[0-9A-Fa-f]{${length}}$`).test(hex)) return undefined;
      const code = parseInt(hex, 16);
      if (code > 0x10ffff) return undefined;
      out += String.fromCodePoint(code);
      i += length;
    } else if (next !== undefined && next in ESCAPES) {
      out += ESCAPES[next];
    } else {
      return undefined;
    }
  }
  return undefined;
}

export function handoffSetting(toml: string): HandoffSetting {
  let table: string[] = [];
  let found: string | undefined;
  for (const line of toml.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    if (trimmed.startsWith('[')) {
      const header = /^\[\s*([^[\]]+?)\s*\]\s*(#.*)?$/.exec(trimmed);
      // `[[session]]` (an array of tables) is not a form the CLI accepts; any other table is left alone.
      table = header ? keyParts(header[1]) ?? ['?'] : ['?'];
      if (/^\[\[\s*session\s*\]\]/.test(trimmed)) return { kind: 'unreadable', reason: 'session is an array of tables' };
      continue;
    }
    const equals = line.indexOf('=');
    if (equals < 0) continue;
    const key = keyParts(line.slice(0, equals));
    if (!key) continue;
    const full = [...table, ...key];
    if (full[0] !== 'session') continue;
    if (full.length === 1) return { kind: 'unreadable', reason: 'session is not a table' };
    if (full[1] !== 'handoff') continue;
    if (full.length !== 2) return { kind: 'unreadable', reason: 'session.handoff is not a string' };
    const value = stringValue(line.slice(equals + 1));
    if (value === undefined) return { kind: 'unreadable', reason: 'session.handoff is not a one-line string' };
    if (found !== undefined) return { kind: 'unreadable', reason: 'session.handoff is set twice' };
    found = value;
  }
  return found === undefined
    ? { kind: 'path', path: DEFAULT_HANDOFF, configured: false }
    : { kind: 'path', path: found, configured: true };
}
