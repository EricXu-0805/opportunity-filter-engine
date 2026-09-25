'use client';

import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { captureOwnerToken, isOwnerTokenValid } from './identity-owner';
import { makeProfileViewSnapshot, type ProfileHydration } from './profile-sync';
import { profileActionKey } from './use-profile-action';
import type { ProfileData } from './types';

/** Share the accepted read/reconcile candidate with writing entry points.
 * A raw storage mirror may lag behind pending journal edits. */
export function useCheckedWritingProfile(rawProfile: ProfileData | null, scope: string) {
  // Keep the exact candidate from hydrate (including unsent journal edits).
  // A later, different raw mirror or owner permanently retires this overlay.
  const rawKey = profileActionKey(rawProfile);
  const rawKeyRef = useRef(rawKey);
  useLayoutEffect(() => { rawKeyRef.current = rawKey; }, [rawKey]);
  const [hydrated, setHydrated] = useState<{ scope: string; before: string | null; key: string | null;
    profile: ProfileData | null; token: ReturnType<typeof captureOwnerToken> } | null>(null);
  const applicable = hydrated && hydrated.scope === scope && isOwnerTokenValid(hydrated.token, hydrated.token.uid)
    && (rawKey === hydrated.before || rawKey === hydrated.key);
  if (hydrated && !applicable) setHydrated(null);
  else if (hydrated && rawKey === hydrated.key && hydrated.before !== hydrated.key) {
    // Once the matching mirror has arrived, going back to the old input is a
    // NEW source change, not permission to resurrect this accepted candidate.
    setHydrated({ ...hydrated, before: hydrated.key });
  }
  const profile = applicable ? hydrated.profile : rawProfile;
  const acceptHydration = useCallback((loaded: ProfileHydration) => {
    if (loaded.quarantineFailed || loaded.conflictKeys.length || loaded.conflicts.length
      || !isOwnerTokenValid(loaded.token, loaded.token.uid)) return;
    const view = loaded.profile ? makeProfileViewSnapshot({ baseProfile: loaded.baseProfile,
      renderedProfile: loaded.profile, revision: loaded.revision, token: loaded.token,
      identityGeneration: loaded.token.epoch, source: 'hydration' }) : null;
    setHydrated({ scope, before: rawKeyRef.current, key: profileActionKey(loaded.profile),
      profile: view?.renderedProfile ?? null, token: loaded.token });
  }, [scope]);
  return { profile, acceptHydration };
}
