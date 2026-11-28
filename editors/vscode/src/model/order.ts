// Newest first (RELEASE_vscode_0.3.0_SPEC E01; roadmap §2 item 9): the order of every list the panels show.
//
// A list is ordered by its entries' dates, newest first, then by their IDs, highest first. IDs compare as people
// read them (`T10` after `T9`). An entry without a date comes after every dated one. This is the order CLI 0.22.0
// prints its text lists in; its versioned JSON keeps its own documented order, so the extension sorts what it shows.
// The dates and IDs are the CLI's (or a file's), never weighed: this is presentation only. Pure: no `vscode` import.

type Part = readonly [number, number, string];

// An ID's natural sort key: runs of digits compare as numbers, the rest as text.
export function idKey(value: string | undefined): readonly Part[] {
  return (String(value ?? '').match(/\d+|\D+/g) ?? []).map((part): Part => (/^\d+$/.test(part) ? [1, Number(part), ''] : [0, 0, part]));
}

function compareParts(a: readonly Part[], b: readonly Part[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    for (let j = 0; j < 3; j++) {
      const x = a[i][j];
      const y = b[i][j];
      if (x !== y) return x < y ? -1 : 1;
    }
  }
  return a.length - b.length;
}

// Ascending natural order of two IDs (negative: a before b).
export function compareIds(a: string | undefined, b: string | undefined): number {
  return compareParts(idKey(a), idKey(b));
}

// A date as milliseconds: a number (ms), or an ISO 8601 date or time. Undefined when there is none or it is unreadable.
export function whenMs(value: string | number | undefined | null): number | undefined {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const text = value.trim();
  const ms = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(text) ? `${text}T00:00:00Z` : text);
  if (Number.isFinite(ms)) return ms;
  const day = Date.parse(`${text.slice(0, 10)}T00:00:00Z`);
  return Number.isFinite(day) ? day : undefined;
}

// `items` by date, newest first, then by ID, highest first; undated entries last. A stable copy; `items` is unchanged.
export function newestFirst<T>(items: readonly T[], when: (item: T) => string | number | undefined | null,
  id: (item: T) => string | undefined): T[] {
  const keyed = items.map((item, index) => ({ item, index, ms: whenMs(when(item)), id: idKey(id(item)) }));
  keyed.sort((a, b) => {
    if (a.ms !== b.ms) {
      if (a.ms === undefined) return 1;
      if (b.ms === undefined) return -1;
      return b.ms - a.ms;
    }
    return compareParts(b.id, a.id) || a.index - b.index;
  });
  return keyed.map(({ item }) => item);
}

// IDs alone (no dates), highest first.
export function highestFirst<T>(items: readonly T[], id: (item: T) => string | undefined): T[] {
  return newestFirst(items, () => undefined, id);
}
