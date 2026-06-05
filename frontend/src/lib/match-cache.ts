// Durable cache for the last generated match set, so returning to /results from
// anywhere (nav, another tab, a later session) is instant instead of re-running
// the match.
//
// Why not cache the raw /matches response: it is ~7 MB for a broad profile
// (~2.3k results × full opportunity bodies), which overflows the ~5 MB Web
// Storage quota — the write threw and the set was silently never cached, so the
// header always fell back to the profile form. Instead we store a COMPACT copy
// (scores/reasons/buckets only, no opportunity bodies ≈ 1 MB) in localStorage,
// and re-hydrate the opportunity payloads by id via /opportunities/batch on read
// — a fast lookup, NOT a re-match.

import { getOpportunitiesByIds } from '@/lib/api';
import type { MatchResult, MatchesResponse, Opportunity } from '@/lib/types';

const KEY = 'ofe_match_results';
const TTL_MS = 7 * 24 * 60 * 60 * 1000; // results older than this re-fetch (corpus drift)
const REDACTED_FIELDS = ['contact_email', 'pi_email'] as const;

type LiteResult = Omit<MatchResult, 'opportunity'>;

interface MatchCacheShape {
  hash: string;
  semantic: boolean;
  savedAt: number;
  total: number;
  high_priority: number;
  good_match: number;
  reach: number;
  low_fit: number;
  results: LiteResult[];
}

function parse(): MatchCacheShape | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const c = JSON.parse(raw) as MatchCacheShape;
    if (!c || typeof c.savedAt !== 'number') return null;
    if (Date.now() - c.savedAt >= TTL_MS) return null;
    return c;
  } catch {
    return null;
  }
}

/** Cheap synchronous probe — does a fresh cached match set exist on this device?
 *  Used by the header to point "Find Matches" at /results instead of the form. */
export function hasMatchCache(): boolean {
  return parse() !== null;
}

export function clearMatchCache(): void {
  try { localStorage.removeItem(KEY); } catch { /* ignore */ }
}

/** Persist a compact copy of the match set (opportunity bodies stripped). */
export function writeMatchCache(hash: string, semantic: boolean, data: MatchesResponse): void {
  try {
    const payload: MatchCacheShape = {
      hash,
      semantic,
      savedAt: Date.now(),
      total: data.total,
      high_priority: data.high_priority,
      good_match: data.good_match,
      reach: data.reach,
      low_fit: data.low_fit,
      results: data.results.map(({ opportunity: _drop, ...lite }) => lite),
    };
    localStorage.setItem(KEY, JSON.stringify(payload));
  } catch {
    // quota or serialization failure → drop any partial write so reads don't
    // resurrect a corrupt entry; the caller already has the live data.
    clearMatchCache();
  }
}

/** Return the full match set (opportunities re-hydrated by id) when a fresh cache
 *  matches this profile+mode; null on miss/expiry/hydration failure (caller then
 *  re-fetches). Crucially this re-hydration is a lookup, never a re-match. */
export async function readMatchCache(
  hash: string,
  semantic: boolean,
): Promise<MatchesResponse | null> {
  const cache = parse();
  if (!cache || cache.hash !== hash || (cache.semantic ?? false) !== semantic) return null;

  try {
    const ids = cache.results.map((r) => r.opportunity_id);
    const opps = await getOpportunitiesByIds(ids);
    const byId = new Map(opps.map((o) => [(o as { id?: string }).id, o]));
    const results: MatchResult[] = [];
    for (const lite of cache.results) {
      const opp = byId.get(lite.opportunity_id);
      if (!opp) continue; // opportunity removed from the corpus since caching
      const clean: Record<string, unknown> = { ...(opp as Record<string, unknown>) };
      for (const f of REDACTED_FIELDS) delete clean[f];
      results.push({ ...lite, opportunity: clean as unknown as Opportunity });
    }
    return {
      total: cache.total,
      high_priority: cache.high_priority,
      good_match: cache.good_match,
      reach: cache.reach,
      low_fit: cache.low_fit,
      results,
    };
  } catch {
    return null;
  }
}
