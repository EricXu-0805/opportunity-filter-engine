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
// The v7 contract stores only the bounded first server-view page (max 100
// cards) plus complete server-derived counts/facets/cursor metadata. A cache
// hit may paint immediately, but useResultsData always validates it in the
// background so a seven-day local copy never becomes the authority for corpus
// or matcher generation. v7 is also the contact-trust boundary: pre-v7
// payloads may contain an address copied into a public text or URL field.

import { STORAGE_KEYS } from '@/lib/storage-keys';
import type { MatchResult, MatchesResponse, Opportunity } from '@/lib/types';

const KEY = STORAGE_KEYS.MATCH_RESULTS;
const CACHE_VERSION = 'contact-trust-v1';
export const MATCH_VIEW_CONTRACT_VERSION = 'match-view-v2-contact-trust';
const OBSOLETE_MATCH_KEYS = [
  'ofe_match_results',
  'ofe_match_results_v2',
  'ofe_match_results_v3',
  'ofe_match_results_v4',
  'ofe_match_results_v5',
  'ofe_match_results_v6',
] as const;
const TTL_MS = 7 * 24 * 60 * 60 * 1000; // results older than this re-fetch (corpus drift)
const MAX_RESULTS = 100;
const DESC_CHARS = 200; // keep a snippet so the free-text search still matches bodies

// Exactly the opportunity fields the results list, filters and sort read
// (see MatchCard + use-results-filters/sort). Everything else — metadata,
// full descriptions, the bulky eligibility/application sub-objects — is dropped.
// school + audience back the discovery-scope facet + MatchCard scope chip
// (PR #191); omitting them strips scope metadata on every cache-hit return,
// hiding the facet and turning a persisted scope=campus into a zero-result
// no-op — see match-cache.test.ts round-trip.
// source_type drives MatchCard's faculty CTA (#218); dropping it on a
// cache-hit turns every faculty card into a dead-end "Apply Now".
const OPP_FIELDS = [
  'id', 'title', 'organization', 'department', 'opportunity_type', 'paid',
  'deadline', 'source', 'on_campus', 'posted_date', 'location', 'url',
  'duration', 'compensation_details', 'keywords', 'lab_or_program', 'pi_name',
  'school', 'audience', 'source_type', 'recent_works',
  'publication_attribution_status',
  // W11: dropping these on a cache-hit would silently change what the card
  // claims — faculty_title gates the "Email Professor" framing and
  // deadline_is_estimate keeps an estimated date from rendering as hard.
  'faculty_title', 'deadline_is_estimate',
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
  version: typeof CACHE_VERSION;
  hash: string;
  semantic: boolean;
  savedAt: number;
  total: number;
  high_priority: number;
  good_match: number;
  reach: number;
  low_fit: number;
  results: MatchResult[];
  // Canonical-matcher metadata (absent on payloads written before _v4):
  // field_relevant_count previously vanished on every cache hit, silently
  // hiding the "N strong matches in your field" header line on return visits.
  field_relevant_count?: number;
  thin_inventory?: boolean;
  matcher_version?: string;
  returned_count?: number;
  has_more?: boolean;
  next_cursor?: string | null;
  result_set_id?: string;
  contract_version: typeof MATCH_VIEW_CONTRACT_VERSION;
  view_start?: number;
  filtered_total?: number;
  view_counts?: MatchesResponse['view_counts'];
  source_facets?: MatchesResponse['source_facets'];
  scope_available?: boolean;
  view_id?: string;
}

/**
 * Boundary check for match-target identity: every result must carry a
 * non-empty top-level `opportunity_id`, its nested `opportunity.id` must be
 * non-empty and exactly equal that id, and no id may repeat. A stale/cached
 * payload, a duplicate row, or an id that drifted between the top-level and
 * nested shape must never let the Detail → Shortlist → reopen journey land
 * on the wrong record. Applied to both live results (before they enter
 * state/cache) and cached results (before they render).
 */
export function hasValidMatchResultIdentity(results: unknown): results is MatchResult[] {
  if (!Array.isArray(results)) return false;
  const seen = new Set<string>();
  for (const r of results) {
    if (!r || typeof r !== 'object') return false;
    const topId = (r as { opportunity_id?: unknown }).opportunity_id;
    if (typeof topId !== 'string' || topId.trim().length === 0) return false;
    const nested = (r as { opportunity?: unknown }).opportunity;
    const nestedId = nested && typeof nested === 'object'
      ? (nested as { id?: unknown }).id
      : undefined;
    // Strict raw equality — a whitespace-only id fails the trim() check above,
    // but two present ids that merely differ in surrounding whitespace are
    // NOT normalized into a match; that would silently repair drifted data.
    if (typeof nestedId !== 'string' || nestedId.trim().length === 0 || nestedId !== topId) return false;
    if (seen.has(topId)) return false;
    seen.add(topId);
  }
  return true;
}

function removeObsoleteMatchCaches(): void {
  for (const key of OBSOLETE_MATCH_KEYS) {
    try { localStorage.removeItem(key); } catch { /* ignore */ }
  }
}

function parse(): MatchCacheShape | null {
  try {
    removeObsoleteMatchCaches();
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const c = JSON.parse(raw) as MatchCacheShape;
    if (!c || c.version !== CACHE_VERSION) {
      localStorage.removeItem(KEY);
      return null;
    }
    if (c.contract_version !== MATCH_VIEW_CONTRACT_VERSION) {
      localStorage.removeItem(KEY);
      return null;
    }
    if (typeof c.savedAt !== 'number') return null;
    if (Date.now() - c.savedAt >= TTL_MS) return null;
    if (!hasValidMatchResultIdentity(c.results)) {
      localStorage.removeItem(KEY);
      return null;
    }
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
  removeObsoleteMatchCaches();
}

/** Persist a compact, self-contained copy of the match set (opportunities
 *  projected to display fields). */
export function writeMatchCache(hash: string, semantic: boolean, data: MatchesResponse): void {
  try {
    if (data.contract_version !== MATCH_VIEW_CONTRACT_VERSION) {
      clearMatchCache();
      return;
    }
    const results = data.results.slice(0, MAX_RESULTS).map((r) => ({
      ...r,
      opportunity: projectOpportunity(r.opportunity),
    }));
    const payload: MatchCacheShape = {
      version: CACHE_VERSION,
      hash,
      semantic,
      savedAt: Date.now(),
      total: data.total,
      high_priority: data.high_priority,
      good_match: data.good_match,
      reach: data.reach,
      low_fit: data.low_fit,
      results,
      field_relevant_count: data.field_relevant_count,
      thin_inventory: data.thin_inventory,
      matcher_version: data.matcher_version,
      returned_count: data.returned_count,
      has_more: data.has_more,
      next_cursor: data.next_cursor,
      result_set_id: data.result_set_id,
      contract_version: MATCH_VIEW_CONTRACT_VERSION,
      view_start: data.view_start,
      filtered_total: data.filtered_total,
      view_counts: data.view_counts,
      source_facets: data.source_facets,
      scope_available: data.scope_available,
      view_id: data.view_id,
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
    field_relevant_count: c.field_relevant_count,
    thin_inventory: c.thin_inventory,
    matcher_version: c.matcher_version,
    returned_count: c.returned_count,
    has_more: c.has_more,
    next_cursor: c.next_cursor,
    result_set_id: c.result_set_id,
    contract_version: c.contract_version,
    view_start: c.view_start,
    filtered_total: c.filtered_total,
    view_counts: c.view_counts,
    source_facets: c.source_facets,
    scope_available: c.scope_available,
    view_id: c.view_id,
  };
}

/** The matcher_version of the cached match set (null when no fresh cache or a
 *  pre-version payload). Other match caches (compare's explain cache) compare
 *  against this so two matcher generations never render side by side. */
export function cachedMatcherVersion(): string | null {
  return parse()?.matcher_version ?? null;
}
