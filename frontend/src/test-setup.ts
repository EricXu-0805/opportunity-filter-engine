import { beforeEach, vi } from 'vitest';

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

if (typeof window !== 'undefined') {
  const needsLocal = !window.localStorage || typeof window.localStorage.setItem !== 'function';
  const needsSession = !window.sessionStorage || typeof window.sessionStorage.setItem !== 'function';
  if (needsLocal) {
    Object.defineProperty(window, 'localStorage', {
      value: makeMemoryStorage(),
      configurable: true,
    });
  }
  if (needsSession) {
    Object.defineProperty(window, 'sessionStorage', {
      value: makeMemoryStorage(),
      configurable: true,
    });
  }
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});
