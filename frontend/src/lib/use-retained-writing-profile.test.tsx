import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { useRetainedWritingProfile } from './use-retained-writing-profile';
import type { ProfileData } from './types';
import { STORAGE_KEYS } from './storage-keys';
const profile = { name: 'Owner A', skills: [], research_interests: 'Original source' } as unknown as ProfileData;
const scope = 'owner-A:1:target-A';
beforeEach(async () => { advanceOwnerEpoch('owner-A'); await syncLocalIdentityOwner('owner-A'); });
function mount(initialProfile: ProfileData | null = profile, open = true) {
  return renderHook(({ value, visible, key }) => useRetainedWritingProfile(value, visible, key), {
    initialProps: { value: initialProfile, visible: open, key: scope },
  });
}
describe('display-only writing profile lifetime', () => {
  it('retains the last shown profile through missing reads with authority false and no storage writes', () => {
    const { result, rerender } = mount();
    const next = { ...profile, research_interests: 'Latest shown source' };
    rerender({ value: next, visible: true, key: scope });
    const writes = vi.spyOn(localStorage, 'setItem');
    rerender({ value: null, visible: true, key: scope });
    expect(result.current).toEqual({ profile: next, profileAvailable: false });
    expect(writes).not.toHaveBeenCalled();
  });
  it('releases the snapshot on close and cannot recover it by reopening without a live profile', () => {
    const { result, rerender } = mount();
    rerender({ value: null, visible: true, key: scope });
    expect(result.current.profile).toBe(profile);
    rerender({ value: null, visible: false, key: scope });
    rerender({ value: null, visible: true, key: scope });
    expect(result.current).toEqual({ profile: null, profileAvailable: false });
  });
  it.each(['different-uid', 'same-uid-new-epoch'] as const)('retires immediately on %s even before parent props change', async (mode) => {
    const { result, rerender } = mount();
    const original = captureOwnerToken();
    await act(async () => {
      advanceOwnerEpoch(mode === 'different-uid' ? 'owner-B' : null);
      if (mode === 'same-uid-new-epoch') advanceOwnerEpoch('owner-A');
      await syncLocalIdentityOwner(mode === 'different-uid' ? 'owner-B' : 'owner-A');
    });
    expect(captureOwnerToken().epoch).not.toBe(original.epoch);
    expect(result.current).toEqual({ profile: null, profileAvailable: false });
    // The old still-open lifetime cannot adopt even legitimate next-owner data.
    rerender({ value: { ...profile, name: 'Next owner' }, visible: true, key: scope });
    expect(result.current.profile).toBeNull();
  });
  it('retires when persistent generation changes at the same uid and epoch', async () => {
    const { result } = mount(); const old = captureOwnerToken();
    await act(async () => {
      localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, JSON.stringify({ v: 2, uid: 'owner-A', generation: old.generation + 1, phase: 'switching' }));
      window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEYS.LOCAL_IDENTITY_OWNER }));
      await syncLocalIdentityOwner('owner-A');
    });
    const next = captureOwnerToken();
    expect(next.uid).toBe(old.uid); expect(next.epoch).toBe(old.epoch); expect(next.generation).not.toBe(old.generation);
    expect(result.current).toEqual({ profile: null, profileAvailable: false });
  });
  it('retires on parent identity/target scope changes without relying on an auth callback', () => {
    const { result, rerender } = mount();
    rerender({ value: profile, visible: true, key: 'owner-A:2:target-B' });
    expect(result.current.profile).toBeNull();
    rerender({ value: profile, visible: false, key: 'owner-A:2:target-B' });
    rerender({ value: profile, visible: true, key: 'owner-A:2:target-B' });
    expect(result.current).toEqual({ profile, profileAvailable: true });
  });
  it('allows a first profile to arrive before any source was ever displayed', async () => {
    const { result, rerender } = mount(null);
    await act(async () => { advanceOwnerEpoch('owner-B'); await syncLocalIdentityOwner('owner-B'); });
    rerender({ value: profile, visible: true, key: 'owner-B:1:target-A' });
    expect(result.current).toEqual({ profile, profileAvailable: true });
  });
});
