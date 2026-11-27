// A small, strict TOML 1.0 reader for the sprint file (S9; `development/sprints/<id>.toml`, schema
// steward.sprint/0.1). Written for this extension so it keeps one runtime dependency; it reads the whole
// TOML 1.0 syntax a sprint file can use (tables, arrays of tables, dotted and quoted keys, the four string forms,
// integers, floats, booleans, date-times, arrays and inline tables) and throws `TomlError` on anything else,
// so the view shows the sprint file as unreadable instead of guessing.
//
// Deliberate limits beyond TOML 1.0 (T12, T11-03): arrays and inline tables nest at most MAX_TOML_DEPTH deep, and
// a key has at most MAX_KEY_PARTS dotted parts. A file past either limit is unreadable, never half-read.
// Integers are read as JavaScript numbers; `isFloat` tells which values were written as floats.

export const MAX_TOML_DEPTH = 32;
export const MAX_KEY_PARTS = 32;

export class TomlError extends Error {
  constructor(message: string, readonly line: number) {
    super(`line ${line}: ${message}`);
  }
}

// A date-time, kept as written; `epochMs` is set only for an offset date-time (one that names its zone).
export class TomlDateTime {
  readonly epochMs: number | undefined;

  constructor(readonly text: string) {
    const offset = /[zZ]|[+-]\d{2}:\d{2}$/.test(text) && /^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}/.test(text);
    const ms = offset ? Date.parse(text.replace(' ', 'T')) : NaN;
    this.epochMs = Number.isFinite(ms) ? ms : undefined;
  }
}

export type TomlValue = string | number | boolean | TomlDateTime | TomlValue[] | TomlTable;
export interface TomlTable {
  [key: string]: TomlValue;
}

const BARE_KEY = /[A-Za-z0-9_-]+/y;
const DATETIME = /(\d{4})-(\d{2})-(\d{2})(?:[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:[zZ]|[+-](\d{2}):(\d{2}))?)?|(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?/y;
const NUMBER = /[+-]?(?:inf|nan)|0x[0-9A-Fa-f](?:_?[0-9A-Fa-f])*|0o[0-7](?:_?[0-7])*|0b[01](?:_?[01])*|[+-]?(?:0|[1-9](?:_?\d)*)(?:\.\d(?:_?\d)*)?(?:[eE][+-]?\d(?:_?\d)*)?/y;
const LINE_END_BACKSLASH = /\\[ \t]*\r?\n/y;

// Tables made by a header or a dotted key may not be redefined; inline tables and arrays are closed.
const defined = new WeakSet<object>();
const closed = new WeakSet<object>();
const implicit = new WeakSet<object>();
// Tables made or extended by a dotted key (`a.b = 1`): a later `[a]` header may not define them (TOML 1.0).
const dotted = new WeakSet<object>();
const floats = new WeakMap<object, Set<string>>();

// Whether `table[key]` was written as a float (`2.0`, `1e3`, `inf`), not an integer.
export function isFloat(table: TomlTable, key: string): boolean {
  return floats.get(table)?.has(key) ?? false;
}

export function parseToml(text: string): TomlTable {
  return new Reader(text).document();
}

function sticky(pattern: RegExp, src: string, at: number): RegExpExecArray | null {
  pattern.lastIndex = at;
  return pattern.exec(src);
}

const DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const leap = (y: number) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;

// RFC 3339 / TOML 1.0 calendar and clock ranges (as Python's datetime, which the CLI's tomllib uses).
function validDateTime(m: RegExpExecArray): boolean {
  const n = (i: number) => (m[i] === undefined ? undefined : Number(m[i]));
  const [year, month, day, hour, minute, second, offH, offM, tH, tM, tS] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map(n);
  if (year !== undefined) {
    if (month! < 1 || month! > 12 || day! < 1) return false;
    if (day! > (month === 2 && leap(year) ? 29 : DAYS[month! - 1])) return false;
  }
  const clock = (h?: number, mi?: number, s?: number) => h === undefined || (h < 24 && mi! < 60 && s! < 60);
  return clock(hour, minute, second) && clock(tH, tM, tS) && (offH === undefined || (offH < 24 && offM! < 60));
}

class Reader {
  #i = 0;
  #depth = 0;
  #float = false;
  readonly root: TomlTable = Object.create(null) as TomlTable;
  readonly #arrays = new WeakSet<object>();

  constructor(private readonly src: string) {}

  get #line(): number {
    let n = 1;
    for (let j = 0; j < this.#i && j < this.src.length; j++) if (this.src[j] === '\n') n++;
    return n;
  }

  #fail(message: string): never {
    throw new TomlError(message, this.#line);
  }

  #peek(n = 0): string {
    return this.src[this.#i + n] ?? '';
  }

  #startsWith(s: string): boolean {
    return this.src.startsWith(s, this.#i);
  }

  #spaces(): void {
    while (this.#peek() === ' ' || this.#peek() === '\t') this.#i++;
  }

  #comment(): void {
    if (this.#peek() !== '#') return;
    while (this.#i < this.src.length && this.#peek() !== '\n') {
      const c = this.src.charCodeAt(this.#i);
      if ((c < 0x20 && c !== 0x09 && c !== 0x0d) || c === 0x7f) this.#fail('control character in a comment');
      this.#i++;
    }
  }

  // The end of a line: spaces, an optional comment, then a newline or the end of the text.
  #endOfLine(): void {
    this.#spaces();
    this.#comment();
    if (this.#startsWith('\r\n')) this.#i += 2;
    else if (this.#peek() === '\n') this.#i++;
    else if (this.#i < this.src.length) this.#fail('expected the end of the line');
  }

  // Blank lines, comments and newlines (inside arrays).
  #blank(): void {
    for (;;) {
      this.#spaces();
      this.#comment();
      if (this.#startsWith('\r\n')) this.#i += 2;
      else if (this.#peek() === '\n') this.#i++;
      else return;
    }
  }

  document(): TomlTable {
    let table = this.root;
    for (;;) {
      this.#blank();
      if (this.#i >= this.src.length) return this.root;
      if (this.#startsWith('[[')) {
        this.#i += 2;
        const key = this.#key();
        this.#spaces();
        if (!this.#startsWith(']]')) this.#fail('expected ]]');
        this.#i += 2;
        table = this.#arrayTable(key);
      } else if (this.#peek() === '[') {
        this.#i++;
        const key = this.#key();
        this.#spaces();
        if (this.#peek() !== ']') this.#fail('expected ]');
        this.#i++;
        table = this.#headerTable(key);
      } else {
        this.#keyValue(table);
      }
      this.#endOfLine();
    }
  }

  #key(): string[] {
    const parts: string[] = [];
    for (;;) {
      if (parts.length >= MAX_KEY_PARTS) this.#fail(`a key with more than ${MAX_KEY_PARTS} parts`);
      this.#spaces();
      const c = this.#peek();
      if (c === '"') parts.push(this.#basicString());
      else if (c === "'") parts.push(this.#literalString());
      else {
        const m = sticky(BARE_KEY, this.src, this.#i);
        if (!m) this.#fail('expected a key');
        parts.push(m[0]);
        this.#i += m[0].length;
      }
      this.#spaces();
      if (this.#peek() !== '.') return parts;
      this.#i++;
    }
  }

  #child(table: TomlTable, key: string): TomlTable {
    if (!Object.prototype.hasOwnProperty.call(table, key)) {
      const made = Object.create(null) as TomlTable;
      implicit.add(made);
      table[key] = made;
      return made;
    }
    const value = table[key];
    if (Array.isArray(value) && this.#arrays.has(value)) {
      const last = value[value.length - 1];
      if (last && typeof last === 'object' && !Array.isArray(last) && !(last instanceof TomlDateTime)) return last;
    }
    if (value && typeof value === 'object' && !Array.isArray(value) && !(value instanceof TomlDateTime) && !closed.has(value)) {
      return value;
    }
    return this.#fail(`key "${key}" is already a value`);
  }

  #headerTable(key: string[]): TomlTable {
    let table = this.root;
    for (const part of key.slice(0, -1)) table = this.#child(table, part);
    const last = key[key.length - 1];
    const existing = Object.prototype.hasOwnProperty.call(table, last) ? table[last] : undefined;
    if (existing !== undefined) {
      if (typeof existing !== 'object' || Array.isArray(existing) || existing instanceof TomlDateTime ||
          closed.has(existing) || defined.has(existing) || dotted.has(existing) || !implicit.has(existing)) {
        this.#fail(`table [${key.join('.')}] is defined twice`);
      }
      implicit.delete(existing);
      defined.add(existing);
      return existing;
    }
    const made = Object.create(null) as TomlTable;
    defined.add(made);
    table[last] = made;
    return made;
  }

  #arrayTable(key: string[]): TomlTable {
    let table = this.root;
    for (const part of key.slice(0, -1)) table = this.#child(table, part);
    const last = key[key.length - 1];
    let array = Object.prototype.hasOwnProperty.call(table, last) ? table[last] : undefined;
    if (array === undefined) {
      array = [];
      this.#arrays.add(array);
      table[last] = array;
    } else if (!Array.isArray(array) || !this.#arrays.has(array)) {
      this.#fail(`[[${key.join('.')}]] is already a value`);
    }
    const made = Object.create(null) as TomlTable;
    defined.add(made);
    array.push(made);
    return made;
  }

  #keyValue(table: TomlTable): void {
    const key = this.#key();
    if (this.#peek() !== '=') this.#fail('expected =');
    this.#i++;
    this.#spaces();
    this.#float = false;
    const value = this.#value();
    const float = this.#float;
    let target = table;
    for (const part of key.slice(0, -1)) {
      target = this.#child(target, part);
      if (defined.has(target) && target !== table && !implicit.has(target)) this.#fail(`key "${part}" is a table defined elsewhere`);
      dotted.add(target);
    }
    const last = key[key.length - 1];
    if (Object.prototype.hasOwnProperty.call(target, last)) this.#fail(`key "${key.join('.')}" is defined twice`);
    target[last] = value;
    if (float) {
      const set = floats.get(target) ?? new Set<string>();
      set.add(last);
      floats.set(target, set);
    }
  }

  #value(): TomlValue {
    const c = this.#peek();
    if (this.#startsWith('"""')) return this.#multiBasic();
    if (this.#startsWith("'''")) return this.#multiLiteral();
    if (c === '"') return this.#basicString();
    if (c === "'") return this.#literalString();
    if (c === '[' || c === '{') {
      if (++this.#depth > MAX_TOML_DEPTH) this.#fail(`arrays or inline tables nested more than ${MAX_TOML_DEPTH} deep`);
      try {
        return c === '[' ? this.#array() : this.#inlineTable();
      } finally {
        this.#depth--;
      }
    }
    if (this.#startsWith('true')) {
      this.#i += 4;
      return true;
    }
    if (this.#startsWith('false')) {
      this.#i += 5;
      return false;
    }
    const date = sticky(DATETIME, this.src, this.#i);
    if (date) {
      if (!validDateTime(date)) this.#fail(`invalid date or time ${date[0]}`);
      this.#i += date[0].length;
      return new TomlDateTime(date[0]);
    }
    const num = sticky(NUMBER, this.src, this.#i);
    if (num) {
      this.#i += num[0].length;
      const text = num[0].replace(/_/g, '');
      this.#float = !/^0[xob]/.test(text) && /[.eEn]/.test(text);
      return numberOf(text);
    }
    return this.#fail('expected a value');
  }

  #escape(): string {
    const c = this.#peek();
    this.#i++;
    const simple: Record<string, string> = { b: '\b', t: '\t', n: '\n', f: '\f', r: '\r', '"': '"', '\\': '\\' };
    if (c in simple) return simple[c];
    if (c === 'u' || c === 'U') {
      const n = c === 'u' ? 4 : 8;
      const hex = this.src.slice(this.#i, this.#i + n);
      if (!new RegExp(`^[0-9A-Fa-f]{${n}}$`).test(hex)) this.#fail('bad unicode escape');
      this.#i += n;
      const code = parseInt(hex, 16);
      if (code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) this.#fail('bad unicode escape');
      return String.fromCodePoint(code);
    }
    return this.#fail('bad escape');
  }

  #control(c: string, multiline: boolean): void {
    const code = c.charCodeAt(0);
    if ((code < 0x20 && code !== 0x09 && !(multiline && (code === 0x0a || code === 0x0d))) || code === 0x7f) {
      this.#fail('control character in a string');
    }
  }

  #basicString(): string {
    this.#i++;
    let out = '';
    for (;;) {
      if (this.#i >= this.src.length) this.#fail('unterminated string');
      const c = this.#peek();
      if (c === '"') {
        this.#i++;
        return out;
      }
      if (c === '\n') this.#fail('newline in a string');
      if (c === '\\') {
        this.#i++;
        out += this.#escape();
        continue;
      }
      this.#control(c, false);
      out += c;
      this.#i++;
    }
  }

  #literalString(): string {
    this.#i++;
    const end = this.src.indexOf("'", this.#i);
    const newline = this.src.indexOf('\n', this.#i);
    if (end < 0 || (newline >= 0 && newline < end)) this.#fail('unterminated string');
    const out = this.src.slice(this.#i, end);
    for (const c of out) this.#control(c, false);
    this.#i = end + 1;
    return out;
  }

  #trimFirstNewline(): void {
    if (this.#startsWith('\r\n')) this.#i += 2;
    else if (this.#peek() === '\n') this.#i++;
  }

  // Up to two quotes directly before the closing delimiter belong to the string.
  #closing(quote: string): number {
    let extra = 0;
    while (extra < 2 && this.src.startsWith(quote.repeat(3), this.#i + extra + 1)) extra++;
    return extra;
  }

  #multiBasic(): string {
    this.#i += 3;
    this.#trimFirstNewline();
    let out = '';
    for (;;) {
      if (this.#i >= this.src.length) this.#fail('unterminated string');
      if (this.#startsWith('"""')) {
        const extra = this.#closing('"');
        out += '"'.repeat(extra);
        this.#i += 3 + extra;
        return out;
      }
      const c = this.#peek();
      if (c === '\\') {
        // A line-ending backslash trims the newline and the whitespace that follows.
        const after = sticky(LINE_END_BACKSLASH, this.src, this.#i);
        if (after) {
          this.#i += after[0].length;
          while (/[ \t\r\n]/.test(this.#peek()) && this.#i < this.src.length) this.#i++;
          continue;
        }
        this.#i++;
        out += this.#escape();
        continue;
      }
      this.#control(c, true);
      out += c;
      this.#i++;
    }
  }

  #multiLiteral(): string {
    this.#i += 3;
    this.#trimFirstNewline();
    const end = this.src.indexOf("'''", this.#i);
    if (end < 0) this.#fail('unterminated string');
    const start = this.#i;
    this.#i = end;
    const extra = this.#closing("'");
    const out = this.src.slice(start, end + extra);
    for (const c of out) this.#control(c, true);
    this.#i = end + 3 + extra;
    return out;
  }

  #array(): TomlValue[] {
    this.#i++;
    const out: TomlValue[] = [];
    for (;;) {
      this.#blank();
      if (this.#peek() === ']') {
        this.#i++;
        break;
      }
      out.push(this.#value());
      this.#blank();
      if (this.#peek() === ',') {
        this.#i++;
        continue;
      }
      if (this.#peek() !== ']') this.#fail('expected , or ] in an array');
      this.#i++;
      break;
    }
    closed.add(out);
    return out;
  }

  // Closed as it is read (no second walk): every table made inside it is collected in `made`.
  #inlineTable(): TomlTable {
    this.#i++;
    const table = Object.create(null) as TomlTable;
    this.#spaces();
    if (this.#peek() === '}') {
      this.#i++;
      closed.add(table);
      return table;
    }
    for (;;) {
      this.#keyValue(table);
      this.#spaces();
      if (this.#peek() === ',') {
        this.#i++;
        this.#spaces();
        if (this.#peek() === '}') this.#fail('a trailing comma in an inline table');
        continue;
      }
      if (this.#peek() !== '}') this.#fail('expected , or } in an inline table');
      this.#i++;
      break;
    }
    // Dotted keys inside it made sub-tables (`{ h.i = 1 }`); those are closed too. Values that are themselves
    // inline tables were closed when they were read.
    const stack: TomlTable[] = [table];
    while (stack.length) {
      const t = stack.pop()!;
      if (closed.has(t)) continue;
      closed.add(t);
      for (const v of Object.values(t)) {
        if (v && typeof v === 'object' && !Array.isArray(v) && !(v instanceof TomlDateTime) && !closed.has(v)) stack.push(v);
      }
    }
    return table;
  }
}

function numberOf(t: string): number {
  if (/^[+-]?inf$/.test(t)) return t.startsWith('-') ? -Infinity : Infinity;
  if (/^[+-]?nan$/.test(t)) return NaN;
  if (t.startsWith('0x')) return parseInt(t.slice(2), 16);
  if (t.startsWith('0o')) return parseInt(t.slice(2), 8);
  if (t.startsWith('0b')) return parseInt(t.slice(2), 2);
  return Number(t);
}
