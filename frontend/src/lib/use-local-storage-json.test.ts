import { afterEach, describe, it, expect, vi } from 'vitest';
import { readLocalStorageJSON, writeLocalStorageJSON } from './use-local-storage-json';

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
    writeLocalStorageJSON('w1', { x: 1 });
    expect(readLocalStorageJSON<{ x: number }>('w1')).toEqual({ x: 1 });
  });

  it('removes the key when value is null', () => {
    writeLocalStorageJSON('w2', { y: 2 });
    expect(localStorage.getItem('w2')).not.toBeNull();
    writeLocalStorageJSON('w2', null);
    expect(localStorage.getItem('w2')).toBeNull();
  });

  it('dispatches a storage event so same-tab subscribers can react', () => {
    const listener = vi.fn();
    window.addEventListener('storage', listener);
    try {
      writeLocalStorageJSON('w3', { z: 3 });
    } finally {
      window.removeEventListener('storage', listener);
    }
    expect(listener).toHaveBeenCalledTimes(1);
    const evt = listener.mock.calls[0][0] as StorageEvent;
    expect(evt.key).toBe('w3');
  });
});
