import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProfileData } from './types';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from './identity-owner';
const auth = vi.hoisted(() => ({ token: vi.fn(), refresh: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.token, refreshRevealAccessToken: auth.refresh }));
vi.mock('./analytics', () => ({ track: vi.fn() }));
// The course list's release switch, as this branch ships it unless a test
// turns it off.
const release = vi.hoisted(() => ({ courseStatus: true }));
vi.mock('./release-scope', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./release-scope')>();
  return { ...actual, RELEASE_SCOPE: { ...actual.RELEASE_SCOPE, get courseStatus() { return release.courseStatus; } } };
});
import {
  chatWithOpportunity, generateColdEmail, generateColdEmailStream, getEmailVariants, getMatches, optimizeBullet,
  refineEmail, renovateResume, tailorResume,
} from './api';
import { hashProfile } from './match-utils';

// Checklist M13: every request that sends the profile sends each course with
// its status, so matching, cold email, Tailor, Renovate and Ask AI read one
// set of statuses. A course nobody marked, legacy names included, goes as
// unknown, whatever its résumé line suggests on the form.
const TOKEN = 'wt1:' + 'b'.repeat(64);
const profile: ProfileData = {
  name: 'Student', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  research_interests: 'robotics', is_international: false, skills: [],
  resume_text: 'Relevant Coursework: CS 225, STAT 400\nCurrent courses: MATH 241',
  coursework: ['CS 225', 'CS 446', 'MATH 241', 'STAT 400'],
  courses: [
    { name: 'CS 225', status: 'completed', source: 'resume' },
    { name: 'CS 446', status: 'planned', source: 'manual' },
    { name: 'MATH 241', source: 'resume' },
  ],
};
const SENT = [
  { name: 'CS 225', status: 'completed', source: 'resume' },
  { name: 'CS 446', status: 'planned', source: 'manual' },
  { name: 'MATH 241', status: 'unknown', source: 'resume' },
  { name: 'STAT 400', status: 'unknown', source: 'resume' },
];
const routes = ['matches', 'email', 'stream', 'variants', 'refine', 'tailor', 'renovate', 'bullet', 'chat'] as const;
type Route = typeof routes[number];
const fetchMock = vi.fn();
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
function call(route: Route, from: ProfileData = profile) {
  const options = { expectedTargetVersion: TOKEN };
  switch (route) {
    case 'matches': return getMatches(from);
    case 'email': return generateColdEmail(from, 'target', { ...options, engine: 'ai' });
    case 'stream': return generateColdEmailStream(from, 'target', options);
    case 'variants': return getEmailVariants(from, 'target', undefined, options);
    case 'refine': return refineEmail('Original body', 'Clearer', from, 'target', options);
    case 'tailor': return tailorResume(from, 'target', ['Built a robot.'], { ...options, locale: 'en', expectedPipelineVersion: 'w14.1' });
    case 'renovate': return renovateResume(from, 'target', [], options);
    case 'bullet': return optimizeBullet(from, 'target', 'Current', 'Original', options);
    case 'chat': return chatWithOpportunity('target', 'Is this a fit?', [], from);
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
afterEach(() => { vi.unstubAllGlobals(); advanceOwnerEpoch(null); release.courseStatus = true; });
async function sentFor(route: Route, from: ProfileData) {
  fetchMock.mockImplementation(async () => reply(route));
  await call(route, from).catch(() => undefined);
  expect(fetchMock).toHaveBeenCalled();
  const body = JSON.parse(fetchMock.mock.calls[0][1].body);
  return route === 'matches' ? body : body.profile;
}

describe('every request that sends the profile sends the courses with their statuses (checklist M13)', () => {
  it.each(routes)('%s', async (route) => {
    fetchMock.mockImplementation(async () => reply(route));
    await call(route).catch(() => undefined);
    expect(fetchMock).toHaveBeenCalled();
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    const sent = route === 'matches' ? body : body.profile;
    expect(sent.courses).toEqual(SENT);
    expect(sent.coursework).toEqual(['CS 225', 'CS 446', 'MATH 241', 'STAT 400']);
    // No résumé line goes with a course.
    expect(JSON.stringify(sent)).not.toContain('Relevant Coursework');
    expect(JSON.stringify(sent)).not.toContain('Current courses');
  });
});

// Checklist M130: what the résumé parser stored for "Relevant Coursework: CS
// 173 Discrete Structures, MATH 241 Calculus III" before it stopped storing a
// code again beside its titled course.
describe('a course the résumé stored by its code and its title goes once', () => {
  const repeated = ['CS 173', 'CS 173 Discrete Structures', 'MATH 241', 'MATH 241 Calculus III'];
  const once = [
    { name: 'CS 173 Discrete Structures', status: 'unknown', source: 'resume' },
    { name: 'MATH 241 Calculus III', status: 'unknown', source: 'resume' },
  ];
  it.each(routes)('%s', async (route) => {
    for (const courses of [undefined, repeated.map((name) => ({ name, source: 'resume' as const }))]) {
      const sent = await sentFor(route, { ...profile, courses, coursework: repeated });
      expect(sent.courses).toEqual(once);
      expect(sent.coursework).toEqual(['CS 173 Discrete Structures', 'MATH 241 Calculus III']);
      fetchMock.mockClear();
    }
  });

  it.each(routes)('%s with the course list switched off sends the names as stored and the list once', async (route) => {
    release.courseStatus = false;
    const sent = await sentFor(route, { ...profile, courses: repeated.map((name) => ({ name, source: 'resume' as const })), coursework: repeated });
    expect(sent.courses).toEqual(once);
    expect(sent.coursework).toEqual(repeated);
  });
});

// Off, a profile goes as b8602cb0 sends it: the names as stored, no
// `courses`, unless the profile holds the list another tab wrote.
describe('with the course list switched off', () => {
  it.each(routes)('%s sends the names as stored and no course list when the profile holds none', async (route) => {
    release.courseStatus = false;
    const sent = await sentFor(route, { ...profile, courses: undefined, coursework: ['CS 225', 'CS225', 'MATH 241'] });
    expect(sent.coursework).toEqual(['CS 225', 'CS225', 'MATH 241']);
    expect(sent).not.toHaveProperty('courses');
  });

  it.each(routes)('%s sends the course list another tab wrote, without the names it lacks', async (route) => {
    release.courseStatus = false;
    // CS 233 is a résumé course nobody marked that the names no longer list
    // (a résumé removed or replaced here): it goes with that résumé.
    const sent = await sentFor(route, { ...profile, courses: [...profile.courses!, { name: 'CS 233', source: 'resume' }] });
    expect(sent.courses).toEqual(SENT.slice(0, 3));
    expect(sent.coursework).toEqual(['CS 225', 'CS 446', 'MATH 241', 'STAT 400']);
  });
});

describe('the match cache key', () => {
  it('changes with a course status, since the matcher does not count a planned course as taken', () => {
    const planned = { ...profile, courses: [{ name: 'CS 225', status: 'planned' as const, source: 'resume' as const }] };
    const done = { ...profile, courses: [{ name: 'CS 225', status: 'completed' as const, source: 'resume' as const }] };
    expect(hashProfile(planned)).not.toBe(hashProfile(done));
    // A status the résumé only suggests is not sent, so it does not re-match.
    expect(hashProfile({ ...profile, resume_text: 'Planned courses: MATH 241' })).toBe(hashProfile(profile));
  });
});
