import { describe, it, expect } from 'vitest';
import { readLocalStorageJSON } from './use-local-storage-json';

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
