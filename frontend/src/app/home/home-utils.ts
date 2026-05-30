import type { TFunc } from './types';

export function formatRelativeAge(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

export function translateKey(t: TFunc, namespace: string, name: string): string {
  const key = `${namespace}.${name}`;
  const out = t(key);
  return out === key ? name : out;
}
