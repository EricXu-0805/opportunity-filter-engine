import type { AdminResponse, HistoryEntry, TFunc } from './types';

const LISTING_QUALITY_KEYS = new Set([
  'empty_majors',
  'empty_keywords',
  'empty_description',
  'short_description',
  'missing_deadline',
  'rolling_deadline',
  'missing_skills',
  'past_deadline',
  'stale_verify',
  'flagged_inactive',
]);

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
  if (
    LISTING_QUALITY_KEYS.has(key)
    && (
      typeof current.global.listing_total !== 'number'
      || typeof previous.listing_total !== 'number'
    )
  ) return null;
  const cur = current.global[key] ?? 0;
  const prev = (previous as unknown as Record<string, unknown>)[key];
  if (typeof prev !== 'number') return null;
  return cur - prev;
}

/**
 * Percentage denominator for the listing-only quality counters.
 *
 * The backend skips faculty contact profiles when counting empty_majors,
 * empty_keywords, missing_deadline and rolling_deadline — a directory row has
 * no opening to be missing a deadline. It ships the matching denominator as
 * `global.listing_total`. Dividing by `total` instead mixes 127,885 faculty
 * rows into the denominator of a listing-only numerator and understates every
 * defect rate ~18x, on the dashboard used to judge whether data is fit to ship.
 */
export function listingPct(key: string, data: AdminResponse): number | undefined {
  const denominator = data.global.listing_total;
  // A legacy response has no compatible denominator. Omitting the percentage
  // is honest; falling back to the mixed faculty+listing total recreates the
  // exact ~18x understatement this helper exists to prevent.
  if (typeof denominator !== 'number' || denominator <= 0) return undefined;
  return ((data.global[key] ?? 0) / denominator) * 100;
}

/** Remove legacy mixed-scope snapshots before rendering listing trends. */
export function listingScopedHistory(history: HistoryEntry[]): HistoryEntry[] {
  return history.filter((entry) => typeof entry.listing_total === 'number');
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
