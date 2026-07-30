import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  getMatches,
  getOpportunities,
  getGapAnalysis,
  chatWithOpportunity,
  getMatchExplanation,
  getOpportunityById,
  getOpportunitiesByIds,
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

  it('throws "API {status}: {body}" on non-2xx', async () => {
    fetchMock.mockResolvedValue(badResponse(500, 'server explode'));
    await expect(getOpportunities()).rejects.toThrow('API 500: server explode');
  });

  it('throws "API 500: Unknown error" when the error body cannot be read', async () => {
    /* Response.text() resolves successfully to "" for an empty body — it does
       not reject. So we install a Response stub whose .text() rejects to
       exercise the .catch(() => 'Unknown error') fallback. */
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.reject(new Error('stream gone')),
      json: () => Promise.resolve({}),
    } as unknown as Response);
    await expect(getOpportunities()).rejects.toThrow('API 500: Unknown error');
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

  it('sends include_cross_school=true when the profile opts in', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile({ include_cross_school: true }));
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.include_cross_school).toBe(true);
  });

  it('removes the dormant fellowship preference before matching', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile({ seeking_types: ['research', 'fellowship'] }));
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.seeking_type).toEqual(['research']);
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

  it('forces deterministic matching while AI refine is outside the release', async () => {
    // Fresh Response per call — this test fetches twice, and a shared
    // mockResolvedValue Response throws "Body has already been read" on the
    // second res.json() (CI Node enforces single-use bodies).
    fetchMock.mockImplementation(async () =>
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile(), { llm: true });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/matches?llm=false');
    await getMatches(makeProfile(), { llm: false });
    expect(fetchMock.mock.calls[1][0]).toBe('/api/matches?llm=false');
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

  it('importByUrl re-throws when the error body cannot be parsed as a FastAPI detail', async () => {
    fetchMock.mockResolvedValue(badResponse(502, 'bad gateway'));
    await expect(importByUrl('https://example.com')).rejects.toThrow('API 502: bad gateway');
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

  it('throws "API {status}" on a non-2xx streaming response', async () => {
    fetchMock.mockResolvedValue(badResponse(429, 'slow down'));
    await expect(
      chatWithOpportunity('opp-1', 'Hi', [], null, undefined, vi.fn()),
    ).rejects.toThrow('API 429: slow down');
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
