import { describe, it, expect, beforeEach } from 'vitest';

import {
  MATCH_VIEW_CONTRACT_VERSION,
  cachedMatcherVersion,
  clearMatchCache,
  hasMatchCache,
  readMatchCache,
  writeMatchCache,
} from './match-cache';
import { STORAGE_KEYS } from './storage-keys';
import type { MatchResult, MatchesResponse } from './types';

const MATCH_KEY = STORAGE_KEYS.MATCH_RESULTS;
const ORIGINAL_MATCH_KEY = 'ofe_match_results';
const LEGACY_RELEASE_SCOPE_KEY = 'ofe_match_results_v4';
const PRE_CONTACT_TRUST_KEY = 'ofe_match_results_v6';

function makeResult(id: string, bucket: MatchResult['bucket'] = 'good_match'): MatchResult {
  return {
    opportunity_id: id,
    eligibility_score: 70, readiness_score: 60, upside_score: 50, final_score: 65,
    bucket, reasons_fit: ['fit'], reasons_gap: [], next_steps: ['apply'],
    opportunity: {
      id, title: `Title ${id}`, organization: 'UIUC',
      description_clean: 'x'.repeat(500),
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
  };
}

describe('match-cache', () => {
  beforeEach(() => { localStorage.clear(); });

  it('projects opportunities to display fields (drops metadata, raw desc, truncates clean)', () => {
    writeMatchCache('h1', false, makeResponse(1));
    const raw = localStorage.getItem(MATCH_KEY)!;
    expect(JSON.parse(raw).version).toBe('contact-trust-v1');
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
    // dead-ends on the professor's bio page instead of "Email Professor".
    const resp = makeResponse(1);
    (resp.results[0].opportunity as unknown as Record<string, unknown>).source_type =
      'faculty_research';
    writeMatchCache('h1', false, resp);
    const out = readMatchCache('h1', false)!;
    const opp = out.results[0].opportunity as unknown as Record<string, unknown>;
    expect(opp.source_type).toBe('faculty_research');
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
});
