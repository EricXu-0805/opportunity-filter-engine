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
export function humanAge(hours: number, t: TFunc): string {
  if (hours < 1 / 60) return t('admin.freshness.justNow');
  if (hours < 1) return t('admin.freshness.minutesAgo', { n: Math.round(hours * 60) });
  if (hours < 48) return t('admin.freshness.hoursAgo', { n: Math.round(hours) });
  return t('admin.freshness.daysAgo', { n: Math.round(hours / 24) });
}
