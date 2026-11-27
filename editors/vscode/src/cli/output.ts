import type { ValidateFunction } from 'ajv';
import { constants } from 'node:fs';
import { open } from 'node:fs/promises';
import { MAX_OUTPUT_BYTES } from './runner';

export type JsonOutput<T> = { kind: 'valid'; value: T } | { kind: 'unreadable' };

function boundedDepth(text: string, limit: number): boolean {
  let depth = 0;
  let inString = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (inString && char === '\\') i++;
    else if (char === '"') inString = !inString;
    else if (!inString && (char === '{' || char === '[')) {
      if (++depth > limit) return false;
    } else if (!inString && (char === '}' || char === ']')) {
      if (--depth < 0) return false;
    }
  }
  return depth === 0 && !inString;
}

export function parseJson<T>(
  raw: string | Buffer,
  validate: ValidateFunction<T>,
  maxBytes = MAX_OUTPUT_BYTES,
): JsonOutput<T> {
  try {
    if (Buffer.byteLength(raw) > maxBytes) return { kind: 'unreadable' };
    const text = typeof raw === 'string' ? raw : new TextDecoder('utf-8', { fatal: true }).decode(raw);
    if (!boundedDepth(text, 64)) return { kind: 'unreadable' };
    const value: unknown = JSON.parse(text);
    return validate(value) ? { kind: 'valid', value } : { kind: 'unreadable' };
  } catch {
    return { kind: 'unreadable' };
  }
}

// The caller supplies a confined path and the schema for the expected response.
export async function readJson<T>(
  path: string,
  validate: ValidateFunction<T>,
  maxBytes = MAX_OUTPUT_BYTES,
): Promise<JsonOutput<T>> {
  try {
    const file = await open(path, constants.O_RDONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW);
    try {
      const status = await file.stat();
      if (!status.isFile() || status.size > maxBytes) return { kind: 'unreadable' };

      let length = 0;
      const chunks: Buffer[] = [];
      while (length <= maxBytes) {
        const chunk = Buffer.allocUnsafe(Math.min(64 * 1024, maxBytes + 1 - length));
        const { bytesRead } = await file.read(chunk);
        if (!bytesRead) return parseJson(Buffer.concat(chunks, length), validate, maxBytes);
        chunks.push(chunk.subarray(0, bytesRead));
        length += bytesRead;
      }
    } finally {
      await file.close();
    }
  } catch {
    return { kind: 'unreadable' };
  }
  return { kind: 'unreadable' };
}
