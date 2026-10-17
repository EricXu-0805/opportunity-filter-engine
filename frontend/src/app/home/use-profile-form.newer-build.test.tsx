import { act, cleanup, render, renderHook } from '@testing-library/react';
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
import { SubmitRow } from './SubmitRow';
import { DEFAULT_PROFILE, FRESH_PROFILE } from './types';
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { HOME_FORM_WRITER, resetProfileDirtyLedger } from '@/lib/profile-sync';
import { readOutstandingOps, resetJournalLaneForTests } from '@/lib/profile-journal';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { writeLocalStorageJSON } from '@/lib/use-local-storage-json';

// Checklist M13 ships in two builds. The build before this one groups the
// course names with the résumé, and holds every question with a journal
// operation carrying `courses` for the course-status build: it says a newer
// version of the page changed these fields and asks for a reload. This is the
// course-status build: it writes those operations and answers their questions
// itself, so no question here is held.
const NAMES = ['CS 225', 'CS 233'];
const LISTED = NAMES.map((name) => ({ name, source: 'resume', status: 'unknown' }));
const MARKED = [LISTED[0], { ...LISTED[1], status: 'completed' }];
const PHYS = { name: 'PHYS 211', source: 'manual', status: 'unknown' };
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
/** A status click (or a course added) in another tab of this build: the
 *  course list and its names, in one operation. */
const click = (courses: unknown[], { baseRevision = 1, seq = 1, base = LISTED as unknown[] } = {}) => op('course-status-tab', [
  ['courses', base, courses], ['coursework', base.map((c) => (c as { name: string }).name), courses.map((c) => (c as { name: string }).name)],
], baseRevision, seq);
/** That tab saves its click (operation `opId`) into a conflict with the
 *  stored row, and its outbox entry is stored as this build writes it
 *  (review m13p1v3-a, dump s1): the two course keys only, locked, over the
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
const sentSince = (from: number) => service.commit.mock.calls.slice(from).map(([intent]) => intent.patch);

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

describe('a conflict question holding an operation carrying `courses` (checklist M13)', () => {
  it('gets its two buttons in this build, and keeping what was typed sends the course click', async () => {
    const { result } = await start();
    const PHONE = { coursework: [...NAMES, PHYS.name], courses: [...LISTED, PHYS] };
    remote = { ...remote, ...PHONE } as unknown as ProfileData; revision += 1;
    await focus();
    // Another tab, open on revision 1, marks a course and saves into a conflict.
    courseTabSaves(MARKED, click(MARKED));
    await focus();
    const { conflicts, saveStatus } = result.current;
    expect(conflicts.map((c) => c.key)).toEqual(expect.arrayContaining(['courses', 'coursework']));
    expect(conflicts.some((c) => 'newerBuild' in c), 'no field is held for another build').toBe(false);
    expect(saveStatus).toBe('conflict');
    // The props Home draws the status line with (app/page.tsx).
    const rendered = render(<SubmitRow isValid shareCopied={false} saveStatus={saveStatus} hydrationState="ready" isSubmitting={false}
      hasConflict={conflicts.length > 0} conflictHeldForNewerBuild={conflicts.length > 0 && conflicts.every((c) => c.newerBuild === true)}
      canRetrySync={false} onRetrySync={vi.fn()} onRetryProfileLoad={vi.fn()} onKeepMyChanges={vi.fn()}
      onUseCloudVersion={vi.fn()} onSubmit={vi.fn()} onShare={vi.fn()} t={t as never} />);
    expect(rendered.getByTestId('conflict-keep-mine')).toBeTruthy();
    expect(rendered.getByTestId('conflict-use-cloud')).toBeTruthy();
    expect(rendered.queryByTestId('conflict-newer-build')).toBeNull();
    act(() => { result.current.keepMyChanges(); }); await tick(3000);
    expect(remote.courses).toEqual(MARKED);
    expect(result.current.conflicts).toEqual([]);
  });
});

describe('a locked field typed again (review m13p1v3-a, item 3)', () => {
  const PHONE = { resume_text: 'Phone résumé: PHYS 211', coursework: ['PHYS 211'], courses: [{ ...PHYS, source: 'resume' }] };

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
