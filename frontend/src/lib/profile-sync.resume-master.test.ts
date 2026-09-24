import { createEmptyResumeMaster } from './resume-master';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ExperienceEntry, ProfileData, ResumeMasterV1 } from './types';
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

const master = (): ResumeMasterV1 => ({
  ...createEmptyResumeMaster('master-a'),
  basics: { links: [], name: { id: 'name', revision: 1, status: 'confirmed', value: 'Alex 王', source: { kind: 'manual' } } },
  other_sections: [{ id: 'additional', heading: 'Additional work', items: [{
    id: 'long-field', revision: 1, status: 'candidate', value: '中文🧪'.repeat(2000), source: { kind: 'manual' },
  }] }],
  section_order: ['basics', 'education', 'activities', 'publications', 'skills', 'additional'],
});
const withMaster = (): ProfileData => ({ ...WITH_RESUME, resume_master: master() });

describe('full resume master persistence', () => {
  it('keeps legacy absence until an edit and saves the entire uncut source bundle', async () => {
    const token = await hydrate();
    expect(readProfileSyncEnvelope()?.confirmed?.profile.resume_master).toBeUndefined();
    expect(commitMock).not.toHaveBeenCalled();
    const desired = withMaster();
    expect(recordProfileIntent(desired, ['resume_master'], token)).toBe(true);
    const journal = readOutstandingOps();
    expect(journal.ok && journal.value[0].fields.map(f => f.key).sort()).toEqual(bundle);
    commitMock.mockImplementation(async (intent) => saved({ ...BASE, ...intent.patch } as ProfileData));
    expect((await stageProfilePatch(desired, ['resume_master'], token)).status).toBe('saved');
    expect(Object.keys(commitMock.mock.calls[0][0].patch).sort()).toEqual(bundle);
    expect(commitMock.mock.calls[0][0].patch.resume_master).toEqual(desired.resume_master);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).resume_master).toEqual(desired.resume_master);
    expect(desired.experience_entries).toEqual([RESUME_ENTRY]);
  });

  it('recovers an offline complete master after reload before retrying the same source', async () => {
    const token = await hydrate(WITH_RESUME);
    const desired = withMaster();
    recordProfileIntent(desired, ['resume_master'], token);
    commitMock.mockResolvedValue({ status: 'transport-error', message: 'offline' });
    await stageProfilePatch(desired, ['resume_master'], token);
    startDocumentForTests('reload'); resetProfileDirtyLedger();
    const recovered = await hydrateProfile();
    expect(recovered.profile?.resume_master).toEqual(desired.resume_master);
    expect(recovered.profile?.experience_entries).toEqual(desired.experience_entries);
    commitMock.mockResolvedValue(saved(desired));
    expect((await flushPendingProfileWrite(captureOwnerToken())).status).toBe('saved');
    expect(readProfileSyncEnvelope()?.confirmed?.profile.resume_master).toEqual(desired.resume_master);
  });

  it('adds a nullable master partner to a legacy pending bundle without inventing a master', async () => {
    const token = await hydrate(WITH_RESUME);
    recordProfileIntent({ ...WITH_RESUME, coursework: [] }, ['coursework'], token);
    commitMock.mockResolvedValue({ status: 'transport-error', message: 'offline' });
    await stageProfilePatch({ ...WITH_RESUME, coursework: [] }, ['coursework'], token);
    const env = readProfileSyncEnvelope()!;
    const pending = env.pending!;
    delete pending.desiredProfile.resume_master;
    delete pending.baseProfile.resume_master;
    pending.dirtyKeys = pending.dirtyKeys.filter(k => k !== 'resume_master');
    delete pending.keyVersions.resume_master;
    pending.lockedKeys = ['coursework'];
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify(env));
    const recovered = readProfileSyncEnvelope()!.pending!;
    expect(recovered.desiredProfile.resume_master).toBeNull();
    expect(recovered.dirtyKeys.sort()).toEqual(bundle);
    expect(recovered.lockedKeys.sort()).toEqual(bundle);
  });

  it('locks the master together with the source when a second device changes the resume', async () => {
    const token = await hydrate(WITH_RESUME);
    const desired = withMaster();
    commitMock.mockResolvedValue({ status: 'conflict', revision: 8,
      profile: { ...WITH_RESUME, resume_text: 'Replacement', experience_entries: [] } as unknown as Record<string, unknown> });
    expect((await stageProfilePatch(desired, ['resume_master'], token)).status).toBe('conflict');
    expect(readProfileSyncEnvelope()?.pending?.lockedKeys.sort()).toEqual(bundle);
    expect(commitMock).toHaveBeenCalledTimes(1);
  });

  it('rejects a malformed edit without changing the previous document or making a request', async () => {
    const token = await hydrate(withMaster());
    const before = localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC);
    const bad = { ...withMaster(), resume_master: { version: 2 } } as unknown as ProfileData;
    expect(recordProfileIntent(bad, ['resume_master'], token)).toBe(false);
    expect(await stageProfilePatch(bad, ['resume_master'], token)).toEqual({ status: 'device-failed', phase: 'stage' });
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)).toBe(before);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it.each(['confirmed', 'baseProfile', 'desiredProfile', 'conflictRemote'])('preserves malformed master bytes in %s', async (slot) => {
    const current = withMaster();
    const token = await hydrate(current);
    const env = readProfileSyncEnvelope()!;
    const bad = { ...current, resume_master: { version: 7 } };
    const pending = { mutationId: 'corrupt-master', baseRevision: 7, baseProfile: current, desiredProfile: current,
      conflictRemote: current, dirtyKeys: ['resume_master'], lockedKeys: [], additiveKeys: [],
      keyVersions: { resume_master: 1 }, skillAdditions: [], skillsReplaced: false, skillOps: [] };
    const corrupt = slot === 'confirmed' ? { ...env, confirmed: { revision: 7, profile: bad } }
      : { ...env, pending: { ...pending, [slot]: bad } };
    const bytes = JSON.stringify(corrupt); localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, bytes);
    expect(readProfileSyncEnvelopeStrict().ok).toBe(false);
    expect(recordProfileIntent(current, ['major'], token)).toBe(false);
    await expect(hydrateProfile()).rejects.toThrow();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)).toBe(bytes);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('preserves an unreadable legacy master and rejects a malformed cloud replacement', async () => {
    const bytes = JSON.stringify({ ...BASE, resume_master: [] });
    localStorage.setItem(STORAGE_KEYS.PROFILE, bytes);
    loadProfileMock.mockResolvedValue({ source: 'cloud-absent', profile: null, revision: 0, token: captureOwnerToken() });
    await expect(hydrateProfile()).rejects.toThrow();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBe(bytes);
    localStorage.removeItem(STORAGE_KEYS.PROFILE);
    await hydrate(withMaster());
    const before = localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC);
    loadProfileMock.mockResolvedValue(cloud({ ...BASE, resume_master: [] } as unknown as ProfileData, 8));
    await expect(hydrateProfile()).rejects.toThrow();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)).toBe(before);
  });

  it('checks master contents in both journal operations and recovery receipts', async () => {
    const token = await hydrate(withMaster());
    const receipt = { v: 1 as const, ancestorOpId: 'master-receipt', ancestorLineage: 'tab', revision: 8,
      profile: { resume_master: { present: true as const, value: master() } }, confirmedKeys: ['resume_master'] };
    expect(appendRebaseReceipt({ ...receipt, profile: { resume_master: { present: true, value: 'corrupt' } } }, token)).toBe(false);
    expect(appendRebaseReceipt(receipt, token)).toBe(true);
    recordProfileIntent(withMaster(), ['resume_master'], token);
    const journal = readOutstandingOps(); if (!journal.ok) throw new Error(journal.reason);
    const key = `${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${journal.value[0].opId}`;
    const op = JSON.parse(localStorage.getItem(key)!);
    op.fields.find((f: {key: string}) => f.key === 'resume_master').desired.value = 'corrupt';
    const bytes = JSON.stringify(op); localStorage.setItem(key, bytes);
    expect(readOutstandingOps().ok).toBe(false);
    expect((await stageProfilePatch(withMaster(), ['major'], token)).status).toBe('device-failed');
    expect(localStorage.getItem(key)).toBe(bytes);
    expect(readRebaseReceipts().ok).toBe(true);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('refuses the previous account callback even if master IDs match', async () => {
    const oldToken = await hydrate(withMaster());
    advanceOwnerEpoch('new-master-owner'); await syncLocalIdentityOwner('new-master-owner');
    await hydrate(BASE);
    expect(recordProfileIntent(withMaster(), ['resume_master'], oldToken)).toBe(false);
    expect((await stageProfilePatch(withMaster(), ['resume_master'], oldToken)).status).toBe('abandoned');
    expect(readProfileSyncEnvelope()?.confirmed?.profile.resume_master).toBeUndefined();
  });
});
