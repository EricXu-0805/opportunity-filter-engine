import { describe, expect, it, vi } from 'vitest';
import { STORAGE_KEYS } from './storage-keys';

const MARKER = STORAGE_KEYS.LOCAL_IDENTITY_OWNER;
const PROFILE = STORAGE_KEYS.PROFILE;

async function realm() {
  vi.resetModules();
  return import('./identity-owner');
}

describe('same-owner cross-tab synchronization', () => {
  it('never makes another ready tab lose its readable profile during repeated synchronization', async () => {
    const first = await realm();
    first.advanceOwnerEpoch('shared-owner');
    expect(await first.syncLocalIdentityOwner('shared-owner')).toBe(true);
    const profile = JSON.stringify({ resume_text: 'Complete original source' });
    expect(first.writeUserScopedRaw(PROFILE, profile, first.captureOwnerToken())).toBe(true);
    const firstToken = first.captureOwnerToken();
    const second = await realm();
    second.advanceOwnerEpoch('shared-owner');
    const observed: Array<string | null> = [];
    const realSet = localStorage.setItem.bind(localStorage);
    // A separate tab can read immediately after each shared-storage write.
    // Sample those observable intermediate states, not merely the final marker.
    const writes = vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
      realSet(key, value);
      observed.push(first.readUserScopedRaw(PROFILE));
    });
    expect(await second.syncLocalIdentityOwner('shared-owner')).toBe(true);
    for (let i = 0; i < 5; i += 1) {
      expect(await first.syncLocalIdentityOwner('shared-owner')).toBe(true);
      expect(await second.syncLocalIdentityOwner('shared-owner')).toBe(true);
    }
    expect(observed).not.toContain(null);
    expect(writes).not.toHaveBeenCalled();
    expect(second.readUserScopedRaw(PROFILE)).toBe(profile);
    expect(first.isOwnerTokenValid(firstToken, firstToken.uid)).toBe(true);
    expect(second.captureOwnerToken().generation).toBe(firstToken.generation);
  });

  it('adopts a verified ready namespace without rewriting even when writes now fail', async () => {
    const first = await realm();
    first.advanceOwnerEpoch('shared-owner');
    await first.syncLocalIdentityOwner('shared-owner');
    const second = await realm();
    second.advanceOwnerEpoch('shared-owner');
    const writes = vi.spyOn(localStorage, 'setItem').mockImplementation(() => { throw new Error('read-only'); });
    expect(await second.syncLocalIdentityOwner('shared-owner')).toBe(true);
    expect(second.isLocalOwnerReady('shared-owner')).toBe(true);
    expect(writes).not.toHaveBeenCalled();
  });

  it('fails closed if the ready namespace sentinel cannot be read', async () => {
    const first = await realm();
    first.advanceOwnerEpoch('shared-owner');
    await first.syncLocalIdentityOwner('shared-owner');
    const second = await realm();
    second.advanceOwnerEpoch('shared-owner');
    const realGet = localStorage.getItem.bind(localStorage);
    vi.spyOn(localStorage, 'getItem').mockImplementation((key) => {
      if (key === '__ofe_ns') throw new Error('unreadable');
      return realGet(key);
    });
    const writes = vi.spyOn(localStorage, 'setItem');
    expect(await second.syncLocalIdentityOwner('shared-owner')).toBe(false);
    expect(second.isLocalOwnerReady('shared-owner')).toBe(false);
    expect(second.readUserScopedRaw(PROFILE)).toBeNull();
    expect(writes).not.toHaveBeenCalled();
  });

  it.each(['switching', 'missing-sentinel', 'wrong-sentinel', 'legacy-marker'])(
    'still repairs an incomplete namespace: %s', async (state) => {
      const current = await realm();
      current.advanceOwnerEpoch('shared-owner');
      localStorage.setItem(MARKER, state === 'legacy-marker' ? 'shared-owner' : JSON.stringify({
        v: 2, uid: 'shared-owner', generation: 0, phase: state === 'switching' ? 'switching' : 'ready',
      }));
      if (state !== 'missing-sentinel') localStorage.setItem('__ofe_ns', state === 'wrong-sentinel' ? '99' : '0');
      // A legacy marker normally predates the namespace sentinel as well.
      if (state === 'legacy-marker') localStorage.removeItem('__ofe_ns');
      expect(await current.syncLocalIdentityOwner('shared-owner')).toBe(true);
      expect(JSON.parse(localStorage.getItem(MARKER)!)).toMatchObject({ phase: 'ready', generation: 0 });
      expect(localStorage.getItem('__ofe_ns')).toBe('0');
      expect(current.isOwnerTokenValid(current.captureOwnerToken(), 'shared-owner')).toBe(true);
    },
  );

  it('does not accept a missing sentinel when its repair silently fails', async () => {
    const current = await realm();
    current.advanceOwnerEpoch('shared-owner');
    localStorage.setItem(MARKER, JSON.stringify({ v: 2, uid: 'shared-owner', generation: 0, phase: 'ready' }));
    const realSet = localStorage.setItem.bind(localStorage);
    vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
      if (key !== '__ofe_ns') realSet(key, value);
    });
    expect(await current.syncLocalIdentityOwner('shared-owner')).toBe(false);
    expect(current.isLocalOwnerReady('shared-owner')).toBe(false);
  });

  it('continues to block the old tab immediately during a real owner change', async () => {
    const first = await realm();
    first.advanceOwnerEpoch('first-owner');
    await first.syncLocalIdentityOwner('first-owner');
    const token = first.captureOwnerToken();
    first.writeUserScopedRaw(PROFILE, 'old private profile', token);
    const second = await realm();
    second.advanceOwnerEpoch('second-owner');
    const intermediateReads: Array<string | null> = [];
    const realSet = localStorage.setItem.bind(localStorage);
    vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
      realSet(key, value);
      if (key === MARKER) intermediateReads.push(first.readUserScopedRaw(PROFILE));
    });
    expect(await second.syncLocalIdentityOwner('second-owner')).toBe(true);
    expect(intermediateReads.length).toBeGreaterThan(0);
    expect(intermediateReads.every(value => value === null)).toBe(true);
    expect(first.isOwnerTokenValid(token, token.uid)).toBe(false);
    expect(first.writeUserScopedRaw(PROFILE, 'late old write', token)).toBe(false);
    expect(second.readUserScopedRaw(PROFILE)).toBeNull();
    expect(second.captureOwnerToken().generation).toBeGreaterThan(token.generation);
  });
});
