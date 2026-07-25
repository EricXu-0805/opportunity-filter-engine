import { describe, expect, it, vi } from 'vitest';
import {
  isSchoolConfirmed,
  persistHomeSchool,
  readSchoolConfirmation,
  recordSchoolConfirmation,
} from './school-confirmation';
import { HOME_SCHOOL_EVENT, STORAGE_KEYS } from './storage-keys';

describe('recordSchoolConfirmation / readSchoolConfirmation', () => {
  it('writes {slug, ts} JSON under the Codex-compatible key', () => {
    recordSchoolConfirmation('ucb');
    const raw = localStorage.getItem('ofe_school_confirmed');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.slug).toBe('ucb');
    expect(typeof parsed.ts).toBe('string');
    expect(readSchoolConfirmation()).toEqual(parsed);
  });

  it('returns null for absent, malformed, or slug-less values', () => {
    expect(readSchoolConfirmation()).toBeNull();
    localStorage.setItem(STORAGE_KEYS.SCHOOL_CONFIRMED, 'not-json{');
    expect(readSchoolConfirmation()).toBeNull();
    localStorage.setItem(STORAGE_KEYS.SCHOOL_CONFIRMED, JSON.stringify({ ts: 'x' }));
    expect(readSchoolConfirmation()).toBeNull();
  });
});

describe('isSchoolConfirmed', () => {
  it('covers only the confirmed slug', () => {
    expect(isSchoolConfirmed('uiuc')).toBe(false);
    recordSchoolConfirmation('uiuc');
    expect(isSchoolConfirmed('uiuc')).toBe(true);
    // A school changed by a flow that skipped the receipt must re-confirm.
    expect(isSchoolConfirmed('ucb')).toBe(false);
  });
});

describe('persistHomeSchool', () => {
  it('merges home_school into the profile blob and broadcasts the event', () => {
    localStorage.setItem(
      STORAGE_KEYS.PROFILE,
      JSON.stringify({ major: 'CS', home_school: 'uiuc' }),
    );
    const seen: string[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent<string>).detail);
    window.addEventListener(HOME_SCHOOL_EVENT, listener);
    try {
      persistHomeSchool('ucb');
    } finally {
      window.removeEventListener(HOME_SCHOOL_EVENT, listener);
    }
    const profile = JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!);
    expect(profile).toEqual({ major: 'CS', home_school: 'ucb' });
    expect(seen).toEqual(['ucb']);
  });

  it('starts a fresh blob when none exists', () => {
    persistHomeSchool('umich');
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!)).toEqual({
      home_school: 'umich',
    });
  });

  it('never throws when storage is unavailable', () => {
    const original = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: vi.fn(() => { throw new Error('denied'); }),
        setItem: vi.fn(() => { throw new Error('denied'); }),
      },
      configurable: true,
    });
    try {
      expect(() => persistHomeSchool('uiuc')).not.toThrow();
      expect(() => recordSchoolConfirmation('uiuc')).not.toThrow();
      expect(readSchoolConfirmation()).toBeNull();
    } finally {
      Object.defineProperty(window, 'localStorage', {
        value: original,
        configurable: true,
      });
    }
  });
});
