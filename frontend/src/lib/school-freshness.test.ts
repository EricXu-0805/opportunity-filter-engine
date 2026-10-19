import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';

import {
  SCHOOL_FRESHNESS_SCHEMA,
  dateLocale,
  formatCheckedDate,
  keptSchoolFreshness,
  loadSchoolFreshness,
  parseSchoolFreshness,
  resetSchoolFreshnessForTests,
  useSchoolFreshness,
} from './school-freshness';

const BODY = {
  schema: SCHOOL_FRESHNESS_SCHEMA,
  schools: {
    uiuc: { last_checked_at: '2026-10-12T19:13:14+00:00', status: 'partly_unchecked' },
    swarthmore: { last_checked_at: '2026-09-05T03:45:00+00:00', status: 'stale' },
    yale: { last_checked_at: '2026-10-17T13:30:52+00:00', status: 'current' },
  },
};

function respond(body: unknown, ok = true) {
  return vi.fn(async () => ({ ok, json: async () => body }) as unknown as Response);
}

beforeEach(() => resetSchoolFreshnessForTests());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('parseSchoolFreshness', () => {
  it('reads each school the response names', () => {
    const schools = parseSchoolFreshness(BODY)!;
    expect(schools.get('swarthmore')).toEqual({
      lastCheckedAt: '2026-09-05T03:45:00+00:00', status: 'stale',
    });
    expect(schools.get('uiuc')?.status).toBe('partly_unchecked');
    expect(schools.has('ucd')).toBe(false);
  });

  it('refuses a body that is not this schema', () => {
    expect(parseSchoolFreshness(null)).toBeNull();
    expect(parseSchoolFreshness('stale')).toBeNull();
    expect(parseSchoolFreshness({ schools: BODY.schools })).toBeNull();
    expect(parseSchoolFreshness({ ...BODY, schema: 'school-freshness-v0' })).toBeNull();
    expect(parseSchoolFreshness({ schema: SCHOOL_FRESHNESS_SCHEMA, schools: [] })).toBeNull();
  });

  it('drops a malformed school and keeps the rest', () => {
    const schools = parseSchoolFreshness({
      schema: SCHOOL_FRESHNESS_SCHEMA,
      schools: {
        ...BODY.schools,
        a: { last_checked_at: 'yesterday', status: 'current' },
        b: { last_checked_at: '2026-10-01T00:00:00Z', status: 'fresh' },
        c: { status: 'current' },
        d: 'stale',
        e: { last_checked_at: null, status: 'stale' },
        ['__proto__']: { last_checked_at: null, status: 'stale' },
      },
    })!;
    expect([...schools.keys()].sort()).toEqual(['__proto__', 'e', 'swarthmore', 'uiuc', 'yale']);
    expect(schools.get('e')).toEqual({ lastCheckedAt: null, status: 'stale' });
  });
});

describe('formatCheckedDate', () => {
  it('writes the date the way the page language writes it', () => {
    const at = '2026-10-12T19:13:14+00:00';
    expect(formatCheckedDate(at, 'en', { timeZone: 'UTC', languages: [] })).toBe('Oct 12, 2026');
    expect(formatCheckedDate(at, 'zh', { timeZone: 'UTC', languages: [] })).toBe('2026年10月12日');
  });

  it("uses the reader's own variant of the page language", () => {
    const at = '2026-10-12T19:13:14+00:00';
    expect(dateLocale('en', ['en-GB', 'en-US'])).toBe('en-GB');
    expect(dateLocale('en', ['zh-TW', 'fr-FR'])).toBe('en');
    expect(formatCheckedDate(at, 'en', { timeZone: 'UTC', languages: ['en-GB'] })).toBe('12 Oct 2026');
    expect(formatCheckedDate(at, 'zh', { timeZone: 'UTC', languages: ['en-US', 'zh-TW'] }))
      .toBe('2026年10月12日');
  });

  it("shows the reader's calendar day: Swarthmore's 03:45 UTC read is 4 September in Chicago", () => {
    const at = '2026-09-05T03:45:00+00:00';
    expect(formatCheckedDate(at, 'en', { timeZone: 'America/Chicago', languages: [] }))
      .toBe('Sep 4, 2026');
    expect(formatCheckedDate(at, 'en', { timeZone: 'UTC', languages: [] })).toBe('Sep 5, 2026');
  });

  it('says nothing for a time it cannot read, and survives a tag Intl rejects', () => {
    expect(formatCheckedDate('not a date', 'en')).toBeNull();
    expect(formatCheckedDate('2026-10-12T19:13:14+00:00', 'en',
      { timeZone: 'UTC', languages: ['en-'] })).toBe('Oct 12, 2026');
  });
});

describe('loadSchoolFreshness', () => {
  it('shares one request and keeps a good answer', async () => {
    const fetchMock = respond(BODY);
    vi.stubGlobal('fetch', fetchMock);
    const [first, second] = await Promise.all([loadSchoolFreshness(), loadSchoolFreshness()]);
    expect(first).toBe(second);
    expect(await loadSchoolFreshness()).toBe(first);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/opportunities/freshness');
    expect(keptSchoolFreshness()).toBe(first);
  });

  it.each([
    ['an error status', () => respond(BODY, false)],
    ['an older schema', () => respond({ schools: BODY.schools })],
    ['a network failure', () => vi.fn(async () => { throw new TypeError('offline'); })],
    ['an unreadable body', () => vi.fn(async () => ({
      ok: true, json: async () => { throw new SyntaxError('bad json'); },
    }) as unknown as Response)],
  ])('answers null for %s and asks again next time', async (_label, make) => {
    vi.stubGlobal('fetch', make());
    expect(await loadSchoolFreshness()).toBeNull();
    expect(keptSchoolFreshness()).toBeNull();
    const retry = respond(BODY);
    vi.stubGlobal('fetch', retry);
    expect((await loadSchoolFreshness())?.get('uiuc')?.status).toBe('partly_unchecked');
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('asks again once the kept answer is ten minutes old', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-18T12:00:00Z'));
    const fetchMock = respond(BODY);
    vi.stubGlobal('fetch', fetchMock);
    await loadSchoolFreshness();
    vi.setSystemTime(new Date('2026-10-18T12:09:59Z'));
    await loadSchoolFreshness();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    vi.setSystemTime(new Date('2026-10-18T12:10:00Z'));
    expect(keptSchoolFreshness()).toBeNull();
    await loadSchoolFreshness();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe('useSchoolFreshness', () => {
  it('is loading until the answer arrives, then ready', async () => {
    let release!: () => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => {
      release = () => resolve({ ok: true, json: async () => BODY } as unknown as Response);
    })));
    const { result } = renderHook(() => useSchoolFreshness());
    expect(result.current.status).toBe('loading');
    await act(async () => { release(); });
    await waitFor(() => expect(result.current.status).toBe('ready'));
  });

  it('fails without a claim when the read fails', async () => {
    vi.stubGlobal('fetch', respond(null, false));
    const { result } = renderHook(() => useSchoolFreshness());
    await waitFor(() => expect(result.current.status).toBe('failed'));
  });

  it('starts ready when an answer is already kept, without asking again', async () => {
    const fetchMock = respond(BODY);
    vi.stubGlobal('fetch', fetchMock);
    await loadSchoolFreshness();
    const { result } = renderHook(() => useSchoolFreshness());
    expect(result.current.status).toBe('ready');
    const first = result.current;
    await act(async () => {});
    expect(result.current).toBe(first);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
