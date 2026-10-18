// Checklist M115. A tab that has not yet seen another tab's save changes one
// field twice before its autosave runs. Both changes were made against what
// that tab shows, so both must be recorded against it: the server's refusal
// then reads as a disagreement and is put to the student, instead of a row
// that "has not changed" and is overwritten by a silent retry.
import { beforeEach, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from './supabase';
import type { ProfileData, StoredCourse } from './types';

const service = vi.hoisted(() => ({
  load: vi.fn<() => Promise<LoadedProfile>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
}));
vi.mock('./supabase', () => ({
  loadProfile: () => service.load(),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
}));

const UID = 'stale-tab-owner';
const COURSES: StoredCourse[] = [
  { name: 'CS 225', source: 'resume' },
  { name: 'CS 233', source: 'resume' },
];
const base: ProfileData = {
  name: 'Synthetic student', institution: 'UIUC', home_school: 'uiuc', college: 'Gies',
  major: 'Finance', grade: 'Sophomore', is_international: false,
  research_interests: 'initial research', skills: [], search_weight: 50,
  resume_text: 'Relevant Coursework: CS 225, CS 233', coursework: ['CS 225', 'CS 233'], courses: COURSES,
  experience_entries: [], resume_master: null,
};

// One row, its revision, and a compare-and-set on it.
const server = { revision: 7, profile: { ...base } as Record<string, unknown>, sent: [] as ProfilePatchIntent[] };
function serverCommit(intent: ProfilePatchIntent): ProfilePatchOutcome {
  server.sent.push(intent);
  if (intent.expectedRevision !== server.revision) {
    return { status: 'conflict', revision: server.revision, profile: { ...server.profile } };
  }
  const next = { ...server.profile };
  for (const [k, v] of Object.entries(intent.patch)) {
    if (v === undefined) delete next[k]; else next[k] = v;
  }
  server.profile = next;
  server.revision += 1;
  return { status: 'saved', revision: server.revision, profile: { ...next } };
}

// Each module graph is an independent tab over the same localStorage and Web
// Locks (as in profile-sync.receipt-repair-deletion.test.ts). A tab learns of
// another tab's save only through that storage; its screen is its view.
async function openTab() {
  vi.resetModules();
  const identity = await import('./identity-owner');
  identity.advanceOwnerEpoch(UID);
  expect(await identity.syncLocalIdentityOwner(UID)).toBe(true);
  const sync = await import('./profile-sync');
  return { sync, token: identity.captureOwnerToken(), view: null as unknown as ReturnType<typeof sync.makeProfileViewSnapshot> };
}
type Tab = Awaited<ReturnType<typeof openTab>>;

async function load(tab: Tab) {
  service.load.mockImplementationOnce(async () => ({
    source: 'cloud', profile: { ...server.profile }, revision: server.revision, token: tab.token,
  }));
  const h = await tab.sync.hydrateProfile();
  tab.view = tab.sync.makeProfileViewSnapshot({
    renderedProfile: h.profile!, baseProfile: h.baseProfile, revision: h.revision,
    token: tab.token, identityGeneration: tab.token.epoch, source: 'hydration',
  });
}

/** Changes made in a tab one after another, each recorded at once against
 *  what the tab shows, then sent together (the form's autosave debounce). */
async function changeThenSave(tab: Tab, steps: Array<Partial<ProfileData>>) {
  let desired = tab.view.renderedProfile as ProfileData;
  const keys = new Set<keyof ProfileData>();
  for (const step of steps) {
    desired = { ...desired, ...step } as ProfileData;
    for (const k of Object.keys(step)) keys.add(k as keyof ProfileData);
    expect(tab.sync.recordProfileIntent(desired, Object.keys(step) as Array<keyof ProfileData>, tab.token, {
      writer: 'home-form', observedBase: { profile: tab.view.baseProfile as ProfileData, revision: tab.view.revision },
    })).toBe(true);
    tab.view = tab.sync.withRenderedProfile(tab.view, desired);
  }
  return tab.sync.stageProfilePatch(desired, [...keys], tab.token);
}

/** A fresh tab and a stale one: both loaded at revision 7, then the fresh
 *  one saves `saved` (revision 8), which the stale one has not seen. */
async function freshSavesThenStale(saved: Partial<ProfileData>) {
  const fresh = await openTab();
  await load(fresh);
  const stale = await openTab();
  await load(stale);
  expect((await changeThenSave(fresh, [saved])).status).toBe('saved');
  expect(server.revision).toBe(8);
  return { fresh, stale };
}

const sends = () => server.sent.map((s) => [s.expectedRevision, Object.keys(s.patch).sort()]);

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  server.revision = 7; server.profile = { ...base }; server.sent = [];
  service.load.mockReset();
  service.commit.mockReset();
  service.commit.mockImplementation(async (intent) => serverCommit(intent));
});

it('two quick changes to the year in a stale tab are asked about, and the other tab\'s save stays until answered', async () => {
  const { stale } = await freshSavesThenStale({ grade: 'Junior' });
  const result = await changeThenSave(stale, [{ grade: 'Senior' }, { grade: 'Freshman' }]);
  expect(result.status).toBe('conflict');
  if (result.status !== 'conflict') return;
  expect(result.conflictKeys).toEqual(['grade']);
  expect(result.conflicts.find((c) => c.key === 'grade')?.remote).toBe('Junior');
  // Refused once at 7; nothing re-sent at 8.
  expect(server.sent.map((s) => [s.expectedRevision, s.patch.grade])).toEqual([[7, 'Junior'], [7, 'Freshman']]);
  expect([server.revision, server.profile.grade]).toEqual([8, 'Junior']);

  // The student answers: keeping what they typed saves it.
  const answer = await stale.sync.resolveProfileConflict({
    prompt: stale.sync.makeConflictPrompt(stale.view, result.conflicts), actionView: stale.view, choice: 'local',
  });
  expect(answer.status).toBe('saved');
  expect([server.revision, server.profile.grade]).toEqual([9, 'Freshman']);
});

it('one change in the stale tab is asked about the same way', async () => {
  const { stale } = await freshSavesThenStale({ grade: 'Junior' });
  expect((await changeThenSave(stale, [{ grade: 'Senior' }])).status).toBe('conflict');
  expect([server.revision, server.profile.grade]).toEqual([8, 'Junior']);
});

it('two quick changes to a field the other tab did not change still merge with no question', async () => {
  const { stale } = await freshSavesThenStale({ grade: 'Junior' });
  const result = await changeThenSave(stale, [{ research_interests: 'robot' }, { research_interests: 'robotics' }]);
  expect(result.status).toBe('saved');
  expect(sends()).toEqual([[7, ['grade']], [7, ['research_interests']], [8, ['research_interests']]]);
  expect([server.revision, server.profile.grade, server.profile.research_interests]).toEqual([9, 'Junior', 'robotics']);
});

it('two quick course status clicks in a stale tab do not reset a status the other tab set', async () => {
  // Tab one marks CS 225 completed. The stale tab, still showing it unmarked,
  // marks CS 233 in progress and then completed (each click writes the list).
  const marked: StoredCourse[] = [{ ...COURSES[0], status: 'completed' }, COURSES[1]];
  const { stale } = await freshSavesThenStale({ courses: marked });
  const result = await changeThenSave(stale, [
    { courses: [COURSES[0], { ...COURSES[1], status: 'in_progress' }] },
    { courses: [COURSES[0], { ...COURSES[1], status: 'completed' }] },
  ]);
  expect(result.status).toBe('conflict');
  expect(server.revision).toBe(8);
  expect(server.profile.courses).toEqual(marked);
});

const OLD_BUILD_REMOVAL: Partial<ProfileData> = { resume_text: '', coursework: [], experience_entries: [], resume_master: null };

it('two quick course additions in a stale tab do not undo an older build\'s résumé removal', async () => {
  // Tab one removes the résumé as the build before course statuses does: the
  // text and its course names go, the course list is left as it was.
  const { stale } = await freshSavesThenStale(OLD_BUILD_REMOVAL);
  // The stale tab, still showing the résumé, adds two courses. Each addition
  // writes the names too, and with them the whole résumé.
  const math: StoredCourse = { name: 'MATH 257', source: 'manual' };
  const stat: StoredCourse = { name: 'STAT 400', source: 'manual' };
  const result = await changeThenSave(stale, [
    { courses: [...COURSES, math], coursework: ['CS 225', 'CS 233', 'MATH 257'] },
    { courses: [...COURSES, math, stat], coursework: ['CS 225', 'CS 233', 'MATH 257', 'STAT 400'] },
  ]);
  expect(result.status).toBe('conflict');
  expect(server.revision).toBe(8);
  expect([server.profile.resume_text, server.profile.coursework]).toEqual(['', []]);
});

it('two quick status clicks in a stale tab do not bring back the courses a résumé removal took', async () => {
  // This build's removal also drops every résumé course nobody marked.
  const { stale } = await freshSavesThenStale({ ...OLD_BUILD_REMOVAL, courses: [] });
  const result = await changeThenSave(stale, [
    { courses: [{ ...COURSES[0], status: 'completed' }, COURSES[1]] },
    { courses: [{ ...COURSES[0], status: 'completed' }, { ...COURSES[1], status: 'planned' }] },
  ]);
  expect(result.status).toBe('conflict');
  expect(server.revision).toBe(8);
  expect([server.profile.courses, server.profile.coursework]).toEqual([[], []]);
});

it('a status click then an addition in a stale tab was already asked about: the addition records the résumé from the tab\'s view', async () => {
  const { stale } = await freshSavesThenStale(OLD_BUILD_REMOVAL);
  const result = await changeThenSave(stale, [
    { courses: [{ ...COURSES[0], status: 'completed' }, COURSES[1]] },
    { courses: [{ ...COURSES[0], status: 'completed' }, COURSES[1], { name: 'MATH 257', source: 'manual' }],
      coursework: ['CS 225', 'CS 233', 'MATH 257'] },
  ]);
  expect(result.status).toBe('conflict');
  expect(server.revision).toBe(8);
  expect([server.profile.resume_text, server.profile.coursework]).toEqual(['', []]);
});
