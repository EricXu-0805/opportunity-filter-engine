import { describe, it, expect, beforeEach, vi } from 'vitest';

import {
  MATCH_VIEW_CONTRACT_VERSION,
  TARGET_TRUTH_CONTRACT,
  cachedMatcherVersion,
  clearMatchCache as clearMatchCacheRaw,
  hasMatchCache,
  hasValidMatchResultIdentity,
  readMatchCache,
  writeMatchCache as writeMatchCacheRaw,
} from './match-cache';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, type OwnerToken } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import type { MatchResult, MatchesResponse } from './types';

const MATCH_KEY = STORAGE_KEYS.MATCH_RESULTS;
const ORIGINAL_MATCH_KEY = 'ofe_match_results';
const LEGACY_RELEASE_SCOPE_KEY = 'ofe_match_results_v4';
const PRE_CONTACT_TRUST_KEY = 'ofe_match_results_v6';

// writeMatchCache/clearMatchCache now require an origin token — every test
// establishes readiness in beforeEach, and these thin wrappers (same name,
// arity minus the token) keep every pre-existing call site below untouched.
let token: OwnerToken;
function writeMatchCache(hash: string, semantic: boolean, data: MatchesResponse) {
  return writeMatchCacheRaw(hash, semantic, data, token);
}
function clearMatchCache() {
  return clearMatchCacheRaw(token);
}

const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

function makeResult(id: string, bucket: MatchResult['bucket'] = 'good_match'): MatchResult {
  return {
    opportunity_id: id,
    eligibility_score: 70, readiness_score: 60, upside_score: 50, final_score: 65,
    bucket, reasons_fit: ['fit'], reasons_gap: [], next_steps: ['apply'],
    opportunity: {
      id, title: `Title ${id}`, organization: 'UIUC',
      // A reviewed source type: an unreviewed one is no longer actionable, so
      // without this every cache fixture would be a page of dead rows and the
      // accept/reject tests would all pass for the wrong reason.
      source_type: 'campus_program',
      record_kind: 'listing',
      description_clean: 'x'.repeat(500),
      // Every live result carries a truth; the cache refuses a page without
      // one, so the default fixture has to look like what the server sends.
      target_truth: { ...ACTIONABLE_TRUTH },
      eligibility: { international_friendly: 'yes', skills_required: ['Python'], eligibility_text_raw: 'y'.repeat(400) },
      application: { application_url: 'http://a', requires_resume: 'yes', contact_method: 'email' },
      metadata: { notes: 'z'.repeat(400) },
    } as never,
  };
}

function makeResponse(n = 3): MatchesResponse {
  return {
    total: n, high_priority: 0, good_match: n, reach: 0, low_fit: 0,
    results: Array.from({ length: n }, (_, i) => makeResult(`o${i}`)),
    contract_version: MATCH_VIEW_CONTRACT_VERSION,
    target_truth_contract: TARGET_TRUTH_CONTRACT,
  };
}

describe('match-cache target-truth fail-close', () => {
  beforeEach(async () => {
    localStorage.clear();
    advanceOwnerEpoch('truth-fail-close-uid');
    await syncLocalIdentityOwner('truth-fail-close-uid');
    token = captureOwnerToken();
  });

  const BAD_TRUTHS: [string, unknown][] = [
    ['missing', undefined],
    ['null', null],
    ['malformed', { listing_state: 'open' }],
    ['closed', {
      ...ACTIONABLE_TRUTH, actionable: false,
      listing_state: 'closed', accepting_state: 'not_accepting',
      reason_code: 'listing_closed',
    }],
    ['reference-only', {
      ...ACTIONABLE_TRUTH, actionable: false,
      reference_only: true, reason_code: 'reference_only',
    }],
    ['inactive', { ...ACTIONABLE_TRUTH, actionable: false, reason_code: 'inactive' }],
    ['self-contradicting', { ...ACTIONABLE_TRUTH, listing_state: 'closed' }],
  ];

  it.each(BAD_TRUTHS)('refuses to persist a page containing a %s truth', (_label, truth) => {
    const response = makeResponse(3);
    const target = response.results[1].opportunity as unknown as Record<string, unknown>;
    if (truth === undefined) delete target.target_truth;
    else target.target_truth = truth;

    // Whole page, not just the bad row: silently dropping it would leave the
    // stored counts describing a page that can no longer be rendered.
    expect(writeMatchCache('h', false, response)).toBe(false);
    expect(readMatchCache('h', false)).toBeNull();
  });

  it('keeps the record-kind attestation across a round trip', () => {
    // `readTruth` cross-checks the wire kind against the source type, so a
    // restored row that lost it would be validated against half the
    // attestation it arrived with — and a mismatch this build refuses live
    // would become invisible on a cache hit.
    expect(writeMatchCache('h', false, makeResponse(1))).toBe(true);
    const back = readMatchCache('h', false);
    expect(
      (back!.results[0].opportunity as unknown as Record<string, unknown>).record_kind,
    ).toBe('listing');
  });

  it('refuses a stored row whose wire kind stopped matching its source type', () => {
    expect(writeMatchCache('h', false, makeResponse(2))).toBe(true);
    const raw = JSON.parse(localStorage.getItem(MATCH_KEY)!);
    raw.results[1].opportunity.record_kind = 'faculty_contact';
    localStorage.setItem(MATCH_KEY, JSON.stringify(raw));

    // Not a row we can vouch for, so the page is refused and cleared whole —
    // the same all-or-nothing rule a bad truth gets.
    expect(readMatchCache('h', false)).toBeNull();
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });

  it('discards the precisely-previous cache version, marker and truth notwithstanding', () => {
    // The version bump is the only thing that retires a pre-target-truth
    // page, and it is easy to lose: revert the string and every existing
    // device silently keeps serving its old cache.
    //
    // The planted entry is the adversarial case — the immediately preceding
    // CACHE_VERSION, but otherwise perfect: current marker, current wire
    // version, every row carrying a valid actionable truth. Nothing about its
    // CONTENT is refusable, so if this is still readable, the bump is gone.
    const PREVIOUS_CACHE_VERSION = 'mvp-core-close-v1-contact-trust-v1-target-truth-v1';
    expect(writeMatchCache('h', false, makeResponse(3))).toBe(true);
    const planted = JSON.parse(localStorage.getItem(MATCH_KEY)!);
    expect(planted.version).not.toBe(PREVIOUS_CACHE_VERSION);
    planted.version = PREVIOUS_CACHE_VERSION;
    localStorage.setItem(MATCH_KEY, JSON.stringify(planted));

    expect(readMatchCache('h', false)).toBeNull();
    // Cleared, not merely ignored: a stale entry left in place keeps the
    // quota occupied and reappears the moment the version string changes.
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });

  it.each(BAD_TRUTHS)('rejects and clears a stored page containing a %s truth', (_label, truth) => {
    expect(writeMatchCache('h', false, makeResponse(3))).toBe(true);
    expect(readMatchCache('h', false)).not.toBeNull();

    // Poison one row in place, as a corpus refresh would.
    const raw = JSON.parse(localStorage.getItem(MATCH_KEY)!);
    if (truth === undefined) delete raw.results[1].opportunity.target_truth;
    else raw.results[1].opportunity.target_truth = truth;
    localStorage.setItem(MATCH_KEY, JSON.stringify(raw));

    expect(readMatchCache('h', false)).toBeNull();
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });

  // Both halves are required, and both are exact. The marker says the backend
  // makes a promise about target truth; the version says which wire shape the
  // rows arrive in. Neither substitutes for the other.
  it('accepts and round-trips the wire this backend speaks', () => {
    const response = {
      ...makeResponse(2),
      contract_version: 'match-view-v3-faculty-trust',
      target_truth_contract: TARGET_TRUTH_CONTRACT,
    };
    expect(writeMatchCache('h', false, response)).toBe(true);
    const back = readMatchCache('h', false);
    expect(back).not.toBeNull();
    // The marker survives the round-trip. Without it the entry would fail its
    // own read check — a cache that never hits, which looks like a working
    // guard and is really a disabled one.
    expect(back!.target_truth_contract).toBe(TARGET_TRUTH_CONTRACT);
    expect(back!.contract_version).toBe('match-view-v3-faculty-trust');
    expect(back!.results).toHaveLength(2);
  });

  it('refuses to store a version nobody has negotiated, marker or not', () => {
    // `match-view-v4-target-truth` was once pre-accepted here so a future
    // rename could not break clients in the wild. That trades a real risk for
    // a hypothetical one: nothing emits v4, so the only payload that could
    // ever arrive under it is one whose fields were never agreed — and this
    // client would have stored it for seven days.
    const response = {
      ...makeResponse(2), contract_version: 'match-view-v4-target-truth',
    };
    expect(writeMatchCache('h', false, response)).toBe(false);
    expect(readMatchCache('h', false)).toBeNull();
  });

  it('leaves a good stored page alone when an unnegotiated version arrives', () => {
    // Refusing is refusing, not erasing. A v4 response showing up is no
    // evidence that the v3 page already on the device went bad, and dropping
    // it would cost the student their instant return-to-results for nothing.
    expect(writeMatchCache('h', false, makeResponse(2))).toBe(true);
    const stored = localStorage.getItem(MATCH_KEY);

    expect(writeMatchCache('h', false, {
      ...makeResponse(1), contract_version: 'match-view-v4-target-truth',
    })).toBe(false);

    expect(localStorage.getItem(MATCH_KEY)).toBe(stored);
    expect(readMatchCache('h', false)!.results).toHaveLength(2);
  });

  it('rejects and clears an already-stored page whose version is not accepted', () => {
    // The upgrade path that matters: a build that DID pre-accept v4 wrote
    // this entry, and the student's next visit runs this build. Read has to
    // refuse it on its own, not merely stop writing new ones.
    expect(writeMatchCache('h', false, makeResponse(2))).toBe(true);
    const raw = JSON.parse(localStorage.getItem(MATCH_KEY)!);
    raw.contract_version = 'match-view-v4-target-truth';
    localStorage.setItem(MATCH_KEY, JSON.stringify(raw));

    expect(readMatchCache('h', false)).toBeNull();
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });

  it.each([
    ['no marker at all', undefined],
    ['an empty marker', ''],
    ['an unknown marker', 'target-truth-v9'],
  ])('rejects a page with %s, whatever its version says', (_label, marker) => {
    const response = {
      ...makeResponse(2), target_truth_contract: marker,
    } as never;
    expect(writeMatchCache('h', false, response)).toBe(false);
    expect(readMatchCache('h', false)).toBeNull();
  });

  it('rejects a marker-less EMPTY page too', () => {
    // Nothing to inspect row by row, so the marker is the only evidence.
    const response = { ...makeResponse(0), target_truth_contract: undefined } as never;
    expect(writeMatchCache('h', false, response)).toBe(false);
    expect(readMatchCache('h', false)).toBeNull();
  });

  it('accepts an EMPTY page that carries the marker', () => {
    const response = { ...makeResponse(0) };
    expect(writeMatchCache('h', false, response)).toBe(true);
    expect(readMatchCache('h', false)).not.toBeNull();
  });

  it('rejects an unknown wire version even with a valid marker', () => {
    const response = { ...makeResponse(2), contract_version: 'match-view-v9-future' };
    expect(writeMatchCache('h', false, response)).toBe(false);
    expect(readMatchCache('h', false)).toBeNull();
  });

  it.each([
    ['a blank top-level id', (r: Record<string, unknown>) => { r.opportunity_id = '   '; }],
    ['a missing top-level id', (r: Record<string, unknown>) => { delete r.opportunity_id; }],
    ['a nested id that drifted', (r: Record<string, unknown>) => {
      (r.opportunity as Record<string, unknown>).id = 'someone-else';
    }],
  ])('refuses to write a page with %s, leaving storage untouched', (_label, poison) => {
    // Validated before the write, not cleaned up after it: storing first would
    // leave the only copy on the device one we would refuse, and would charge
    // the user a write for a page that can never be read back.
    const response = makeResponse(3);
    poison(response.results[1] as unknown as Record<string, unknown>);

    expect(writeMatchCache('h', false, response)).toBe(false);
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });

  it('refuses to write a page with duplicate ids, leaving storage untouched', () => {
    const response = makeResponse(2);
    response.results[1] = JSON.parse(JSON.stringify(response.results[0]));

    expect(writeMatchCache('h', false, response)).toBe(false);
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });

  it('does not overwrite a good entry with a rejected one', () => {
    expect(writeMatchCache('good', false, makeResponse(2))).toBe(true);
    const before = localStorage.getItem(MATCH_KEY);

    const poisoned = makeResponse(2);
    (poisoned.results[0] as unknown as Record<string, unknown>).opportunity_id = '';
    expect(writeMatchCache('bad', false, poisoned)).toBe(false);

    expect(localStorage.getItem(MATCH_KEY)).toBe(before);
    expect(readMatchCache('good', false)).not.toBeNull();
  });

  it('clears a stored entry written before the marker existed', () => {
    expect(writeMatchCache('h', false, makeResponse(2))).toBe(true);
    const raw = JSON.parse(localStorage.getItem(MATCH_KEY)!);
    delete raw.target_truth_contract;
    localStorage.setItem(MATCH_KEY, JSON.stringify(raw));

    expect(readMatchCache('h', false)).toBeNull();
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });
});

describe('match-cache', () => {
  beforeEach(async () => {
    localStorage.clear();
    advanceOwnerEpoch('match-cache-test-uid');
    await syncLocalIdentityOwner('match-cache-test-uid');
    token = captureOwnerToken();
  });

  it('projects opportunities to display fields (drops metadata, raw desc, truncates clean)', () => {
    writeMatchCache('h1', false, makeResponse(1));
    const raw = localStorage.getItem(MATCH_KEY)!;
    // Pinned as a literal on purpose: this version string is what invalidates
    // seven-day local payloads when the record-visibility contract moves, so
    // moving it has to be a deliberate edit here too. `-pubtrust-v3` is the
    // historical publication remediation — a page cached before it holds
    // citations the server has since withdrawn.
    expect(JSON.parse(raw).version).toBe(
      'mvp-core-close-v1-contact-trust-v1-target-truth-v2-pubtrust-v3',
    );
    expect(raw).not.toContain('"metadata"');
    expect(raw).not.toContain('eligibility_text_raw');
    expect(raw).not.toContain('x'.repeat(500)); // full description not stored
    expect(raw).toContain('x'.repeat(200)); // 200-char snippet kept
    expect(raw).toContain('international_friendly');
    expect(raw).toContain('application_url');
  });

  it('reads back synchronously with projected opportunities and counts', () => {
    writeMatchCache('h1', false, makeResponse(2));
    const out = readMatchCache('h1', false);
    expect(out).not.toBeNull();
    expect(out!.results).toHaveLength(2);
    expect(out!.good_match).toBe(2);
    const opp = out!.results[0].opportunity as unknown as Record<string, unknown>;
    expect(opp.title).toBe('Title o0');
    expect(opp.metadata).toBeUndefined();
    expect((opp.eligibility as Record<string, unknown>).international_friendly).toBe('yes');
    expect((opp.eligibility as Record<string, unknown>).eligibility_text_raw).toBeUndefined();
  });

  it('preserves source_type so the faculty CTA survives a cache-hit return', () => {
    // Regression guard for the honest faculty CTA (#218, regressed in #368):
    // without source_type, MatchCard renders a green "Apply Now" that
    // dead-ends on the professor's bio page instead of the safe draft/profile
    // actions.
    const resp = makeResponse(1);
    const target = resp.results[0].opportunity as unknown as Record<string, unknown>;
    target.source_type = 'faculty_research';
    // The wire kind travels with the source type; leaving the listing default
    // behind would be a mismatch the cache correctly refuses.
    target.record_kind = 'faculty_contact';
    target.target_truth = {
      listing_state: 'unknown', reference_only: false, actionable: true,
      accepting_state: 'unknown', reason_code: null,
      verified_at: null, expires_at: null,
    };
    writeMatchCache('h1', false, resp);
    const out = readMatchCache('h1', false)!;
    const opp = out.results[0].opportunity as unknown as Record<string, unknown>;
    expect(opp.source_type).toBe('faculty_research');
  });

  it('preserves a source-backed faculty stop status across a cache hit', () => {
    const resp = makeResponse(1);
    const target = resp.results[0].opportunity as unknown as Record<string, unknown>;
    target.source_type = 'faculty_research';
    // The wire kind travels with the source type; leaving the listing default
    // behind would be a mismatch the cache correctly refuses.
    target.record_kind = 'faculty_contact';
    target.target_truth = {
      listing_state: 'unknown', reference_only: false, actionable: true,
      accepting_state: 'unknown', reason_code: null,
      verified_at: null, expires_at: null,
    };
    resp.results[0].opportunity.faculty_availability_status =
      'not_accepting_undergraduates';

    writeMatchCache('h1', false, resp);
    const hit = readMatchCache('h1', false);
    expect(hit?.results[0].opportunity.faculty_availability_status).toBe(
      'not_accepting_undergraduates',
    );
  });

  it('preserves school + audience so the scope facet survives a cache-hit return', () => {
    // Regression guard for the discovery-scope facet (PR #191): if these
    // fields are dropped on projection, every cache-hit return strips scope
    // metadata — the facet hides itself and a persisted scope=campus filters
    // to zero results. school: null (national records) must round-trip too.
    const resp = makeResponse(2);
    (resp.results[0].opportunity as unknown as Record<string, unknown>).school = 'uiuc';
    (resp.results[0].opportunity as unknown as Record<string, unknown>).audience = 'campus';
    (resp.results[1].opportunity as unknown as Record<string, unknown>).school = null;
    (resp.results[1].opportunity as unknown as Record<string, unknown>).audience = 'open';
    writeMatchCache('h1', false, resp);
    const out = readMatchCache('h1', false)!;
    const a = out.results[0].opportunity as unknown as Record<string, unknown>;
    const b = out.results[1].opportunity as unknown as Record<string, unknown>;
    expect(a.school).toBe('uiuc');
    expect(a.audience).toBe('campus');
    expect(b.school).toBeNull(); // national record: null must survive, not become undefined
    expect(b.audience).toBe('open');
  });

  it('ai_reason and recent_works survive the cache round-trip', () => {
    // Both back the card's new lead line / recent-work line; dropping them on
    // a cache-hit return would silently strip the personalization.
    const resp = makeResponse(1);
    (resp.results[0] as unknown as Record<string, unknown>).ai_reason =
      'Their vision work matches your CV interest.';
    (resp.results[0].opportunity as unknown as Record<string, unknown>).recent_works = [
      { title: 'Paper A', year: 2025 },
    ];
    writeMatchCache('h1', false, resp);
    const out = readMatchCache('h1', false)!;
    const r = out.results[0] as unknown as Record<string, unknown>;
    expect(r.ai_reason).toBe('Their vision work matches your CV interest.');
    expect((r.opportunity as Record<string, unknown>).recent_works).toEqual([
      { title: 'Paper A', year: 2025 },
    ]);
  });

  it('hasMatchCache reflects presence', () => {
    expect(hasMatchCache()).toBe(false);
    writeMatchCache('h1', false, makeResponse());
    expect(hasMatchCache()).toBe(true);
  });

  it('does not read the pre-release-scope v4 cache', () => {
    localStorage.setItem(ORIGINAL_MATCH_KEY, '{"contact":"legacy@example.edu"}');
    localStorage.setItem(
      LEGACY_RELEASE_SCOPE_KEY,
      JSON.stringify({
        hash: 'h1',
        semantic: false,
        savedAt: Date.now(),
        total: 1,
        high_priority: 0,
        good_match: 1,
        reach: 0,
        low_fit: 0,
        results: [makeResult('hidden-fellowship')],
      }),
    );

    expect(MATCH_KEY).toBe('ofe_match_results_v7');
    expect(hasMatchCache()).toBe(false);
    expect(readMatchCache('h1', false)).toBeNull();
    expect(localStorage.getItem(ORIGINAL_MATCH_KEY)).toBeNull();
    expect(localStorage.getItem(LEGACY_RELEASE_SCOPE_KEY)).toBeNull();
  });

  it('does not read the pre-contact-trust v6 cache', () => {
    localStorage.setItem(
      PRE_CONTACT_TRUST_KEY,
      JSON.stringify({
        hash: 'h1',
        semantic: false,
        savedAt: Date.now(),
        total: 1,
        high_priority: 0,
        good_match: 1,
        reach: 0,
        low_fit: 0,
        results: [makeResult('contact-bearing')],
      }),
    );

    expect(hasMatchCache()).toBe(false);
    expect(readMatchCache('h1', false)).toBeNull();
    expect(localStorage.getItem(PRE_CONTACT_TRUST_KEY)).toBeNull();
  });

  it('rejects and removes an unversioned payload under the current key', () => {
    localStorage.setItem(
      MATCH_KEY,
      JSON.stringify({
        hash: 'h1',
        semantic: false,
        savedAt: Date.now(),
        total: 1,
        high_priority: 0,
        good_match: 1,
        reach: 0,
        low_fit: 0,
        results: [makeResult('contact-bearing')],
      }),
    );

    expect(hasMatchCache()).toBe(false);
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });

  it('rejects and removes the open-capability cache version under the current key', () => {
    const response = makeResponse(1);
    response.results[0].opportunity.opportunity_type = 'fellowship';
    localStorage.setItem(
      MATCH_KEY,
      JSON.stringify({
        version: 'contact-trust-v1',
        hash: 'h1',
        semantic: false,
        savedAt: Date.now(),
        ...response,
      }),
    );

    expect(readMatchCache('h1', false)).toBeNull();
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });

  it('does not re-stamp a pre-contact-trust backend response as a v7 cache', () => {
    writeMatchCache('h1', false, {
      ...makeResponse(1),
      contract_version: 'match-view-v1',
    });

    expect(hasMatchCache()).toBe(false);
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });

  it('misses on a different profile hash or semantic mode', () => {
    writeMatchCache('h1', false, makeResponse());
    expect(readMatchCache('h2', false)).toBeNull();
    expect(readMatchCache('h1', true)).toBeNull();
  });

  it('expires after the TTL', () => {
    writeMatchCache('h1', false, makeResponse());
    const c = JSON.parse(localStorage.getItem(MATCH_KEY)!);
    c.savedAt = Date.now() - 8 * 24 * 60 * 60 * 1000;
    localStorage.setItem(MATCH_KEY, JSON.stringify(c));
    expect(hasMatchCache()).toBe(false);
    expect(readMatchCache('h1', false)).toBeNull();
  });

  it('caps the cached server-view page but keeps complete server counts', () => {
    const big = makeResponse(2700);
    big.total = 2700; big.good_match = 2700;
    writeMatchCache('h1', false, big);
    const out = readMatchCache('h1', false)!;
    expect(out.results.length).toBe(100); // one bounded page
    expect(out.good_match).toBe(2700); // counts preserved
  });

  it('clearMatchCache removes the entry', () => {
    writeMatchCache('h1', false, makeResponse());
    clearMatchCache();
    expect(hasMatchCache()).toBe(false);
  });

  it('round-trips field_relevant_count, thin_inventory and matcher_version', () => {
    // These previously vanished on every cache hit — the "N strong matches in
    // your field" header line silently disappeared on return visits.
    const resp = { ...makeResponse(), field_relevant_count: 7, thin_inventory: true, matcher_version: '3.abc12345' };
    writeMatchCache('h1', false, resp);
    const out = readMatchCache('h1', false)!;
    expect(out.field_relevant_count).toBe(7);
    expect(out.thin_inventory).toBe(true);
    expect(out.matcher_version).toBe('3.abc12345');
  });

  it('cachedMatcherVersion exposes the stored version (null when absent)', () => {
    expect(cachedMatcherVersion()).toBeNull();
    writeMatchCache('h1', false, { ...makeResponse(), matcher_version: '3.abc12345' });
    expect(cachedMatcherVersion()).toBe('3.abc12345');
    clearMatchCache();
    expect(cachedMatcherVersion()).toBeNull();
  });

  describe('hasValidMatchResultIdentity', () => {
    it('accepts a well-formed result set (top-level id === nested id, no dupes)', () => {
      expect(hasValidMatchResultIdentity(makeResponse(3).results)).toBe(true);
    });

    it('accepts an empty result set', () => {
      expect(hasValidMatchResultIdentity([])).toBe(true);
    });

    it('rejects a non-array', () => {
      expect(hasValidMatchResultIdentity(null)).toBe(false);
      expect(hasValidMatchResultIdentity(undefined)).toBe(false);
      expect(hasValidMatchResultIdentity('not-an-array')).toBe(false);
    });

    it('rejects a missing top-level opportunity_id', () => {
      const results = makeResponse(1).results;
      delete (results[0] as unknown as Record<string, unknown>).opportunity_id;
      expect(hasValidMatchResultIdentity(results)).toBe(false);
    });

    it('rejects an empty-string top-level opportunity_id', () => {
      const results = makeResponse(1).results;
      results[0].opportunity_id = '';
      expect(hasValidMatchResultIdentity(results)).toBe(false);
    });

    it('rejects a whitespace-only top-level opportunity_id, even when the nested id matches it raw', () => {
      const results = makeResponse(1).results;
      results[0].opportunity_id = '   ';
      (results[0].opportunity as unknown as Record<string, unknown>).id = '   ';
      expect(hasValidMatchResultIdentity(results)).toBe(false);
    });

    it('rejects a whitespace-only nested opportunity.id', () => {
      const results = makeResponse(1).results;
      (results[0].opportunity as unknown as Record<string, unknown>).id = '   ';
      // top-level id is untouched (non-whitespace), so this isolates the nested check.
      expect(hasValidMatchResultIdentity(results)).toBe(false);
    });

    it('does not normalize whitespace: ids differing only by surrounding whitespace still fail raw equality', () => {
      const results = makeResponse(1).results;
      const id = results[0].opportunity_id;
      (results[0].opportunity as unknown as Record<string, unknown>).id = ` ${id} `;
      expect(hasValidMatchResultIdentity(results)).toBe(false);
    });

    it('rejects a missing nested opportunity.id', () => {
      const results = makeResponse(1).results;
      delete (results[0].opportunity as unknown as Record<string, unknown>).id;
      expect(hasValidMatchResultIdentity(results)).toBe(false);
    });

    it('rejects a nested opportunity.id that does not match the top-level opportunity_id', () => {
      const results = makeResponse(1).results;
      (results[0].opportunity as unknown as Record<string, unknown>).id = 'drifted-id';
      expect(hasValidMatchResultIdentity(results)).toBe(false);
    });

    it('rejects duplicate opportunity_id across results', () => {
      const results = makeResponse(2).results;
      results[1].opportunity_id = results[0].opportunity_id;
      (results[1].opportunity as unknown as Record<string, unknown>).id = results[0].opportunity_id;
      expect(hasValidMatchResultIdentity(results)).toBe(false);
    });
  });

  it('readMatchCache fails closed and clears a cache whose nested id drifted from the top-level id', () => {
    writeMatchCache('h1', false, makeResponse(1));
    const raw = JSON.parse(localStorage.getItem(MATCH_KEY)!);
    raw.results[0].opportunity.id = 'drifted-id';
    localStorage.setItem(MATCH_KEY, JSON.stringify(raw));

    expect(readMatchCache('h1', false)).toBeNull();
    expect(hasMatchCache()).toBe(false);
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });

  it('readMatchCache fails closed and clears a cache with duplicate result ids', () => {
    writeMatchCache('h1', false, makeResponse(2));
    const raw = JSON.parse(localStorage.getItem(MATCH_KEY)!);
    raw.results[1].opportunity_id = raw.results[0].opportunity_id;
    raw.results[1].opportunity.id = raw.results[0].opportunity_id;
    localStorage.setItem(MATCH_KEY, JSON.stringify(raw));

    expect(readMatchCache('h1', false)).toBeNull();
    expect(localStorage.getItem(MATCH_KEY)).toBeNull();
  });
});

describe('match-cache: origin-token discipline, boolean returns, same-tab notification', () => {
  beforeEach(async () => {
    localStorage.clear();
    advanceOwnerEpoch('match-cache-token-test-uid');
    await syncLocalIdentityOwner('match-cache-token-test-uid');
    token = captureOwnerToken();
  });

  it('writeMatchCache returns true and dispatches "storage" on a real, current-token write', () => {
    const listener = vi.fn();
    window.addEventListener('storage', listener);
    try {
      const wrote = writeMatchCacheRaw('h1', false, makeResponse(1), token);
      expect(wrote).toBe(true);
    } finally {
      window.removeEventListener('storage', listener);
    }
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('a STALE token: writeMatchCache returns false, dispatches NOTHING, and never touches the CURRENT owner\'s real cache', async () => {
    const staleToken = token;
    advanceOwnerEpoch('match-cache-token-u2');
    await syncLocalIdentityOwner('match-cache-token-u2');
    const currentToken = captureOwnerToken();
    writeMatchCacheRaw('h1', false, makeResponse(1), currentToken); // U2's real cache

    const listener = vi.fn();
    window.addEventListener('storage', listener);
    try {
      const wrote = writeMatchCacheRaw('h2', true, makeResponse(3), staleToken);
      expect(wrote).toBe(false);
    } finally {
      window.removeEventListener('storage', listener);
    }
    expect(listener).not.toHaveBeenCalled();
    // U2's real cache is untouched — still readable under its own hash/mode.
    expect(readMatchCache('h1', false)).not.toBeNull();
    expect(readMatchCache('h1', false)!.total).toBe(1);
  });

  it('a valid token whose underlying write fails (quota) clears the now-stale old cache and notifies — never silently leaves a mismatched entry', () => {
    writeMatchCacheRaw('h1', false, makeResponse(1), token); // an existing, valid cache
    expect(readMatchCache('h1', false)).not.toBeNull();

    const original = window.localStorage;
    // Seeds the shared-owner marker too, not just MATCH_KEY: identity-owner's
    // write/remove gate also verifies ownership against the REAL browser-side
    // marker (not merely in-memory readiness), so a stub that only carries
    // the one key under test would make every write/remove attempt look
    // like a different browser and fail the gate before ever reaching
    // setItem/removeItem — never exercising the quota/verify-removal
    // behavior these tests exist to prove.
    const store = new Map<string, string>([
      [MATCH_KEY, original.getItem(MATCH_KEY)!],
      [STORAGE_KEYS.LOCAL_IDENTITY_OWNER, original.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER)!],
    ]);
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
        setItem: () => { throw new Error('QuotaExceededError'); },
        removeItem: (k: string) => { store.delete(k); },
        clear: () => store.clear(),
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        get length() { return store.size; },
      },
      configurable: true,
    });
    const listener = vi.fn();
    window.addEventListener('storage', listener);
    try {
      const wrote = writeMatchCacheRaw('h2', true, makeResponse(3), token);
      expect(wrote).toBe(false);
      // The OLD (now stale-relative-to-this-attempt) cache was dropped —
      // never left silently serving h1's data as if it were still current.
      expect(store.has(MATCH_KEY)).toBe(false);
    } finally {
      window.removeEventListener('storage', listener);
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
    expect(listener).toHaveBeenCalledTimes(1); // the clear notified same-tab readers
  });

  it('clearMatchCache returns true and dispatches "storage" when it actually removes the current-format key', () => {
    writeMatchCacheRaw('h1', false, makeResponse(1), token);
    const listener = vi.fn();
    window.addEventListener('storage', listener);
    try {
      const removed = clearMatchCacheRaw(token);
      expect(removed).toBe(true);
    } finally {
      window.removeEventListener('storage', listener);
    }
    expect(listener).toHaveBeenCalledTimes(1);
    expect(hasMatchCache()).toBe(false);
  });

  it('clearMatchCache with a STALE token returns false, dispatches nothing, and does not delete the CURRENT owner\'s cache', async () => {
    const staleToken = token;
    advanceOwnerEpoch('match-cache-clear-u2');
    await syncLocalIdentityOwner('match-cache-clear-u2');
    const currentToken = captureOwnerToken();
    writeMatchCacheRaw('h1', false, makeResponse(1), currentToken);

    const listener = vi.fn();
    window.addEventListener('storage', listener);
    try {
      const removed = clearMatchCacheRaw(staleToken);
      expect(removed).toBe(false);
    } finally {
      window.removeEventListener('storage', listener);
    }
    expect(listener).not.toHaveBeenCalled();
    expect(hasMatchCache()).toBe(true); // U2's cache survives the stale U1 clear attempt
  });

  it('a write fails (quota) AND its own fallback clear ALSO fails to verify removal (removeItem throws): reads fail closed for the REST of this session for this SAME owner, even though the old entry is genuinely still sitting in storage', () => {
    writeMatchCacheRaw('h1', false, makeResponse(1), token); // an existing, valid cache
    expect(readMatchCache('h1', false)).not.toBeNull();

    const original = window.localStorage;
    // Seeds the shared-owner marker too, not just MATCH_KEY: identity-owner's
    // write/remove gate also verifies ownership against the REAL browser-side
    // marker (not merely in-memory readiness), so a stub that only carries
    // the one key under test would make every write/remove attempt look
    // like a different browser and fail the gate before ever reaching
    // setItem/removeItem — never exercising the quota/verify-removal
    // behavior these tests exist to prove.
    const store = new Map<string, string>([
      [MATCH_KEY, original.getItem(MATCH_KEY)!],
      [STORAGE_KEYS.LOCAL_IDENTITY_OWNER, original.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER)!],
    ]);
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
        setItem: () => { throw new Error('QuotaExceededError'); },
        removeItem: () => { throw new Error('removeItem also fails'); },
        clear: () => store.clear(),
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        get length() { return store.size; },
      },
      configurable: true,
    });
    try {
      const wrote = writeMatchCacheRaw('h2', true, makeResponse(3), token);
      expect(wrote).toBe(false);
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
    // The underlying storage genuinely still holds the old h1 entry — the
    // clear never verifiably completed — but reads must not confidently
    // serve it as if the failure never happened.
    expect(hasMatchCache()).toBe(false);
    expect(readMatchCache('h1', false)).toBeNull();
  });

  it('a write fails (quota) AND its fallback clear cannot verify removal because removeItem silently no-ops (no throw, key still readable): same fail-closed outcome as an outright throw', () => {
    writeMatchCacheRaw('h1', false, makeResponse(1), token);
    expect(readMatchCache('h1', false)).not.toBeNull();

    const original = window.localStorage;
    // Seeds the shared-owner marker too, not just MATCH_KEY: identity-owner's
    // write/remove gate also verifies ownership against the REAL browser-side
    // marker (not merely in-memory readiness), so a stub that only carries
    // the one key under test would make every write/remove attempt look
    // like a different browser and fail the gate before ever reaching
    // setItem/removeItem — never exercising the quota/verify-removal
    // behavior these tests exist to prove.
    const store = new Map<string, string>([
      [MATCH_KEY, original.getItem(MATCH_KEY)!],
      [STORAGE_KEYS.LOCAL_IDENTITY_OWNER, original.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER)!],
    ]);
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
        setItem: () => { throw new Error('QuotaExceededError'); },
        removeItem: () => { /* silent no-op — never actually deletes */ },
        clear: () => store.clear(),
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        get length() { return store.size; },
      },
      configurable: true,
    });
    try {
      const wrote = writeMatchCacheRaw('h2', true, makeResponse(3), token);
      expect(wrote).toBe(false);
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
    expect(hasMatchCache()).toBe(false);
    expect(readMatchCache('h1', false)).toBeNull();
  });

  it('a tainted owner never blocks a DIFFERENT (later, genuinely current) owner — a real identity transition is not the same owner+epoch the failed cleanup happened under', async () => {
    writeMatchCacheRaw('h1', false, makeResponse(1), token);

    const original = window.localStorage;
    // Seeds the shared-owner marker too, not just MATCH_KEY: identity-owner's
    // write/remove gate also verifies ownership against the REAL browser-side
    // marker (not merely in-memory readiness), so a stub that only carries
    // the one key under test would make every write/remove attempt look
    // like a different browser and fail the gate before ever reaching
    // setItem/removeItem — never exercising the quota/verify-removal
    // behavior these tests exist to prove.
    const store = new Map<string, string>([
      [MATCH_KEY, original.getItem(MATCH_KEY)!],
      [STORAGE_KEYS.LOCAL_IDENTITY_OWNER, original.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER)!],
    ]);
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
        setItem: () => { throw new Error('QuotaExceededError'); },
        removeItem: () => { throw new Error('removeItem also fails'); },
        clear: () => store.clear(),
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        get length() { return store.size; },
      },
      configurable: true,
    });
    try {
      writeMatchCacheRaw('h2', true, makeResponse(3), token);
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
    expect(hasMatchCache()).toBe(false); // tainted for the U1 owner+epoch that failed

    advanceOwnerEpoch('match-cache-token-taint-u2');
    await syncLocalIdentityOwner('match-cache-token-taint-u2');
    const u2Token = captureOwnerToken();
    expect(hasMatchCache()).toBe(false); // fresh owner, nothing written yet — not "still tainted"
    const wrote = writeMatchCacheRaw('u2-hash', false, makeResponse(2), u2Token);
    expect(wrote).toBe(true);
    expect(readMatchCache('u2-hash', false)).not.toBeNull();
  });

  it('a deferred U1 write that resolves AFTER U2 becomes the current owner never lands in U2\'s cache slot', async () => {
    // Simulates use-results-data.ts's own pattern: cacheToken captured at
    // request-start, the actual write happening only after an await.
    const u1Token = token;
    advanceOwnerEpoch('match-cache-deferred-u2');
    await syncLocalIdentityOwner('match-cache-deferred-u2');
    const u2Token = captureOwnerToken();
    // U2 has already written their own real, current results.
    writeMatchCacheRaw('u2-hash', false, makeResponse(2), u2Token);

    // U1's stale, deferred response finally arrives and is written with
    // U1's ORIGIN token (captured before the switch) — not a fresh one.
    const wrote = writeMatchCacheRaw('u1-hash', false, makeResponse(5), u1Token);

    expect(wrote).toBe(false);
    // U2's cache is exactly what U2 wrote — never overwritten by U1's
    // stale response landing under u1-hash.
    expect(readMatchCache('u1-hash', false)).toBeNull();
    const u2Cache = readMatchCache('u2-hash', false);
    expect(u2Cache).not.toBeNull();
    expect(u2Cache!.total).toBe(2);
  });
});
