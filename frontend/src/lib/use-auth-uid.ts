'use client';

import { useEffect, useState } from 'react';

import { onAuthChange } from './supabase';

export interface AuthUidState {
  /** Current auth.uid() as observed on this tab; null until known (or signed out). */
  uid: string | null;
  /**
   * Identity epoch: bumps ONLY on a real identity switch after the initial
   * resolution. Key user-data fetch effects on this so a cross-tab account
   * switch clears + refetches, while the initial null→uid resolution does
   * not double-fetch a surface that already loaded at mount.
   */
  epoch: number;
}

/**
 * W14 cross-tab uid isolation: subscribe to auth changes (via the existing
 * `onAuthChange` wrapper — every uid observed there already passes through
 * the local-identity-owner sync) and expose the current uid plus an identity
 * epoch.
 *
 * Epoch semantics (the double-fetch guard lives HERE, once):
 *   - null → uid : absorbed (epoch unchanged). This is either the initial
 *     session resolution, or the anon re-creation triggered by a surface's
 *     own in-flight load right after sign-out — in both cases a fetch under
 *     that identity is already running, so re-firing effects would only
 *     cancel and duplicate it.
 *   - uid A → B (or A → null): epoch + 1. Stale Account-A state must be
 *     cleared and refetched under the new identity.
 *
 * Usage: `const { epoch } = useAuthUid();` and add `epoch` to the existing
 * fetch effect's dependency array; reset the surface's user state at the top
 * of the effect (a no-op on mount, the isolation clear on a switch).
 */
export function useAuthUid(): AuthUidState {
  const [state, setState] = useState<AuthUidState>({ uid: null, epoch: 0 });

  useEffect(() => {
    const unsub = onAuthChange((s) => {
      const next = s.user?.id ?? null;
      setState((prev) => {
        if (next === prev.uid) return prev;
        if (prev.uid === null) return { uid: next, epoch: prev.epoch };
        return { uid: next, epoch: prev.epoch + 1 };
      });
    });
    return unsub;
  }, []);

  return state;
}
