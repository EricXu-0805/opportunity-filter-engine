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
import { courseRows, storedCourse } from '@/lib/course-status';

// Checklist M13 phase 2. Every tab of an older build (1cc92a31, or the
// phase-1 build after it) in the browser leaves a question holding a
// `courses` operation to this build, so a question this build cannot answer
// is one nobody can. Every build writes the résumé as ONE operation of four
// fields, the course names among them; this build writes a course edit that
// changes the names with them, and a status click as the course list alone.
// The operations below are the older builds', written as their code writes
// them; this build's own come from its hook. Whatever is answered, the résumé text and the course names
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
async function courseTabLeaves(courses: unknown[], how?: 'status') {
  const tab = await open();
  offline();
  act(() => { tab.result.current.update('courses', courses as never, how); }); await tick(3000);
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
/** An older build's experience edit: the four résumé fields as that tab
 *  shows them, the experience entries changed. */
function olderExperienceOp(entries: unknown[], { text = RT, names = NAMES, baseRevision = 1 }: { text?: string; names?: string[]; baseRevision?: number } = {}) {
  const ops = readOutstandingOps();
  const clock = Math.max(0, ...(ops.ok ? ops.value.map((o) => o.clock ?? 0) : [])) + 1;
  const opId = crypto.randomUUID();
  const field = (key: string, from: unknown, to: unknown) => ({ key, base: { present: true, value: from }, desired: { present: true, value: to } });
  localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${opId}`, JSON.stringify({
    opId, originId: 'older-tab-document', lineage: 'older-tab', seq: 1, clock, baseRevision, writer: HOME_FORM_WRITER, mode: 'set', bundle: 'resume',
    fields: [field('resume_text', text, text), field('coursework', names, names), field('experience_entries', [], entries), field('resume_master', null, null)],
  }));
}
const ENTRY = { id: 'exp-1', revision: 1, status: 'confirmed', text: 'Built a robot.', source: { kind: 'manual' } };
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
    await courseTabLeaves(MARKED, 'status');
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

  it('kept in the removal\'s tab once reloaded into this build, the removal lands whole beside the course list the other tab typed', async () => {
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
    // The removal's tab typed no course list: the other tab's is kept, its
    // mark and the course it added, as this build's own removal keeps them.
    expect(statuses(remote.courses)).toEqual(['CS 225', 'CS 233:completed', 'STAT 400:in_progress']);
    expect(settled()).toBe(true);
  });
});

describe('another device adds a course name, this tab marks a course, an older tab removes the résumé (review m13fe-b-r3, F4b-d)', () => {
  async function marked() {
    const tab = await open();
    remote = { ...remote, coursework: [...NAMES, 'PHYS 211'] } as ProfileData; revision = 2;
    act(() => { tab.result.current.update('courses', MARKED as never, 'status'); }); await tick(3000);
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

  it('F4d: a course added while the removal waits is one question; kept here it lands with the removal this tab showed, never half of it', async () => {
    const tab = await marked();
    olderResumeOp('', [], { baseRevision: 2, base: [...NAMES, 'PHYS 211'] });
    await focus();
    // This tab shows the removal; the course list adds to the rows it shows.
    expect(tab.result.current.profile.resume_text).toBe('');
    const added = [...courseRows(tab.result.current.profile).map(storedCourse), STAT];
    act(() => { tab.result.current.update('courses', added as never); }); await tick(3000);
    expect(tab.result.current.conflicts.map((q) => q.key)).toContain('resume_text');
    expect(remote.resume_text).toBe(RT);
    await answer(tab, 'keep');
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    oneResume({ ...remote, coursework: remote.coursework?.filter((name) => name !== 'STAT 400') } as ProfileData, '', ['CS 233']);
    expect(statuses(remote.courses)).toEqual(['CS 233:completed', 'STAT 400:in_progress']);
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
    await courseTabLeaves(MARKED, 'status');
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
  it('is in the question, and Keep here keeps the résumé this tab added a course on, with its names, never the typed text apart from them', async () => {
    const tab = await open();
    remote = { ...remote, coursework: [...NAMES, 'PHYS 211'] } as ProfileData; revision = 2;
    act(() => { tab.result.current.update('courses', [...MARKED, STAT] as never); }); await tick(3000);
    // The names are the résumé's: asked about, the résumé is asked with them.
    expect(tab.result.current.conflicts.map((q) => q.key).sort())
      .toEqual(['courses', 'coursework', 'experience_entries', 'resume_master', 'resume_text']);
    // Its form showed this tab's course names while the question was held.
    olderResumeOp(`${RT}\nTA for CS 225`, [...NAMES, 'STAT 400'], { lineage: 'phase-1-tab', baseRevision: 2, base: [...NAMES, 'PHYS 211'] });
    await focus();
    expect(tab.result.current.conflicts.map((q) => q.key)).toContain('resume_text');
    await answer(tab, 'keep');
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    // This tab's course edit carries the résumé it was made on (the names
    // are one unit with it), and Keep keeps what this tab typed, as for any
    // résumé edit: the other tab's text is the other version.
    oneResume(remote, RT, [...NAMES, 'STAT 400']);
    expect(statuses(remote.courses)).toEqual(['CS 225', 'CS 233:completed', 'STAT 400:in_progress']);
    expect(settled()).toBe(true);
  });
});


describe('a status click after an older build wrote the course names (review p2-a, U2 and U7)', () => {
  it.each([
    ['imported a résumé', { resume_text: NEW, coursework: ['ECE 210', 'CS 225'] }, ['CS 225:in_progress', 'ECE 210']],
    ['removed the résumé', { resume_text: '', coursework: [], courses: MARKED }, ['CS 233:in_progress']],
  ])('after an older build %s, writes the course list alone and lands beside that build\'s experience edit, no question', async (_, landed, marked) => {
    remote = { ...remote, ...landed } as ProfileData; revision = 2;
    const tab = await open();
    offline();
    // The course list's rows on this screen, the first one clicked.
    const rows = courseRows(tab.result.current.profile).map((row, at) => storedCourse(at === 0 ? { ...row, marked: 'in_progress' } : row));
    act(() => { tab.result.current.update('courses', rows as never, 'status'); }); await tick(3000);
    await close(tab);
    service.commit.mockImplementation(apply);
    olderExperienceOp([ENTRY], { text: landed.resume_text, names: landed.coursework, baseRevision: 2 });
    const next = await open();
    expect(next.result.current.conflicts).toEqual([]);
    // The names are the older build's, as it wrote them: no write sends others.
    expect(service.commit.mock.calls.map(([intent]) => intent.patch.coursework).filter(Boolean)).toEqual([landed.coursework]);
    oneResume(remote, landed.resume_text, landed.coursework);
    expect(remote.experience_entries).toEqual([ENTRY]);
    expect(statuses(remote.courses)).toEqual(marked);
    expect(settled()).toBe(true);
  });
});

describe('an experience edit in a tab opened before another device imported a résumé (review p2-a, U8; review m13p1v2-a, MF1a)', () => {
  it('asks about the résumé with its names, and Keep stores this tab\'s text with this tab\'s names', async () => {
    const tab = await open();
    remote = { ...remote, resume_text: PHONE, coursework: ['PHYS 211'], courses: [{ name: 'PHYS 211', source: 'resume' }] } as ProfileData; revision = 2;
    act(() => { tab.result.current.update('experience_entries', [ENTRY] as never); }); await tick(3000);
    expect(tab.result.current.conflicts.map((q) => q.key)).toEqual(expect.arrayContaining(['resume_text', 'coursework']));
    await answer(tab, 'keep');
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    oneResume(remote, RT, NAMES);
    expect(remote.experience_entries).toEqual([ENTRY]);
    // The list shows the courses of the résumé it stores.
    expect(courseRows(remote).map((row) => row.name)).toEqual(NAMES);
    expect(settled()).toBe(true);
  });
});

describe('a college change beside another tab\'s major, the row\'s college changed elsewhere (review p2-b, N3)', () => {
  it('Keep here answers each field as before checklist M13: this tab\'s major, the college the other tab chose', async () => {
    const tab = await open();
    // The other tab picks a college from the catalog, which clears the major.
    const ops = readOutstandingOps();
    const clock = Math.max(0, ...(ops.ok ? ops.value.map((o) => o.clock ?? 0) : [])) + 1;
    const field = (key: string, from: unknown, to: unknown) => ({ key, base: { present: true, value: from }, desired: { present: true, value: to } });
    localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_college-tab`, JSON.stringify({
      opId: 'college-tab', originId: 'college-tab-document', lineage: 'college-tab', seq: 1, clock, baseRevision: 1,
      writer: HOME_FORM_WRITER, mode: 'set',
      fields: [field('college', 'Engineering', 'Liberal Arts & Sciences'), field('major', 'Computer Science', ''), field('additional_majors', [], [])],
    }));
    remote = { ...remote, college: 'Business' } as ProfileData; revision = 2;
    act(() => { tab.result.current.update('major', 'Mathematics'); }); await tick(3000);
    await focus();
    expect(tab.result.current.conflicts.map((q) => q.key).sort()).toEqual(['college', 'major']);
    await answer(tab, 'keep');
    await focus();
    expect(tab.result.current.conflicts).toEqual([]);
    // Each field from who typed it: the major here, the college there (the
    // other tab's operation is not dropped whole for its major).
    expect({ college: remote.college, major: remote.major, additional_majors: remote.additional_majors })
      .toEqual({ college: 'Liberal Arts & Sciences', major: 'Mathematics', additional_majors: [] });
    expect(settled()).toBe(true);
  });
});
