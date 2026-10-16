import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProfileData } from './types';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from './identity-owner';
const auth = vi.hoisted(() => ({ token: vi.fn(), refresh: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.token, refreshRevealAccessToken: auth.refresh }));
vi.mock('./analytics', () => ({ track: vi.fn() }));
import {
  chatWithOpportunity, generateColdEmail, generateColdEmailStream, getEmailVariants, getMatches, optimizeBullet,
  refineEmail, renovateResume, tailorResume,
} from './api';
import { hashProfile } from './match-utils';

// Checklist M13: every request that sends the profile sends each course with
// its status, so matching, cold email, Tailor, Renovate and Ask AI read one
// set of statuses. A course not marked, and every legacy name, goes as unknown.
const TOKEN = 'wt1:' + 'b'.repeat(64);
const profile: ProfileData = {
  name: 'Student', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  research_interests: 'robotics', is_international: false, skills: [],
  coursework: ['CS 225', 'CS 446', 'MATH 241'],
  courses: [
    { name: 'CS 225', status: 'completed', source: 'resume', evidence: 'Relevant Coursework: CS 225' },
    { name: 'CS 446', status: 'planned', source: 'manual' },
  ],
};
const SENT = [
  { name: 'CS 225', status: 'completed', source: 'resume' },
  { name: 'CS 446', status: 'planned', source: 'manual' },
  { name: 'MATH 241', status: 'unknown', source: 'resume' },
];
const routes = ['matches', 'email', 'stream', 'variants', 'refine', 'tailor', 'renovate', 'bullet', 'chat'] as const;
type Route = typeof routes[number];
const fetchMock = vi.fn();
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
function call(route: Route) {
  const options = { expectedTargetVersion: TOKEN };
  switch (route) {
    case 'matches': return getMatches(profile);
    case 'email': return generateColdEmail(profile, 'target', { ...options, engine: 'ai' });
    case 'stream': return generateColdEmailStream(profile, 'target', options);
    case 'variants': return getEmailVariants(profile, 'target', undefined, options);
    case 'refine': return refineEmail('Original body', 'Clearer', profile, 'target', options);
    case 'tailor': return tailorResume(profile, 'target', ['Built a robot.'], { ...options, locale: 'en', expectedPipelineVersion: 'w14.1' });
    case 'renovate': return renovateResume(profile, 'target', [], options);
    case 'bullet': return optimizeBullet(profile, 'target', 'Current', 'Original', options);
    case 'chat': return chatWithOpportunity('target', 'Is this a fit?', [], profile);
  }
}
function reply(route: Route) {
  const data = { opportunity_id: 'target', target_version: TOKEN, subject: 'Subject', body: 'Draft', recipient_status: 'sign_in_required',
    total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0, results: [], reply: 'Yes.' };
  return route === 'stream'
    ? new Response(`data: ${JSON.stringify({ stage: 'done', ...data })}\n\n`, { headers: { 'content-type': 'text/event-stream' } })
    : json(data);
}
beforeEach(async () => {
  localStorage.clear(); advanceOwnerEpoch('course-requests'); await syncLocalIdentityOwner('course-requests');
  auth.token.mockReset().mockResolvedValue('token'); auth.refresh.mockReset().mockResolvedValue('refreshed');
  fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); advanceOwnerEpoch(null); });

describe('every request that sends the profile sends the courses with their statuses (checklist M13)', () => {
  it.each(routes)('%s', async (route) => {
    fetchMock.mockImplementation(async () => reply(route));
    await call(route).catch(() => undefined);
    expect(fetchMock).toHaveBeenCalled();
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    const sent = route === 'matches' ? body : body.profile;
    expect(sent.courses).toEqual(SENT);
    expect(sent.coursework).toEqual(['CS 225', 'CS 446', 'MATH 241']);
    // The résumé line stays in the browser.
    expect(JSON.stringify(sent)).not.toContain('Relevant Coursework');
  });
});

describe('the match cache key', () => {
  it('changes with a course status, since the matcher does not count a planned course as taken', () => {
    const planned = { ...profile, courses: [{ name: 'CS 225', status: 'planned' as const, source: 'resume' as const }] };
    const done = { ...profile, courses: [{ name: 'CS 225', status: 'completed' as const, source: 'resume' as const }] };
    expect(hashProfile(planned)).not.toBe(hashProfile(done));
  });
});
