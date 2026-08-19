import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  ApiError,
  getMatches,
  getMatchView,
  getOpportunities,
  getGapAnalysis,
  chatWithOpportunity,
  getMatchExplanation,
  getOpportunityById,
  getOpportunitiesByIds,
  getShortlistOpportunities,
  generateColdEmail,
  getEmailVariants,
  refineEmail,
  parseGitHubProfile,
  getStats,
  wakeBackend,
  getUpcomingDeadlines,
  sendMatchesEmail,
  sendFavoritesEmail,
  importByUrl,
  importByText,
  deriveDesiredFields,
} from './api';
import type { ProfileData } from './types';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function okJson<T>(body: T): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

function badResponse(status: number, body = ''): Response {
  return new Response(body, { status });
}

function makeProfile(overrides: Partial<ProfileData> = {}): ProfileData {
  return {
    institution: 'UIUC',
    college: 'Grainger',
    major: 'CS',
    grade: 'Sophomore',
    is_international: false,
    research_interests: 'machine learning',
    skills: [{ name: 'Python', level: 'experienced' }],
    coursework: ['CS 225'],
    ...overrides,
  };
}

describe('request<T> (internal helper, exercised through every endpoint)', () => {
  it('returns parsed JSON on 200', async () => {
    fetchMock.mockResolvedValue(okJson({ total: 0, opportunities: [] }));
    const result = await getOpportunities();
    expect(result).toEqual({ total: 0, opportunities: [] });
  });

  it('does not expose an unstructured 5xx body', async () => {
    fetchMock.mockResolvedValue(badResponse(500, 'server explode'));
    await expect(getOpportunities()).rejects.toThrow(
      'The service is temporarily unavailable. Please try again.',
    );
  });

  it('uses the same safe fallback when the error body cannot be read', async () => {
    /* Response.text() resolves successfully to "" for an empty body — it does
       not reject. So we install a Response stub whose .text() rejects to
       exercise the .catch(() => 'Unknown error') fallback. */
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.reject(new Error('stream gone')),
      json: () => Promise.resolve({}),
    } as unknown as Response);
    await expect(getOpportunities()).rejects.toThrow(
      'The service is temporarily unavailable. Please try again.',
    );
  });

  it('sets Content-Type: application/json on every JSON request', async () => {
    fetchMock.mockResolvedValue(okJson({ total: 0, opportunities: [] }));
    await getOpportunities();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('defaults API_BASE to /api when NEXT_PUBLIC_API_URL is unset', async () => {
    fetchMock.mockResolvedValue(okJson({ total: 0, opportunities: [] }));
    await getOpportunities();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe('/api/opportunities');
  });
});

describe('getMatches', () => {
  it('POSTs /matches with the profile body and an explicit deterministic flag', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile());
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toBe('/api/matches?llm=false');
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body as string);
    expect(body.school).toBe('UIUC');
    expect(body.major).toBe('CS');
    expect(body.year).toBe('sophomore');
    expect(body.research_interests_text).toBe('machine learning');
    expect(body.hard_skills).toEqual([{ name: 'Python', level: 'experienced' }]);
    expect(body.exploring).toBe(false);
    expect(body.include_cross_school).toBe(false);
  });

  it('sends exploring=true when the profile opts into explore mode', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile({ exploring: true }));
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.exploring).toBe(true);
  });

  it('sends accepted preferences through instead of stripping them', async () => {
    // Both families normalizeProfileForRelease guards are accepted now, so it
    // is a pass-through here. The enforced boundary is the server's
    // (_normalized_profile, tests/test_release_scope.py) — this one only stops
    // a stale local profile from re-showing a selector.
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile({
      include_cross_school: true,
      seeking_types: ['research', 'fellowship'],
    }));
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.include_cross_school).toBe(true);
    expect(body.seeking_type).toEqual(['research', 'fellowship']);
  });

  it('maps scholar_url into the request and defaults it to "" when absent', async () => {
    fetchMock.mockImplementation(async () =>
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile({ scholar_url: 'https://scholar.google.com/citations?user=ABC123&hl=en' }));
    const withUrl = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(withUrl.scholar_url).toBe('https://scholar.google.com/citations?user=ABC123&hl=en');

    await getMatches(makeProfile());
    const without = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string);
    expect(without.scholar_url).toBe('');
  });

  it('maps additional_majors to secondary_interests', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile({ additional_majors: ['Statistics', 'Data Science'] }));
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.secondary_interests).toEqual(['Statistics', 'Data Science']);
  });

  it('sends secondary_interests=[] for profiles that predate additional majors', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile());
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.secondary_interests).toEqual([]);
  });

  it('defaults home_school to uiuc for profiles that predate the switcher', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile());
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.home_school).toBe('uiuc');
    expect(body.school).toBe('UIUC');
  });

  it('sends the stored home_school slug and the matching display name', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile({ home_school: 'ucb' }));
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.home_school).toBe('ucb');
    expect(body.school).toBe('UC Berkeley');
  });

  it('fails closed to deterministic matching while AI Refine is outside release scope', async () => {
    // Fresh Response per call — this test fetches twice, and a shared
    // mockResolvedValue Response throws "Body has already been read" on the
    // second res.json() (CI Node enforces single-use bodies).
    fetchMock.mockImplementation(async () =>
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile(), { llm: true });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/matches?llm=false');
    // Still explicit rather than omitted: the server cannot infer a paid mode
    // from stale client state while the feature is closed.
    await getMatches(makeProfile(), { llm: false });
    expect(fetchMock.mock.calls[1][0]).toBe('/api/matches?llm=false');
  });
});

describe('getMatchView', () => {
  it('POSTs the complete view state and cursor in the body', async () => {
    fetchMock.mockResolvedValue(
      okJson({
        total: 0,
        high_priority: 0,
        good_match: 0,
        reach: 0,
        low_fit: 0,
        results: [],
        filtered_total: 0,
        view_counts: { all: 0, high_priority: 0, good_match: 0, reach: 0, starred: 0 },
        contract_version: 'match-view-v3-faculty-trust',
      }),
    );
    const view = {
      tab: 'starred' as const,
      search_query: 'ml',
      paid: 'yes' as const,
      intl: '' as const,
      source: 'uiuc_faculty',
      on_campus: '' as const,
      deadline: '30' as const,
      min_score: 70,
      scope: 'campus' as const,
      sort_by: 'score' as const,
      show_dismissed: false,
      favorite_ids: ['opp-1'],
      dismissed_ids: ['opp-2'],
      today: '2026-07-31',
    };
    await getMatchView(makeProfile(), view, {
      cursor: 'opaque-cursor',
      pageSize: 50,
    });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/matches/view?llm=false');
    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit).body as string,
    );
    expect(body.profile.major).toBe('CS');
    expect(body.view).toEqual(view);
    expect(body.page_size).toBe(50);
    expect(body.cursor).toBe('opaque-cursor');
  });

  it('fails closed when a caller asks for AI refine before release acceptance', async () => {
    // In the query, not the body: the server's spend backstop reads the query,
    // and this route is the one the results page calls. Sending nothing here is
    // how the toggle came to change the cache key and nothing else.
    fetchMock.mockResolvedValue(
      okJson({
        total: 0,
        high_priority: 0,
        good_match: 0,
        reach: 0,
        low_fit: 0,
        results: [],
        filtered_total: 0,
        view_counts: { all: 0, high_priority: 0, good_match: 0, reach: 0, starred: 0 },
        contract_version: 'match-view-v2-contact-trust',
      }),
    );
    const view = {
      tab: 'all' as const,
      search_query: '',
      paid: '' as const,
      intl: '' as const,
      source: '',
      on_campus: '' as const,
      deadline: '' as const,
      min_score: 0,
      scope: '' as const,
      sort_by: 'score' as const,
      show_dismissed: false,
      favorite_ids: [],
      dismissed_ids: [],
      today: '2026-07-31',
    };
    await getMatchView(makeProfile(), view, { llm: true });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/matches/view?llm=false');
  });

  it('never includes an HTML gateway body in the user-facing error', async () => {
    fetchMock.mockResolvedValue(
      badResponse(502, '<html><body>upstream trace and internal host</body></html>'),
    );
    const view = {
      tab: 'all' as const,
      search_query: '',
      paid: '' as const,
      intl: '' as const,
      source: '',
      on_campus: '' as const,
      deadline: '' as const,
      min_score: 0,
      scope: '' as const,
      sort_by: 'score' as const,
      show_dismissed: false,
      favorite_ids: [],
      dismissed_ids: [],
      today: '2026-07-31',
    };
    const promise = getMatchView(makeProfile(), view);
    await expect(promise).rejects.toThrow(
      'The service is temporarily unavailable. Please try again.',
    );
    await expect(promise).rejects.not.toThrow('upstream trace');
  });
});

describe('per-opportunity endpoints', () => {
  it('getGapAnalysis POSTs /matches/{id}/gaps with the encoded id', async () => {
    fetchMock.mockResolvedValue(
      okJson({ missing_skills: [], suggested_coursework: [], resume_tips: [], preparation_timeline: [] }),
    );
    await getGapAnalysis(makeProfile(), 'uiuc/cs:101');
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe('/api/matches/uiuc%2Fcs%3A101/gaps');
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST');
  });

  it('getMatchExplanation POSTs /matches/{id}/explain with the profile body', async () => {
    fetchMock.mockResolvedValue(
      okJson({
        explanation: '...',
        method: 'local',
        final_score: 80,
        bucket: 'good_match',
        reasons_fit: [],
        reasons_gap: [],
        eligibility_score: 1,
        readiness_score: 1,
        upside_score: 1,
      }),
    );
    await getMatchExplanation(makeProfile(), 'opp-1');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/matches/opp-1/explain?llm=false');
  });

  it('chatWithOpportunity passes profile through toProfileRequest when present', async () => {
    fetchMock.mockResolvedValue(okJson({ reply: 'hi', method: 'local' }));
    await chatWithOpportunity('opp-1', 'Tell me more', [], makeProfile());
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.message).toBe('Tell me more');
    expect(body.history).toEqual([]);
    expect(body.profile.school).toBe('UIUC');
  });

  it('chatWithOpportunity passes null profile through unchanged', async () => {
    fetchMock.mockResolvedValue(okJson({ reply: 'hi', method: 'local' }));
    await chatWithOpportunity('opp-1', 'Hi', [], null);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.profile).toBeNull();
  });

  it('getOpportunityById URL-encodes the id', async () => {
    fetchMock.mockResolvedValue(okJson({ id: 'x' }));
    await getOpportunityById('uiuc/cs:101');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/opportunities/uiuc%2Fcs%3A101');
  });
});

describe('getOpportunitiesByIds (batching)', () => {
  it('returns [] without hitting fetch when ids is empty', async () => {
    const result = await getOpportunitiesByIds([]);
    expect(result).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('POSTs a single batch when ids.length <= 200', async () => {
    fetchMock.mockResolvedValue(okJson({ opportunities: [{ id: 'a' }, { id: 'b' }] }));
    const result = await getOpportunitiesByIds(['a', 'b']);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/opportunities/batch');
    expect(result).toEqual([{ id: 'a' }, { id: 'b' }]);
  });

  it('chunks ids into 200-sized batches and flattens results', async () => {
    const ids = Array.from({ length: 450 }, (_, i) => `id-${i}`);
    fetchMock
      .mockResolvedValueOnce(okJson({ opportunities: Array.from({ length: 200 }, (_, i) => ({ id: `id-${i}` })) }))
      .mockResolvedValueOnce(okJson({ opportunities: Array.from({ length: 200 }, (_, i) => ({ id: `id-${200 + i}` })) }))
      .mockResolvedValueOnce(okJson({ opportunities: Array.from({ length: 50 }, (_, i) => ({ id: `id-${400 + i}` })) }));
    const result = await getOpportunitiesByIds(ids);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(result.length).toBe(450);
  });

  it('deduplicates ids before chunking', async () => {
    fetchMock.mockResolvedValue(okJson({ opportunities: [{ id: 'a' }] }));
    await getOpportunitiesByIds(['a', 'a', 'a']);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.ids).toEqual(['a']);
  });
});

describe('getShortlistOpportunities (fail-closed accounting)', () => {
  function batchBody(ids: string[]): { opportunities: { id: string }[]; requested: number; found: number } {
    const opportunities = ids.map((id) => ({ id }));
    return { opportunities, requested: ids.length, found: opportunities.length };
  }

  it('returns [] / [] without hitting fetch when ids is empty', async () => {
    const result = await getShortlistOpportunities([]);
    expect(result).toEqual({ opportunities: [], unavailableIds: [] });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('accepts a valid payload: ordered opportunities, no unavailable', async () => {
    fetchMock.mockResolvedValue(okJson(batchBody(['a', 'b'])));
    const result = await getShortlistOpportunities(['a', 'b']);
    expect(result).toEqual({ opportunities: [{ id: 'a' }, { id: 'b' }], unavailableIds: [] });
  });

  it('normalizes/dedupes requested ids while preserving first-request order', async () => {
    fetchMock.mockResolvedValue(okJson(batchBody(['b', 'a'])));
    await getShortlistOpportunities(['b', 'a', 'b', 'a']);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.ids).toEqual(['b', 'a']);
  });

  it('chunks requests at 200 and preserves overall first-seen order across chunks', async () => {
    const ids = Array.from({ length: 250 }, (_, i) => `id-${i}`);
    fetchMock
      .mockResolvedValueOnce(okJson(batchBody(ids.slice(0, 200))))
      .mockResolvedValueOnce(okJson(batchBody(ids.slice(200))));
    const result = await getShortlistOpportunities(ids);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.opportunities.map((o) => o.id)).toEqual(ids);
    expect(result.unavailableIds).toEqual([]);
  });

  it('returns missing (backend-skipped) ids as unavailableIds, in request order, without dropping found rows', async () => {
    fetchMock.mockResolvedValue(okJson({ opportunities: [{ id: 'a' }], requested: 3, found: 1 }));
    const result = await getShortlistOpportunities(['a', 'missing-1', 'missing-2']);
    expect(result.opportunities).toEqual([{ id: 'a' }]);
    expect(result.unavailableIds).toEqual(['missing-1', 'missing-2']);
  });

  it('never auto-drops a requested id that IS found — round-trips extra fields untouched', async () => {
    fetchMock.mockResolvedValue(okJson({
      opportunities: [{ id: 'a', title: 'Research Assistant' }],
      requested: 1,
      found: 1,
    }));
    const result = await getShortlistOpportunities(['a']);
    expect(result.opportunities).toEqual([{ id: 'a', title: 'Research Assistant' }]);
  });

  describe('fail-closed on the request side (before any fetch)', () => {
    it('rejects a non-string id (e.g. 123) and never calls fetch', async () => {
      await expect(getShortlistOpportunities([123 as unknown as string]))
        .rejects.toMatchObject({ name: 'ApiError', code: 'SHORTLIST_MALFORMED_REQUEST_ID' });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('rejects a null id and never calls fetch', async () => {
      await expect(getShortlistOpportunities([null as unknown as string]))
        .rejects.toBeInstanceOf(ApiError);
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('rejects an empty-string id and never calls fetch', async () => {
      await expect(getShortlistOpportunities(['']))
        .rejects.toMatchObject({ code: 'SHORTLIST_MALFORMED_REQUEST_ID' });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('rejects a whitespace-only id and never calls fetch', async () => {
      await expect(getShortlistOpportunities(['   ']))
        .rejects.toMatchObject({ code: 'SHORTLIST_MALFORMED_REQUEST_ID' });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('rejects an id over 100 chars and never calls fetch', async () => {
      await expect(getShortlistOpportunities(['x'.repeat(101)]))
        .rejects.toMatchObject({ code: 'SHORTLIST_MALFORMED_REQUEST_ID' });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('accepts an id at exactly 100 chars and uses it raw, untrimmed', async () => {
      const id = 'x'.repeat(100);
      fetchMock.mockResolvedValue(okJson(batchBody([id])));
      const result = await getShortlistOpportunities([id]);
      expect(result.opportunities).toEqual([{ id }]);
    });

    it('fails closed on the whole call when only ONE id among many is malformed — no partial fetch', async () => {
      await expect(getShortlistOpportunities(['good-1', '   ', 'good-2']))
        .rejects.toMatchObject({ code: 'SHORTLIST_MALFORMED_REQUEST_ID' });
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  describe('fail-closed on the response side', () => {
    it('rejects an unknown id (not among the requested chunk) as a safe ApiError', async () => {
      fetchMock.mockResolvedValue(okJson({ opportunities: [{ id: 'not-requested' }], requested: 1, found: 1 }));
      await expect(getShortlistOpportunities(['a']))
        .rejects.toMatchObject({ name: 'ApiError', code: 'SHORTLIST_UNKNOWN_ID', retryable: true });
    });

    it('rejects a duplicate returned id as a safe ApiError', async () => {
      fetchMock.mockResolvedValue(okJson({
        opportunities: [{ id: 'a' }, { id: 'a' }],
        requested: 2,
        found: 2,
      }));
      await expect(getShortlistOpportunities(['a', 'b']))
        .rejects.toMatchObject({ code: 'SHORTLIST_DUPLICATE_ID' });
    });

    it('rejects an incoherent requested/found count as a safe ApiError', async () => {
      fetchMock.mockResolvedValue(okJson({ opportunities: [{ id: 'a' }], requested: 5, found: 1 }));
      await expect(getShortlistOpportunities(['a']))
        .rejects.toMatchObject({ code: 'SHORTLIST_CONTRACT_MISMATCH' });
    });

    it('rejects a malformed result missing an id', async () => {
      fetchMock.mockResolvedValue(okJson({ opportunities: [{ title: 'no id' }], requested: 1, found: 1 }));
      await expect(getShortlistOpportunities(['a']))
        .rejects.toMatchObject({ code: 'SHORTLIST_MALFORMED_RESULT' });
    });

    it('rejects a result whose id is whitespace-only', async () => {
      fetchMock.mockResolvedValue(okJson({ opportunities: [{ id: '   ' }], requested: 1, found: 1 }));
      await expect(getShortlistOpportunities(['a']))
        .rejects.toMatchObject({ code: 'SHORTLIST_MALFORMED_RESULT' });
    });

    it('rejects a result item that is itself an array', async () => {
      fetchMock.mockResolvedValue(okJson({ opportunities: [['a']], requested: 1, found: 1 }));
      await expect(getShortlistOpportunities(['a']))
        .rejects.toMatchObject({ code: 'SHORTLIST_MALFORMED_RESULT' });
    });

    it('rejects a non-array opportunities field', async () => {
      fetchMock.mockResolvedValue(okJson({ opportunities: 'not-an-array', requested: 1, found: 0 }));
      await expect(getShortlistOpportunities(['a']))
        .rejects.toMatchObject({ code: 'SHORTLIST_CONTRACT_MISMATCH' });
    });

    it('does not repair or trim a mismatched id — fails closed instead', async () => {
      const id = 'exact-id';
      fetchMock.mockResolvedValue(okJson({ opportunities: [{ id: ` ${id} ` }], requested: 1, found: 1 }));
      await expect(getShortlistOpportunities([id]))
        .rejects.toMatchObject({ code: 'SHORTLIST_UNKNOWN_ID' });
    });
  });
});

describe('cold-email endpoints', () => {
  it('generateColdEmail without engine option omits engine from the body', async () => {
    fetchMock.mockResolvedValue(
      okJson({
        subject: 'S',
        body: 'B',
        recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu',
        method: 'template',
      }),
    );
    await generateColdEmail(makeProfile(), 'opp-1');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.opportunity_id).toBe('opp-1');
    expect(body.engine).toBeUndefined();
  });

  it('generateColdEmail with engine=ai sends engine in the body', async () => {
    fetchMock.mockResolvedValue(
      okJson({
        subject: 'S',
        body: 'B',
        recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu',
        method: 'ai',
      }),
    );
    await generateColdEmail(makeProfile(), 'opp-1', { engine: 'ai' });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.engine).toBe('ai');
  });

  it('getEmailVariants POSTs /cold-email/variants with profile + opportunity_id', async () => {
    fetchMock.mockResolvedValue(okJson({ variants: [] }));
    await getEmailVariants(makeProfile(), 'opp-1');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/cold-email/variants');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.opportunity_id).toBe('opp-1');
    expect(body.profile.school).toBe('UIUC');
  });

  it('refineEmail POSTs /cold-email/refine with current_body + instruction', async () => {
    fetchMock.mockResolvedValue(okJson({ body: 'new', method: 'llm' }));
    await refineEmail('old body', 'make warmer');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/cold-email/refine');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.current_body).toBe('old body');
    expect(body.instruction).toBe('make warmer');
  });
});

describe('github + stats', () => {
  it('parseGitHubProfile URL-encodes the username path segment', async () => {
    fetchMock.mockResolvedValue(
      okJson({ username: 'a/b', extracted_skills: [], topics: [], repo_count: 0, top_repos: [] }),
    );
    await parseGitHubProfile('a/b');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/resume/github/a%2Fb');
  });

  it('getStats GETs /opportunities/stats/summary', async () => {
    fetchMock.mockResolvedValue(
      okJson({
        total: 1,
        active: 1,
        paid_total: 1,
        international_friendly_total: 1,
        by_type: {},
        by_source: {},
        by_paid: {},
        by_international: {},
      }),
    );
    await getStats();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/opportunities/stats/summary');
  });
});

describe('wakeBackend', () => {
  it('hits /health and resolves silently on success', async () => {
    fetchMock.mockResolvedValue(okJson({ ok: true }));
    await expect(wakeBackend()).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/health');
  });

  it('swallows network errors without re-throwing', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
    await expect(wakeBackend()).resolves.toBeUndefined();
  });
});

describe('email endpoints', () => {
  it('getUpcomingDeadlines defaults to days=30', async () => {
    fetchMock.mockResolvedValue(okJson({ total: 0, opportunities: [], days: 30 }));
    await getUpcomingDeadlines();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/opportunities/upcoming?days=30');
  });

  it('sendMatchesEmail POSTs /email/send-matches with subject_hint passthrough', async () => {
    fetchMock.mockResolvedValue(okJson({ ok: true, count: 1 }));
    await sendMatchesEmail('alex@illinois.edu', [{ title: 'REU' }], 'weekly digest');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/email/send-matches');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.email).toBe('alex@illinois.edu');
    expect(body.subject_hint).toBe('weekly digest');
  });

  it('sendFavoritesEmail POSTs /email/send-favorites', async () => {
    fetchMock.mockResolvedValue(okJson({ ok: true, count: 0 }));
    await sendFavoritesEmail('alex@illinois.edu', []);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/email/send-favorites');
  });
});

describe('import endpoints (FastAPI detail handling)', () => {
  it('importByUrl returns the parsed body on success', async () => {
    fetchMock.mockResolvedValue(okJson({ ok: true, llm_enriched: false }));
    const result = await importByUrl('https://example.com');
    expect(result).toEqual({ ok: true, llm_enriched: false });
  });

  it('importByUrl unwraps a FastAPI detail STRING into { ok:false, error }', async () => {
    fetchMock.mockResolvedValue(
      badResponse(422, JSON.stringify({ detail: 'invalid URL' })),
    );
    const result = await importByUrl('not-a-url');
    expect(result).toEqual({ ok: false, error: 'invalid URL', llm_enriched: false });
  });

  it('importByUrl unwraps a FastAPI detail ARRAY into the first msg', async () => {
    fetchMock.mockResolvedValue(
      badResponse(422, JSON.stringify({ detail: [{ msg: 'too short', loc: ['body', 'url'] }] })),
    );
    const result = await importByUrl('x');
    expect(result).toEqual({ ok: false, error: 'too short', llm_enriched: false });
  });

  it('importByUrl re-throws a safe message when the body is not structured detail', async () => {
    fetchMock.mockResolvedValue(badResponse(502, 'bad gateway'));
    await expect(importByUrl('https://example.com')).rejects.toThrow(
      'The service is temporarily unavailable. Please try again.',
    );
  });

  it('importByText POSTs /import-text with the body field', async () => {
    fetchMock.mockResolvedValue(okJson({ ok: true, llm_enriched: false }));
    await importByText('paste of an opp');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/import-text');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.text).toBe('paste of an opp');
  });

  it('importByText unwraps a FastAPI detail string', async () => {
    fetchMock.mockResolvedValue(
      badResponse(422, JSON.stringify({ detail: 'text too short' })),
    );
    const result = await importByText('x');
    expect(result).toEqual({ ok: false, error: 'text too short', llm_enriched: false });
  });
});

describe('deriveDesiredFields', () => {
  it('splits comma + "and" separated interests into discrete terms', () => {
    expect(
      deriveDesiredFields('computer vision and machine learning, deep learning'),
    ).toEqual(['computer vision', 'machine learning', 'deep learning']);
  });

  it('returns [] for empty/undefined', () => {
    expect(deriveDesiredFields('')).toEqual([]);
    expect(deriveDesiredFields(undefined)).toEqual([]);
  });

  it('dedupes case-insensitively and caps at 20', () => {
    expect(deriveDesiredFields('AI, ai, Ai')).toEqual(['AI']);
    const many = Array.from({ length: 30 }, (_, i) => `field${i}`).join(', ');
    expect(deriveDesiredFields(many).length).toBe(20);
  });

  it('does not split the substring "and" inside a word', () => {
    expect(deriveDesiredFields('understanding language')).toEqual(['understanding language']);
  });
})

describe('chatWithOpportunity — SSE streaming (onDelta present)', () => {
  function sseResponse(frames: string[]): Response {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const frame of frames) controller.enqueue(encoder.encode(frame));
        controller.close();
      },
    });
    return new Response(stream, {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    });
  }

  it('accumulates deltas, calls onDelta per chunk, and takes method from the done event', async () => {
    fetchMock.mockResolvedValue(sseResponse([
      'data: {"delta":"Hel"}\n\n',
      'data: {"delta":"lo"}\n\ndata: {"done":true,"method":"llm"}\n\n',
    ]));
    const onDelta = vi.fn();
    const result = await chatWithOpportunity('opp-1', 'Hi', [], null, undefined, onDelta);

    expect(result).toEqual({ reply: 'Hello', method: 'llm', errored: false });
    expect(onDelta.mock.calls.map((c) => c[0])).toEqual(['Hel', 'lo']);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe('/api/opportunities/opp-1/chat?stream=1');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)['Accept']).toBe('text/event-stream');
  });

  it('falls back to res.json() when the backend answers plain JSON, calling onDelta once', async () => {
    fetchMock.mockResolvedValue(okJson({ reply: 'plain reply', method: 'llm' }));
    const onDelta = vi.fn();
    const result = await chatWithOpportunity('opp-1', 'Hi', [], null, undefined, onDelta);

    expect(result).toEqual({ reply: 'plain reply', method: 'llm' });
    expect(onDelta).toHaveBeenCalledTimes(1);
    expect(onDelta).toHaveBeenCalledWith('plain reply');
  });

  it('marks the result errored when an error event follows partial deltas', async () => {
    fetchMock.mockResolvedValue(sseResponse([
      'data: {"delta":"par"}\n\n',
      'data: {"error":true}\n\n',
      'data: {"done":true,"method":"llm"}\n\n',
    ]));
    const result = await chatWithOpportunity('opp-1', 'Hi', [], null, undefined, vi.fn());
    expect(result).toEqual({ reply: 'par', method: 'llm', errored: true });
  });

  it('surfaces the local-fallback stream with method local', async () => {
    fetchMock.mockResolvedValue(sseResponse([
      'data: {"delta":"AI chat is not configured…","method":"local"}\n\n',
      'data: {"done":true,"method":"local"}\n\n',
    ]));
    const result = await chatWithOpportunity('opp-1', 'Hi', [], null, undefined, vi.fn());
    expect(result.method).toBe('local');
    expect(result.reply).toContain('AI chat is not configured');
  });

  it('throws a structured safe error on a non-2xx streaming response', async () => {
    fetchMock.mockResolvedValue(badResponse(429, 'slow down'));
    const promise = chatWithOpportunity(
      'opp-1',
      'Hi',
      [],
      null,
      undefined,
      vi.fn(),
    );
    await expect(promise).rejects.toMatchObject({
      name: 'ApiError',
      status: 429,
      code: 'HTTP_429',
      retryable: true,
      message: 'The service is busy. Please try again shortly.',
    });
  });

  it('returns the partial reply as errored when the stream breaks mid-read', async () => {
    const encoder = new TextEncoder();
    let pulls = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (pulls++ === 0) {
          controller.enqueue(encoder.encode('data: {"delta":"cut "}\n\n'));
        } else {
          controller.error(new Error('network reset'));
        }
      },
    });
    fetchMock.mockResolvedValue(new Response(stream, {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    }));
    const result = await chatWithOpportunity('opp-1', 'Hi', [], null, undefined, vi.fn());
    expect(result).toEqual({ reply: 'cut ', method: 'llm', errored: true });
  });
});

describe('the match request built from a profile whose résumé was removed', () => {
  // The end of the removal journey: what the matcher is actually asked for.
  // Everything before this (local write, cloud row) only matters because it
  // decides this request body.
  const withResume: ProfileData = {
    name: 'Test',
    home_school: 'uiuc',
    institution: 'UIUC',
    college: 'Grainger',
    major: 'Computer Science',
    grade: 'Junior',
    is_international: false,
    research_interests: 'robotics and controls',
    skills: [{ name: 'Python', level: 'experienced' }],
    coursework: ['ECE 220', 'CS 225'],
    resume_text: 'the full text of my resume',
  } as unknown as ProfileData;

  const afterRemoval: ProfileData = {
    ...withResume,
    resume_text: '',
    coursework: [],
  } as unknown as ProfileData;

  async function requestBodyFor(profile: ProfileData): Promise<Record<string, unknown>> {
    fetchMock.mockResolvedValueOnce(okJson({
      total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [],
    }));
    await getMatches(profile);
    const init = fetchMock.mock.calls[0][1] as { body: string };
    return JSON.parse(init.body) as Record<string, unknown>;
  }

  it('sends resume_ready true and the coursework while the résumé is on file', async () => {
    const body = await requestBodyFor(withResume);
    expect(body.resume_ready).toBe(true);
    expect(body.coursework).toEqual(['ECE 220', 'CS 225']);
  });

  it('sends resume_ready false and no coursework once it has been removed, keeping skills and interests', async () => {
    const body = await requestBodyFor(afterRemoval);
    expect(body.resume_ready).toBe(false);
    expect(body.coursework).toEqual([]);
    // The evidence the user did NOT delete is still theirs.
    expect(body.hard_skills).toEqual([{ name: 'Python', level: 'experienced' }]);
    expect(body.research_interests_text).toBe('robotics and controls');
  });
});

describe('retryable server errors are retried, not shown', () => {
  function matchBusy(): Response {
    return new Response(
      JSON.stringify({
        detail: {
          code: 'MATCH_BUSY',
          message: 'Matching is busy. Please retry shortly.',
          retryable: true,
        },
      }),
      { status: 503, headers: { 'retry-after': '0', 'content-type': 'application/json' } },
    );
  }

  const emptyMatches = {
    total: 0,
    high_priority: 0,
    good_match: 0,
    reach: 0,
    low_fit: 0,
    results: [],
    opportunities: [],
  };

  it('recovers a match view from the exact 503 -> 504 pair seen in production', async () => {
    fetchMock
      .mockResolvedValueOnce(matchBusy())
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          detail: {
            code: 'MATCH_TIMEOUT',
            message: 'Matching took too long. Please retry.',
            retryable: true,
          },
        }),
        { status: 504, headers: { 'retry-after': '0', 'content-type': 'application/json' } },
      ))
      .mockResolvedValueOnce(okJson(emptyMatches));

    await expect(getMatchView(makeProfile(), {
      tab: 'all', search_query: '', paid: '', intl: '', source: '', on_campus: '',
      deadline: '', min_score: 0, scope: '', sort_by: 'score', show_dismissed: false,
      favorite_ids: [], dismissed_ids: [], today: '2026-08-14',
    })).resolves.toMatchObject({ total: 0 });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('gives up and surfaces the last error rather than retrying forever', async () => {
    fetchMock.mockResolvedValue(matchBusy());
    await expect(getMatches(makeProfile())).rejects.toThrow(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('does not retry a client error, which repeating cannot fix', async () => {
    fetchMock.mockResolvedValue(badResponse(422, JSON.stringify({ detail: 'bad' })));
    await expect(getMatches(makeProfile())).rejects.toThrow(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('leaves endpoints that must not replay on a single attempt', async () => {
    // A cold email is a side effect. "Retryable" describes the server, not
    // whether sending twice is acceptable.
    fetchMock.mockResolvedValue(badResponse(503, ''));
    await expect(sendMatchesEmail('a@b.edu', [])).rejects.toThrow(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
