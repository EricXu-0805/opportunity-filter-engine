export type HumanizedAgo =
  | { kind: 'just-now' }
  | { kind: 'minutes'; n: number }
  | { kind: 'hours'; n: number }
  | { kind: 'days'; n: number }
  | { kind: 'date'; iso: string };

const MS_PER_MIN = 60_000;
const MS_PER_HOUR = 3_600_000;
const MS_PER_DAY = 86_400_000;

// Buckets (rounded): <1m just-now · <1h minutes · <1d hours · <7d days · else date.
// Future timestamps collapse to just-now so clock skew can't render "in 3h".
export function humanizeTime(
  iso: string | null | undefined,
  now: Date = new Date(),
): HumanizedAgo | null {
  if (!iso) return null;
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return null;

  const diffMs = now.getTime() - ts;
  if (diffMs < MS_PER_MIN) return { kind: 'just-now' };
  if (diffMs < MS_PER_HOUR) {
    return { kind: 'minutes', n: Math.max(1, Math.round(diffMs / MS_PER_MIN)) };
  }
  if (diffMs < MS_PER_DAY) {
    return { kind: 'hours', n: Math.max(1, Math.round(diffMs / MS_PER_HOUR)) };
  }
  if (diffMs < 7 * MS_PER_DAY) {
    return { kind: 'days', n: Math.max(1, Math.round(diffMs / MS_PER_DAY)) };
  }
  // .slice(0,10) is timezone-safe only because the backend cron writes UTC ISO
  // for last_run_at — see backend/cron/saved_searches.py.
  return { kind: 'date', iso: iso.slice(0, 10) };
}

type AgoTFunc = (path: string, vars?: Record<string, string | number>) => string;

/**
 * The rendered, translated form — the half that kept getting reimplemented.
 *
 * humanizeTime deliberately returns a shape rather than a string so the caller
 * can translate it, but two components (the home page's live-database card and
 * the tracker timeline) each grew their own private `formatRelativeAge` that
 * returned hardcoded English instead. Both sat directly after a translated
 * label, so a zh reader saw "数据更新于 3h ago". Returns '' for an unusable
 * timestamp, matching what those callers already did.
 */
export function formatAgo(
  iso: string | null | undefined,
  t: AgoTFunc,
  now: Date = new Date(),
): string {
  const result = humanizeTime(iso, now);
  if (!result) return '';
  switch (result.kind) {
    case 'just-now':
      return t('common.ago.justNow');
    case 'minutes':
      return t('common.ago.minutes', { n: result.n });
    case 'hours':
      return t('common.ago.hours', { n: result.n });
    case 'days':
      return t('common.ago.days', { n: result.n });
    case 'date':
      return t('common.ago.onDate', { date: result.iso });
  }
}
