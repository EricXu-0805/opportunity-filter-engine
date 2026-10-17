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
  stageProfilePatch, storedProfileIs, type ProfileConflict,
} from './profile-sync';
import { STORAGE_KEYS } from './storage-keys';
import { writeLocalStorageJSON } from './use-local-storage-json';

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

/** A résumé removal left by a tab of this build that is gone now. */
function removalFromClosedTab(token: ReturnType<typeof captureOwnerToken>) {
  return appendJournalOp({
    fields: [
      { key: 'resume_text', base: { present: true, value: FULL.resume_text }, desired: { present: true, value: '' } },
      { key: 'coursework', base: { present: true, value: NAMES }, desired: { present: true, value: [] } },
      { key: 'experience_entries', base: { present: false }, desired: { present: true, value: [] } },
      { key: 'resume_master', base: { present: false }, desired: { present: true, value: null } },
    ],
    baseRevision: 7, writer: HOME_FORM_WRITER, mode: 'set', originId: 'closed-tab', lineage: 'closed-tab-lineage',
  }, token);
}

describe('a question holding a course-status operation is not answered by this build (checklist M13)', () => {
  it('marks every field of such a question, and no field of any other', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, courses: LISTED }, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    expect(removalFromClosedTab(token)).not.toBeNull();
    // Without a `courses` operation: the question this build always asked.
    expect(appendJournalOp({
      fields: [{ key: 'coursework', base: { present: true, value: NAMES }, desired: { present: true, value: ['CS 225'] } }],
      baseRevision: 7, writer: HOME_FORM_WRITER, mode: 'set', originId: 'other-tab', lineage: 'other-tab-lineage',
    }, token)).not.toBeNull();
    const plain = (await hydrateProfile()).conflicts;
    expect(plain.map((c) => c.key)).toEqual(expect.arrayContaining(['coursework', 'resume_text']));
    expect(plain.some((c) => 'newerBuild' in c)).toBe(false);
    expect(readCurrentConflicts(['coursework'], token).some((c) => 'newerBuild' in c)).toBe(false);

    expect(courseClickFromNewerTab(token)).not.toBeNull();
    const held = (await hydrateProfile()).conflicts;
    expect(held.map((c) => c.key)).toEqual(expect.arrayContaining(['courses', 'coursework', 'resume_text']));
    expect(held.every((c) => c.newerBuild === true)).toBe(true);
    expect(readCurrentConflicts(['coursework'], token).every((c) => c.newerBuild === true)).toBe(true);
  });

  it('refuses an answer to it even when the question comes unmarked, and writes and sends nothing', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, courses: LISTED }, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    removalFromClosedTab(token);
    courseClickFromNewerTab(token);
    const asked = (await hydrateProfile()).conflicts;
    const unmarked = asked.map(({ newerBuild: _, ...rest }) => rest as ProfileConflict);
    const view = makeProfileViewSnapshot({ baseProfile: { ...FULL, courses: LISTED }, renderedProfile: { ...FULL, courses: LISTED },
      revision: 7, token, identityGeneration: token.epoch, source: 'hydration' });
    for (const rendered of [asked, unmarked]) {
      for (const choice of ['local', 'cloud'] as const) {
        const before = readOutstandingOps();
        const result = await resolveProfileConflict({ prompt: makeConflictPrompt(view, rendered), actionView: view, choice });
        expect(result).toEqual({ status: 'newer-build' });
        expect(readOutstandingOps(), 'no receipt').toEqual(before);
      }
    }
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('leaves the course tab\'s entry as it wrote it when the form is saved again, and sends only the other fields', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, courses: LISTED }, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    // The course-status tab's click saved into another device's change, and
    // its outbox entry is stored as that build writes it: the two course keys
    // only, locked (review m13p1v3-a, MF1).
    const opId = courseClickFromNewerTab(token)!.opId;
    const remote = { ...FULL, courses: [...LISTED, { name: 'PHYS 211', source: 'manual' as const }], coursework: [...NAMES, 'PHYS 211'] };
    const keys = ['courses', 'coursework'];
    const written = { mutationId: 'course-tab-write', baseRevision: 8, baseProfile: remote,
      desiredProfile: { ...FULL, courses: MARKED }, dirtyKeys: keys, keyVersions: { courses: 3, coursework: 3 },
      skillAdditions: [], skillsReplaced: false, skillOps: [], additiveKeys: [], lockedKeys: keys, conflictRemote: remote,
      legacy: false, deferredCreate: false, journalOpIds: [opId], journalPlan: { courses: [opId], coursework: [opId] } };
    expect(writeLocalStorageJSON(STORAGE_KEYS.PROFILE_SYNC, { v: 1, confirmed: { revision: 8, profile: remote },
      pending: written, tombstone: null }, token)).toBe(true);
    commitMock.mockImplementation(async (intent) => saved({ ...remote, ...intent.patch } as ProfileData, 9));
    // This build's form saves an unrelated edit with every key the journal
    // has outstanding, the course keys among them.
    const edited = { ...FULL, courses: LISTED, research_interests: 'robotics, control' };
    expect(recordProfileIntent(edited, ['research_interests'], token)).toBe(true);
    await stageProfilePatch(edited, ['research_interests', 'courses', 'coursework'], token);
    expect(commitMock.mock.calls.map(([intent]) => intent.patch)).toEqual([{ research_interests: 'robotics, control' }]);
    const left = readProfileSyncEnvelope()!.pending!;
    const coursePart = (entry: typeof written | typeof left) => ({ dirtyKeys: entry.dirtyKeys, lockedKeys: entry.lockedKeys,
      courses: entry.desiredProfile.courses, coursework: entry.desiredProfile.coursework,
      keyVersions: keys.map((k) => (entry.keyVersions as Record<string, number>)[k]),
      journalPlan: keys.map((k) => (entry.journalPlan as Record<string, string[]>)[k]) });
    expect(coursePart(left)).toEqual(coursePart(written));
    // Nothing of it alone is staged here either.
    const before = readProfileSyncEnvelope();
    expect(await stageProfilePatch(edited, ['courses', 'coursework'], token)).toEqual({ status: 'newer-build' });
    expect(readProfileSyncEnvelope()).toEqual(before);
    expect(commitMock).toHaveBeenCalledTimes(1);
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
