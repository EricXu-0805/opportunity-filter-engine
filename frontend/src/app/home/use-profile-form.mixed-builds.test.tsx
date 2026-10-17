import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData } from '@/lib/types';

const service = vi.hoisted(() => ({
  auth: null as null | ((state: { user: { id: string } | null }) => void),
  load: vi.fn<(signal?: AbortSignal) => Promise<LoadedProfile>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
vi.mock('next/navigation', () => ({ useRouter: () => service.router, useSearchParams: () => service.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
vi.mock('@/lib/supabase', () => ({
  loadProfile: (signal?: AbortSignal) => service.load(signal),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof service.auth) => { service.auth = callback; return () => { service.auth = null; }; },
}));
import { useProfileForm } from './use-profile-form';
import { DEFAULT_PROFILE } from './types';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { HOME_FORM_WRITER, resetProfileDirtyLedger } from '@/lib/profile-sync';
import { getJournalLineageId, readOutstandingOps, resetJournalLaneForTests, startDocumentForTests } from '@/lib/profile-journal';
import { STORAGE_KEYS } from '@/lib/storage-keys';

// Checklist M13 phase 2. Every tab of an older build (1cc92a31, or the
// phase-1 build after it) in the browser leaves a question holding a
// `courses` operation to this build, so a question this build cannot answer
// is one nobody can. Those builds write the résumé as ONE operation of four
// fields, the course names among them; this build writes the résumé as three
// and a course edit as the courses with their names. The operations below are
// the older builds', written as their code writes them; this build's own come
// from its hook. Whatever is answered, the résumé text and the course names
// stored together come from one résumé, a status the student set and kept is
// stored, and nothing stays asked that no button settles.
const NAMES = ['CS 225', 'CS 233'];
const LISTED = NAMES.map((name) => ({ name, source: 'resume' }));
const MARKED = [LISTED[0], { ...LISTED[1], status: 'completed' }];
const STAT = { name: 'STAT 400', source: 'manual', status: 'in_progress' };
const RT = 'Relevant Coursework: CS 225, CS 233';
const NEW = 'Relevant Coursework: ECE 210, CS 225';
const PHONE = 'Phone résumé. Relevant Coursework: PHYS 211';
const BASE = { ...DEFAULT_PROFILE, name: 'Alex', home_school: 'uiuc', institution: 'UIUC',
  college: 'Engineering', major: 'Computer Science', grade: 'Junior', research_interests: 'Original research',
  resume_text: RT, coursework: NAMES, courses: LISTED, experience_entries: [], resume_master: null } as unknown as ProfileData;
const t = (key: string) => key;
let remote: ProfileData;
let revision: number;
let sequence = 0;
const row = (): LoadedProfile => ({ source: 'cloud', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision, token: captureOwnerToken() });
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  if (intent.expectedRevision !== revision) return { status: 'conflict', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision };
  remote = { ...remote, ...intent.patch } as ProfileData; revision += 1;
  return { status: 'saved', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision };
}
async function drain() { for (let p = 0; p < 4; p += 1) await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); }); }
async function tick(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await drain(); }
type Tab = ReturnType<typeof renderHook<ReturnType<typeof useProfileForm>, unknown>>;
/** A tab of this build: a new document, or the same tab reloaded. */
async function open(kind: 'other' | 'reload' = 'other'): Promise<Tab> {
  startDocumentForTests(kind); resetProfileDirtyLedger();
  const tab = renderHook(() => useProfileForm(t));
  act(() => { service.auth?.({ user: { id: `mixed-builds-${sequence}` } }); }); await drain(); await tick(3000);
  return tab as Tab;
}
async function close(tab: Tab) { tab.unmount(); await drain(); }
async function focus() { act(() => { window.dispatchEvent(new Event('focus')); }); await drain(); await tick(3000); }
async function answer(tab: Tab, how: 'keep' | 'cloud') {
  act(() => { if (how === 'keep') tab.result.current.keepMyChanges(); else tab.result.current.useCloudVersion(); });
  await tick(3000);
}
const offline = () => service.commit.mockImplementation(async () => { throw new Error('offline'); });
/** This build's tab edits the course list without reaching the server, and closes. */
async function courseTabLeaves(courses: unknown[]) {
  const tab = await open();
  offline();
  act(() => { tab.result.current.update('courses', courses as never); }); await tick(3000);
  await close(tab);
  service.commit.mockImplementation(apply);
}
/** An older build's résumé operation: text, names, experience and master, one 'resume' bundle. */
function olderResumeOp(text: string | null, names: string[], { lineage = 'older-tab', baseRevision = 1, base = NAMES } = {}) {
  const ops = readOutstandingOps();
  const clock = Math.max(0, ...(ops.ok ? ops.value.map((o) => o.clock ?? 0) : [])) + 1;
  const opId = crypto.randomUUID();
  const field = (key: string, from: unknown, to: unknown) => ({ key, base: { present: true, value: from }, desired: to === null ? { present: false } : { present: true, value: to } });
  localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${opId}`, JSON.stringify({
    opId, originId: `${lineage}-document`, lineage, seq: 1, clock, baseRevision, writer: HOME_FORM_WRITER, mode: 'set', bundle: 'resume',
    fields: [field('resume_text', RT, text), field('coursework', base, names), field('experience_entries', [], []), field('resume_master', null, null)],
  }));
}
const statuses = (courses: unknown) => (courses as { name: string; status?: string }[]).map((c) => `${c.name}${c.status ? `:${c.status}` : ''}`);
/** The text and the names come from one résumé: a removal removes both. */
function oneResume(stored: ProfileData, text: string, names: string[]) {
  expect({ text: stored.resume_text, names: stored.coursework }).toEqual({ text, names });
}
const settled = () => { const ops = readOutstandingOps(); return ops.ok && ops.value.length === 0; };

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auth = null; service.params = new URLSearchParams();
  localStorage.clear(); sessionStorage.clear();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  sequence += 1;
  const uid = `mixed-builds-${sequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  remote = structuredClone(BASE); revision = 1;
  service.load.mockReset().mockImplementation(async () => row());
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('a status click beside an older build\'s write of the course names (review m13p1v3-a-r2, R2a; review m13p1v2-a, MF2)', () => {
  it.each([
    ['a résumé removal', '', [] as string[], ''],
    ['a résumé import', NEW, ['ECE 210', 'CS 225'], NEW],
    ['a share link generated', null, ['MATH 241'], RT],
  ])('is no question: with %s, both are stored, the names with the text they came with and the status kept', async (_, text, names, stored) => {
    await courseTabLeaves(MARKED);
    olderResumeOp(text, names);
    const tab = await open();
    expect(tab.result.current.conflicts).toEqual([]);
    oneResume(remote, stored, names);
    expect(statuses(remote.courses)).toEqual(['CS 225', 'CS 233:completed']);
    expect(settled()).toBe(true);
  });
});

describe('a course added beside an older build\'s résumé removal (R2a, MF2): one question every tab can settle', () => {
  it('asks every résumé and course field of both operations, and in a tab that typed neither keeps nothing and takes the other version', async () => {
    await courseTabLeaves([...MARKED, STAT]);
    olderResumeOp('', []);
    const tab = await open();
    expect(tab.result.current.conflicts.map((q) => q.key).sort())
      .toEqual(['courses', 'coursework', 'experience_entries', 'resume_master', 'resume_text']);
    expect(tab.result.current.conflicts.every((q) => q.candidates.some((c) => c.opIds.length > 0))).toBe(true);
    await answer(tab, 'keep');
    expect(tab.result.current.saveStatus).toBe('conflict-several-typed');
    await answer(tab, 'cloud');
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    expect(remote).toEqual(BASE);
    expect(settled()).toBe(true);
  });

  it('kept in the course tab, the removal is dropped whole: the old résumé stays with its names, the added course and the mark', async () => {
    await courseTabLeaves([...MARKED, STAT]);
    olderResumeOp('', []);
    const tab = await open('reload');
    expect(tab.result.current.conflicts.map((q) => q.key)).toContain('resume_text');
    await answer(tab, 'keep');
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    oneResume(remote, RT, [...NAMES, 'STAT 400']);
    expect(statuses(remote.courses)).toEqual(['CS 225', 'CS 233:completed', 'STAT 400:in_progress']);
    expect(settled()).toBe(true);
  });

  it('kept in the removal\'s tab once reloaded into this build, the removal lands whole and the course edit is dropped', async () => {
    await courseTabLeaves([...MARKED, STAT]);
    startDocumentForTests('other');
    olderResumeOp('', [], { lineage: getJournalLineageId() });
    const tab = renderHook(() => useProfileForm(t));
    act(() => { service.auth?.({ user: { id: `mixed-builds-${sequence}` } }); }); await drain(); await tick(3000);
    expect(tab.result.current.conflicts.map((q) => q.key)).toContain('resume_text');
    await answer(tab as Tab, 'keep');
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    oneResume(remote, '', []);
    expect(remote.courses).toEqual(LISTED);
    expect(settled()).toBe(true);
  });
});

describe('another device adds a course name, this tab marks a course, an older tab removes the résumé (review m13fe-b-r3, F4b-d)', () => {
  async function marked() {
    const tab = await open();
    remote = { ...remote, coursework: [...NAMES, 'PHYS 211'] } as ProfileData; revision = 2;
    act(() => { tab.result.current.update('courses', MARKED as never); }); await tick(3000);
    return tab;
  }
  it('F4b/F4c: the mark is stored and the removal lands whole, whichever tab opens next', async () => {
    const tab = await marked();
    expect(tab.result.current.conflicts).toEqual([]);
    olderResumeOp('', [], { baseRevision: 2, base: [...NAMES, 'PHYS 211'] });
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    await close(tab);
    const next = await open();
    expect(next.result.current.conflicts).toEqual([]);
    oneResume(remote, '', []);
    expect(statuses(remote.courses)).toEqual(['CS 225', 'CS 233:completed']);
    expect(settled()).toBe(true);
  });

  it('F4d: a course added while the removal waits is one question; kept here it never lands half the removal', async () => {
    const tab = await marked();
    olderResumeOp('', [], { baseRevision: 2, base: [...NAMES, 'PHYS 211'] });
    await focus();
    act(() => { tab.result.current.update('courses', [...MARKED, STAT] as never); }); await tick(3000);
    expect(tab.result.current.conflicts.map((q) => q.key)).toContain('resume_text');
    expect(remote.resume_text).toBe(RT);
    await answer(tab, 'keep');
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    expect(remote.resume_text).toBe(RT);
    expect(remote.coursework).toContain('STAT 400');
    expect(statuses(remote.courses)).toEqual(['CS 225', 'CS 233:completed', 'STAT 400:in_progress']);
    expect(settled()).toBe(true);
  });
});

describe('another device adds a course name after an older tab recorded a résumé removal (F4b-d, the removal sent here)', () => {
  it('asks about the removal whole and never sends its text apart from the names', async () => {
    olderResumeOp('', []);
    remote = { ...remote, coursework: [...NAMES, 'PHYS 211'] } as ProfileData; revision = 2;
    const tab = await open();
    expect(remote.resume_text).toBe(RT);
    expect(tab.result.current.conflicts.map((q) => q.key)).toEqual(expect.arrayContaining(['resume_text', 'coursework']));
    await answer(tab, 'cloud');
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    oneResume(remote, RT, [...NAMES, 'PHYS 211']);
    expect(settled()).toBe(true);
  });
});

describe('a status click sent after the row took a new résumé (review m13p1v3-a-r2, R2b)', () => {
  it.each([
    ['before this tab reads the row', false],
    ['while the click is being sent', true],
  ])('stores the click with the names of the résumé on the row, %s', async (_, race) => {
    await courseTabLeaves(MARKED);
    const phone = () => { remote = { ...remote, resume_text: PHONE, coursework: ['PHYS 211'] } as ProfileData; revision += 1; };
    if (race) {
      let moved = false;
      service.commit.mockImplementation(async (intent) => { if (!moved) { moved = true; phone(); } return apply(intent); });
    } else phone();
    const tab = await open('reload');
    if (tab.result.current.conflicts.length > 0) { await answer(tab, 'keep'); await focus(); }
    expect(tab.result.current.conflicts).toEqual([]);
    oneResume(remote, PHONE, ['PHYS 211']);
    expect(statuses(remote.courses)).toEqual(['CS 225', 'CS 233:completed']);
  });
});

describe('a résumé a phase-1 tab typed while it held the course question (review m13p1v3-a-r2, R2c)', () => {
  it('is in the question, and Keep here sends it with the course answer', async () => {
    const tab = await open();
    remote = { ...remote, coursework: [...NAMES, 'PHYS 211'] } as ProfileData; revision = 2;
    act(() => { tab.result.current.update('courses', [...MARKED, STAT] as never); }); await tick(3000);
    expect(tab.result.current.conflicts.map((q) => q.key).sort()).toEqual(['courses', 'coursework']);
    // Its form showed this tab's course names while the question was held.
    olderResumeOp(`${RT}\nTA for CS 225`, [...NAMES, 'STAT 400'], { lineage: 'phase-1-tab', baseRevision: 2, base: [...NAMES, 'PHYS 211'] });
    await focus();
    expect(tab.result.current.conflicts.map((q) => q.key)).toContain('resume_text');
    await answer(tab, 'keep');
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    oneResume(remote, `${RT}\nTA for CS 225`, [...NAMES, 'STAT 400']);
    expect(statuses(remote.courses)).toEqual(['CS 225', 'CS 233:completed', 'STAT 400:in_progress']);
    expect(settled()).toBe(true);
  });
});
