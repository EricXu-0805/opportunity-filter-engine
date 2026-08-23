import { QUALITY_SCOPE } from './types';
import type { AdminResponse, HistoryEntry, TFunc } from './types';

/**
 * Whether a snapshot describes the population the current build measures.
 *
 * Presence of `listing_total` is NOT the test. An entry written before
 * `reviewed-record-kind-v1` has that field too — it just counted every
 * unreviewed record as a listing, so its denominator and its defect numerators
 * describe a different set. Comparing across that boundary reports a change in
 * the data when what changed was the definition.
 */
export function isCurrentQualityScope(
  snapshot: { quality_scope?: string } | null | undefined,
): boolean {
  return snapshot?.quality_scope === QUALITY_SCOPE;
}

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
  // Both sides must describe the same population. A delta across the scope
  // boundary is the definition changing, presented as the data moving — and
  // it would show up as a green ▼ on exactly the counters that got smaller
  // only because unreviewed rows stopped being counted as listings.
  //
  // The marker is necessary, not sufficient: a correctly-marked payload can
  // still arrive without the denominator (a truncated response, a partial
  // write), and treating a missing number as zero is how a comparison gets
  // invented out of nothing. Both checks, both sides.
  if (
    LISTING_QUALITY_KEYS.has(key)
    && (
      !isCurrentQualityScope(current)
      || !isCurrentQualityScope(previous)
      || typeof current.global.listing_total !== 'number'
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
  // The marker, not the field. A legacy response ships `listing_total` as
  // well; it simply counted unreviewed records inside it, so the rate it
  // produces is over a set nobody meant. Omitting the percentage is honest —
  // the absolute count beside it is still true and still shown.
  if (!isCurrentQualityScope(data)) return undefined;
  const denominator = data.global.listing_total;
  if (typeof denominator !== 'number' || denominator <= 0) return undefined;
  return ((data.global[key] ?? 0) / denominator) * 100;
}

/**
 * Keep only snapshots that describe the population this build measures AND
 * carry the denominator a listing trend is drawn against. A correctly-marked
 * but malformed row would otherwise plot as a zero — a cliff in the chart
 * that never happened in the data.
 */
export function listingScopedHistory(history: HistoryEntry[]): HistoryEntry[] {
  return history.filter(
    (entry) => isCurrentQualityScope(entry) && typeof entry.listing_total === 'number',
  );
}

/**
 * The history entry immediately preceding the snapshot on screen.
 *
 * Not `history[length - 2]`. Two things break an index-based answer. Scope:
 * the row before last may be a legacy entry, and comparing across that
 * boundary shows every listing counter improving when all that happened is
 * unreviewed records leaving the denominator. Position: `data` and `history`
 * are fetched together while the backend appends at most one entry per hour,
 * so the current snapshot may or may not already be in the list — making
 * "second from the end" mean two different things on consecutive loads.
 *
 * Answered by timestamp instead, strictly earlier: an entry sharing the
 * current snapshot's time IS that snapshot, and comparing it with itself
 * shows no change on a board whose whole job is to show change. A current
 * snapshot that is out of scope or has an unparseable time yields null —
 * there is no "now" to measure from, and picking an index anyway would answer
 * a question nobody asked.
 */
export function findPreviousSnapshot(
  history: HistoryEntry[],
  data: AdminResponse | null | undefined,
): HistoryEntry | null {
  const scoped = listingScopedHistory(history);
  if (!scoped.length) return null;
  const currentAt = isCurrentQualityScope(data) ? Date.parse(data?.generated_at ?? '') : NaN;
  if (Number.isNaN(currentAt)) return null;
  for (let i = scoped.length - 1; i >= 0; i -= 1) {
    const at = Date.parse(scoped[i].t);
    if (!Number.isNaN(at) && at < currentAt) return scoped[i];
  }
  return null;
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
