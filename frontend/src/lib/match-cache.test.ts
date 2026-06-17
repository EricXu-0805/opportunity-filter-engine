import { describe, it, expect, beforeEach } from 'vitest';

import {
  clearMatchCache,
  hasMatchCache,
  readMatchCache,
  writeMatchCache,
} from './match-cache';
import { STORAGE_KEYS } from './storage-keys';
import type { MatchResult, MatchesResponse } from './types';

const MATCH_KEY = STORAGE_KEYS.MATCH_RESULTS;

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
  };
}

describe('match-cache', () => {
  beforeEach(() => { localStorage.clear(); });

  it('projects opportunities to display fields (drops metadata, raw desc, truncates clean)', () => {
    writeMatchCache('h1', false, makeResponse(1));
    const raw = localStorage.getItem(MATCH_KEY)!;
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

  it('hasMatchCache reflects presence', () => {
    expect(hasMatchCache()).toBe(false);
    writeMatchCache('h1', false, makeResponse());
    expect(hasMatchCache()).toBe(true);
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

  it('caps the cached results array but keeps the full counts', () => {
    const big = makeResponse(2700);
    big.total = 2700; big.good_match = 2700;
    writeMatchCache('h1', false, big);
    const out = readMatchCache('h1', false)!;
    expect(out.results.length).toBe(2500); // capped
    expect(out.good_match).toBe(2700); // counts preserved
  });

  it('clearMatchCache removes the entry', () => {
    writeMatchCache('h1', false, makeResponse());
    clearMatchCache();
    expect(hasMatchCache()).toBe(false);
  });
});
