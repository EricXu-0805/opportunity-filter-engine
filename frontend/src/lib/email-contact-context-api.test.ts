import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProfileData } from './types';
const auth = vi.hoisted(() => ({ token: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.token, refreshRevealAccessToken: vi.fn() }));
vi.mock('./analytics', () => ({ track: vi.fn() }));
import { generateColdEmail, generateColdEmailStream, getEmailVariants, refineEmail } from './api';
const profile: ProfileData = { name: 'Student', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false, research_interests: 'robotics', skills: [], coursework: [] };
const referral = () => ({ version: 1 as const, purpose: 'referral' as const, referral: { referrer_name: ' 陈老师 ', referral_note: ' Please contact the lab.\nI discussed the parser. ', confirmed: true as const } });
const fetchMock = vi.fn();
const routes = {
  generate: (context?: ReturnType<typeof referral> | null) => generateColdEmail(profile, 'A', { contactContext: context }),
  stream: (context?: ReturnType<typeof referral> | null) => generateColdEmailStream(profile, 'A', { contactContext: context }),
  variants: (context?: ReturnType<typeof referral> | null) => getEmailVariants(profile, 'A', [], { contactContext: context }),
  refine: (context?: ReturnType<typeof referral> | null) => refineEmail('Old hand-written body', 'Shorten', profile, 'A', { contactContext: context }),
};
function mockResponse(stream = false) {
  const response = { subject: 'Subject', body: 'Body', method: 'ai', opportunity_id: 'A', target_version: `wt1:${'a'.repeat(64)}`, contact_context_receipt: { version: 1, purpose: 'referral', context_sig: 'b'.repeat(64) }, variants: [] };
  return stream ? new Response(`data: ${JSON.stringify({ stage: 'done', ...response })}\n\n`, { headers: { 'content-type': 'text/event-stream' } }) : new Response(JSON.stringify(response), { headers: { 'content-type': 'application/json' } });
}
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); auth.token.mockReset().mockResolvedValue(null); });
afterEach(() => { vi.unstubAllGlobals(); });
describe('email contact context transport', () => {
  it.each(Object.keys(routes) as (keyof typeof routes)[])('%s sends the same normalized top-level context and keeps receipts', async key => {
    fetchMock.mockResolvedValue(mockResponse(key === 'stream'));
    const result = await routes[key](referral());
    expect(fetchMock).toHaveBeenCalledOnce();
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.contact_context).toEqual({ version: 1, purpose: 'referral', referral: { referrer_name: '陈老师', referral_note: 'Please contact the lab.\nI discussed the parser.', confirmed: true } });
    expect(body.profile).not.toHaveProperty('contact_context');
    expect(body.experience_evidence).not.toHaveProperty('contact_context');
    expect(result).toMatchObject({ contact_context_receipt: { version: 1, purpose: 'referral', context_sig: 'b'.repeat(64) } });
  });
  it.each(['generate', 'stream', 'variants'] as const)('%s snapshots nested context before waiting for auth', async key => {
    let release!: (token: string | null) => void;
    auth.token.mockReturnValue(new Promise<string | null>(resolve => { release = resolve; }));
    fetchMock.mockResolvedValue(mockResponse(key === 'stream'));
    const input = referral(); const request = routes[key](input);
    input.referral.referrer_name = 'Wrong later person'; input.referral.referral_note = 'Wrong later instruction';
    release(null); await request;
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).contact_context.referral).toEqual({ referrer_name: '陈老师', referral_note: 'Please contact the lab.\nI discussed the parser.', confirmed: true });
  });
  it.each(Object.keys(routes) as (keyof typeof routes)[])('%s rejects invalid context before any request', async key => {
    fetchMock.mockResolvedValue(mockResponse(key === 'stream'));
    const input = referral(); input.referral.referrer_name = 'Two\nlines';
    await expect(routes[key](input)).rejects.toMatchObject({ code: 'INVALID_CONTACT_CONTEXT' });
    expect(fetchMock).not.toHaveBeenCalled(); expect(auth.token).not.toHaveBeenCalled();
  });
  it.each(Object.keys(routes) as (keyof typeof routes)[])('%s omits absent or null optional context for older callers', async key => {
    fetchMock.mockImplementation(() => Promise.resolve(mockResponse(key === 'stream')));
    await routes[key](); await routes[key](null);
    for (const call of fetchMock.mock.calls) expect(JSON.parse(call[1].body)).not.toHaveProperty('contact_context');
  });
});
