import { act, cleanup, render } from '@testing-library/react';
import { useEffect } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData, ResumeParseResponse } from '@/lib/types';

const service = vi.hoisted(() => ({
  auth: null as null | ((state: { user: { id: string } | null }) => void),
  load: vi.fn<(signal?: AbortSignal) => Promise<LoadedProfile>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
const pdf = vi.hoisted(() => ({ lines: [] as string[] }));
vi.mock('next/navigation', () => ({ useRouter: () => service.router, useSearchParams: () => service.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
// Only transport is replaced: the coordinator, the journal, the owner
// capabilities and Home's save handling are the real ones.
vi.mock('@/lib/supabase', () => ({
  loadProfile: (signal?: AbortSignal) => service.load(signal),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof service.auth) => { service.auth = callback; return () => { service.auth = null; }; },
}));
// A résumé whose every line is one PDF text item, read by the real parser.
vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: () => ({ promise: Promise.resolve({
    numPages: pdf.lines.length,
    destroy: async () => {},
    getPage: async (n: number) => ({ cleanup: () => {}, getTextContent: async () => ({ items: [{ str: pdf.lines[n - 1] }] }) }),
  }) }),
}));
// The course list's release switch, as this branch ships it unless a test
// turns it off.
const release = vi.hoisted(() => ({ courseStatus: true }));
vi.mock('@/lib/release-scope', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/release-scope')>();
  return { ...actual, RELEASE_SCOPE: { ...actual.RELEASE_SCOPE, get courseStatus() { return release.courseStatus; } } };
});
import { useProfileForm } from './use-profile-form';
import { translate } from '@/i18n/translate';
import { courseEntries, courseRows, storedCourse } from '@/lib/course-status';
import { parseResumePDF } from '@/lib/pdf-parser';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { resetProfileDirtyLedger } from '@/lib/profile-sync';
import { resetJournalLaneForTests, startDocumentForTests } from '@/lib/profile-journal';

// Checklist M13: what the form, every request and the cloud row say of a
// course after a résumé import, a removal and a re-import, including the
// writes of a tab still on the previous build.
let row: { profile: ProfileData; revision: number } | null;
let uid: string;
let sequence = 0;
function read(): LoadedProfile {
  const token = captureOwnerToken();
  return row
    ? { source: 'cloud', profile: structuredClone(row.profile) as unknown as Record<string, unknown>, revision: row.revision, token }
    : { source: 'cloud-absent', profile: null, revision: 0, token };
}
function completeCreate(patch: Record<string, unknown>): boolean {
  const filled = (k: string) => typeof patch[k] === 'string' && (patch[k] as string).trim() !== '';
  return 'home_school' in patch && filled('college') && filled('major') && filled('grade')
    && typeof patch.search_weight === 'number' && patch.search_weight >= 0 && patch.search_weight <= 100;
}
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  if (!row) {
    if (intent.expectedRevision !== 0) return { status: 'missing', reason: 'absent' };
    if (!completeCreate(intent.patch)) {
      return { status: 'transport-error', message: 'commit_profile_patch_cas: incomplete_create' };
    }
    row = { profile: structuredClone(intent.patch) as unknown as ProfileData, revision: 1 };
    return { status: 'saved', profile: structuredClone(row.profile) as unknown as Record<string, unknown>, revision: 1 };
  }
  const answer = () => structuredClone(row!.profile) as unknown as Record<string, unknown>;
  if (intent.expectedRevision !== row.revision) return { status: 'conflict', profile: answer(), revision: row.revision };
  row.profile = { ...row.profile, ...intent.patch } as ProfileData; row.revision += 1;
  return { status: 'saved', profile: answer(), revision: row.revision };
}
/** A tab on the previous build writes its patch the same way: per key, merged. */
function previousBuildWrites(patch: Partial<ProfileData>) {
  row = { profile: { ...row!.profile, ...patch }, revision: row!.revision + 1 };
}
const sends = () => service.commit.mock.calls.map(([intent]) => ({ expected: intent.expectedRevision, patch: intent.patch }));
async function drain() {
  for (let pass = 0; pass < 4; pass += 1) {
    await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); });
  }
}
async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await drain();
}

const EN = (key: string) => translate('en', key);
const live: { form: ReturnType<typeof useProfileForm> | null } = { form: null };
const form = () => live.form!;
function Home() {
  const home = useProfileForm(EN);
  useEffect(() => { live.form = home; });
  return null;
}
async function mount() {
  const view = render(<Home />);
  act(() => { service.auth?.({ user: { id: uid } }); }); await drain();
  expect(form().hydrationState).toBe('ready');
  return view;
}
async function reload(view: ReturnType<typeof render>) {
  view.unmount();
  cleanup(); await drain(); startDocumentForTests('reload'); resetProfileDirtyLedger();
  return mount();
}
async function edit<K extends keyof ProfileData>(key: K, value: ProfileData[K]) {
  act(() => { form().update(key, value); });
  await tick(1600);
}
async function importResume(...lines: string[]) {
  pdf.lines = lines;
  const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'resume.pdf', { type: 'application/pdf' });
  const parsed: ResumeParseResponse = await parseResumePDF(file);
  expect(parsed.success).toBe(true);
  act(() => { expect(form().handleResumeParsed(parsed)).toBe(true); });
  await tick(1600);
}
async function removeResume() {
  await act(async () => { expect(form().handleResumeRemoved()).toBe(true); });
  await tick(1600);
}
/** What every request, email and quick action says of each course. */
const statuses = () => Object.fromEntries(courseEntries(form().profile).map((course) => [course.name, course.status]));
/** What the form only suggests, from the current résumé text. */
const suggestions = () => Object.fromEntries(courseRows(form().profile).map((row) => [row.name, row.suggested ?? null]));

const SIGNED_UP: ProfileData = {
  name: '', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
  major: 'Computer Science', grade: 'Junior', is_international: false, research_interests: 'robotics', skills: [],
  search_weight: 50,
};

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auth = null; service.params = new URLSearchParams();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  uid = `home-courses-${++sequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  row = null;
  service.load.mockReset().mockImplementation(async () => read());
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('after a résumé import the form suggests a status only after a label opening a line or a column (R2)', () => {
  it('suggests one for every course of such a list and nothing else, and nothing leaves the form with it', async () => {
    row = { revision: 1, profile: SIGNED_UP };
    await mount();
    await importResume(
      'Current courses - CS 374, MATH 415',
      'Planned Courses — CS 446, CS 411',
      'Courses in progress - Machine Learning, Data Mining',
      'B.S. Computer Engineering | Currently taking: ECE 391 | Course Assistant, CS 124',
      'Peer Mentor: advised freshmen on courses to take: CS 128, MATH 221',
      'Completed/Current Coursework: CS 225, CS 233',
      'Current Coursework: STAT 410 | Completed: CS 357',
      'University of Illinois, B.S. Computer Engineering (expected May 2027) Coursework: ECE 220, ECE 385',
      'Coursework: CS 433 (Spring 2027)',
      'Course Assistant, CS 173 (Current)',
    );
    // "CS 433" is the listed "CS 433 (Spring 2027)" again, and is not stored (checklist M130).
    const none = ['CS 124', 'CS 128', 'MATH 221', 'CS 225', 'CS 233', 'CS 357', 'ECE 220', 'ECE 385', 'CS 433 (Spring 2027)', 'CS 173'];
    expect(suggestions()).toEqual({
      'CS 374': 'in_progress', 'MATH 415': 'in_progress', 'Machine Learning': 'in_progress', 'Data Mining': 'in_progress',
      'ECE 391': 'in_progress', 'STAT 410': 'in_progress', 'CS 446': 'planned', 'CS 411': 'planned',
      ...Object.fromEntries(none.map((name) => [name, null])),
    });
    // Requests, emails and the quick action: not marked until confirmed.
    expect(Object.values(statuses()).every((status) => status === 'unknown')).toBe(true);
    expect(Object.keys(statuses()).sort()).toEqual(Object.keys(suggestions()).sort());
  });
});

describe('a status read from the résumé is only a suggestion, never stored (R1, R3)', () => {
  it('stores the courses found without a status or a line, and sends them as not marked', async () => {
    row = { revision: 1, profile: SIGNED_UP };
    await mount();
    await importResume('Current Coursework: CS 374', 'Relevant Coursework: CS 225');
    expect(suggestions()).toEqual({ 'CS 225': null, 'CS 374': 'in_progress' });
    expect(statuses()).toEqual({ 'CS 225': 'unknown', 'CS 374': 'unknown' });
    expect(row?.profile.courses).toEqual([{ name: 'CS 225', source: 'resume' }, { name: 'CS 374', source: 'resume' }]);
    expect(row?.profile.coursework).toEqual(['CS 225', 'CS 374']);
    expect(JSON.stringify(row?.profile.courses)).not.toContain('Coursework:');
  });

  it('leaves nothing of a suggestion behind when the résumé is removed', async () => {
    row = { revision: 1, profile: SIGNED_UP };
    await mount();
    await importResume('Current Coursework: CS 374', 'Relevant Coursework: CS 225');
    await removeResume();
    expect(row?.profile.resume_text).toBe('');
    expect(row?.profile.courses).toEqual([]);
    expect(row?.profile.coursework).toEqual([]);
    expect(suggestions()).toEqual({});
  });

  it('keeps a suggestion the student confirmed, as their own status, when the résumé is removed', async () => {
    row = { revision: 1, profile: SIGNED_UP };
    await mount();
    await importResume('Current Coursework: CS 374', 'Relevant Coursework: CS 225');
    await edit('courses', [{ name: 'CS 225', source: 'resume' }, { name: 'CS 374', source: 'resume', status: 'in_progress' }]);
    expect(statuses()).toEqual({ 'CS 225': 'unknown', 'CS 374': 'in_progress' });
    await removeResume();
    expect(row?.profile.courses).toEqual([{ name: 'CS 374', source: 'resume', status: 'in_progress' }]);
    expect(statuses()).toEqual({ 'CS 374': 'in_progress' });
  });

  it('reads the suggestions again from the new text on a re-import', async () => {
    row = { revision: 1, profile: SIGNED_UP };
    const view = await mount();
    await importResume('Current Coursework: CS 374');
    expect(suggestions()).toEqual({ 'CS 374': 'in_progress' });
    await importResume('Relevant Coursework: CS 374', 'Planned courses: CS 446');
    expect(suggestions()).toEqual({ 'CS 374': null, 'CS 446': 'planned' });
    expect(statuses()).toEqual({ 'CS 374': 'unknown', 'CS 446': 'unknown' });
    expect(row?.profile.courses).toEqual([{ name: 'CS 374', source: 'resume' }, { name: 'CS 446', source: 'resume' }]);
    // And after a reload, from the stored text.
    await reload(view);
    expect(suggestions()).toEqual({ 'CS 374': null, 'CS 446': 'planned' });
  });
});

describe('a résumé course nobody marked counts only while the stored coursework names it (R4)', () => {
  // What this build stores after an import, a mark and an added course.
  const STORED: ProfileData = {
    ...SIGNED_UP,
    resume_text: 'Relevant Coursework: CS 225, CS 233, MATH 257\nCurrent courses: CS 374',
    courses: [
      { name: 'CS 225', source: 'resume' }, { name: 'CS 233', source: 'resume' }, { name: 'CS 374', source: 'resume' },
      { name: 'MATH 257', source: 'resume', status: 'completed' }, { name: 'STAT 400', source: 'manual', status: 'unknown' },
    ],
    coursework: ['CS 225', 'CS 233', 'CS 374', 'MATH 257', 'STAT 400'],
  };

  it('takes a removal made by a tab on the previous build, and the next course edit stores only what is shown', async () => {
    row = { revision: 3, profile: STORED };
    const view = await mount();
    expect(statuses()).toEqual({ 'CS 225': 'unknown', 'CS 233': 'unknown', 'CS 374': 'unknown', 'MATH 257': 'completed', 'STAT 400': 'unknown' });
    expect(suggestions()['CS 374']).toBe('in_progress');
    // 5181e8e8 use-profile-form.ts: removal writes these four keys only.
    previousBuildWrites({ resume_text: '', coursework: [], experience_entries: [], resume_master: null });
    await reload(view);
    expect(statuses()).toEqual({ 'MATH 257': 'completed', 'STAT 400': 'unknown' });
    // The names the old tab left in `courses` stay hidden until the next
    // course edit here, which writes the list the student sees.
    expect(row?.profile.courses).toHaveLength(5);
    await edit('courses', [...courseRows(form().profile).map(storedCourse), { name: 'ECE 110', source: 'manual', status: 'completed' }]);
    expect(row?.profile.courses).toEqual([
      { name: 'MATH 257', source: 'resume', status: 'completed' }, { name: 'STAT 400', source: 'manual', status: 'unknown' },
      { name: 'ECE 110', source: 'manual', status: 'completed' },
    ]);
    expect(row?.profile.coursework).toEqual(['MATH 257', 'STAT 400', 'ECE 110']);
  });

  it('takes a re-import made by a tab on the previous build', async () => {
    row = { revision: 3, profile: STORED };
    const view = await mount();
    previousBuildWrites({ resume_text: 'Relevant Coursework: CS 225, CS 411\nPlanned courses: CS 374', coursework: ['CS 225', 'CS 374', 'CS 411'] });
    await reload(view);
    expect(statuses()).toEqual({ 'CS 225': 'unknown', 'CS 374': 'unknown', 'MATH 257': 'completed', 'STAT 400': 'unknown', 'CS 411': 'unknown' });
    expect(suggestions()).toEqual({ 'CS 225': null, 'CS 374': 'planned', 'MATH 257': null, 'STAT 400': null, 'CS 411': null });
    // The next course edit writes the list as the student set it.
    await edit('courses', [
      { name: 'CS 225', source: 'resume', status: 'completed' }, { name: 'CS 374', source: 'resume' },
      { name: 'MATH 257', source: 'resume', status: 'completed' }, { name: 'STAT 400', source: 'manual', status: 'unknown' },
      { name: 'CS 411', source: 'resume' },
    ]);
    expect(row?.profile.courses).toEqual([
      { name: 'CS 225', source: 'resume', status: 'completed' }, { name: 'CS 374', source: 'resume' },
      { name: 'MATH 257', source: 'resume', status: 'completed' }, { name: 'STAT 400', source: 'manual', status: 'unknown' },
      { name: 'CS 411', source: 'resume' },
    ]);
    expect(row?.profile.coursework).toEqual(['CS 225', 'CS 374', 'MATH 257', 'STAT 400', 'CS 411']);
  });
});

describe('courses on a never-created row keep the M109 guarantees', () => {
  const C = (status: 'completed' | 'planned') => [{ name: 'CS 225', source: 'manual' as const, status }];
  it('a guest without college, major and grade who marks a course is awaiting-required, and nothing is sent', async () => {
    await mount();
    await edit('courses', C('planned'));
    expect(form().saveStatus).toBe('awaiting-required');
    expect(form().canRetrySync).toBe(false);
    expect(sends()).toEqual([]);
    expect(form().profile.coursework).toEqual(['CS 225']);
  });

  it('a newer session replaces an older session\'s course edit without a question, and the create carries both keys', async () => {
    let view = await mount();
    await edit('courses', C('planned'));
    view.unmount();
    cleanup(); await drain(); resetJournalLaneForTests(); resetProfileDirtyLedger();
    view = await mount();
    expect(form().profile.courses).toEqual(C('planned'));
    await edit('courses', C('completed'));
    expect(form().saveStatus).toBe('awaiting-required');
    view = await reload(view);
    expect(form().conflicts).toEqual([]);
    expect(form().profile.courses).toEqual(C('completed'));
    await edit('college', 'Grainger College of Engineering');
    await edit('major', 'Computer Science');
    await edit('grade', 'Junior');
    expect(sends()).toHaveLength(1);
    expect(sends()[0].patch).toMatchObject({ courses: C('completed'), coursework: ['CS 225'] });
    expect(row?.profile).toMatchObject({ courses: C('completed'), coursework: ['CS 225'] });
    expect(form().saveStatus).toBe('saved');
  });
});

describe('the course list release switch, RELEASE_SCOPE.courseStatus', () => {
  afterEach(() => { release.courseStatus = true; });
  // Another tab marked MATH 257 before this one opened.
  const MARKED_ELSEWHERE: ProfileData = { ...SIGNED_UP, resume_text: 'Relevant Coursework: MATH 257',
    courses: [{ name: 'MATH 257', source: 'resume', status: 'completed' }], coursework: ['MATH 257'] };

  it.each([true, false])('on: %s. A résumé import and removal write `courses` only while it is on, and the status another tab set is kept and sent either way', async (on) => {
    release.courseStatus = on;
    row = { revision: 1, profile: MARKED_ELSEWHERE };
    await mount();
    expect(statuses()).toEqual({ 'MATH 257': 'completed' });
    await importResume('Relevant Coursework: CS 225, MATH 257');
    expect(statuses()).toEqual({ 'MATH 257': 'completed', 'CS 225': 'unknown' });
    expect([...row!.profile.coursework!].sort()).toEqual(['CS 225', 'MATH 257']);
    expect(row?.profile.courses).toEqual(on
      ? expect.arrayContaining([...MARKED_ELSEWHERE.courses!, { name: 'CS 225', source: 'resume' }])
      : MARKED_ELSEWHERE.courses);
    await removeResume();
    expect(row?.profile.resume_text).toBe('');
    // Off, the names go as the build before this one removes them.
    expect(row?.profile.coursework).toEqual(on ? ['MATH 257'] : []);
    expect(row?.profile.courses).toEqual(MARKED_ELSEWHERE.courses);
    expect(statuses()).toEqual({ 'MATH 257': 'completed' });
    expect(sends().length).toBeGreaterThan(1);
    expect(sends().some(({ patch }) => 'courses' in patch)).toBe(on);
  });
});
