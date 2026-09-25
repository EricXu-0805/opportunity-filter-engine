'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange, type OwnerToken } from './identity-owner';
import { hydrateProfile, makeProfileViewSnapshot, type ProfileHydration } from './profile-sync';
import type { LoadedProfile } from './supabase';
import type { ProfileData } from './types';

/** A read/reconcile receipt, not an assertion of continuously current cloud data. */
export type ProfileActionReceipt = {
  checkId: number;
  owner: OwnerToken;
  revision: number;
  source: LoadedProfile['source'];
  profile: ProfileData | null;
};
export type ProfileRefreshState = {
  status: 'checking' | 'ready' | 'failed' | 'local-only' | 'conflict';
  refresh: () => Promise<boolean>;
  checkForAction?: () => Promise<ProfileActionReceipt | null>;
};
export const PROFILE_REFRESH_DEADLINE_MS = 15_000;

function ownerSnapshot(): string {
  const token = captureOwnerToken();
  return JSON.stringify([token.uid, token.epoch, token.generation, isOwnerTokenValid(token, token.uid)]);
}
function subscribeOwner(changed: () => void): () => void {
  const unsubscribe = onLocalOwnerStateChange(changed);
  window.addEventListener('storage', changed);
  return () => { unsubscribe(); window.removeEventListener('storage', changed); };
}
const serverOwner = () => 'server';

/** Read/reconcile only: local pending edits/conflicts stay owned by the existing
 * coordinator. A host shares this status with its children, rather than mounting
 * a second refresher. Disabled is unverified (checking), never a fresh receipt. */
export function useProfileRefresh(enabled: boolean, onAccepted?: (loaded: ProfileHydration) => void): ProfileRefreshState {
  const acceptedRef = useRef(onAccepted);
  useLayoutEffect(() => { acceptedRef.current = onAccepted; }, [onAccepted]);
  const checkSequence = useRef(0);
  const owner = useSyncExternalStore(subscribeOwner, ownerSnapshot, serverOwner);
  const [state, setState] = useState<{ owner: string; enabled: boolean; status: ProfileRefreshState['status'] }>({ owner, enabled, status: 'checking' });
  // A new enabled period is unverified even before its passive effect runs.
  // Otherwise consumers could observe the previous period's ready receipt.
  if (state.enabled !== enabled) setState({ owner, enabled, status: 'checking' });
  type Attempt = { controller: AbortController; promise: Promise<ProfileActionReceipt | null>; ready: Promise<boolean> };
  const runner = useRef<(() => Attempt | null) | null>(null);
  const refresh = useCallback(() => runner.current?.()?.ready ?? Promise.resolve(false), []);
  const checkForAction = useCallback(() => runner.current?.()?.promise ?? Promise.resolve(null), []);

  useEffect(() => {
    if (!enabled) { runner.current = null; return; }
    let disposed = false;
    let attempt: Attempt | null = null;
    const current = () => !disposed && ownerSnapshot() === owner;
    const run = (): Attempt | null => {
      if (!current()) return null;
      if (attempt && !attempt.controller.signal.aborted) return attempt;
      const controller = new AbortController();
      const record: Attempt = { controller, promise: Promise.resolve(null), ready: Promise.resolve(false) };
      const checkId = ++checkSequence.current;
      attempt = record;
      setState({ owner, enabled: true, status: 'checking' });
      const timer = setTimeout(() => controller.abort(), PROFILE_REFRESH_DEADLINE_MS);
      record.promise = Promise.resolve().then(async () => {
        try {
          const loaded = await hydrateProfile(controller.signal);
          if (!current() || attempt !== record || controller.signal.aborted || !isOwnerTokenValid(loaded.token, loaded.token.uid)) return null;
          const status: ProfileRefreshState['status'] = loaded.quarantineFailed ? 'failed'
            : loaded.conflictKeys.length || loaded.conflicts.length ? 'conflict'
              : loaded.source === 'local-only' ? 'local-only' : 'ready';
          setState({ owner, enabled: true, status });
          if (status !== 'ready' && status !== 'local-only') return null;
          // Freeze an independent copy before a host receives the hydration.
          // The candidate includes local pending edits; a fresh raw/envelope
          // read here could pair a different document with this revision.
          const view = loaded.profile ? makeProfileViewSnapshot({ baseProfile: loaded.baseProfile,
            renderedProfile: loaded.profile, revision: loaded.revision, token: loaded.token,
            identityGeneration: loaded.token.epoch, source: 'hydration' }) : null;
          const receipt: ProfileActionReceipt = Object.freeze({ checkId,
            owner: Object.freeze({ ...loaded.token }), revision: loaded.revision,
            source: loaded.source, profile: view?.renderedProfile ?? null });
          acceptedRef.current?.(loaded);
          if (!current() || controller.signal.aborted || !isOwnerTokenValid(receipt.owner, receipt.owner.uid)) return null;
          return receipt;
        } catch {
          if (current() && attempt === record) setState({ owner, enabled: true, status: 'failed' });
          return null;
        } finally {
          clearTimeout(timer);
          if (attempt === record) attempt = null;
        }
      });
      record.ready = record.promise.then((receipt) => receipt !== null);
      return record;
    };
    runner.current = run;
    const visible = () => { if (document.visibilityState === 'visible') void run(); };
    const recheck = () => { void run(); };
    window.addEventListener('focus', recheck);
    window.addEventListener('online', recheck);
    document.addEventListener('visibilitychange', visible);
    void run();
    return () => {
      disposed = true;
      if (runner.current === run) runner.current = null;
      attempt?.controller.abort();
      window.removeEventListener('focus', recheck);
      window.removeEventListener('online', recheck);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [enabled, owner]);

  return { status: enabled && state.enabled === enabled && state.owner === owner ? state.status : 'checking', refresh, checkForAction };
}
