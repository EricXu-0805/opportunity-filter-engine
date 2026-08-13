import type { TFunc } from './types';

// formatRelativeAge lived here and returned hardcoded English. It is now
// lib/humanize-time.formatAgo, which renders through the dictionary.

export function translateKey(t: TFunc, namespace: string, name: string): string {
  const key = `${namespace}.${name}`;
  const out = t(key);
  return out === key ? name : out;
}
