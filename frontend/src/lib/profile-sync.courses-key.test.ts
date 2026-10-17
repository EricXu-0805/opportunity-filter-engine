import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ProfileData } from './types';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from './supabase';

// The service layer is faked; the journal, the coordinator and jsdom's
// localStorage are the production code.
const loadProfileMock = vi.fn<() => Promise<LoadedProfile>>();
const commitMock = vi.fn<(i: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>();
vi.mock('./supabase', () => ({
  loadProfile: () => loadProfileMock(),
  commitProfilePatch: (intent: ProfilePatchIntent) => commitMock(intent),
}));

import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { appendJournalOp, readOutstandingOps, resetJournalLaneForTests, type JournalOp } from './profile-journal';
import {
  HOME_FORM_WRITER, hydrateProfile, makeConflictPrompt, makeProfileViewSnapshot, planKeysFromJournalForTests,
  readCurrentConflicts, readProfileSyncEnvelope, recordProfileIntent, resetProfileDirtyLedger, resolveProfileConflict,
  stageProfilePatch, storedProfileIs,
} from './profile-sync';

// Checklist M13 ships in two steps. The build that stores course statuses
// writes a profile key, `courses`, that a build without it does not know: its
// journal fails closed on an unknown key, so one `courses` operation left in
// the browser by a tab of the newer build stopped every save of an older tab
// (review-m13fe-b round 2, F/F2/F4/F5). This build only learns the key: it
// accepts and sends such an operation, and holds `courses` and `coursework`
// together in a conflict. Nothing here writes `courses` itself.
const FULL: ProfileData = {
  institution: 'UIUC', home_school: 'uiuc', college: 'Grainger', major: 'CS', grade: 'Junior',
  is_international: false, research_interests: 'robotics', skills: [{ name: 'Python', level: 'experienced' }],
  search_weight: 50, resume_text: 'Relevant Coursework: CS 225, CS 233', coursework: ['CS 225', 'CS 233'],
};
const LISTED = [
  { name: 'CS 225', source: 'resume' as const, status: 'unknown' as const },
  { name: 'CS 233', source: 'resume' as const, status: 'unknown' as const },
];
const MARKED = [{ name: 'CS 225', source: 'resume' as const, status: 'completed' as const }, LISTED[1]];
const NAMES = ['CS 225', 'CS 233'];

const cloud = (profile: ProfileData, revision: number): LoadedProfile => (
  { source: 'cloud', profile: profile as unknown as Record<string, unknown>, revision, token: captureOwnerToken() });
const saved = (profile: ProfileData, revision: number): ProfilePatchOutcome => (
  { status: 'saved', revision, profile: profile as unknown as Record<string, unknown> });
const conflict = (profile: ProfileData, revision: number): ProfilePatchOutcome => (
  { status: 'conflict', revision, profile: profile as unknown as Record<string, unknown> });

/** What a home-form tab of the course-status build appends after one status
 *  click: the course list and its names, in one operation. */
function courseClickFromNewerTab(token: ReturnType<typeof captureOwnerToken>, courses: unknown = MARKED) {
  return appendJournalOp({
    fields: [
      { key: 'courses', base: { present: false }, desired: { present: true, value: courses } },
      { key: 'coursework', base: { present: true, value: NAMES }, desired: { present: true, value: NAMES } },
    ],
    baseRevision: 7,
    writer: HOME_FORM_WRITER,
    mode: 'set',
    originId: 'course-status-tab',
    lineage: 'course-status-tab-lineage',
  }, token);
}

beforeEach(async () => {
  let chain: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, 'locks', {
    configurable: true,
    value: {
      request: (_name: string, _opts: unknown, fn: () => Promise<unknown>) => {
        const run = chain.then(() => fn());
        chain = run.then(() => undefined, () => undefined);
        return run;
      },
    },
  });
  localStorage.clear();
  resetJournalLaneForTests();
  loadProfileMock.mockReset();
  commitMock.mockReset();
  resetProfileDirtyLedger();
  advanceOwnerEpoch(null);
  advanceOwnerEpoch('courses-key-u1');
  await syncLocalIdentityOwner('courses-key-u1');
});

describe('a `courses` operation written by the course-status build (checklist M13)', () => {
  it('is read, not refused as an unknown profile key, and a save of another field goes through', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    expect(courseClickFromNewerTab(token)).not.toBeNull();

    const read = readOutstandingOps();
    expect(read.ok ? null : read.reason, 'the journal reads').toBeNull();
    expect(read.ok && read.value.flatMap((op) => op.fields.map((field) => field.key))).toEqual(['courses', 'coursework']);

    // This tab's own edit is recorded and saved.
    const edited = { ...FULL, research_interests: 'robotics, control' };
    expect(recordProfileIntent(edited, ['research_interests'], token)).toBe(true);
    commitMock.mockImplementation(async (intent) => saved({ ...FULL, ...intent.patch } as ProfileData, 8));
    const result = await stageProfilePatch(edited, ['research_interests'], token);
    expect(result.status).toBe('saved');
    expect(commitMock.mock.calls.at(-1)?.[0].patch).toMatchObject({ research_interests: 'robotics, control' });
  });

  it('reads an operation continuing a course edit whose base held no courses', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    // The newer build carries a field's first base through an edit chain; one
    // that began before the row had `courses` is written as present with no value.
    expect(appendJournalOp({
      fields: [{ key: 'courses', base: { present: true, value: undefined }, desired: { present: true, value: MARKED } }],
      baseRevision: 7, writer: HOME_FORM_WRITER, mode: 'set', originId: 'course-status-tab', lineage: 'course-status-tab-lineage',
    }, captureOwnerToken())).not.toBeNull();
    const read = readOutstandingOps();
    expect(read.ok ? null : read.reason).toBeNull();
  });

  it('refuses a `courses` value that is not a course list, as for any known key', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    expect(courseClickFromNewerTab(captureOwnerToken(), 'CS 225')).toBeNull();
    expect(courseClickFromNewerTab(captureOwnerToken(), [{ name: 'CS 225', status: 1 }])).toBeNull();
    expect(readOutstandingOps()).toMatchObject({ ok: true, value: [] });
  });
});

describe('the courses and their names are one unit in a conflict (checklist M13)', () => {
  it('a collision on one holds both, and neither goes out without the other', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, courses: LISTED }, 7));
    await hydrateProfile();
    // Meanwhile a tab without `courses` removed the résumé: it writes the
    // names, never `courses`.
    const remote = { ...FULL, resume_text: '', courses: LISTED, coursework: [] };
    commitMock
      .mockResolvedValueOnce(conflict(remote, 8))
      .mockImplementation(async (intent) => saved({ ...remote, ...intent.patch } as ProfileData, 9));
    const result = await stageProfilePatch({ ...FULL, courses: MARKED }, ['courses', 'coursework'], captureOwnerToken());
    expect(result.status).toBe('conflict');
    expect((result as { conflictKeys: string[] }).conflictKeys).toEqual(expect.arrayContaining(['courses', 'coursework']));
    expect(commitMock, 'neither course key goes out without the other').toHaveBeenCalledTimes(1);
  });

  it('the journal plan holds both while either is in question', () => {
    const op = (originId: string, fields: JournalOp['fields']): JournalOp => ({
      opId: `${originId}-op`, originId, lineage: `${originId}-lineage`, seq: 1, fields, baseRevision: 7, writer: 'default', mode: 'set',
    });
    const plan = planKeysFromJournalForTests([
      op('this-tab', [
        { key: 'courses', base: { present: true, value: LISTED }, desired: { present: true, value: MARKED } },
        { key: 'coursework', base: { present: true, value: NAMES }, desired: { present: true, value: NAMES } },
      ]),
      op('other-tab', [{ key: 'coursework', base: { present: true, value: NAMES }, desired: { present: true, value: [] } }]),
    ], ['courses', 'coursework']);
    expect(plan.get('coursework')?.kind).toBe('conflict');
    expect(plan.get('courses')?.kind).toBe('conflict');
  });
});

// The build before this one holds such a question for the course-status
// build (rollout phase 1). This is the course-status build: it answers it.
describe('a question holding a course-status operation is answered by this build (checklist M13)', () => {
  it('stages a status click, marks no field of its question, and keeps what was clicked when asked to', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, courses: LISTED }, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    // This tab, on revision 7, marks a course while another device adds one.
    const remote = { ...FULL, courses: [...LISTED, { name: 'PHYS 211', source: 'manual' as const, status: 'unknown' as const }], coursework: [...NAMES, 'PHYS 211'] };
    commitMock
      .mockResolvedValueOnce(conflict(remote, 8))
      .mockImplementation(async (intent) => saved({ ...remote, ...intent.patch } as ProfileData, 9));
    const clicked = { ...FULL, courses: MARKED };
    expect(recordProfileIntent(clicked, ['courses', 'coursework'], token)).toBe(true);
    const staged = await stageProfilePatch(clicked, ['courses', 'coursework'], token);
    expect(staged.status).toBe('conflict');
    const asked = readCurrentConflicts((staged as { conflictKeys: string[] }).conflictKeys, token);
    expect(asked.map((c) => c.key)).toEqual(expect.arrayContaining(['courses', 'coursework']));
    expect(asked.some((c) => 'newerBuild' in c)).toBe(false);
    const view = makeProfileViewSnapshot({ baseProfile: clicked, renderedProfile: clicked,
      revision: readProfileSyncEnvelope()?.confirmed?.revision ?? 0, token, identityGeneration: token.epoch, source: 'hydration' });
    const result = await resolveProfileConflict({ prompt: makeConflictPrompt(view, asked), actionView: view, choice: 'local' });
    expect(result.status).toBe('saved');
    expect(commitMock.mock.calls.at(-1)![0].patch).toMatchObject({ courses: MARKED, coursework: NAMES });
  });
});

describe('a row restored by a build without `courses` (review m13reg nit 1)', () => {
  it('holds no courses: absent is the same as an empty list', () => {
    const restored = { ...FULL, courses: [] } as unknown as Record<string, unknown>;
    expect(storedProfileIs({ ...FULL } as unknown as Record<string, unknown>, restored)).toBe(true);
    expect(storedProfileIs({ ...FULL, courses: [] } as unknown as Record<string, unknown>, { ...FULL } as unknown as Record<string, unknown>)).toBe(true);
    expect(storedProfileIs({ ...FULL } as unknown as Record<string, unknown>, { ...FULL, courses: LISTED } as unknown as Record<string, unknown>)).toBe(false);
    expect(storedProfileIs({ ...FULL, coursework: [] } as unknown as Record<string, unknown>, { ...FULL } as unknown as Record<string, unknown>)).toBe(false);
  });
});
