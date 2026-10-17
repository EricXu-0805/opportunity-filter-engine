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
import { DEFAULT_PROFILE, FRESH_PROFILE, hasSelectedSeekingType } from './types';
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { HOME_FORM_WRITER, resetProfileDirtyLedger } from '@/lib/profile-sync';
import { readOutstandingOps, resetJournalLaneForTests } from '@/lib/profile-journal';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { writeLocalStorageJSON } from '@/lib/use-local-storage-json';

// Checklist M13 ships in two builds. The course-status build writes journal
// operations carrying `courses` and groups the course names with the courses
// rather than with the résumé; this build groups them with the résumé. A
// question holding such an operation, planned here, pulls the résumé in with
// the clicking tab's old copy of it (review batch P, F1) or cannot be answered
// at all (F2; review m13fe-b round 3, F4b-d). So this build answers none: it
// says a newer version of the page changed these fields and a reload lets the
// student answer, keeps the screen, and sends nothing.
const NAMES = ['CS 225', 'CS 233'];
const LISTED = NAMES.map((name) => ({ name, source: 'resume', status: 'unknown' }));
const MARKED = [LISTED[0], { ...LISTED[1], status: 'completed' }];
const PHYS = { name: 'PHYS 211', source: 'manual', status: 'unknown' };
const STAT = { name: 'STAT 400', source: 'manual', status: 'in_progress' };
const RT0 = 'Relevant Coursework: CS 225, CS 233';
const BASE = { ...DEFAULT_PROFILE, name: 'Alex', home_school: 'uiuc', institution: 'UIUC',
  college: 'Engineering', major: 'Computer Science', grade: 'Junior', research_interests: 'Original research',
  resume_text: RT0, coursework: NAMES, courses: LISTED } as unknown as ProfileData;
const t = (key: string) => key;
let remote: ProfileData;
let revision: number;
let sequence = 0;
function row(): LoadedProfile {
  return { source: 'cloud', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision, token: captureOwnerToken() };
}
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  if (intent.expectedRevision !== revision) return { status: 'conflict', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision };
  remote = { ...remote, ...intent.patch } as ProfileData; revision += 1;
  return { status: 'saved', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision };
}
async function drain() {
  for (let pass = 0; pass < 4; pass += 1) {
    await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); });
  }
}
async function tick(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await drain(); }
async function start() {
  const hook = renderHook(() => useProfileForm(t));
  act(() => { service.auth?.({ user: { id: `newer-build-${sequence}` } }); }); await drain();
  expect(hook.result.current.hydrationState).toBe('ready');
  return hook;
}
async function focus() { act(() => { window.dispatchEvent(new Event('focus')); }); await drain(); await tick(100); }

/** An operation as another tab appended it, by its lineage. */
function op(lineage: string, fields: [string, unknown, unknown][], baseRevision = 1, seq = 1): string {
  const ops = readOutstandingOps();
  const clock = Math.max(0, ...(ops.ok ? ops.value.map((o) => o.clock ?? 0) : [])) + 1;
  const opId = crypto.randomUUID();
  localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${opId}`, JSON.stringify({
    opId, originId: lineage, lineage,
    fields: fields.map(([key, base, desired]) => ({ key, base: base === undefined ? { present: false } : { present: true, value: base }, desired: { present: true, value: desired } })),
    baseRevision, writer: HOME_FORM_WRITER, mode: 'set', seq, clock,
  }));
  return opId;
}
/** A status click (or a course added) in a tab of the course-status build:
 *  the course list and its names, in one operation. */
const click = (courses: unknown[], { baseRevision = 1, seq = 1, base = LISTED as unknown[] } = {}) => op('course-status-tab', [
  ['courses', base, courses], ['coursework', base.map((c) => (c as { name: string }).name), courses.map((c) => (c as { name: string }).name)],
], baseRevision, seq);
/** A résumé removal in a tab of this build that is gone now. */
const removal = (lineage: string) => op(lineage, [['resume_text', RT0, ''], ['coursework', NAMES, []],
  ['experience_entries', undefined, []], ['resume_master', undefined, null]]);
/** The course-status tab saves its click (operation `opId`) into a conflict
 *  with the stored row, and its outbox entry is stored as that build writes
 *  it (review m13p1v3-a, dump s1): the two course keys only, locked, over the
 *  row that refused them, with the rest of that tab's form as it last drew
 *  it, the old résumé included. */
function courseTabSaves(courses: unknown[], opId: string, extra: Record<string, unknown> = {}, extraOps: string[] = []) {
  const shown = { ...BASE, courses, coursework: courses.map((c) => (c as { name: string }).name), ...extra };
  const keys = ['courses', 'coursework', ...Object.keys(extra)];
  const entry = { v: 1, confirmed: { revision, profile: structuredClone(remote) }, tombstone: null, pending: {
    mutationId: crypto.randomUUID(), baseRevision: revision, baseProfile: structuredClone(remote), desiredProfile: shown,
    dirtyKeys: keys, keyVersions: Object.fromEntries(keys.map((k) => [k, 2])), skillAdditions: [], skillsReplaced: false,
    skillOps: [], additiveKeys: [], lockedKeys: keys, conflictRemote: structuredClone(remote), legacy: false,
    deferredCreate: false, journalOpIds: [opId, ...extraOps],
    journalPlan: { courses: [opId], coursework: [opId], ...Object.fromEntries(Object.keys(extra).map((k) => [k, extraOps])) },
  } };
  expect(writeLocalStorageJSON(STORAGE_KEYS.PROFILE_SYNC, entry, captureOwnerToken())).toBe(true);
  expect(writeLocalStorageJSON(STORAGE_KEYS.PROFILE, { ...remote, ...Object.fromEntries(keys.map((k) => [k, (shown as Record<string, unknown>)[k]])) },
    captureOwnerToken())).toBe(true);
  return entry.pending;
}
/** The outbox entry as stored, read raw rather than through this build. */
const storedEntry = () => (JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC) ?? 'null') as { pending: Record<string, unknown> | null } | null)?.pending ?? null;

type R = { current: ReturnType<typeof useProfileForm> };
const KEYS = ['resume_text', 'coursework', 'courses', 'experience_entries', 'resume_master'] as const;
const screen = (result: R) => Object.fromEntries(KEYS.map((k) => [k, structuredClone((result.current.profile as unknown as Record<string, unknown>)[k])]));
const outstanding = () => { const read = readOutstandingOps(); return read.ok ? read.value.filter((o) => o.mode !== 'resolve').length : -1; };
const sentSince = (from: number) => service.commit.mock.calls.slice(from).map(([intent]) => intent.patch);

/** This build's answer to the question: the reload message, no way to answer
 *  it here, the screen as it was, and nothing sent. */
async function expectHeld(result: R, shown: ReturnType<typeof screen>) {
  expect(result.current.conflicts.length, 'the question is still open').toBeGreaterThan(0);
  expect(screen(result), 'the fields stay as they are on screen').toEqual(shown);
  const atRevision = revision;
  const stored = structuredClone(remote);
  const ops = outstanding();
  const said = [result.current.saveStatus];
  for (const answer of ['keepMyChanges', 'useCloudVersion'] as const) {
    const before = service.commit.mock.calls.length;
    act(() => { result.current[answer](); }); await tick(3000);
    expect(sentSince(before), `${answer} sends nothing`).toEqual([]);
    expect(result.current.conflicts.length).toBeGreaterThan(0);
    expect(screen(result)).toEqual(shown);
    said.push(result.current.saveStatus);
  }
  // Generate does not go past the question.
  expect(hasSelectedSeekingType(result.current.profile)).toBe(true);
  const before = service.commit.mock.calls.length;
  await act(async () => { result.current.handleSubmit(); }); await tick(4000);
  expect(service.router.push, 'Generate stays on the form').not.toHaveBeenCalled();
  expect(sentSince(before), 'Generate sends nothing').toEqual([]);
  expect(screen(result)).toEqual(shown);
  expect(revision).toBe(atRevision);
  expect(remote).toEqual(stored);
  expect(outstanding(), 'nothing typed is dropped').toBe(ops);
  said.push(result.current.saveStatus);
  expect(said, 'shown, after each answer and after Generate').toEqual(Array(4).fill('conflict-newer-build'));
  expect(result.current.conflicts.every((c) => c.newerBuild === true), 'asked as a newer build\'s question').toBe(true);
}

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auth = null; service.params = new URLSearchParams(); service.router.push.mockReset();
  localStorage.clear(); sessionStorage.clear();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  sequence += 1;
  const uid = `newer-build-${sequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  expect(isOwnerTokenValid(captureOwnerToken(), uid)).toBe(true);
  remote = structuredClone(BASE); revision = 1;
  service.load.mockReset().mockImplementation(async () => row());
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('a conflict question holding an operation of the course-status build (checklist M13)', () => {
  it('F1: a tab that typed nothing keeps the newer résumé it shows and sends nothing', async () => {
    const { result } = await start();
    const PHONE = { resume_text: 'Phone résumé: PHYS 211', coursework: ['PHYS 211'], courses: [{ ...PHYS, source: 'resume' }] };
    remote = { ...remote, ...PHONE } as unknown as ProfileData; revision += 1;
    await focus();
    expect(result.current.profile.resume_text).toBe(PHONE.resume_text);
    const shown = screen(result);
    // A tab of the course-status build, open on revision 1, marks a course.
    courseTabSaves(MARKED, click(MARKED));
    await focus();
    await expectHeld(result, shown);
    expect(remote.resume_text, 'nobody typed the old résumé over the phone\'s').toBe(PHONE.resume_text);
    // A field outside the question still saves, alone, and the message stays.
    const before = service.commit.mock.calls.length;
    act(() => { result.current.update('research_interests', 'Robotics'); }); await tick(3000);
    expect(sentSince(before).length).toBeGreaterThan(0);
    expect(sentSince(before).every((patch) => JSON.stringify(patch) === '{"research_interests":"Robotics"}')).toBe(true);
    expect(remote.research_interests).toBe('Robotics');
    expect(result.current.saveStatus).toBe('conflict-newer-build');
    expect(screen(result)).toEqual(shown);
    expect(remote.resume_text).toBe(PHONE.resume_text);
  });

  it('F2: an older tab\'s résumé removal beside a status click is not answered here', async () => {
    const { result } = await start();
    const shown = screen(result);
    removal('closed-tab');
    click(MARKED);
    await focus();
    await expectHeld(result, shown);
  });

  it('F4b: a résumé removal typed here while the course question is open is held, not lost', async () => {
    // Another device added a course (revision 2); the course-status tab, open
    // on revision 1, marks one and saves into a conflict.
    remote = { ...remote, coursework: [...NAMES, PHYS.name], courses: [...LISTED, PHYS] } as unknown as ProfileData; revision += 1;
    const { result } = await start();
    courseTabSaves(MARKED, click(MARKED));
    await focus();
    expect(result.current.conflicts.length).toBeGreaterThan(0);
    const before = service.commit.mock.calls.length;
    act(() => { expect(result.current.handleResumeRemoved()).toBe(true); }); await tick(3000);
    expect(result.current.profile.resume_text).toBe('');
    expect(sentSince(before), 'the removal is held with the question').toEqual([]);
    await expectHeld(result, screen(result));
    expect(outstanding(), 'the course click and the removal').toBe(2);
  });

  it('F4c: after a reload, with the newer tab\'s partial answer stored, still nothing is answered here', async () => {
    remote = { ...remote, coursework: [...NAMES, PHYS.name], courses: [...LISTED, PHYS] } as unknown as ProfileData; revision += 1;
    const first = await start();
    courseTabSaves(MARKED, click(MARKED));
    await focus();
    act(() => { first.result.current.handleResumeRemoved(); }); await tick(3000);
    first.unmount();
    // The course-status tab answered and stored only the résumé text.
    remote = { ...remote, resume_text: '' } as ProfileData; revision += 1;
    const { result } = await start();
    await focus();
    await expectHeld(result, screen(result));
  });

  it('F4d: a tab opened after the removing tab closed, with a course added while asked, sends nothing', async () => {
    remote = { ...remote, coursework: [...NAMES, PHYS.name], courses: [...LISTED, PHYS] } as unknown as ProfileData; revision += 1;
    courseTabSaves(MARKED, click(MARKED));
    removal('closed-tab');
    click([...MARKED, STAT], { base: MARKED, seq: 2 });
    const { result } = await start();
    await focus();
    await expectHeld(result, screen(result));
    expect(outstanding()).toBe(3);
  });
});

describe('what this build leaves to the course-status build (review m13p1v3-a)', () => {
  const PHONE = { resume_text: 'Phone résumé: PHYS 211', coursework: ['PHYS 211'], courses: [{ ...PHYS, source: 'resume' }] };
  /** The course-status tab's part of an outbox entry: its keys, their locks,
   *  values, versions and operations. */
  const coursePart = (entry: Record<string, unknown> | null) => {
    const keys = ['courses', 'coursework'];
    const pick = (record: unknown) => Object.fromEntries(keys.map((k) => [k, (record as Record<string, unknown>)?.[k]]));
    return { dirtyKeys: entry?.dirtyKeys, lockedKeys: entry?.lockedKeys, desired: pick(entry?.desiredProfile),
      keyVersions: pick(entry?.keyVersions), journalPlan: pick(entry?.journalPlan) };
  };

  /** An outbox entry with only the values it would send: a load moves the
   *  rest of its working copy onto the stored row, in every build. */
  const unsent = (entry: Record<string, unknown> | null) => entry && { ...entry,
    desiredProfile: Object.fromEntries((entry.dirtyKeys as string[]).map((k) => [k, (entry.desiredProfile as Record<string, unknown>)[k]])) };

  it('MF1: a tab opened here neither completes nor re-stages the course tab\'s unsent entry, and shows the newer résumé', async () => {
    remote = { ...remote, ...PHONE } as unknown as ProfileData; revision += 1;
    const written = structuredClone(courseTabSaves(MARKED, click(MARKED)));
    const { result } = await start();
    await focus();
    expect(unsent(storedEntry()), 'the entry as the course-status build wrote it').toEqual(unsent(written));
    expect(result.current.profile.resume_text, 'the phone\'s résumé, not the course tab\'s old copy').toBe(PHONE.resume_text);
    expect(result.current.saveStatus).toBe('conflict-newer-build');
    expect(result.current.conflicts.map((c) => c.key).sort()).toEqual(['courses', 'coursework']);
    // An autosave of another field sends that field alone and leaves the
    // course tab's part of the entry as it was.
    act(() => { result.current.update('research_interests', 'Robotics'); }); await tick(3000);
    expect(sentSince(0)).toEqual(sentSince(0).map(() => ({ research_interests: 'Robotics' })));
    expect(remote.research_interests).toBe('Robotics');
    expect(coursePart(storedEntry())).toEqual(coursePart(written));
    expect(result.current.profile.resume_text).toBe(PHONE.resume_text);
    expect(remote.resume_text).toBe(PHONE.resume_text);
    expect(result.current.saveStatus).toBe('conflict-newer-build');
  });

  it('item 2: a question the course operation reaches only through fields pulled into it is held', async () => {
    const EA = { id: 'ea', revision: 1, status: 'confirmed', text: 'Lab A', source: { kind: 'manual' } };
    const EC = { id: 'ec', revision: 1, status: 'confirmed', text: 'Lab C', source: { kind: 'manual' } };
    const experience = (lineage: string, entry: unknown) => op(lineage, [['resume_text', RT0, RT0],
      ['coursework', NAMES, NAMES], ['experience_entries', [], [entry]], ['resume_master', null, null]]);
    remote = { ...remote, experience_entries: [] } as unknown as ProfileData;
    experience('tab-a', EA); experience('tab-c', EC); click(MARKED);
    const { result } = await start();
    await focus();
    expect(result.current.conflicts.map((c) => c.key)).toContain('courses');
    await expectHeld(result, screen(result));
  });

  it('item 3: an unrelated question shown beside a held one is answered as without it', async () => {
    op('t1', [['research_interests', 'Original research', 'Bio']]);
    op('t2', [['research_interests', 'Original research', 'Chem']]);
    removal('closed-tab'); click(MARKED);
    const { result } = await start();
    await focus();
    const marked = (c: { newerBuild?: true }) => c.newerBuild === true;
    expect(result.current.conflicts.filter((c) => !marked(c)).map((c) => c.key)).toEqual(['research_interests']);
    expect(result.current.conflicts.filter(marked).map((c) => c.key)).toContain('courses');
    expect(result.current.saveStatus, 'the unrelated question can be answered').toBe('conflict');
    const shown = screen(result);
    act(() => { result.current.useCloudVersion(); }); await tick(3000);
    expect(sentSince(0), 'the other version is the stored one').toEqual([]);
    expect(result.current.conflicts.map((c) => c.key)).not.toContain('research_interests');
    expect(result.current.profile.research_interests).toBe('Original research');
    expect(outstanding(), 'only the two research-interest edits were settled').toBe(2);
    await expectHeld(result, shown);
  });

  /** This tab types a research interest while a phone stores a new résumé
   *  and research interest: the save comes back a conflict, locked. */
  async function lockedHere() {
    const hook = await start();
    remote = { ...remote, ...PHONE, research_interests: 'Phone research' } as unknown as ProfileData; revision += 1;
    act(() => { hook.result.current.update('research_interests', 'Mine'); }); await tick(3000);
    expect(storedEntry()?.lockedKeys).toEqual(['research_interests']);
    return hook;
  }
  /** Typed again here, a locked field is this tab's answer: it is sent. */
  async function typedAgain(result: R) {
    const before = service.commit.mock.calls.length;
    act(() => { result.current.update('research_interests', 'Mine again'); }); await tick(3000);
    expect(sentSince(before).length).toBeGreaterThan(0);
    expect(sentSince(before)).toEqual(sentSince(before).map(() => ({ research_interests: 'Mine again' })));
    expect(remote.research_interests).toBe('Mine again');
    await focus();
    expect(result.current.conflicts.map((c) => c.key)).not.toContain('research_interests');
  }

  it('item 3, control: with no course question, a locked field typed again unlocks and is sent', async () => {
    const { result } = await lockedHere();
    await focus();
    await typedAgain(result);
  });

  it('item 3: a locked field outside the held question, typed again, unlocks and is sent as without it', async () => {
    const { result } = await lockedHere();
    // The course-status tab's click is refused too, and staged into the same
    // outbox entry, as that build layers it.
    const opId = click(MARKED);
    const entry = storedEntry()!;
    const desired = entry.desiredProfile as Record<string, unknown>;
    expect(writeLocalStorageJSON(STORAGE_KEYS.PROFILE_SYNC, { ...JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)!), pending: {
      ...entry, desiredProfile: { ...desired, courses: MARKED, coursework: NAMES },
      dirtyKeys: [...entry.dirtyKeys as string[], 'courses', 'coursework'], lockedKeys: [...entry.lockedKeys as string[], 'courses', 'coursework'],
      keyVersions: { ...entry.keyVersions as object, courses: 2, coursework: 2 },
      journalOpIds: [...entry.journalOpIds as string[], opId],
      journalPlan: { ...entry.journalPlan as object, courses: [opId], coursework: [opId] },
    } }, captureOwnerToken())).toBe(true);
    await focus();
    expect(result.current.conflicts.filter((c) => !c.newerBuild).map((c) => c.key)).toEqual(['research_interests']);
    await typedAgain(result);
    expect(result.current.conflicts.map((c) => c.key).sort()).toEqual(['courses', 'coursework']);
    expect(result.current.saveStatus).toBe('conflict-newer-build');
    expect(remote.resume_text).toBe(PHONE.resume_text);
  });
});

describe('the reload message (checklist M13)', () => {
  it('has English and Chinese text', async () => {
    const { dictionaries } = await import('@/i18n/dictionaries');
    for (const locale of ['en', 'zh'] as const) {
      const actions = (dictionaries[locale].home as Record<string, unknown>).actions as Record<string, string>;
      expect(actions.profileConflictNewerBuild, `${locale}.home.actions.profileConflictNewerBuild`).toBeTruthy();
      expect(actions.profileConflictNewerBuild).not.toBe(actions.profileConflict);
    }
  });
});

describe('a guest profile restored by a build without `courses` (review m13reg nit 1)', () => {
  it('reads as restored, so the notice does not offer the restore again', async () => {
    const GUEST = { ...DEFAULT_PROFILE, name: 'Guest', college: 'Engineering', major: 'Physics', grade: 'Freshman',
      research_interests: 'Guest research', search_weight: 70 };
    const restored = { ...FRESH_PROFILE, ...GUEST } as Record<string, unknown>;
    delete restored.courses;
    remote = restored as unknown as ProfileData;
    const { result } = await start();
    expect(result.current.isArchivedProfileStored(structuredClone(GUEST), captureOwnerToken())).toBe(true);
  });
});
