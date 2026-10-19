/**
 * The client half of `GET /api/opportunities/freshness`: when each school's
 * pages were last read successfully, and whether that read covers the school.
 *
 * Computed by the backend from the per-source ledger alone
 * (src/collectors/source_health.py, `public_school_freshness`), never from the
 * corpus-wide update time, so one school's refresh cannot stand in for
 * another's. A school the response does not name has no monitored source, and
 * every surface renders nothing for it — as it does for a failed or malformed
 * read: no claim is better than a wrong one.
 */

import { useEffect, useState } from 'react';

/** Mirrors `SCHOOL_FRESHNESS_SCHEMA` in backend/routes/opportunities.py. */
export const SCHOOL_FRESHNESS_SCHEMA = 'school-freshness-v1';

/**
 * `stale`: the release gate calls the school fully stale or without fresh
 * faculty data. `partly_unchecked`: not stale, but at least one of its sources
 * is stale or failed on its latest run. `current`: neither.
 */
export type SchoolFreshnessStatus = 'current' | 'partly_unchecked' | 'stale';

export interface SchoolFreshness {
  /** The newest successful read among the school's sources; null when none ever succeeded. */
  readonly lastCheckedAt: string | null;
  readonly status: SchoolFreshnessStatus;
}

export type SchoolFreshnessMap = ReadonlyMap<string, SchoolFreshness>;

export type SchoolFreshnessState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly schools: SchoolFreshnessMap }
  | { readonly status: 'failed' };

const STATUSES: ReadonlySet<string> = new Set(['current', 'partly_unchecked', 'stale']);

/**
 * Narrow an untyped body to the schools it describes, or null when the body is
 * not this schema at all. A malformed entry is dropped on its own, so it shows
 * nothing for that school instead of costing every other school its line.
 */
export function parseSchoolFreshness(body: unknown): SchoolFreshnessMap | null {
  if (!body || typeof body !== 'object') return null;
  const { schema, schools } = body as { schema?: unknown; schools?: unknown };
  if (schema !== SCHOOL_FRESHNESS_SCHEMA) return null;
  if (!schools || typeof schools !== 'object' || Array.isArray(schools)) return null;
  const parsed = new Map<string, SchoolFreshness>();
  for (const [slug, entry] of Object.entries(schools)) {
    if (!entry || typeof entry !== 'object') continue;
    const { last_checked_at: at, status } = entry as { last_checked_at?: unknown; status?: unknown };
    if (typeof status !== 'string' || !STATUSES.has(status)) continue;
    if (at !== null && (typeof at !== 'string' || Number.isNaN(Date.parse(at)))) continue;
    parsed.set(slug, { lastCheckedAt: at, status: status as SchoolFreshnessStatus });
  }
  return parsed;
}

// One request per page load, shared by every surface that asks. A good answer
// is kept for ten minutes — the statuses change on a scale of days — so moving
// from the profile to the results finds it already here; a failure is not
// kept, and the next surface to mount asks again.
const KEEP_MS = 10 * 60_000;
let kept: { at: number; schools: SchoolFreshnessMap } | null = null;
let inflight: Promise<SchoolFreshnessMap | null> | null = null;

/** The kept answer while it is still young enough to show, else null. */
export function keptSchoolFreshness(): SchoolFreshnessMap | null {
  return kept && Date.now() - kept.at < KEEP_MS ? kept.schools : null;
}

/** The parsed response, or null for any failure. Never rejects. */
export function loadSchoolFreshness(): Promise<SchoolFreshnessMap | null> {
  const ready = keptSchoolFreshness();
  if (ready) return Promise.resolve(ready);
  if (!inflight) {
    inflight = fetch('/api/opportunities/freshness')
      .then((response) => (response.ok ? response.json() : null))
      .then((body: unknown) => {
        const schools = parseSchoolFreshness(body);
        if (schools) kept = { at: Date.now(), schools };
        return schools;
      })
      .catch(() => null)
      .finally(() => { inflight = null; });
  }
  return inflight;
}

export function resetSchoolFreshnessForTests(): void {
  kept = null;
  inflight = null;
}

export function useSchoolFreshness(): SchoolFreshnessState {
  const [state, setState] = useState<SchoolFreshnessState>(() => {
    const schools = keptSchoolFreshness();
    return schools ? { status: 'ready', schools } : { status: 'loading' };
  });
  useEffect(() => {
    let cancelled = false;
    void loadSchoolFreshness().then((schools) => {
      if (cancelled) return;
      setState((previous) => {
        if (!schools) return { status: 'failed' };
        return previous.status === 'ready' && previous.schools === schools
          ? previous
          : { status: 'ready', schools };
      });
    });
    return () => { cancelled = true; };
  }, []);
  return state;
}

function preferredLanguages(): readonly string[] {
  if (typeof navigator === 'undefined') return [];
  return navigator.languages?.length ? navigator.languages : [navigator.language];
}

/**
 * The reader's own locale for the page's language: an en-GB reader of the
 * English page sees "12 Oct 2026", a zh-TW reader of the Chinese page
 * "2026年10月12日". Falls back to the page language itself.
 */
export function dateLocale(pageLocale: string, languages = preferredLanguages()): string {
  return languages.find((tag) => tag?.toLowerCase().split('-')[0] === pageLocale) ?? pageLocale;
}

/**
 * The calendar date of `iso` in the reader's time zone and locale, or null
 * when it cannot be read. A read at 03:45 UTC on 5 September is 4 September
 * for a reader in Chicago, and that is the date they should see.
 */
export function formatCheckedDate(
  iso: string,
  pageLocale: string,
  { timeZone, languages }: { timeZone?: string; languages?: readonly string[] } = {},
): string | null {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return null;
  const locale = dateLocale(pageLocale, languages);
  try {
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone }).format(at);
  } catch {
    // A browser language tag Intl cannot use: the page's own language can.
    return new Intl.DateTimeFormat(pageLocale, { dateStyle: 'medium', timeZone }).format(at);
  }
}
