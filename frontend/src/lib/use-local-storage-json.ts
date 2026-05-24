'use client';

import { useSyncExternalStore } from 'react';

type Cache = { raw: string | null; parsed: unknown };

const snapshotCache = new Map<string, Cache>();

// Pure reader exposed for tests + non-React callers.
// Returns referentially-stable values across calls when the underlying
// raw string hasn't changed — required for useSyncExternalStore to avoid
// firing re-renders on every parent re-render.
export function readLocalStorageJSON<T>(key: string): T | null {
  if (typeof window === 'undefined') return null;
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    return null;
  }
  const cached = snapshotCache.get(key);
  if (cached && cached.raw === raw) return cached.parsed as T | null;
  let parsed: unknown = null;
  if (raw !== null) {
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = null;
    }
  }
  snapshotCache.set(key, { raw, parsed });
  return parsed as T | null;
}

function subscribe(onStoreChange: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  window.addEventListener('storage', onStoreChange);
  return () => window.removeEventListener('storage', onStoreChange);
}

// useSyncExternalStore-based hook for reading JSON-serialized localStorage
// values. Replaces the common `useState(null) + useEffect(() => setX(read()))`
// pattern that eslint-plugin-react-hooks v7 flags as set-state-in-effect.
//
// Returns null during SSR (matches getServerSnapshot) and during the
// initial client render before getSnapshot fires; matches the historical
// useEffect-based behavior so callers don't need to handle a new state.
//
// Subscribes to cross-tab 'storage' events. Same-tab writes by other code
// paths do NOT trigger re-renders here (browsers don't fire 'storage' for
// the writing tab) — that's matches the previous useEffect-on-mount
// semantics where same-tab writes also wouldn't propagate.
export function useLocalStorageJSON<T>(key: string): T | null {
  return useSyncExternalStore(
    subscribe,
    () => readLocalStorageJSON<T>(key),
    () => null,
  );
}
