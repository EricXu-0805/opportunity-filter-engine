import { describe, it, expect, vi, beforeEach } from 'vitest';

import {
  clearMatchCache,
  hasMatchCache,
  readMatchCache,
  writeMatchCache,
} from './match-cache';
import type { MatchesResponse } from './types';

const getOpportunitiesByIds = vi.fn((ids: string[]) =>
  Promise.resolve(
    ids.map((id) => ({ id, title: `Opp ${id}`, contact_email: 'secret@x.edu', pi_email: 'pi@x.edu' })),
  ),
);
vi.mock('@/lib/api', () => ({
  getOpportunitiesByIds: (ids: string[]) => getOpportunitiesByIds(ids),
}));

function makeResponse(): MatchesResponse {
  return {
    total: 2, high_priority: 1, good_match: 1, reach: 0, low_fit: 0,
    results: [
      {
        opportunity_id: 'o1', eligibility_score: 90, readiness_score: 80, upside_score: 70,
        final_score: 88, bucket: 'high_priority', reasons_fit: ['fit'], reasons_gap: [], next_steps: ['apply'],
        opportunity: { id: 'o1', title: 'Big heavy body', contact_email: 'a@x.edu' } as never,
      },
      {
        opportunity_id: 'o2', eligibility_score: 60, readiness_score: 55, upside_score: 50,
        final_score: 57, bucket: 'good_match', reasons_fit: [], reasons_gap: ['gap'], next_steps: [],
        opportunity: { id: 'o2', title: 'Another body' } as never,
      },
    ],
  };
}

describe('match-cache', () => {
  beforeEach(() => {
    localStorage.clear();
    getOpportunitiesByIds.mockClear();
  });

  it('stores a compact copy (no opportunity bodies) and reports presence', () => {
    writeMatchCache('h1', false, makeResponse());
    expect(hasMatchCache()).toBe(true);
    const raw = localStorage.getItem('ofe_match_results')!;
    expect(raw).not.toContain('Big heavy body'); // opportunity body stripped
    expect(raw).toContain('o1'); // ids + scores kept
  });

  it('re-hydrates opportunities by id and strips redacted fields on read', async () => {
    writeMatchCache('h1', false, makeResponse());
    const out = await readMatchCache('h1', false);
    expect(out).not.toBeNull();
    expect(getOpportunitiesByIds).toHaveBeenCalledWith(['o1', 'o2']);
    expect(out!.results).toHaveLength(2);
    expect(out!.results[0].opportunity.title).toBe('Opp o1');
    expect((out!.results[0].opportunity as unknown as Record<string, unknown>).contact_email).toBeUndefined();
    expect((out!.results[0].opportunity as unknown as Record<string, unknown>).pi_email).toBeUndefined();
    expect(out!.high_priority).toBe(1);
  });

  it('misses on a different profile hash or semantic mode', async () => {
    writeMatchCache('h1', false, makeResponse());
    expect(await readMatchCache('h2', false)).toBeNull();
    expect(await readMatchCache('h1', true)).toBeNull();
  });

  it('expires after the TTL', async () => {
    writeMatchCache('h1', false, makeResponse());
    const c = JSON.parse(localStorage.getItem('ofe_match_results')!);
    c.savedAt = Date.now() - 8 * 24 * 60 * 60 * 1000; // 8 days ago
    localStorage.setItem('ofe_match_results', JSON.stringify(c));
    expect(hasMatchCache()).toBe(false);
    expect(await readMatchCache('h1', false)).toBeNull();
  });

  it('drops results whose opportunity no longer exists', async () => {
    writeMatchCache('h1', false, makeResponse());
    getOpportunitiesByIds.mockResolvedValueOnce([
      { id: 'o1', title: 'Opp o1', contact_email: '', pi_email: '' },
    ]); // o2 gone
    const out = await readMatchCache('h1', false);
    expect(out!.results.map((r) => r.opportunity_id)).toEqual(['o1']);
  });

  it('clearMatchCache removes the entry', () => {
    writeMatchCache('h1', false, makeResponse());
    clearMatchCache();
    expect(hasMatchCache()).toBe(false);
  });
});
