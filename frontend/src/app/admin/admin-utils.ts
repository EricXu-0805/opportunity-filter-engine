import type { AdminResponse, HistoryEntry, TFunc } from './types';

/**
 * Returns the delta between current's `key` and previous's `key`, or
 * null if previous is missing or the value is not a number. Used by
 * StatCard to render ▲/▼ deltas against the prior history snapshot.
 */
export function diff(
  key: string,
  current: AdminResponse,
  previous: HistoryEntry | null,
): number | null {
  if (!previous) return null;
  const cur = current.global[key] ?? 0;
  const prev = (previous as unknown as Record<string, unknown>)[key];
  if (typeof prev !== 'number') return null;
  return cur - prev;
}

/**
 * Humanizes a duration in hours into a localized string. Buckets:
 *   < 1 minute → "just now"
 *   < 1 hour   → "N min ago"
 *   < 48 hours → "Nh ago"
 *   ≥ 48 hours → "Nd ago"
 */
/**
 * Looks up `${prefix}.${value}` in the dictionary and falls back to the raw
 * value when no key exists. Backends own these enums (ticket status, incident
 * kind, resolution…) and can add a member before the dictionary catches up —
 * showing `admin.ops.kind.new_thing` to an operator would be worse than
 * showing `new_thing`.
 */
export function enumLabel(
  t: TFunc,
  prefix: string,
  value: string | null | undefined,
  fallback = '',
): string {
  if (!value) return fallback;
  const key = `${prefix}.${value}`;
  const label = t(key);
  return label === key ? value : label;
}

/** Age of an ISO timestamp, humanized. Empty string when the value is absent. */
export function isoAge(iso: string | null | undefined, t: TFunc): string {
  if (!iso) return '';
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return '';
  return humanAge(ms / (1000 * 60 * 60), t);
}

export function humanAge(hours: number, t: TFunc): string {
  if (hours < 1 / 60) return t('admin.freshness.justNow');
  if (hours < 1) return t('admin.freshness.minutesAgo', { n: Math.round(hours * 60) });
  if (hours < 48) return t('admin.freshness.hoursAgo', { n: Math.round(hours) });
  return t('admin.freshness.daysAgo', { n: Math.round(hours / 24) });
}
