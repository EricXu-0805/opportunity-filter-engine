import { afterEach, beforeEach, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';

function makeMemoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() { return store.size; },
    key: (i) => Array.from(store.keys())[i] ?? null,
    getItem: (k) => store.get(k) ?? null,
    setItem: (k, v) => { store.set(k, String(v)); },
    removeItem: (k) => { store.delete(k); },
    clear: () => { store.clear(); },
  };
}

/**
 * jsdom has no Web Locks. Every browser this ships to does (Chrome 69,
 * Firefox 96, Safari 15.4), and the private-storage authority treats their
 * absence as "this browser cannot serialize, so it gets no private
 * persistence at all" — the correct production rule, and a pure environment
 * artefact here. Supplying a real serial implementation keeps every suite
 * about its own subject; the fail-closed path has its own fixture that
 * deliberately removes this again.
 */
function installWebLocks(): void {
  let held = false;
  const waiting: Array<() => void> = [];
  const start = (
    fn: () => unknown,
    resolve: (v: unknown) => void,
    reject: (e: unknown) => void,
  ): void => {
    held = true;
    const done = (): void => { held = false; waiting.shift()?.(); };
    let out: unknown;
    try {
      out = fn();
    } catch (err) {
      done();
      reject(err);
      return;
    }
    Promise.resolve(out).then(
      (v) => { done(); resolve(v); },
      (e) => { done(); reject(e); },
    );
  };
  Object.defineProperty(navigator, 'locks', {
    configurable: true,
    writable: true,
    value: {
      request: (_name: string, _opts: unknown, fn: () => unknown) => new Promise((resolve, reject) => {
        if (held) waiting.push(() => start(fn, resolve, reject));
        else start(fn, resolve, reject);
      }),
    },
  });
}

if (typeof window !== 'undefined') {
  installWebLocks();
  // ALWAYS the memory storage, never jsdom's own. jsdom Storage instances
  // route own-property definition through their named-properties proxy, so
  // vi.spyOn(window.localStorage, 'setItem') stores the mock as a storage
  // ITEM named "setItem" while the real method keeps running — a spy that
  // silently intercepts nothing. Whether that happens depends on the
  // jsdom/Node pairing (it did on CI's Node 24 and not on a local Node 25),
  // which made the write-verification suites pass or fail by runtime
  // version. A plain object storage is deterministically spyable everywhere.
  Object.defineProperty(window, 'localStorage', {
    value: makeMemoryStorage(),
    configurable: true,
  });
  Object.defineProperty(window, 'sessionStorage', {
    value: makeMemoryStorage(),
    configurable: true,
  });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
});
