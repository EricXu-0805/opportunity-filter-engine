// Durable cache for the last generated match set, so returning to /results from
// anywhere (nav, another tab, a later session) shows results INSTANTLY instead
// of re-running the match — or even a network round-trip.
//
// Why not cache the raw /matches response: it is ~7 MB for a broad profile
// (~2.3k results × full opportunity bodies), which overflows the ~5 MB Web
// Storage quota — the write threw and was swallowed, so the set was never
// cached and the header always fell back to the profile form. And re-fetching
// the bodies by id on return is a visible load.
//
// Instead we store a self-contained but COMPACT copy in localStorage: each
// opportunity is projected to just the fields the results list/filters render
// (no metadata, no full descriptions ≈ 3 MB for the broadest profile), so the
// read is a synchronous localStorage parse — instant, no network. The /matches
// response is already email-redacted, so the projection carries no PII.

import { STORAGE_KEYS } from '@/lib/storage-keys';
import type { MatchResult, MatchesResponse, Opportunity } from '@/lib/types';

const KEY = STORAGE_KEYS.MATCH_RESULTS;
const TTL_MS = 7 * 24 * 60 * 60 * 1000; // results older than this re-fetch (corpus drift)
const MAX_RESULTS = 2500; // hard size bound; far past what anyone scrolls/paginates
const DESC_CHARS = 200; // keep a snippet so the free-text search still matches bodies

// Exactly the opportunity fields the results list, filters and sort read
// (see MatchCard + use-results-filters/sort). Everything else — metadata,
// full descriptions, the bulky eligibility/application sub-objects — is dropped.
// school + audience back the discovery-scope facet + MatchCard scope chip
// (PR #191); omitting them strips scope metadata on every cache-hit return,
// hiding the facet and turning a persisted scope=campus into a zero-result
// no-op — see match-cache.test.ts round-trip.
const OPP_FIELDS = [
  'id', 'title', 'organization', 'department', 'opportunity_type', 'paid',
  'deadline', 'source', 'on_campus', 'posted_date', 'location', 'url',
  'duration', 'compensation_details', 'keywords', 'lab_or_program', 'pi_name',
  'school', 'audience',
] as const;
const ELIG_FIELDS = ['international_friendly', 'skills_required', 'skills_preferred'] as const;
const APP_FIELDS = [
  'application_url', 'requires_resume', 'requires_recommendation',
  'requires_cover_letter', 'contact_method',
] as const;

function projectOpportunity(opp: Opportunity): Opportunity {
  const src = opp as unknown as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const k of OPP_FIELDS) if (src[k] !== undefined) out[k] = src[k];
  const elig = src.eligibility as Record<string, unknown> | undefined;
  if (elig) {
    const e: Record<string, unknown> = {};
    for (const k of ELIG_FIELDS) if (elig[k] !== undefined) e[k] = elig[k];
    out.eligibility = e;
  }
  const app = src.application as Record<string, unknown> | undefined;
  if (app) {
    const a: Record<string, unknown> = {};
    for (const k of APP_FIELDS) if (app[k] !== undefined) a[k] = app[k];
    out.application = a;
  }
  const dc = src.description_clean;
  if (typeof dc === 'string') out.description_clean = dc.slice(0, DESC_CHARS);
  return out as unknown as Opportunity;
}

interface MatchCacheShape {
  hash: string;
  semantic: boolean;
  savedAt: number;
  total: number;
  high_priority: number;
  good_match: number;
  reach: number;
  low_fit: number;
  results: MatchResult[];
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

/** Persist a compact, self-contained copy of the match set (opportunities
 *  projected to display fields). */
export function writeMatchCache(hash: string, semantic: boolean, data: MatchesResponse): void {
  try {
    const results = data.results.slice(0, MAX_RESULTS).map((r) => ({
      ...r,
      opportunity: projectOpportunity(r.opportunity),
    }));
    const payload: MatchCacheShape = {
      hash,
      semantic,
      savedAt: Date.now(),
      total: data.total,
      high_priority: data.high_priority,
      good_match: data.good_match,
      reach: data.reach,
      low_fit: data.low_fit,
      results,
    };
    localStorage.setItem(KEY, JSON.stringify(payload));
  } catch {
    // quota or serialization failure → drop any partial write; the caller still
    // has the live data, and returning later simply re-matches (old behavior).
    clearMatchCache();
  }
}

/** Synchronously return the cached match set when a fresh one matches this
 *  profile+mode; null on miss/expiry. Synchronous = instant render, no network. */
export function readMatchCache(hash: string, semantic: boolean): MatchesResponse | null {
  const c = parse();
  if (!c || c.hash !== hash || (c.semantic ?? false) !== semantic) return null;
  return {
    total: c.total,
    high_priority: c.high_priority,
    good_match: c.good_match,
    reach: c.reach,
    low_fit: c.low_fit,
    results: c.results,
  };
}
