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
import { captureOwnerToken, isOwnerTokenValid, readUserScopedRaw, removeUserScopedRaw, writeUserScopedRaw, type OwnerToken } from '@/lib/identity-owner';
import { everyResultActionable } from '@/lib/target-truth';
import type { MatchResult, MatchesResponse, Opportunity } from '@/lib/types';

const KEY = STORAGE_KEYS.MATCH_RESULTS;
// Bump when the public result-set capability boundary changes. This invalidates
// seven-day local payloads written while fellowships and other MTP surfaces
// were public without changing the server match-view protocol or storage key.
// Bumped with target-truth-v2: a page cached before this build can contain
// rows whose kind was never reviewed, which this build refuses to present as
// listings. Reusing it would serve exactly the records the change removed.
const CACHE_VERSION = 'mvp-core-close-v1-contact-trust-v1-target-truth-v2';
// Exactly the wire this backend speaks — `MATCH_VIEW_CONTRACT_VERSION` in
// backend/routes/matches.py — and nothing else. A version string nobody
// emits is not forward compatibility; it is a promise accepted in advance
// from a payload whose shape has never been agreed, let alone reviewed. When
// a v4 is actually negotiated it arrives with the field changes that define
// it, and this list is part of that change.
//
// Equally required is TARGET_TRUTH_CONTRACT below: a response without that
// marker comes from a backend that makes no promise about truth, and is refused
// whatever its version says — including an empty page, which has no rows to
// inspect. Both are necessary; neither alone is sufficient.
export const ACCEPTED_MATCH_VIEW_CONTRACT_VERSIONS = [
  'match-view-v3-faculty-trust',
] as const;

/** The version this client writes into its own cache entries. */
export const MATCH_VIEW_CONTRACT_VERSION = 'match-view-v3-faculty-trust';

/** Required on every accepted response — see above. */
// v2 adds `record_kind_unverified`. Kept as a single accepted value rather
// than a set: a v1 page cannot contain that reason, so its rows describe a
// universe this build no longer serves, and accepting it would mix the two.
export const TARGET_TRUTH_CONTRACT = 'target-truth-v2';

export function isAcceptedMatchViewContract(response: {
  contract_version?: string;
  target_truth_contract?: string;
}): boolean {
  return (
    response.target_truth_contract === TARGET_TRUTH_CONTRACT
    && (ACCEPTED_MATCH_VIEW_CONTRACT_VERSIONS as readonly string[])
      .includes(response.contract_version ?? '')
  );
}
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
  'deadline', 'is_rolling', 'source', 'on_campus', 'posted_date', 'location', 'url',
  'duration', 'compensation_details', 'keywords', 'lab_or_program', 'pi_name',
  'school', 'audience', 'source_type', 'recent_works',
  'faculty_availability_status',
  'publication_attribution_status',
  // Both are load-bearing on a cache hit. `target_truth` is what every CTA
  // gates on — dropping it turns a restored closed listing back into an
  // actionable one. `source_url` is the only link a historical record may
  // still offer, and opportunitySourceUrl reads it before `url`.
  'target_truth', 'source_url',
  // The server's normalization of source_type, kept beside the truth for the
  // same reason: `readTruth` cross-checks the two, so a restored row that
  // dropped it would be validated against only half the attestation it
  // arrived with. Absent stays absent — an older backend never sent it — but
  // a row that HAD it must keep it, or a wire/local mismatch this build
  // would have refused becomes invisible on a cache hit.
  'record_kind',
  // W11: keep the stated faculty title for rank-aware profile copy, while
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
  contract_version: string;
  // Persisted, not re-derived: a cache entry has to answer the same question a
  // live response does. Omitting it would make every stored page fail the
  // marker check on read — a cache that never hits, which looks like a working
  // guard and is really a disabled one.
  target_truth_contract: string;
  view_start?: number;
  filtered_total?: number;
  view_counts?: MatchesResponse['view_counts'];
  source_facets?: MatchesResponse['source_facets'];
  scope_available?: boolean;
  deadline_facets?: MatchesResponse['deadline_facets'];
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

/**
 * The one question every consumer of a match page has to ask.
 *
 * There are four places a page can enter the app — the results hook, the cache
 * (on write and on read), the email loader, and the CSV export — and each one
 * used to ask its own subset. That is how a gap appears: one surface checks the
 * contract, another checks identity, and the export checks neither. Consumers
 * call this and nothing else.
 *
 * Trusted means all four at once:
 *   1. a wire version we recognise,
 *   2. the target-truth marker (the promise itself — readable even on an
 *      empty page, which has no rows to inspect),
 *   3. identity: every row's nested id matches its top-level id, no duplicates,
 *   4. every row still actionable.
 */
export function isTrustedMatchViewPage(page: {
  contract_version?: string;
  target_truth_contract?: string;
  results?: unknown;
}): boolean {
  return (
    isAcceptedMatchViewContract(page)
    && hasValidMatchResultIdentity(page.results)
    && everyResultActionable(page.results as MatchResult[])
  );
}

// Legacy (pre-v7) key names — NOT in USER_SCOPED_KEYS (only the CURRENT
// ofe_match_results_v7 is registered there), so these stay on raw
// localStorage.removeItem: they are dead, superseded key names being swept
// up as a one-time migration cleanup, never data anyone currently owns or
// reads. The static USER_SCOPED contract test allowlists exactly these
// literals for that reason.
function removeObsoleteMatchCaches(): void {
  for (const key of OBSOLETE_MATCH_KEYS) {
    try { localStorage.removeItem(key); } catch { /* ignore */ }
  }
}

// Fail-closed backstop for the case removeUserScopedRaw's own read-back
// verification is designed to catch but a caller here must still degrade
// safely from: a write fails (quota) AND the fallback clearMatchCache
// below ALSO cannot VERIFY the stale/half-written entry is gone (a thrown
// removeItem, or a read-back that still finds it there). Storage itself is
// left in an unknown state at that point — this module has no way to prove
// the single cache slot doesn't contain mismatched or half-written data —
// so reads fail closed for the REST of this session rather than risk
// serving it. Scoped to the SPECIFIC (uid, epoch) this happened under: a
// later, genuinely different owner (a real identity transition) was never
// the one whose cleanup failed and must never inherit the block.
let taintedOwnerKey: string | null = null;

function ownerKey(token: OwnerToken): string {
  return `${token.uid ?? ''}:${token.epoch}`;
}

function taintForFailedCleanup(token: OwnerToken): void {
  taintedOwnerKey = ownerKey(token);
}

function clearTaintOnSuccess(token: OwnerToken): void {
  if (taintedOwnerKey === ownerKey(token)) taintedOwnerKey = null;
}

function isTaintedForCurrentOwner(): boolean {
  return taintedOwnerKey !== null && taintedOwnerKey === ownerKey(captureOwnerToken());
}

function parse(): MatchCacheShape | null {
  try {
    removeObsoleteMatchCaches();
    if (isTaintedForCurrentOwner()) return null;
    const raw = readUserScopedRaw(KEY);
    if (!raw) return null;
    const c = JSON.parse(raw) as MatchCacheShape;
    // Cleanup-on-read: a synchronous call with no await in between, so a
    // freshly-captured token is trivially current — there is no staleness
    // window for a self-correcting read to race across.
    const token = captureOwnerToken();
    if (!c || c.version !== CACHE_VERSION) {
      removeUserScopedRaw(KEY, token);
      return null;
    }
    if (typeof c.savedAt !== 'number') return null;
    if (Date.now() - c.savedAt >= TTL_MS) return null;
    // The same question the live path asks, all-or-nothing. One restored row
    // whose truth is missing, malformed, or no longer actionable makes the
    // whole payload unshowable: dropping it silently would leave total/bucket
    // counts and facet numbers describing a page with one fewer card and no
    // explanation. Refuse, clear, and re-fetch.
    if (!isTrustedMatchViewPage(c)) {
      removeUserScopedRaw(KEY, token);
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

// `token` MUST be captured (via captureOwnerToken()) at the moment the
// caller's own clear intent began — see writeUserScopedRaw's own doc
// comment. A stale token silently no-ops the CURRENT-format removal (the
// legacy-key sweep still runs regardless, since those are dead keys no
// current owner could ever have written).
//
// Returns whether the CURRENT-format key was actually removed (false for
// a stale token — removeUserScopedRaw re-validates it independently, so
// this can never touch a DIFFERENT identity's cache no matter who calls
// it or why). Dispatches a same-tab 'storage' event on an actual removal
// — same-tab readers (Header's "Find Matches" link) subscribe to this,
// not to raw sessionStorage, and writeUserScopedRaw/removeUserScopedRaw
// themselves never dispatch it.
export function clearMatchCache(token: OwnerToken): boolean {
  // Captured before the attempt, not after: nothing async happens between
  // here and removeUserScopedRaw's own call, so this is exactly "was the
  // acting identity current for this whole attempt" — a stale token was
  // never going to touch storage at all (removeUserScopedRaw's own gate),
  // so a false return in that case needs no taint; only a CURRENT token
  // whose removal still couldn't be verified means something is actually
  // wrong with storage for THIS owner.
  const tokenWasCurrent = isOwnerTokenValid(token, token.uid);
  const removed = removeUserScopedRaw(KEY, token);
  removeObsoleteMatchCaches();
  if (removed) {
    clearTaintOnSuccess(token);
    try { window.dispatchEvent(new StorageEvent('storage', { key: KEY })); } catch { /* SSR */ }
    return true;
  }
  if (tokenWasCurrent) taintForFailedCleanup(token);
  return false;
}

/** Persist a compact, self-contained copy of the match set (opportunities
 *  projected to display fields). `token` MUST be captured at the moment
 *  the caller's own write intent began. Returns whether it actually
 *  landed. */
export function writeMatchCache(hash: string, semantic: boolean, data: MatchesResponse, token: OwnerToken): boolean {
  try {
    // Validated BEFORE anything is written. Storing first and letting the read
    // path clean up leaves a window where the only copy on the device is one
    // we would refuse — and it means a rejected page still costs a write.
    //
    // Refusing means refusing, nothing more: this primitive does not also
    // delete whatever is already stored. A bad page arriving is not evidence
    // that the good page already on the device went bad, and a storage
    // primitive with a hidden erase makes every caller reason about a side
    // effect it did not ask for. Clearing on an untrusted LIVE response is the
    // caller's decision, taken explicitly in use-results-data.
    if (!isTrustedMatchViewPage(data)) return false;
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
      // Whatever the server said, so a cache entry stays comparable with the
      // responses that follow it, whatever version those carry. Non-empty by
      // construction: isAcceptedMatchViewContract already rejected anything
      // else above.
      contract_version: data.contract_version ?? '',
      target_truth_contract: data.target_truth_contract ?? '',
      view_start: data.view_start,
      filtered_total: data.filtered_total,
      view_counts: data.view_counts,
      source_facets: data.source_facets,
      scope_available: data.scope_available,
      deadline_facets: data.deadline_facets,
      view_id: data.view_id,
    };
    const wrote = writeUserScopedRaw(KEY, JSON.stringify(payload), token);
    if (!wrote) {
      // writeUserScopedRaw returns false for TWO different reasons this
      // function cannot itself distinguish: a stale token (clearMatchCache
      // below then ALSO no-ops, since removeUserScopedRaw re-validates the
      // SAME token — a different identity's cache is never touched), or a
      // valid token whose underlying setItem failed (quota) — that clear
      // genuinely runs, dropping the now half-written/stale entry rather
      // than silently serving it (or a wrong-for-this-write leftover) on
      // the next visit. If that fallback clear ALSO can't verify the entry
      // is gone, clearMatchCache itself taints this owner+epoch so reads
      // fail closed rather than risk serving whatever is actually left.
      clearMatchCache(token);
      return false;
    }
    clearTaintOnSuccess(token);
    try { window.dispatchEvent(new StorageEvent('storage', { key: KEY })); } catch { /* SSR */ }
    return true;
  } catch {
    // quota or serialization failure → drop any partial write; the caller still
    // has the live data, and returning later simply re-matches (old behavior).
    clearMatchCache(token);
    return false;
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
    target_truth_contract: c.target_truth_contract,
    view_start: c.view_start,
    filtered_total: c.filtered_total,
    view_counts: c.view_counts,
    source_facets: c.source_facets,
    scope_available: c.scope_available,
    deadline_facets: c.deadline_facets,
    view_id: c.view_id,
  };
}

/** The matcher_version of the cached match set (null when no fresh cache or a
 *  pre-version payload). Other match caches (compare's explain cache) compare
 *  against this so two matcher generations never render side by side. */
export function cachedMatcherVersion(): string | null {
  return parse()?.matcher_version ?? null;
}
