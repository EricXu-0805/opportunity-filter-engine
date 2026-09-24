'use client';

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange } from './identity-owner';
import { hydrateProfile } from './profile-sync';

export type ProfileRefreshState = {
  status: 'checking' | 'ready' | 'failed' | 'local-only' | 'conflict';
  refresh: () => Promise<boolean>;
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
export function useProfileRefresh(enabled: boolean): ProfileRefreshState {
  const owner = useSyncExternalStore(subscribeOwner, ownerSnapshot, serverOwner);
  const [state, setState] = useState<{ owner: string; enabled: boolean; status: ProfileRefreshState['status'] }>({ owner, enabled, status: 'checking' });
  // A new enabled period is unverified even before its passive effect runs.
  // Otherwise consumers could observe the previous period's ready receipt.
  if (state.enabled !== enabled) setState({ owner, enabled, status: 'checking' });
  const runner = useRef<(() => Promise<boolean>) | null>(null);
  const refresh = useCallback(() => runner.current?.() ?? Promise.resolve(false), []);

  useEffect(() => {
    if (!enabled) { runner.current = null; return; }
    let disposed = false;
    let attempt: { controller: AbortController; promise: Promise<boolean> } | null = null;
    const current = () => !disposed && ownerSnapshot() === owner;
    const run = (): Promise<boolean> => {
      if (!current()) return Promise.resolve(false);
      if (attempt && !attempt.controller.signal.aborted) return attempt.promise;
      const controller = new AbortController();
      const record = { controller, promise: Promise.resolve(false) };
      attempt = record;
      setState({ owner, enabled: true, status: 'checking' });
      const timer = setTimeout(() => controller.abort(), PROFILE_REFRESH_DEADLINE_MS);
      record.promise = Promise.resolve().then(async () => {
        try {
          const loaded = await hydrateProfile(controller.signal);
          if (!current() || attempt !== record || controller.signal.aborted || !isOwnerTokenValid(loaded.token, loaded.token.uid)) return false;
          const status: ProfileRefreshState['status'] = loaded.quarantineFailed ? 'failed'
            : loaded.conflictKeys.length || loaded.conflicts.length ? 'conflict'
              : loaded.source === 'local-only' ? 'local-only' : 'ready';
          setState({ owner, enabled: true, status });
          return status === 'ready' || status === 'local-only';
        } catch {
          if (current() && attempt === record) setState({ owner, enabled: true, status: 'failed' });
          return false;
        } finally {
          clearTimeout(timer);
          if (attempt === record) attempt = null;
        }
      });
      return record.promise;
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

  return { status: enabled && state.enabled === enabled && state.owner === owner ? state.status : 'checking', refresh };
}
