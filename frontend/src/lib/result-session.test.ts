import { beforeEach, describe, expect, it, vi } from 'vitest';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { discardResultSession, publicResultsUrl, readResultSession, RESULT_SESSION_PREFIX, resultListKey, resultRequestKey, resultSessionUrl, writeResultSession } from './result-session';
import type { MatchViewRequestState } from './api';
import type { ProfileData } from './types';

const input = {
  requestKey: 'accepted-profile:0:view', page: 2, cursors: [[1, null], [2, 'server-cursor']] as Array<[number, string | null]>,
  returnUrl: '/results?q=robotics&paid=yes', showDismissed: true,
  anchorId: 'opp-1', anchorOffset: 150, scrollY: 1500, viewedIds: ['opp-1'],
};
beforeEach(async () => {
  advanceOwnerEpoch('session-a');
  await syncLocalIdentityOwner('session-a');
});

describe('bounded result return tickets', () => {
  it('round-trips navigation metadata without storing rows or runtime epoch', () => {
    const saved = writeResultSession(input)!;
    expect(readResultSession(saved.id)).toEqual(saved);
    expect(saved.owner).toEqual({ uid: 'session-a', generation: captureOwnerToken().generation });
    expect(saved).not.toHaveProperty('results');
    expect(saved).not.toHaveProperty('profile');
    expect(saved.owner).not.toHaveProperty('epoch');
  });

  it('accepts the same persisted owner after runtime epoch changes, but refuses a stale token', async () => {
    const oldToken = captureOwnerToken();
    const saved = writeResultSession(input)!;
    advanceOwnerEpoch(null);
    advanceOwnerEpoch('session-a');
    await syncLocalIdentityOwner('session-a');
    expect(readResultSession(saved.id, oldToken)).toBeNull();
    expect(readResultSession(saved.id)).toEqual(saved);
  });

  it('refuses another account and the original account after its namespace was replaced', async () => {
    const saved = writeResultSession(input)!;
    advanceOwnerEpoch('session-b');
    await syncLocalIdentityOwner('session-b');
    expect(readResultSession(saved.id)).toBeNull();
    advanceOwnerEpoch('session-a');
    await syncLocalIdentityOwner('session-a');
    expect(readResultSession(saved.id)).toBeNull();
  });

  it.each([
    { page: 0 }, { page: 2.1 }, { page: 3 }, { cursors: [[2, 'cursor']] },
    { cursors: [[1, 'bad'], [2, 'cursor']] }, { cursors: [[1, null], [2, 'x'], [2, 'y']] },
    { cursors: [[1, null], [2, '']] }, { savedAt: Date.now() - 31 * 60_000 },
    { scrollY: -1 }, { returnUrl: '//evil.example/results' },
  ])('refuses malformed or expired persisted navigation: %j', (patch) => {
    const saved = writeResultSession(input)!;
    sessionStorage.setItem(RESULT_SESSION_PREFIX + saved.id, JSON.stringify({ ...saved, ...patch }));
    expect(readResultSession(saved.id)).toBeNull();
  });

  it('caps earlier visits, cursor chains, and viewed ids', () => {
    for (let i = 0; i < 12; i++) expect(writeResultSession(input)).not.toBeNull();
    expect(sessionStorage.length).toBe(8);
    const saved = writeResultSession({ ...input, page: 200,
      cursors: Array.from({ length: 200 }, (_, i) => [i + 1, i ? `cursor-${i}` : null]),
      viewedIds: Array.from({ length: 600 }, (_, i) => `opp-${i}`),
    })!;
    expect(saved.cursors).toHaveLength(128);
    expect(saved.cursors[0]).toEqual([1, null]);
    expect(saved.viewedIds).toHaveLength(512);
  });

  it('degrades safely when reading, writing, or removal is refused', () => {
    const saved = writeResultSession(input)!;
    const read = vi.spyOn(sessionStorage, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(readResultSession(saved.id)).toBeNull();
    read.mockRestore();
    vi.spyOn(sessionStorage, 'setItem').mockImplementation(() => { throw new Error('quota'); });
    expect(writeResultSession(input)).toBeNull();
    vi.spyOn(sessionStorage, 'removeItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(() => discardResultSession(saved.id)).not.toThrow();
  });
});

describe('public results return links', () => {
  it('keeps only public filters, stripping private tokens, page, and fragments', () => {
    expect(publicResultsUrl('/results?q=robotics&paid=yes&returnSession=private&page=2&uid=alice#anchor'))
      .toBe('/results?q=robotics&paid=yes');
    expect(resultSessionUrl('/results?q=robotics', '0123456789abcdef')).toBe('/results?q=robotics&returnSession=0123456789abcdef');
  });
  it.each(['https://evil.example/results', '//evil.example/results', '/results/other', '/results\\evil',
    '/results?q=hi\nthere', '/results?q=hi%0athere', '/results?q=%5Cevil', 'javascript:alert(1)'])('refuses unsafe route %s', (url) => {
    expect(publicResultsUrl(url)).toBeNull();
  });
});

describe('list key for a return ticket', () => {
  const profile: ProfileData = { institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false, research_interests: 'robots', skills: [] };
  const view: MatchViewRequestState = { tab: 'all', search_query: 'a:b "quoted"', paid: '', intl: '', source: '', on_campus: '', deadline: '', min_score: 0, scope: '', sort_by: 'score', show_dismissed: false, favorite_ids: [], dismissed_ids: [], today: '2026-09-24' };
  const list = (v: MatchViewRequestState, semantic = false) => resultListKey(resultRequestKey(profile, semantic, v));

  it('ignores only the star and dismissal sets', () => {
    expect(list(view)).not.toBeNull();
    expect(list({ ...view, favorite_ids: ['x'], dismissed_ids: ['y'] })).toBe(list(view));
    expect(list({ ...view, search_query: 'other' })).not.toBe(list(view));
    expect(list({ ...view, tab: 'starred' })).not.toBe(list(view));
    expect(list(view, true)).not.toBe(list(view));
    expect(resultListKey(resultRequestKey({ ...profile, major: 'Math' }, false, view))).not.toBe(list(view));
  });

  it('refuses a key it cannot parse rather than equating it with anything', () => {
    expect(resultListKey('accepted-profile:0:view')).toBeNull();
    expect(resultListKey('')).toBeNull();
  });
});
