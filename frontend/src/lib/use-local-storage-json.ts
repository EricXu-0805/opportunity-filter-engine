'use client';

import { useSyncExternalStore } from 'react';

type Transformer = (value: unknown) => unknown;

type Cache = {
  raw: string | null;
  parsed: unknown;
  // Tracks which transformer the cached `transformed` was produced by.
  // `undefined` here means "no transformer was passed" — distinct from
  // a real transformer that happens to return undefined.
  transformer: Transformer | undefined;
  transformed: unknown;
};

const snapshotCache = new Map<string, Cache>();

// Pure reader exposed for tests + non-React callers.
//
// Returns referentially-stable values across calls when the underlying raw
// string AND the transformer reference are unchanged — required for
// useSyncExternalStore to avoid firing re-renders on every parent render.
//
// Transformer contract:
//   - Receives the parsed JSON value (or null when key is missing /
//     malformed / window is undefined / localStorage threw).
//   - MUST be a module-level constant (stable identity across renders) or
//     wrapped in useCallback if defined inline. Passing a fresh closure
//     each render invalidates the cache and re-invokes the transformer
//     every snapshot read.
//   - For SSR/hydration safety, MUST return a referentially-stable value
//     for the `null` input (typically a module-level EMPTY constant);
//     useSyncExternalStore compares snapshots by identity.
export function readLocalStorageJSON<T>(key: string): T | null;
export function readLocalStorageJSON<T, U>(
  key: string,
  transformer: (value: T | null) => U,
): U;
export function readLocalStorageJSON(
  key: string,
  transformer?: Transformer,
): unknown {
  if (typeof window === 'undefined') {
    return transformer ? transformer(null) : null;
  }
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    return transformer ? transformer(null) : null;
  }
  const cached = snapshotCache.get(key);
  if (
    cached
    && cached.raw === raw
    && cached.transformer === transformer
  ) {
    return cached.transformed;
  }
  let parsed: unknown = null;
  if (raw !== null) {
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = null;
    }
  }
  const transformed = transformer ? transformer(parsed) : parsed;
  snapshotCache.set(key, { raw, parsed, transformer, transformed });
  return transformed;
}

function subscribe(onStoreChange: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  window.addEventListener('storage', onStoreChange);
  return () => window.removeEventListener('storage', onStoreChange);
}

// Companion writer for useLocalStorageJSON readers. The native 'storage'
// event fires only on OTHER tabs by spec, so same-tab subscribers via
// useSyncExternalStore miss updates without a synthetic dispatch. Use
// this writer instead of localStorage.setItem when other components in
// the SAME tab need to react (e.g. /favorites re-rendering after a save
// click on /import).
//
// Passing null removes the key. Throws are swallowed (quota, private
// browsing); callers should treat as best-effort persistence.
export function writeLocalStorageJSON<T>(key: string, value: T | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (value === null) {
      window.localStorage.removeItem(key);
    } else {
      window.localStorage.setItem(key, JSON.stringify(value));
    }
    window.dispatchEvent(new StorageEvent('storage', { key }));
  } catch {
    /* localStorage unavailable / quota exceeded */
  }
}

// useSyncExternalStore-based hook for reading JSON-serialized localStorage
// values. Replaces the common `useState(null) + useEffect(() => setX(read()))`
// pattern that eslint-plugin-react-hooks v7 flags as set-state-in-effect.
//
// Returns null during SSR (matches getServerSnapshot) and during the
// initial client render before getSnapshot fires; matches the historical
// useEffect-based behavior so callers don't need to handle a new state.
//
// Optional transformer signature lets callers validate / normalise the
// parsed value at the snapshot boundary so the hook output is always the
// already-validated shape (no need for `?? []` + a parallel parser at the
// call site). See readLocalStorageJSON for the transformer contract.
//
// Subscribes to cross-tab 'storage' events. Same-tab writes by other code
// paths do NOT trigger re-renders here (browsers don't fire 'storage' for
// the writing tab) — use writeLocalStorageJSON to dispatch a synthetic
// event so same-tab readers re-render.
export function useLocalStorageJSON<T>(key: string): T | null;
export function useLocalStorageJSON<T, U>(
  key: string,
  transformer: (value: T | null) => U,
): U;
export function useLocalStorageJSON(
  key: string,
  transformer?: Transformer,
): unknown {
  return useSyncExternalStore(
    subscribe,
    () => readLocalStorageJSON(key, transformer as never),
    () => (transformer ? transformer(null) : null),
  );
}

// Tri-state existence probe for "is this key set?" decisions.
//   undefined → still hydrating (don't act yet)
//   true      → key is present in localStorage
//   false     → confirmed absent
// Returns undefined during SSR + first client render so callers can
// distinguish "not yet known" from "confirmed missing" —
// useLocalStorageJSON returns null for both, which conflates the two
// and causes redirect-on-hydrate races for pages that bounce to '/'
// when storage is empty.
export function useHasLocalStorageKey(key: string): boolean | undefined {
  return useSyncExternalStore<boolean | undefined>(
    subscribe,
    () => {
      try {
        return window.localStorage.getItem(key) !== null;
      } catch {
        return false;
      }
    },
    () => undefined,
  );
}
