/**
 * W10b reveal-aware requests: token attach + one-shot degrade-retry.
 * The supabase module is mocked so the token source is controllable; the
 * network boundary is the stubbed global fetch, as in api.test.ts.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockGetToken = vi.fn();
const mockRefreshToken = vi.fn();
vi.mock('./supabase', () => ({
  getRevealAccessToken: (...args: unknown[]) => mockGetToken(...args),
  refreshRevealAccessToken: (...args: unknown[]) => mockRefreshToken(...args),
}));

import { getEmailVariants, getOpportunityById } from './api';
import type { ProfileData } from './types';

const fetchMock = vi.fn();

beforeEach(() => {
  mockGetToken.mockReset().mockResolvedValue(null);
  mockRefreshToken.mockReset().mockResolvedValue(null);
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

function sentAuthHeader(call: number): string | undefined {
  const headers = (fetchMock.mock.calls[call][1] as RequestInit).headers as
    Record<string, string>;
  return headers.Authorization;
}

const profile: ProfileData = {
  name: 'Alex',
  institution: 'UIUC',
  college: 'Grainger',
  major: 'CS',
  grade: 'Sophomore',
  is_international: false,
  research_interests: 'ml',
  skills: [],
  coursework: [],
};

describe('getOpportunityById (reveal-aware)', () => {
  it('anonymous: single request, no Authorization header', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ id: 'x', contact_email_status: 'sign_in_required' }));
    const body = await getOpportunityById('x');
    expect(body.contact_email_status).toBe('sign_in_required');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sentAuthHeader(0)).toBeUndefined();
    expect(mockRefreshToken).not.toHaveBeenCalled();
  });

  it('signed in: token attached, revealed response returned as-is', async () => {
    mockGetToken.mockResolvedValue('tok-1');
    fetchMock.mockResolvedValueOnce(
      okJson({ id: 'x', contact_email: 'a@b.edu', contact_email_status: 'revealed' }),
    );
    const body = await getOpportunityById('x');
    expect(body.contact_email).toBe('a@b.edu');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sentAuthHeader(0)).toBe('Bearer tok-1');
  });

  it('stale token: refreshes once and retries once with the new token', async () => {
    mockGetToken.mockResolvedValue('tok-stale');
    mockRefreshToken.mockResolvedValue('tok-fresh');
    fetchMock
      .mockResolvedValueOnce(okJson({ id: 'x', contact_email_status: 'sign_in_required' }))
      .mockResolvedValueOnce(
        okJson({ id: 'x', contact_email: 'a@b.edu', contact_email_status: 'revealed' }),
      );
    const body = await getOpportunityById('x');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sentAuthHeader(0)).toBe('Bearer tok-stale');
    expect(sentAuthHeader(1)).toBe('Bearer tok-fresh');
    expect(mockRefreshToken).toHaveBeenCalledTimes(1);
    expect(body.contact_email_status).toBe('revealed');
  });

  it('refresh failure: degrades to the locked shape without a second request', async () => {
    mockGetToken.mockResolvedValue('tok-stale');
    mockRefreshToken.mockResolvedValue(null);
    fetchMock.mockResolvedValueOnce(okJson({ id: 'x', contact_email_status: 'sign_in_required' }));
    const body = await getOpportunityById('x');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(body.contact_email_status).toBe('sign_in_required');
  });

  it('never retries more than once even if the retry is still locked', async () => {
    mockGetToken.mockResolvedValue('tok-stale');
    mockRefreshToken.mockResolvedValue('tok-still-stale');
    fetchMock
      .mockResolvedValueOnce(okJson({ id: 'x', contact_email_status: 'sign_in_required' }))
      .mockResolvedValueOnce(okJson({ id: 'x', contact_email_status: 'sign_in_required' }));
    const body = await getOpportunityById('x');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(mockRefreshToken).toHaveBeenCalledTimes(1);
    expect(body.contact_email_status).toBe('sign_in_required');
  });
});

describe('getEmailVariants (reveal-aware)', () => {
  it('retries once on a stale-token locked response', async () => {
    mockGetToken.mockResolvedValue('tok-stale');
    mockRefreshToken.mockResolvedValue('tok-fresh');
    fetchMock
      .mockResolvedValueOnce(okJson({ variants: [], recipient_status: 'sign_in_required' }))
      .mockResolvedValueOnce(okJson({ variants: [], recipient_status: 'revealed' }));
    const body = await getEmailVariants(profile, 'opp-1');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(body.recipient_status).toBe('revealed');
  });

  it('sends the student\'s own resume bullets with the request', async () => {
    // #803 wired resume_bullets through /cold-email/variants — its message
    // says leaving them out "would keep three of the four generated emails
    // empty of the student's own work" — and no caller ever sent any, so
    // every template variant was built without them.
    fetchMock.mockResolvedValueOnce(okJson({ recipient_status: 'revealed', variants: [] }));

    await getEmailVariants(profile, 'opp-1', ['Built a CV pipeline in PyTorch']);

    const sent = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(sent.resume_bullets).toEqual(['Built a CV pipeline in PyTorch']);
  });

  it('sends an empty list when the student has no parsed resume', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ recipient_status: 'revealed', variants: [] }));

    await getEmailVariants(profile, 'opp-1');

    const sent = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(sent.resume_bullets).toEqual([]);
  });

  it('treats "unavailable" as final — no retry burned on it', async () => {
    mockGetToken.mockResolvedValue('tok-1');
    fetchMock.mockResolvedValueOnce(okJson({ variants: [], recipient_status: 'unavailable' }));
    const body = await getEmailVariants(profile, 'opp-1');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(mockRefreshToken).not.toHaveBeenCalled();
    expect(body.recipient_status).toBe('unavailable');
  });
});
