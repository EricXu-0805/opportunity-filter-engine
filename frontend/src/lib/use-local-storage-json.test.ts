import { afterEach, describe, it, expect, vi } from 'vitest';
import { readLocalStorageJSON, useHasLocalStorageKey, writeLocalStorageJSON } from './use-local-storage-json';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import { act, renderHook } from '@testing-library/react';

// A device-scoped key (not in USER_SCOPED_KEYS/PREFIXES) never consults the
// token's validity — any well-formed token works for these generic tests.
const deviceToken = captureOwnerToken();

afterEach(() => {
  localStorage.clear();
});

describe('readLocalStorageJSON', () => {
  it('returns null for missing key', () => {
    expect(readLocalStorageJSON('missing-key')).toBeNull();
  });

  it('parses valid JSON objects', () => {
    localStorage.setItem('obj', JSON.stringify({ a: 1, b: 'two' }));
    expect(readLocalStorageJSON<{ a: number; b: string }>('obj')).toEqual({
      a: 1,
      b: 'two',
    });
  });

  it('parses valid JSON arrays', () => {
    localStorage.setItem('arr', JSON.stringify([1, 2, 3]));
    expect(readLocalStorageJSON<number[]>('arr')).toEqual([1, 2, 3]);
  });

  it('returns null for malformed JSON', () => {
    localStorage.setItem('bad', '{not-json');
    expect(readLocalStorageJSON('bad')).toBeNull();
  });

  it('returns null for non-JSON primitive when stored without JSON-encoding', () => {
    localStorage.setItem('plain', 'hello');
    expect(readLocalStorageJSON('plain')).toBeNull();
  });

  it('returns the same reference across calls when raw value unchanged', () => {
    localStorage.setItem('stable', JSON.stringify({ x: 1 }));
    const first = readLocalStorageJSON('stable');
    const second = readLocalStorageJSON('stable');
    expect(first).toBe(second);
  });

  it('returns a fresh reference when raw value changes', () => {
    localStorage.setItem('mut', JSON.stringify({ x: 1 }));
    const first = readLocalStorageJSON<{ x: number }>('mut');
    localStorage.setItem('mut', JSON.stringify({ x: 2 }));
    const second = readLocalStorageJSON<{ x: number }>('mut');
    expect(first).not.toBe(second);
    expect(second).toEqual({ x: 2 });
  });

  it('handles transitions to and from missing key', () => {
    localStorage.setItem('toggle', JSON.stringify({ a: 1 }));
    expect(readLocalStorageJSON('toggle')).toEqual({ a: 1 });
    localStorage.removeItem('toggle');
    expect(readLocalStorageJSON('toggle')).toBeNull();
    localStorage.setItem('toggle', JSON.stringify({ a: 2 }));
    expect(readLocalStorageJSON('toggle')).toEqual({ a: 2 });
  });
});

describe('readLocalStorageJSON with transformer', () => {
  const EMPTY_NUMS: number[] = [];
  const onlyNumbers = (raw: unknown): number[] => {
    if (!Array.isArray(raw)) return EMPTY_NUMS;
    const out = raw.filter((v): v is number => typeof v === 'number');
    return out.length === 0 ? EMPTY_NUMS : out;
  };

  it('invokes the transformer on the parsed value', () => {
    localStorage.setItem('nums', JSON.stringify([1, 'two', 3, null, 4]));
    expect(readLocalStorageJSON('nums', onlyNumbers)).toEqual([1, 3, 4]);
  });

  it('invokes the transformer with null when key is missing', () => {
    expect(readLocalStorageJSON('absent', onlyNumbers)).toBe(EMPTY_NUMS);
  });

  it('invokes the transformer with null when JSON is malformed', () => {
    localStorage.setItem('bad', '{not-json');
    expect(readLocalStorageJSON('bad', onlyNumbers)).toBe(EMPTY_NUMS);
  });

  it('returns the same transformed reference across calls when raw + transformer unchanged', () => {
    localStorage.setItem('stable-t', JSON.stringify([1, 2, 3]));
    const first = readLocalStorageJSON('stable-t', onlyNumbers);
    const second = readLocalStorageJSON('stable-t', onlyNumbers);
    expect(first).toBe(second);
  });

  it('returns a fresh transformed reference when raw changes', () => {
    localStorage.setItem('mut-t', JSON.stringify([1, 2]));
    const first = readLocalStorageJSON('mut-t', onlyNumbers);
    localStorage.setItem('mut-t', JSON.stringify([1, 2, 3]));
    const second = readLocalStorageJSON('mut-t', onlyNumbers);
    expect(first).not.toBe(second);
    expect(second).toEqual([1, 2, 3]);
  });

  it('returns a fresh transformed reference when transformer identity changes', () => {
    localStorage.setItem('swap-t', JSON.stringify([1, 2, 3]));
    const otherTransformer = (raw: unknown) => (Array.isArray(raw) ? raw.length : 0);
    const first = readLocalStorageJSON('swap-t', onlyNumbers);
    const second = readLocalStorageJSON('swap-t', otherTransformer);
    expect(first).toEqual([1, 2, 3]);
    expect(second).toBe(3);
  });

  it('keeps no-transformer and transformer caches separable by re-invoking on switch', () => {
    localStorage.setItem('mix-t', JSON.stringify([1, 2, 3]));
    const plain = readLocalStorageJSON<number[]>('mix-t');
    const transformed = readLocalStorageJSON('mix-t', onlyNumbers);
    expect(plain).toEqual([1, 2, 3]);
    expect(transformed).toEqual([1, 2, 3]);
  });
});

describe('writeLocalStorageJSON', () => {
  it('writes JSON and is readable via readLocalStorageJSON', () => {
    writeLocalStorageJSON('w1', { x: 1 }, deviceToken);
    expect(readLocalStorageJSON<{ x: number }>('w1')).toEqual({ x: 1 });
  });

  it('removes the key when value is null', () => {
    writeLocalStorageJSON('w2', { y: 2 }, deviceToken);
    expect(localStorage.getItem('w2')).not.toBeNull();
    writeLocalStorageJSON('w2', null, deviceToken);
    expect(localStorage.getItem('w2')).toBeNull();
  });

  it('dispatches a storage event so same-tab subscribers can react', () => {
    const listener = vi.fn();
    window.addEventListener('storage', listener);
    try {
      writeLocalStorageJSON('w3', { z: 3 }, deviceToken);
    } finally {
      window.removeEventListener('storage', listener);
    }
    expect(listener).toHaveBeenCalledTimes(1);
    const evt = listener.mock.calls[0][0] as StorageEvent;
    expect(evt.key).toBe('w3');
  });

  it('returns true on a successful device-scoped write and false when storage throws', async () => {
    expect(writeLocalStorageJSON('w4', { ok: 1 }, deviceToken)).toBe(true);
    const original = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      value: { ...original, setItem: () => { throw new Error('quota'); } },
      configurable: true,
    });
    try {
      expect(writeLocalStorageJSON('w5', { ok: 2 }, deviceToken)).toBe(false);
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
  });

  it('a USER_SCOPED key returns false and suppresses the storage event when the token is stale', async () => {
    advanceOwnerEpoch('use-lsj-u1');
    await syncLocalIdentityOwner('use-lsj-u1');
    const staleToken = captureOwnerToken();
    advanceOwnerEpoch('use-lsj-u2');
    await syncLocalIdentityOwner('use-lsj-u2');
    const listener = vi.fn();
    window.addEventListener('storage', listener);
    try {
      const wrote = writeLocalStorageJSON(STORAGE_KEYS.FILTER_PRESETS, [{ id: '1' }], staleToken);
      expect(wrote).toBe(false);
    } finally {
      window.removeEventListener('storage', listener);
    }
    expect(listener).not.toHaveBeenCalled();
    expect(readLocalStorageJSON(STORAGE_KEYS.FILTER_PRESETS)).toBeNull();
  });

  it('a USER_SCOPED key returns true and dispatches the storage event when the token is current', async () => {
    advanceOwnerEpoch('use-lsj-u3');
    await syncLocalIdentityOwner('use-lsj-u3');
    const token = captureOwnerToken();
    const listener = vi.fn();
    window.addEventListener('storage', listener);
    try {
      const wrote = writeLocalStorageJSON(STORAGE_KEYS.FILTER_PRESETS, [{ id: '1' }], token);
      expect(wrote).toBe(true);
    } finally {
      window.removeEventListener('storage', listener);
    }
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('returns false (never throws) for a circular value — JSON.stringify itself throws before any storage call', () => {
    const listener = vi.fn();
    window.addEventListener('storage', listener);
    try {
      const circular: Record<string, unknown> = { a: 1 };
      circular.self = circular;
      expect(() => writeLocalStorageJSON('w6', circular, deviceToken)).not.toThrow();
      expect(writeLocalStorageJSON('w6', circular, deviceToken)).toBe(false);
    } finally {
      window.removeEventListener('storage', listener);
    }
    expect(listener).not.toHaveBeenCalled();
    expect(localStorage.getItem('w6')).toBeNull();
  });

  it('returns false (never throws) for a BigInt value', () => {
    expect(() => writeLocalStorageJSON('w7', { n: BigInt(1) } as never, deviceToken)).not.toThrow();
    expect(writeLocalStorageJSON('w7', { n: BigInt(1) } as never, deviceToken)).toBe(false);
    expect(localStorage.getItem('w7')).toBeNull();
  });
});

describe('useHasLocalStorageKey', () => {
  it('returns undefined (not false) when localStorage access throws — "unknown", not "confirmed absent"', () => {
    const original = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      value: { ...original, getItem: () => { throw new Error('denied'); } },
      configurable: true,
    });
    try {
      const { result } = renderHook(() => useHasLocalStorageKey('device-key'));
      expect(result.current).toBeUndefined();
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
  });

  it('returns false for a confirmed-absent device key (no throw)', () => {
    const { result } = renderHook(() => useHasLocalStorageKey('device-key-absent'));
    expect(result.current).toBe(false);
  });

  it('returns undefined for a USER_SCOPED key while local ownership is blocked', () => {
    // No advanceOwnerEpoch/syncLocalIdentityOwner call in this test — a
    // fresh module state (or an unrelated prior identity) leaves the
    // realm blocked for this key's uid.
    advanceOwnerEpoch('use-has-blocked-uid'); // marks blocked, no sync
    const { result } = renderHook(() => useHasLocalStorageKey(STORAGE_KEYS.FILTER_PRESETS));
    expect(result.current).toBeUndefined();
  });

  it('flips to true once local ownership becomes ready and the key is present', async () => {
    advanceOwnerEpoch('use-has-ready-uid');
    localStorage.setItem(STORAGE_KEYS.FILTER_PRESETS, JSON.stringify([{ id: '1' }]));
    const { result } = renderHook(() => useHasLocalStorageKey(STORAGE_KEYS.FILTER_PRESETS));
    expect(result.current).toBeUndefined(); // blocked — the raw write above isn't trusted yet

    // The readiness transition itself (via onLocalOwnerStateChange, part
    // of this hook's subscribe) re-invokes the snapshot — no separate
    // rehydrate logic needed, unlike a plain storage write which would
    // need writeLocalStorageJSON's own synthetic 'storage' dispatch.
    act(() => { syncLocalIdentityOwner('use-has-ready-uid'); });
    expect(result.current).toBe(true);
  });
});
