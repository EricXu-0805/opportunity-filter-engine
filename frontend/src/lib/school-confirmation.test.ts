import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  isSchoolConfirmed,
  persistHomeSchool,
  readSchoolConfirmation,
  recordSchoolConfirmation,
} from './school-confirmation';
import { HOME_SCHOOL_EVENT, STORAGE_KEYS } from './storage-keys';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, type OwnerToken } from './identity-owner';
import {
  makeProfileViewSnapshot,
  readProfileView,
  resetProfileDirtyLedger,
} from './profile-sync';
import type { ProfileData } from './types';

/** The view a surface would have accepted from the storage state as it stands
 *  right now — the production shape, not a hand-built pair. A surface with
 *  nothing to read declares an explicitly unknown baseline rather than
 *  inventing one. */
function viewFor(owner: OwnerToken) {
  return readProfileView(owner) ?? makeProfileViewSnapshot({
    baseProfile: null,
    renderedProfile: {} as ProfileData,
    revision: 0,
    token: owner,
    identityGeneration: owner.epoch,
    source: 'storage',
  });
}

// persistHomeSchool goes through the profile coordinator now: one CAS patch
// of `home_school`, and only if that lands do the receipt, the cache clear
// and the broadcast follow. The service layer is faked so these tests stay
// about the ORDERING, which is what they were written for.
const commitMock = vi.fn(async (intent: { patch: Record<string, unknown>; expectedRevision: number }) => {
  serverRow = { ...(serverRow ?? {}), ...intent.patch };
  serverRevision += 1;
  return { status: 'saved' as const, revision: serverRevision, profile: serverRow };
});
let serverRow: Record<string, unknown> | null = null;
let serverRevision = 0;
vi.mock('./supabase', () => ({
  loadProfile: async () => (serverRow
    ? { source: 'cloud' as const, profile: serverRow, revision: serverRevision, token: captureOwnerToken() }
    : { source: 'cloud-absent' as const, profile: null, revision: 0, token: captureOwnerToken() }),
  commitProfilePatch: (intent: { patch: Record<string, unknown>; expectedRevision: number }) => commitMock(intent),
}));

// These writes now go through writeLocalStorageJSON's origin-token
// discipline — every test needs local-owner readiness established first.
let token: OwnerToken;
beforeEach(async () => {
  let chain: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, 'locks', {
    configurable: true,
    value: {
      request: (_n: string, _o: unknown, fn: () => Promise<unknown>) => {
        const run = chain.then(() => fn());
        chain = run.then(() => undefined, () => undefined);
        return run;
      },
    },
  });
  serverRow = null;
  serverRevision = 0;
  commitMock.mockClear();
  resetProfileDirtyLedger();
  advanceOwnerEpoch(null);
  advanceOwnerEpoch('school-confirmation-test-uid');
  await syncLocalIdentityOwner('school-confirmation-test-uid');
  token = captureOwnerToken();
});

describe('recordSchoolConfirmation / readSchoolConfirmation', () => {
  it('writes {slug, ts} JSON under the Codex-compatible key', () => {
    recordSchoolConfirmation('ucb', token);
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
    recordSchoolConfirmation('uiuc', token);
    expect(isSchoolConfirmed('uiuc')).toBe(true);
    // A school changed by a flow that skipped the receipt must re-confirm.
    expect(isSchoolConfirmed('ucb')).toBe(false);
  });
});

describe('persistHomeSchool', () => {
  it('merges home_school into the profile blob and broadcasts the event', async () => {
    localStorage.setItem(
      STORAGE_KEYS.PROFILE,
      JSON.stringify({ major: 'CS', home_school: 'uiuc' }),
    );
    // A row already exists in the cloud, so this is a PATCH rather than the
    // brand-new-account case covered below.
    serverRow = { major: 'CS', home_school: 'uiuc' };
    serverRevision = 1;
    const seen: string[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent<string>).detail);
    window.addEventListener(HOME_SCHOOL_EVENT, listener);
    try {
      const result = await persistHomeSchool('ucb', viewFor(token));
      expect(result.ok).toBe(true);
    } finally {
      window.removeEventListener(HOME_SCHOOL_EVENT, listener);
    }
    // ONE key was sent — this caller holds a localStorage snapshot that may
    // be older than another device's row, so it says only what it changed.
    expect(commitMock.mock.calls.map((c) => c[0].patch)).toEqual([{ home_school: 'ucb' }]);
    const profile = JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!);
    expect(profile.home_school).toBe('ucb');
    expect(profile.major).toBe('CS');
    expect(seen).toEqual(['ucb']);
  });

  it('a brand new account stages the campus locally with ZERO requests', async () => {
    // The cloud confirms there is no row yet, and a one-field writer may not
    // create one. Refusing outright would strand the onboarding tour.
    const result = await persistHomeSchool('umich', viewFor(token));
    expect(result.ok).toBe(true);
    expect(result.ok && result.synced).toBe(false);
    expect(commitMock).not.toHaveBeenCalled();
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).home_school).toBe('umich');
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
      expect(() => persistHomeSchool('uiuc', viewFor(token))).not.toThrow();
      expect(() => recordSchoolConfirmation('uiuc', token)).not.toThrow();
      expect(readSchoolConfirmation()).toBeNull();
    } finally {
      Object.defineProperty(window, 'localStorage', {
        value: original,
        configurable: true,
      });
    }
  });

  it('a STALE view (U1) must not read U2\'s profile, clear U2\'s cache, or broadcast the event that would corrupt U2\'s live form state', async () => {
    // Captured while signed in as U1, exactly as a surface that stays mounted
    // through the switch would still be holding it.
    const staleView = viewFor(token);
    // U2 takes over.
    advanceOwnerEpoch('school-confirmation-u2');
    await syncLocalIdentityOwner('school-confirmation-u2');
    // U2 has a real profile and a real match cache — persistHomeSchool
    // must not touch either when called with U1's stale token.
    localStorage.setItem(
      STORAGE_KEYS.PROFILE,
      JSON.stringify({ major: 'ME', home_school: 'u2-school' }),
    );
    localStorage.setItem(
      STORAGE_KEYS.MATCH_RESULTS,
      JSON.stringify({ version: 'sentinel', contract_version: 'sentinel' }),
    );
    // A row already exists in the cloud, so this is a PATCH rather than the
    // brand-new-account case covered below.
    serverRow = { major: 'CS', home_school: 'uiuc' };
    serverRevision = 1;
    const seen: string[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent<string>).detail);
    window.addEventListener(HOME_SCHOOL_EVENT, listener);
    try {
      persistHomeSchool('u1-school', staleView);
    } finally {
      window.removeEventListener(HOME_SCHOOL_EVENT, listener);
    }
    // U2's profile is untouched — not merged, not overwritten.
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!)).toEqual({
      major: 'ME',
      home_school: 'u2-school',
    });
    // U2's match cache was NOT cleared.
    expect(localStorage.getItem(STORAGE_KEYS.MATCH_RESULTS)).not.toBeNull();
    // The event never fired — U2's live in-memory form state (which would
    // react to it) was never touched.
    expect(seen).toEqual([]);
  });

  it('a STALE view triggers ZERO localStorage reads — proves the preflight runs before any read, not merely gating the final write', async () => {
    const staleView = viewFor(token);
    advanceOwnerEpoch('school-confirmation-noread-u2');
    await syncLocalIdentityOwner('school-confirmation-noread-u2');
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ home_school: 'u2-school' }));
    const getItemSpy = vi.spyOn(window.localStorage, 'getItem');
    getItemSpy.mockClear();
    try {
      const result = await persistHomeSchool('u1-school', staleView);
      expect(result.ok).toBe(false);
      // A fix that only gates the WRITE would still call readUserScopedRaw
      // (a getItem call) to build the merge base before discovering the
      // write itself no-ops — this asserts the read never happens at all.
      expect(getItemSpy).not.toHaveBeenCalled();
    } finally {
      getItemSpy.mockRestore();
    }
  });
});
