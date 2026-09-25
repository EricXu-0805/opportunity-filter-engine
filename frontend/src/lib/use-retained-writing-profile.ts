'use client';

import { useState, useSyncExternalStore } from 'react';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange } from './identity-owner';
import type { ProfileData } from './types';

const ownerSnapshot = () => {
  const owner = captureOwnerToken();
  return JSON.stringify([owner.uid, owner.epoch, owner.generation, isOwnerTokenValid(owner, owner.uid)]);
};
const serverOwner = () => 'server';
const subscribeOwner = (changed: () => void) => {
  const unsubscribe = onLocalOwnerStateChange(changed);
  window.addEventListener('storage', changed);
  return () => { unsubscribe(); window.removeEventListener('storage', changed); };
};
type Retained = { scope: string; owner: string; profile: ProfileData | null; retired: boolean };

/** An already-open editor may keep its source snapshot for display after the
 * live profile disappears. This grants no source authority and writes nothing.
 * A new owner/target retires the entire open lifetime, even before its parent's
 * auth callback closes it; it must close before it can acquire another owner. */
export function useRetainedWritingProfile(profile: ProfileData | null, open: boolean, scope: string) {
  const owner = useSyncExternalStore(subscribeOwner, ownerSnapshot, serverOwner);
  const [retained, setRetained] = useState<Retained | null>(null);
  let current = retained;
  if (!open) {
    if (retained) setRetained(null);
    return { profile, profileAvailable: profile !== null };
  }
  if (!current) {
    // No source has ever been shown in this open lifetime yet.
    if (!profile) return { profile: null, profileAvailable: false };
    current = { scope, owner, profile, retired: false };
    setRetained(current);
  } else if (!current.retired && (current.scope !== scope || current.owner !== owner)) {
    current = { scope, owner, profile: null, retired: true };
    setRetained(current);
  } else if (!current.retired && profile && current.profile !== profile) {
    current = { ...current, profile };
    setRetained(current);
  }
  return {
    profile: current.retired ? null : profile ?? current.profile,
    profileAvailable: !current.retired && profile !== null,
  };
}
