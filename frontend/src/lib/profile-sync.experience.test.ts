import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ExperienceEntry, ProfileData } from './types';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from './supabase';
const loadProfileMock = vi.fn<() => Promise<LoadedProfile>>();
const commitMock = vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>();
vi.mock('./supabase', () => ({
  loadProfile: () => loadProfileMock(), commitProfilePatch: (intent: ProfilePatchIntent) => commitMock(intent),
}));
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import { appendRebaseReceipt, readOutstandingOps, readRebaseReceipts, resetJournalLaneForTests, startDocumentForTests } from './profile-journal';
import {
  flushPendingProfileWrite, hydrateProfile, readProfileSyncEnvelope, readProfileSyncEnvelopeStrict,
  recordProfileIntent, resetProfileDirtyLedger, RESUME_BUNDLE, stageProfilePatch,
} from './profile-sync';

const BASE: ProfileData = {
  institution: 'UIUC', home_school: 'uiuc', college: 'Grainger', major: 'CS', grade: 'Junior',
  is_international: false, research_interests: 'robotics', skills: [], search_weight: 50,
};
const ENTRY: ExperienceEntry = {
  id: 'exp-a', revision: 1, status: 'candidate', text: 'Built a robot', source: { kind: 'manual' },
};
const RESUME_ENTRY: ExperienceEntry = {
  ...ENTRY, source: { kind: 'resume', signature: 'a'.repeat(64), quote: 'Built a robot', start: 0, end: 13 },
};
const WITH_RESUME: ProfileData = { ...BASE, resume_text: 'Built a robot', coursework: ['CS 225'], experience_entries: [RESUME_ENTRY] };
const bundle = [...RESUME_BUNDLE].sort();

function cloud(profile: ProfileData, revision = 7): LoadedProfile {
  return { source: 'cloud', profile: profile as unknown as Record<string, unknown>, revision, token: captureOwnerToken() };
}
function saved(profile: ProfileData, revision = 8): ProfilePatchOutcome {
  return { status: 'saved', profile: profile as unknown as Record<string, unknown>, revision };
}
async function hydrate(profile: ProfileData = BASE) {
  loadProfileMock.mockResolvedValue(cloud(profile));
  await hydrateProfile();
  return captureOwnerToken();
}

beforeEach(async () => {
  let chain: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: {
    request: (_name: string, _opts: unknown, fn: () => unknown) => {
      const next = chain.then(fn); chain = next.then(() => undefined, () => undefined); return next;
    },
  } });
  localStorage.clear(); resetJournalLaneForTests(); resetProfileDirtyLedger();
  loadProfileMock.mockReset(); commitMock.mockReset();
  advanceOwnerEpoch(null); advanceOwnerEpoch('experience-owner');
  await syncLocalIdentityOwner('experience-owner');
});

describe('experience profile persistence', () => {
  it('preserves legacy absence and journals/stages all resume partners for the first evidence edit', async () => {
    const token = await hydrate();
    expect(readProfileSyncEnvelope()?.confirmed?.profile.experience_entries).toBeUndefined();
    const desired = { ...BASE, experience_entries: [ENTRY] };
    expect(recordProfileIntent(desired, ['experience_entries'], token)).toBe(true);
    const journal = readOutstandingOps();
    expect(journal.ok).toBe(true);
    if (!journal.ok) throw new Error(journal.reason);
    expect(journal.value[0].fields.map((field) => field.key).sort()).toEqual(bundle);
    commitMock.mockImplementation(async (intent) => saved({ ...BASE, ...intent.patch } as ProfileData));
    expect((await stageProfilePatch(desired, ['experience_entries'], token)).status).toBe('saved');
    expect(Object.keys(commitMock.mock.calls[0][0].patch).sort()).toEqual(bundle);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).experience_entries).toEqual([ENTRY]);
  });

  it('recovers an unsent evidence confirmation after reload without losing the source', async () => {
    const token = await hydrate(WITH_RESUME);
    const confirmed = { ...RESUME_ENTRY, status: 'confirmed' as const, revision: 2 };
    const desired = { ...WITH_RESUME, experience_entries: [confirmed] };
    recordProfileIntent(desired, ['experience_entries'], token);
    commitMock.mockResolvedValue({ status: 'transport-error', message: 'offline' });
    await stageProfilePatch(desired, ['experience_entries'], token);
    startDocumentForTests('reload'); resetProfileDirtyLedger();
    const recovered = await hydrateProfile();
    expect(recovered.profile?.experience_entries).toEqual([confirmed]);
    commitMock.mockResolvedValue(saved(desired));
    expect((await flushPendingProfileWrite(captureOwnerToken())).status).toBe('saved');
    expect(readProfileSyncEnvelope()?.confirmed?.profile.experience_entries).toEqual([confirmed]);
  });

  it('migrates an old partial bundle using the correct array default, maximum version and complete lock set', async () => {
    await hydrate(WITH_RESUME);
    const env = readProfileSyncEnvelope()!;
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({ ...env, pending: {
      mutationId: 'legacy-resume', baseRevision: 7, baseProfile: WITH_RESUME,
      desiredProfile: { ...BASE, resume_text: 'replacement', coursework: [] },
      dirtyKeys: ['coursework', 'resume_text'], keyVersions: { coursework: 9, resume_text: 2 },
      lockedKeys: ['coursework'], additiveKeys: [], skillAdditions: [], skillsReplaced: false,
      skillOps: [], conflictRemote: WITH_RESUME, legacy: false, deferredCreate: false, journalOpIds: [], journalPlan: {},
    } }));
    const pending = readProfileSyncEnvelope()!.pending!;
    expect(pending.dirtyKeys.sort()).toEqual(bundle);
    expect(pending.lockedKeys.sort()).toEqual(bundle);
    expect(pending.keyVersions.experience_entries).toBe(9);
    expect(pending.desiredProfile.experience_entries).toEqual([RESUME_ENTRY]);
    const noOldEvidence = { ...pending, baseProfile: BASE, desiredProfile: BASE };
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({ ...env, pending: noOldEvidence }));
    expect(readProfileSyncEnvelope()!.pending!.desiredProfile.experience_entries).toEqual([]);
  });

  it('locks the entire resume bundle when two tabs disagree about confirmation', async () => {
    const token = await hydrate(WITH_RESUME);
    const accepted = { ...WITH_RESUME, experience_entries: [{ ...RESUME_ENTRY, revision: 2, status: 'confirmed' as const }] };
    const rejected = { ...WITH_RESUME, experience_entries: [{ ...RESUME_ENTRY, revision: 2, status: 'rejected' as const }] };
    expect(recordProfileIntent(accepted, ['experience_entries'], token)).toBe(true);
    startDocumentForTests('other'); resetProfileDirtyLedger();
    expect(recordProfileIntent(rejected, ['experience_entries'], token)).toBe(true);
    const result = await stageProfilePatch(rejected, ['experience_entries'], token);
    expect(result.status).toBe('conflict');
    expect(readProfileSyncEnvelope()?.pending?.lockedKeys.sort()).toEqual(bundle);
    expect(commitMock).not.toHaveBeenCalled();
    const journal = readOutstandingOps();
    expect(journal.ok && journal.value).toHaveLength(2);
  });

  it('does not send confirmation against a remotely replaced resume', async () => {
    const token = await hydrate(WITH_RESUME);
    const desired = { ...WITH_RESUME, experience_entries: [{ ...RESUME_ENTRY, revision: 2, status: 'confirmed' as const }] };
    const remote = { ...WITH_RESUME, resume_text: 'New project', experience_entries: [] };
    commitMock.mockResolvedValue({ status: 'conflict', revision: 8, profile: remote as unknown as Record<string, unknown> });
    const result = await stageProfilePatch(desired, ['experience_entries'], token);
    expect(result.status).toBe('conflict');
    expect(readProfileSyncEnvelope()?.pending?.lockedKeys.sort()).toEqual(bundle);
    expect(commitMock).toHaveBeenCalledTimes(1);
  });

  it('rejects malformed new edits before journaling or sending', async () => {
    const token = await hydrate(WITH_RESUME);
    const before = localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC);
    const invalid = { ...WITH_RESUME, experience_entries: [{ ...ENTRY, revision: 0 }] };
    expect(recordProfileIntent(invalid, ['experience_entries'], token)).toBe(false);
    expect(await stageProfilePatch(invalid, ['experience_entries'], token)).toEqual({ status: 'device-failed', phase: 'stage' });
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)).toBe(before);
    expect(readOutstandingOps()).toMatchObject({ ok: true, value: [] });
    expect(commitMock).not.toHaveBeenCalled();
  });

  it.each(['confirmed', 'baseProfile', 'desiredProfile', 'conflictRemote'])('preserves a malformed %s envelope instead of treating it as empty', async (slot) => {
    const token = await hydrate(WITH_RESUME);
    const env = readProfileSyncEnvelope()!;
    const bad = { ...WITH_RESUME, experience_entries: 'damaged' };
    const pending = {
      mutationId: 'corrupt', baseRevision: 7, baseProfile: WITH_RESUME, desiredProfile: WITH_RESUME,
      conflictRemote: WITH_RESUME, dirtyKeys: ['experience_entries'], lockedKeys: [], additiveKeys: [],
      keyVersions: { experience_entries: 1 }, skillAdditions: [], skillsReplaced: false, skillOps: [],
    };
    const corrupted = slot === 'confirmed'
      ? { ...env, confirmed: { revision: 7, profile: bad } }
      : { ...env, pending: { ...pending, [slot]: bad } };
    const bytes = JSON.stringify(corrupted);
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, bytes);
    expect(readProfileSyncEnvelopeStrict().ok).toBe(false);
    expect(recordProfileIntent(WITH_RESUME, ['major'], token)).toBe(false);
    expect((await stageProfilePatch(WITH_RESUME, ['major'], token)).status).not.toBe('saved');
    await expect(hydrateProfile()).rejects.toThrow();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)).toBe(bytes);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('preserves malformed legacy evidence when no envelope exists', async () => {
    const bytes = JSON.stringify({ ...BASE, experience_entries: { broken: true } });
    localStorage.setItem(STORAGE_KEYS.PROFILE, bytes);
    loadProfileMock.mockResolvedValue({ source: 'cloud-absent', profile: null, revision: 0, token: captureOwnerToken() });
    await expect(hydrateProfile()).rejects.toThrow();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBe(bytes);
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)).toBeNull();
  });

  it('refuses corrupt journal evidence without deleting its recoverable bytes', async () => {
    const token = await hydrate(WITH_RESUME);
    recordProfileIntent({ ...WITH_RESUME, experience_entries: [ENTRY] }, ['experience_entries'], token);
    const outstanding = readOutstandingOps();
    if (!outstanding.ok) throw new Error(outstanding.reason);
    const key = `${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${outstanding.value[0].opId}`;
    const op = JSON.parse(localStorage.getItem(key)!);
    op.fields.find((field: { key: string }) => field.key === 'experience_entries').desired.value = [{ ...ENTRY, status: 'invented' }];
    const bytes = JSON.stringify(op); localStorage.setItem(key, bytes);
    expect(readOutstandingOps().ok).toBe(false);
    expect((await stageProfilePatch(WITH_RESUME, ['major'], token)).status).toBe('device-failed');
    expect(localStorage.getItem(key)).toBe(bytes);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('rejects malformed cloud evidence without replacing the last valid local profile', async () => {
    await hydrate(WITH_RESUME);
    const before = localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC);
    loadProfileMock.mockResolvedValue(cloud({ ...WITH_RESUME, experience_entries: [{ ...ENTRY, revision: 0 }] }, 8));
    await expect(hydrateProfile()).rejects.toThrow();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)).toBe(before);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).experience_entries).toEqual([RESUME_ENTRY]);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('validates evidence in durable rebase receipts on write and recovery', async () => {
    const token = await hydrate(WITH_RESUME);
    const receipt = { v: 1 as const, ancestorOpId: 'receipt-op', ancestorLineage: 'source-tab', revision: 8,
      profile: { experience_entries: { present: true as const, value: [ENTRY] } }, confirmedKeys: ['experience_entries'] };
    expect(appendRebaseReceipt({ ...receipt, profile: { experience_entries: { present: true, value: 'corrupt' } } }, token)).toBe(false);
    expect(appendRebaseReceipt(receipt, token)).toBe(true);
    const key = `${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}rebase_receipt-op`;
    const broken = { ...receipt, profile: { experience_entries: { present: true, value: 'corrupt' } } };
    const bytes = JSON.stringify(broken); localStorage.setItem(key, bytes);
    expect(readRebaseReceipts().ok).toBe(false);
    expect((await stageProfilePatch(WITH_RESUME, ['major'], token)).status).toBe('device-failed');
    expect(localStorage.getItem(key)).toBe(bytes);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('blocks a retired owner from restoring or confirming the previous account evidence', async () => {
    const oldToken = await hydrate(WITH_RESUME);
    advanceOwnerEpoch('next-owner'); await syncLocalIdentityOwner('next-owner');
    await hydrate(BASE);
    const before = localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC);
    expect(recordProfileIntent(WITH_RESUME, ['experience_entries'], oldToken)).toBe(false);
    expect((await stageProfilePatch(WITH_RESUME, ['experience_entries'], oldToken)).status).toBe('abandoned');
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)).toBe(before);
    expect(readProfileSyncEnvelope()?.confirmed?.profile.experience_entries).toBeUndefined();
    expect(commitMock).not.toHaveBeenCalled();
  });
});
