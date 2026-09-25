import { beforeEach, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from './supabase';
import type { ProfileData } from './types';
import { STORAGE_KEYS } from './storage-keys';

const service = vi.hoisted(() => ({
  load: vi.fn<() => Promise<LoadedProfile>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
}));
vi.mock('./supabase', () => ({
  loadProfile: () => service.load(),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
}));
const UID = 'receipt-repair-owner';
const base: ProfileData = {
  name: 'Synthetic student', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger',
  major: 'Computer Science', grade: 'Junior', is_international: false,
  research_interests: 'initial research', skills: [], search_weight: 50,
};
const desired = { ...base, research_interests: 'My complete unsaved research edit' };

// Each module graph represents an independent tab, with separate owner/queue/
// coordinator state and the same real guarded storage and serial Web Locks.
async function realm() {
  vi.resetModules();
  const identity = await import('./identity-owner');
  identity.advanceOwnerEpoch(UID);
  expect(await identity.syncLocalIdentityOwner(UID)).toBe(true);
  const sync = await import('./profile-sync');
  return { identity, sync, token: identity.captureOwnerToken() };
}
type Realm = Awaited<ReturnType<typeof realm>>;
function cloud(tab: Realm, profile: ProfileData | null, revision = 7): LoadedProfile {
  return { source: profile ? 'cloud' : 'cloud-absent', profile: profile as unknown as Record<string, unknown> | null,
    revision: profile ? revision : 0, token: tab.token };
}
async function hydrate(tab: Realm, profile: ProfileData | null, revision = 7) {
  service.load.mockResolvedValueOnce(cloud(tab, profile, revision));
  return tab.sync.hydrateProfile();
}
function view(tab: Realm) {
  return tab.sync.makeProfileViewSnapshot({ renderedProfile: base, baseProfile: base, revision: 7,
    token: tab.token, identityGeneration: tab.token.epoch, source: 'hydration' });
}
function write(tab: Realm, value = desired, keys: Array<keyof ProfileData> = ['research_interests']) {
  return tab.sync.commitProfileAction({ view: view(tab), desiredAfter: value, keys, writer: 'receipt-repair-test', allowCreate: false });
}
function saved(): ProfilePatchOutcome {
  return { status: 'saved', revision: 8, profile: { ...desired } };
}
beforeEach(() => { service.load.mockReset(); service.commit.mockReset(); });

async function owedLocalConfirmation() {
  const tab = await realm();
  await hydrate(tab, base);
  let rejectEnvelope = false;
  const realSet = localStorage.setItem.bind(localStorage);
  const storage = vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
    if (rejectEnvelope && key === STORAGE_KEYS.PROFILE_SYNC) throw new Error('QuotaExceededError');
    realSet(key, value);
  });
  service.commit.mockImplementationOnce(async () => {
    // Staging succeeded and the request reached the server. Only persisting
    // the successful receipt fails, which arms the real local repair path.
    rejectEnvelope = true;
    return saved();
  });
  try {
    const receipt = await write(tab);
    expect(receipt).toMatchObject({ durable: true, result: { status: 'device-failed', phase: 'confirm' } });
    expect(service.commit).toHaveBeenCalledTimes(1);
  } finally { storage.mockRestore(); }
  expect(tab.sync.readProfileSyncEnvelope()?.pending?.desiredProfile.research_interests).toBe(desired.research_interests);
  return tab;
}

it('repairs an unwritten confirmation locally when no deletion fence exists', async () => {
  const tab = await owedLocalConfirmation();
  const repaired = await tab.sync.flushPendingProfileWrite(tab.token);
  expect(repaired).toEqual({ status: 'already-saved', revision: 8, profile: desired });
  expect(tab.sync.readProfileSyncEnvelope()?.tombstone).toBeNull();
  expect(JSON.parse(tab.identity.readUserScopedRaw(STORAGE_KEYS.PROFILE)!)).toEqual(desired);
  expect(service.commit, 'a quota repair must not issue a second CAS').toHaveBeenCalledTimes(1);
});

it('rechecks deletion after a local confirmation repair waited to acquire the shared lock', async () => {
  const tab = await owedLocalConfirmation();
  expect(tab.sync.readProfileSyncEnvelope()?.tombstone).toBeNull();
  const locks = navigator.locks as unknown as {
    request: (name: string, options: unknown, callback: () => unknown) => Promise<unknown>;
  };
  const realRequest = locks.request.bind(locks);
  let release!: () => void;
  let waiting!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const reachedLock = new Promise<void>(resolve => { waiting = resolve; });
  let holdNext = true;
  const intercepted = vi.spyOn(locks, 'request').mockImplementation(async (name, options, callback) => {
    if (holdNext) {
      holdNext = false;
      waiting();
      // Pause before entering the real lock so the deletion reconciliation
      // can acquire it first; never run a network await while holding it.
      await gate;
    }
    return realRequest(name, options, callback);
  });
  const repair = tab.sync.flushPendingProfileWrite(tab.token);
  try {
    await reachedLock;
    const gone = await hydrate(tab, null);
    expect(gone.profile).toBeNull();
    expect(tab.sync.readProfileSyncEnvelope()?.tombstone).toEqual({ reason: 'deleted', rawQuarantined: true });
    expect(tab.identity.readUserScopedRaw(STORAGE_KEYS.PROFILE)).toBeNull();
    const pending = tab.sync.readProfileSyncEnvelope()?.pending;
    expect(pending?.desiredProfile.research_interests).toBe(desired.research_interests);
    release();
    expect(await repair).toEqual({ status: 'missing', reason: 'absent' });
    expect(tab.sync.readProfileSyncEnvelope()?.tombstone).toEqual({ reason: 'deleted', rawQuarantined: true });
    expect(tab.sync.readProfileSyncEnvelope()?.pending).toEqual(pending);
    expect(tab.identity.readUserScopedRaw(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(service.commit, 'the stale local repair must not replay the old profile').toHaveBeenCalledTimes(1);
  } finally { release(); await repair; intercepted.mockRestore(); }
});

it('a real merged-away receipt from another tab dominates an older saved response', async () => {
  const first = await realm();
  await hydrate(first, base);
  let release!: (receipt: ProfilePatchOutcome) => void;
  let dispatched!: () => void;
  const sent = new Promise<void>(resolve => { dispatched = resolve; });
  service.commit.mockImplementationOnce(() => {
    dispatched();
    return new Promise(resolve => { release = resolve; });
  });
  const oldSave = write(first);
  await sent;
  try {
    const second = await realm();
    expect(second.token.generation).toBe(first.token.generation);
    expect(first.identity.isOwnerTokenValid(first.token, UID)).toBe(true);
    await hydrate(second, base);
    service.commit.mockResolvedValueOnce({ status: 'missing', reason: 'merged_away' });
    const merged = await write(second, { ...base, major: 'Physics' }, ['major']);
    expect(merged.result).toEqual({ status: 'missing', reason: 'merged_away' });
    expect(second.sync.readProfileSyncEnvelope()?.tombstone?.reason).toBe('merged');
    expect(second.identity.readUserScopedRaw(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(second.sync.readProfileSyncEnvelope()?.pending).toBeNull();
    release(saved());
    expect((await oldSave).result).toEqual({ status: 'missing', reason: 'merged_away' });
    expect(first.sync.readProfileSyncEnvelope()?.tombstone?.reason).toBe('merged');
    expect(first.sync.readProfileSyncEnvelope()?.pending).toBeNull();
    expect(first.identity.readUserScopedRaw(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(await first.sync.flushPendingProfileWrite(first.token)).toEqual({ status: 'missing', reason: 'merged_away' });
    expect(service.commit, 'only the two user writes were dispatched; nothing recreated the merged account').toHaveBeenCalledTimes(2);
  } finally { release(saved()); await oldSave; }
});
