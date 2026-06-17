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
  uploadResume,
  refineEmail,
  parseGitHubProfile,
  getStats,
  wakeBackend,
  getUpcomingDeadlines,
  sendMatchesEmail,
  sendFavoritesEmail,
  sendRestoreLink,
  verifyRestoreLink,
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
  it('POSTs /matches with the profile body and no semantic flag by default', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile());
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toBe('/api/matches');
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body as string);
    expect(body.school).toBe('UIUC');
    expect(body.major).toBe('CS');
    expect(body.year).toBe('sophomore');
    expect(body.research_interests_text).toBe('machine learning');
    expect(body.hard_skills).toEqual([{ name: 'Python', level: 'experienced' }]);
    expect(body.exploring).toBe(false);
  });

  it('sends exploring=true when the profile opts into explore mode', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile({ exploring: true }));
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.exploring).toBe(true);
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

  it('appends ?llm=true when options.llm is set (AI smart match)', async () => {
    fetchMock.mockResolvedValue(
      okJson({ total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [] }),
    );
    await getMatches(makeProfile(), { llm: true });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/matches?llm=true');
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
    expect(fetchMock.mock.calls[0][0]).toBe('/api/matches/opp-1/explain');
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

describe('resume + github + stats', () => {
  it('uploadResume POSTs FormData (no Content-Type override) to /resume/upload', async () => {
    fetchMock.mockResolvedValue(
      okJson({
        extracted_skills: [],
        extracted_coursework: [],
        experience_level: 'beginner',
        raw_text: '',
        success: true,
        message: 'ok',
      }),
    );
    const file = new File(['hello'], 'resume.pdf', { type: 'application/pdf' });
    await uploadResume(file);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/resume/upload');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    /* Critical: FormData uploads must NOT have a Content-Type header — the
       browser/node fetch needs to set the multipart boundary itself. */
    expect(init.headers).toBeUndefined();
  });

  it('uploadResume throws on non-2xx with the API error message', async () => {
    fetchMock.mockResolvedValue(badResponse(413, 'too big'));
    const file = new File(['x'], 'r.pdf', { type: 'application/pdf' });
    await expect(uploadResume(file)).rejects.toThrow('API 413: too big');
  });

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

  it('sendRestoreLink POSTs /email/restore-link with device_id', async () => {
    fetchMock.mockResolvedValue(okJson({ ok: true }));
    await sendRestoreLink('alex@illinois.edu', 'device-1');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.device_id).toBe('device-1');
  });

  it('verifyRestoreLink encodes (d, t, s) as a query string', async () => {
    fetchMock.mockResolvedValue(okJson({ ok: true, device_id: 'device-1' }));
    await verifyRestoreLink({ d: 'device-1', t: 'abc', s: 'sig+pad' });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/api/email/verify-restore?');
    expect(url).toContain('d=device-1');
    expect(url).toContain('t=abc');
    expect(url).toContain('s=sig%2Bpad');
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
