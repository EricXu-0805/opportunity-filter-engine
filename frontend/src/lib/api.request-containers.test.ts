import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProfileData, ResumeSectionInput } from './types';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from './identity-owner';
const auth = vi.hoisted(() => ({ token: vi.fn(), refresh: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.token, refreshRevealAccessToken: auth.refresh }));
vi.mock('./analytics', () => ({ track: vi.fn() }));
import { extractResumeBullets, optimizeBullet, renovateResume, structureResume, tailorResume } from './api';

// The lists and objects the browser's Tailor request builders send at the input limits. The server
// refuses a body with more than its route's bound (backend/lib/request_body.py: 10,000 for these
// three writing routes, 100 for the two extraction routes) before parsing it.
const fetchMock = vi.fn();
const TOKEN = 'wt1:' + 'b'.repeat(64);
const many = (count: number, prefix: string) => Array.from({ length: count }, (_, i) => `${prefix} ${i}`);
const profile: ProfileData = {
  name: 'Student', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false,
  research_interests: many(512, 'field').join(', '), additional_majors: many(512, 'major'), coursework: many(512, 'course'),
  seeking_types: ['research', 'summer_program'],
  skills: many(512, 'skill').map((name) => ({ name, level: 'experienced', source: 'resume', confirmed: true })),
};
const sections: ResumeSectionInput[] = Array.from({ length: 15 }, (_, s) => ({
  id: `s${s}`, heading: `Section ${s}`, kind: 'experience',
  bullets: Array.from({ length: s < 10 ? 7 : 6 }, (_, b) => ({ id: `s${s}-b${b}`, text: 'Built [a] {robot}, "fast".' })),
}));

function containers(value: unknown): number {
  if (Array.isArray(value)) return 1 + value.reduce((sum: number, item) => sum + containers(item), 0);
  if (value && typeof value === 'object') return 1 + Object.values(value).reduce((sum: number, item) => sum + containers(item), 0);
  return 0;
}
function sent(path: string): string {
  const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith(path));
  expect(call, path).toBeDefined();
  return (call![1] as RequestInit).body as string;
}

beforeEach(async () => {
  localStorage.clear(); advanceOwnerEpoch('request-containers'); await syncLocalIdentityOwner('request-containers');
  auth.token.mockReset().mockResolvedValue('token'); auth.refresh.mockReset().mockResolvedValue('refreshed');
  fetchMock.mockReset().mockImplementation(async () => new Response('{}', { headers: { 'content-type': 'application/json' } }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); advanceOwnerEpoch(null); });

describe('Tailor request bodies at the input limits', () => {
  it('hold 521, 519 and 650 lists and objects on the three writing routes', async () => {
    const bullets = many(12, 'Built [a] robot');
    await tailorResume(profile, 'target', bullets, { sourceBullets: bullets, locale: 'en', expectedPipelineVersion: 'w14.1', expectedTargetVersion: TOKEN });
    await optimizeBullet(profile, 'target', 'Built a robot.', 'Built a robot.', { instruction: 'Lead with the method.', locale: 'en', expectedTargetVersion: TOKEN });
    await renovateResume(profile, 'target', sections, { locale: 'en', expectedTargetVersion: TOKEN });
    const tailor = JSON.parse(sent('/tailor'));
    expect(tailor.profile.hard_skills).toHaveLength(512);
    expect(containers(tailor)).toBe(521);
    expect(containers(JSON.parse(sent('/tailor/bullet')))).toBe(519);
    expect(containers(JSON.parse(sent('/tailor/renovate')))).toBe(650);
  });

  it('hold one object on the two extraction routes, and one comma more than the résumé', async () => {
    const resume = ',[{"\\'.repeat(12_000);
    await extractResumeBullets(resume, { expectedPipelineVersion: 'w14.1' });
    await structureResume(resume, { locale: 'en' });
    for (const path of ['/tailor/extract-bullets', '/tailor/structure']) {
      const body = sent(path);
      expect(containers(JSON.parse(body)), path).toBe(1);
      expect(body.split(',').length - 1, path).toBe(12_000 + 1);
    }
  });
});
