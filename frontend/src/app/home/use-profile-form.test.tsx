import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { cleanup, render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { Suspense, useState } from 'react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string) => key,
  }),
}));


const refreshSpy = vi.fn();
const pushSpy = vi.fn();
const prefetchSpy = vi.fn();
const pathnameRef = { current: '/' };
const searchRef = { current: '' };

// Cache the URLSearchParams instance so re-renders with the same query
// string return the same object reference. Without this cache,
// useEffect([searchParams, ...]) treats every render as a new search-
// params and re-fires the mount load, which makes call-count
// assertions (used in the cross-device-sync tests below) impossible.
// Production `useSearchParams()` from next/navigation is already stable.
let cachedParams: URLSearchParams | null = null;
let cachedParamsKey: string | null = null;

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: refreshSpy, push: pushSpy, prefetch: prefetchSpy }),
  useSearchParams: () => {
    if (cachedParamsKey !== searchRef.current) {
      cachedParams = new URLSearchParams(searchRef.current);
      cachedParamsKey = searchRef.current;
    }
    return cachedParams!;
  },
  usePathname: () => pathnameRef.current,
}));

vi.mock('@/lib/api', () => ({
  getStats: () => Promise.resolve({ total: 100, last_updated_at: '2026-04-01T00:00:00Z' }),
  parseGitHubProfile: vi.fn(),
}));

// clearMatchCache reports whether the stale cache was VERIFIABLY removed;
// submit treats that as a gate, so tests need to drive both outcomes.
// The token is part of the signature so a test can answer for the identity it
// was actually handed, rather than rigging an unconditional `true`.
const cacheMocks = vi.hoisted(() => ({
  clearMatchCache: vi.fn((_token?: { uid: string | null; epoch: number; generation: number }) => true),
}));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: cacheMocks.clearMatchCache }));

// R67 problem #4: cross-device profile sync.
//
// `mockLoadProfile` is reassigned per-test so we can simulate the
// "different account / different device" reload (first call returns
// account A's profile, second call returns account B's). Tests fire
// the auth change manually via `authChangeCb`, which is captured the
// moment useProfileForm subscribes.
// Post-CAS the load answers three questions, not one: WHAT the row holds,
// WHICH revision that is, and whether the cloud was even asked. Tests set a
// row via `await cloudRow(...)`; the default is a confirmed-absent row (a brand new
// account), which is what `null` used to stand for.
let mockLoadProfile: () => Promise<LoadedProfile> = () => Promise.resolve(absentRow());
let authChangeCb: ((s: { user: { id: string } | null }) => void) | null = null;
const unsubSpy = vi.fn();

// The hook asks for the real storage status to tell "this device has no
// cloud to sync to" apart from "the cloud write did not land".
let mockStorageStatus: 'synced' | 'local-only' | 'unknown' = 'synced';
// The CAS endpoint, backed by a mutable server row so a sequence of patches
// accumulates exactly as the real one does (027 shallow-merges). Tests read
// `serverRow` to see what actually landed, and `commitProfilePatch.mock.calls`
// to see what was SENT — which, under the patch contract, is the interesting
// half.
let serverRow: Record<string, unknown> | null = null;
let serverRevision = 0;
/** Apply a patch exactly as 027 does and answer with the row it produced:
 *  shallow-merged, revision bumped by one, the WHOLE row echoed back. Every
 *  mock that reports a success goes through here — a hand-written
 *  `{status:'saved', revision:1, profile:{}}` is not an answer the server can
 *  give, and testing the coordinator's merge against one measures nothing. */
function applyIntent(intent: ProfilePatchIntent): ProfilePatchOutcome {
  serverRow = { ...(serverRow ?? {}), ...intent.patch };
  serverRevision += 1;
  return { status: 'saved', revision: serverRevision, profile: serverRow };
}
const defaultCommit = async (intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> => {
  if (intent.expectedRevision !== serverRevision) {
    return serverRow
      ? { status: 'conflict', revision: serverRevision, profile: serverRow }
      : { status: 'missing', reason: 'absent' };
  }
  return await applyIntent(intent);
};
const commitProfilePatch = vi.fn(defaultCommit);

vi.mock('@/lib/supabase', () => ({
  loadProfile: () => mockLoadProfile(),
  commitProfilePatch: (intent: ProfilePatchIntent) => commitProfilePatch(intent),
  getStorageStatus: () => ({ status: mockStorageStatus, error: null }),
  onAuthChange: (cb: (s: { user: { id: string } | null }) => void) => {
    authChangeCb = cb;
    return unsubSpy;
  },
}));

// Partial mock of the coordinator: every export delegates to the real module
// unless a test installs an override. That lets a Home test hand the result
// HANDLERS a legitimate ProfileSaveResult directly — the contract under test —
// instead of trying to coax one out of an end-to-end coordinator run that
// fails closed long before the handler is reached.
const syncOverrides = vi.hoisted(() => ({
  stageProfilePatch: null as null | ((...args: never[]) => unknown),
  refreshConflictQuestion: null as null | ((...args: never[]) => unknown),
  resolveProfileConflict: null as null | ((...args: never[]) => unknown),
  flushPendingProfileWrite: null as null | ((...args: never[]) => unknown),
  hydrateProfile: null as null | ((...args: never[]) => unknown),
  refreshCalls: [] as { keys: string[]; uid: string | null }[],
  stageCalls: 0,
  flushCalls: 0,
}));
vi.mock('@/lib/profile-sync', async (importActual) => {
  const actual = await importActual<typeof import('@/lib/profile-sync')>();
  return {
    ...actual,
    stageProfilePatch: (...args: Parameters<typeof actual.stageProfilePatch>) => {
      syncOverrides.stageCalls += 1;
      return syncOverrides.stageProfilePatch
        ? (syncOverrides.stageProfilePatch as (...a: unknown[]) => unknown)(...args)
        : actual.stageProfilePatch(...args);
    },
    hydrateProfile: (...args: Parameters<typeof actual.hydrateProfile>) => (
      syncOverrides.hydrateProfile
        ? (syncOverrides.hydrateProfile as (...a: unknown[]) => unknown)(...args)
        : actual.hydrateProfile(...args)
    ),
    flushPendingProfileWrite: (...args: Parameters<typeof actual.flushPendingProfileWrite>) => {
      syncOverrides.flushCalls += 1;
      return syncOverrides.flushPendingProfileWrite
        ? (syncOverrides.flushPendingProfileWrite as (...a: unknown[]) => unknown)(...args)
        : actual.flushPendingProfileWrite(...args);
    },
    resolveProfileConflict: (...args: Parameters<typeof actual.resolveProfileConflict>) => (
      syncOverrides.resolveProfileConflict
        ? (syncOverrides.resolveProfileConflict as (...a: unknown[]) => unknown)(...args)
        : actual.resolveProfileConflict(...args)
    ),
    refreshConflictQuestion: (...args: Parameters<typeof actual.refreshConflictQuestion>) => {
      syncOverrides.refreshCalls.push({ keys: [...args[0]], uid: args[1]?.uid ?? null });
      return syncOverrides.refreshConflictQuestion
        ? (syncOverrides.refreshConflictQuestion as (...a: unknown[]) => unknown)(...args)
        : actual.refreshConflictQuestion(...args);
    },
  };
});

import { useProfileForm } from './use-profile-form';
import { SubmitRow } from './SubmitRow';
import {
  advanceOwnerEpoch,
  captureOwnerToken,
  OwnerScopedLoadError,
  isOwnerTokenValid,
  isTokenOwnerStillCurrent,
  isUserScopedStorageKey,
  readUserScopedRaw,
  syncLocalIdentityOwner,
} from '@/lib/identity-owner';
import { DEFAULT_PROFILE } from './types';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import {
  resetProfileDirtyLedger,
  getDirtyProfileKeys,
  HOME_FORM_WRITER,
  hasConfirmedProfileRevision,
  planKeysFromJournalForTests,
  readCurrentConflicts,
  readProfileSyncEnvelope,
  recordProfileIntent,
} from '@/lib/profile-sync';
import {
  appendJournalOp,
  getJournalLineageId,
  readOutstandingOps,
  startDocumentForTests,
  type JournalOp,
} from '@/lib/profile-journal';
import { parseGitHubProfile } from '@/lib/api';
import { HOME_SCHOOL_EVENT, STORAGE_KEYS } from '@/lib/storage-keys';
import { decodeProfileWithKeys, encodeProfile } from '@/lib/profile-share';
import { persistHomeSchool } from '@/lib/school-confirmation';
import { readProfileView, type ProfileViewSnapshot } from '@/lib/profile-sync';

/** The exact object the school switcher handed to the ordered helper. */
let handedToPersist: ProfileViewSnapshot | null = null;

const RESUME = (suggested_interests: string, extracted_skills: string[] = []) => ({
  extracted_skills,
  extracted_coursework: [] as string[],
  experience_level: 'beginner',
  raw_text: 'resume body',
  success: true,
  message: '',
  suggested_interests,
});

// Stable `t` reference to avoid re-firing the mount load effect on each
// render. Without this, useEffect([searchParams, t]) treats every render
// as a deps change because each inline `(k) => k` is a new function.
const stableT = (k: string) => k;

/** A read whose OWNER is captured when it is ISSUED, exactly as production's
 *  loadProfile does. Resolving with a token captured later attributes one
 *  identity's row to whoever happens to be current by then — which the
 *  coordinator correctly refuses as two different rows at one revision, and
 *  which no server can actually produce. */
function deferredLoad(push: (settle: (row: LoadedProfile) => void) => void): Promise<LoadedProfile> {
  const token = captureOwnerToken();
  return new Promise<LoadedProfile>((resolve) => {
    push((row) => resolve({ ...row, token }));
  });
}

function cloudRow(profile: Record<string, unknown>, revision = 1): LoadedProfile {
  serverRow = { ...profile };
  serverRevision = revision;
  return { source: 'cloud', profile: serverRow, revision, token: captureOwnerToken() };
}
function absentRow(): LoadedProfile {
  return { source: 'cloud-absent', profile: null, revision: 0, token: captureOwnerToken() };
}
/**
 * How many operation keys are physically on disk, in ANY generation.
 *
 * The test's own X-ray, not the app's read path. `journalOps()` below goes
 * through the authority, which refuses to enumerate at all while ownership is
 * unconfirmed — correct for production and useless for asserting "this stale
 * screen wrote nothing", which is a claim about bytes.
 */
function rawJournalOpCount(): number {
  let n = 0;
  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i);
    if (key && key.includes(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_`)) n += 1;
  }
  return n;
}

/** The durable operations this form recorded, newest last. */
function journalOps(): JournalOp[] {
  const read = readOutstandingOps();
  if (!read.ok) throw new Error(`journal unreadable: ${read.reason}`);
  return read.value;
}

/** The most recent recorded operation touching `key`. */
/** The journal, or a hard failure. Tests must never silently read `[]` from
 *  a journal this build could not parse. */
function outstandingOps(): JournalOp[] {
  const read = readOutstandingOps();
  if (!read.ok) throw new Error(`journal unreadable: ${read.reason}`);
  return read.value;
}

/** The NEWEST operation touching `key`, by its lineage sequence.
 *
 *  Not by enumeration order: the journal is one storage key per operation and
 *  the ids are uuids, so the order a scan returns them in has nothing to do
 *  with which one the person made last. */
/** Storage that fails exactly the keys `fail` names. Whole-accessor
 *  replacement: jsdom's Storage proxy swallows a spy on the prototype
 *  method, so a spy would silently do nothing. */
function breakStorageFor(fail: (key: string) => boolean) {
  const real = window.localStorage;
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => real.getItem(k),
      setItem: (k: string, v: string) => {
        if (fail(k)) throw new Error('quota');
        real.setItem(k, v);
      },
      removeItem: (k: string) => {
        if (fail(k)) throw new Error('quota');
        real.removeItem(k);
      },
      clear: () => real.clear(),
      key: (i: number) => real.key(i),
      get length() { return real.length; },
    },
  });
  return () => Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
}

function lastOpFor(key: string, lineage?: string): JournalOp | undefined {
  const touching = journalOps()
    .filter((o) => o.fields.some((f) => f.key === key))
    .filter((o) => lineage === undefined || o.lineage === lineage);
  if (touching.length === 0) return undefined;
  const lineages = new Set(touching.map((o) => o.lineage));
  if (lineages.size > 1) {
    // `seq` only orders operations WITHIN a lineage. Picking one across
    // lineages would be picking whichever the scan happened to return first,
    // and a test built on that is testing enumeration order.
    throw new Error(
      `await lastOpFor(${key}): ${lineages.size} lineages present — name the one you mean`,
    );
  }
  return touching.reduce((newest, op) => (op.seq > newest.seq ? op : newest), touching[0]);
}

/** Every patch the form actually sent, in order. */
function sentPatches(): Record<string, unknown>[] {
  return commitProfilePatch.mock.calls.map((c) => c[0].patch);
}

function TestHarness() {
  const form = useProfileForm(stableT);
  return (
    <div>
      <span data-testid="grade">{form.profile.grade}</span>
      <span data-testid="seeking">{(form.profile.seeking_types ?? []).join(',')}</span>
    </div>
  );
}

function Wrapped() {
  return (
    <Suspense fallback={null}>
      <TestHarness />
    </Suspense>
  );
}

/**
 * Fills the fields a row cannot be CREATED without.
 *
 * The tests below are about identity and races, not about what makes a
 * profile worth storing — but a create from a form whose major and grade are
 * still blank is refused by design, on this side and by migration 027 alike.
 * They say so in one line rather than nine.
 */
function seedCreatableProfile() {
  fireEvent.click(screen.getByTestId('make-valid'));
}

/**
 * Fills the fields a create needs, WITHOUT touching college.
 *
 * Changing the college deliberately clears the major (see AcademicProfileCard
 * — a major from the old school is meaningless at the new one), so a test
 * that switches college and then expects a row to be created has to say what
 * the major became. Called AFTER that click for exactly that reason.
 */
function completeRequiredAfterCollegeChange() {
  fireEvent.click(screen.getByTestId('seed-required'));
}

// The identity every test starts under. PROFILE is a USER_SCOPED key, so
// none of the hook's writes land until identity-owner has actually claimed
// this browser for a uid — exactly what production's auth choke points do
// before any screen renders.
const HOME_UID = 'home-form-u1';

/** Fire an auth observation the way production does: lib/supabase.ts's
 *  onAuthChange wrapper advances the shared owner epoch and runs the
 *  local-owner sync BEFORE invoking subscribers, so a subscriber that
 *  captures an owner token during the event already sees the new identity. */
/** One auth event, start to finish. The epoch fence is synchronous — every
 *  reader is blocked the instant it lands — but the namespace transition runs
 *  under the private-storage lock, so subscribers are notified only once this
 *  browser's data is confirmed for the new owner, exactly as production does. */
async function emitAuth(uid: string | null) {
  await act(async () => {
    advanceOwnerEpoch(uid);
    if (uid) await syncLocalIdentityOwner(uid);
    authChangeCb?.({ user: uid ? { id: uid } : null });
  });
}

// Every temporary Storage spy registers here, so a failed assertion can never
// leave one installed and take the NEXT test down with it.
const storageSpies: { mockRestore: () => void }[] = [];
function registerSpy<T extends { mockRestore: () => void }>(spy: T): T {
  storageSpies.push(spy);
  return spy;
}
afterEach(async () => {
  while (storageSpies.length > 0) storageSpies.pop()!.mockRestore();
});

beforeEach(async () => {
  syncOverrides.stageProfilePatch = null;
  syncOverrides.refreshConflictQuestion = null;
  syncOverrides.resolveProfileConflict = null;
  syncOverrides.flushPendingProfileWrite = null;
  syncOverrides.hydrateProfile = null;
  syncOverrides.refreshCalls = [];
  syncOverrides.stageCalls = 0;
  syncOverrides.flushCalls = 0;
  // jsdom has no Web Locks; every browser this ships to does. The coordinator
  // takes one around each read-decide-write of shared local state, so without
  // a serial fake here every save reports device-failed and these tests would
  // be measuring the environment gap instead of the hook. The genuine
  // "no lock manager" path has its own test in profile-journal.test.ts.
  let lockChain: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, 'locks', {
    configurable: true,
    value: {
      request: (_name: string, _opts: unknown, fn: () => Promise<unknown>) => {
        const run = lockChain.then(() => fn());
        lockChain = run.then(() => undefined, () => undefined);
        return run;
      },
    },
  });
  refreshSpy.mockReset();
  pushSpy.mockReset();
  prefetchSpy.mockReset();
  searchRef.current = '';
  cachedParams = null;
  cachedParamsKey = null;
  mockLoadProfile = () => Promise.resolve(absentRow());
  mockStorageStatus = 'synced';
  authChangeCb = null;
  unsubSpy.mockReset();
  localStorage.clear();
  cacheMocks.clearMatchCache.mockReset();
  cacheMocks.clearMatchCache.mockReturnValue(true);
  // The CAS fake and the coordinator both hold module state — a revision
  // left over from the previous test would make the next one's load and its
  // saves disagree about what the server holds.
  serverRow = null;
  serverRevision = 0;
  commitProfilePatch.mockReset();
  commitProfilePatch.mockImplementation(defaultCommit);
  resetProfileDirtyLedger();
  advanceOwnerEpoch(null);
  advanceOwnerEpoch(HOME_UID);
  await syncLocalIdentityOwner(HOME_UID);
});

describe('useProfileForm — prefill from URL', () => {
  it('does not prefill anything when no prefill_* params present', async () => {
    searchRef.current = '';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe(''));
  });

  it('prefills grade when prefill_year is a valid grade', async () => {
    searchRef.current = 'prefill_year=Junior';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Junior'));
  });

  it('ignores invalid prefill_year values', async () => {
    searchRef.current = 'prefill_year=PostDoc';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe(''));
  });

  it('prefills seeking_types when prefill_seeking is valid', async () => {
    searchRef.current = 'prefill_seeking=summer_program';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('seeking').textContent).toContain('summer_program'));
  });

  it('ignores invalid prefill_seeking values', async () => {
    searchRef.current = 'prefill_seeking=internship_extreme';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('seeking').textContent).toBe(''));
  });

  it('applies both prefill_year and an accepted prefill_seeking when present', async () => {
    searchRef.current = 'prefill_year=Senior&prefill_seeking=internship';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Senior'));
    expect(screen.getByTestId('seeking').textContent).toContain('internship');
  });

  it('ignores the dormant fellowship prefill', async () => {
    searchRef.current = 'prefill_seeking=fellowship';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('seeking').textContent).toBe(''));
  });

  it('removes a stale fellowship preference from a stored profile', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ seeking_types: ['research', 'fellowship'] }));
    render(<Wrapped />);
    await waitFor(() =>
      expect(screen.getByTestId('seeking').textContent).toBe('research'),
    );
  });

  it('removes a stale fellowship preference from a shared profile', async () => {
    const share = encodeProfile({
      ...DEFAULT_PROFILE,
      seeking_types: ['internship', 'fellowship'],
    });
    searchRef.current = `share=${share}`;
    render(<Wrapped />);
    await waitFor(() =>
      expect(screen.getByTestId('seeking').textContent).toBe('internship'),
    );
  });
});

function FullHarness() {
  const form = useProfileForm(stableT);
  return (
    <div>
      <span data-testid="college">{form.profile.college}</span>
      <button data-testid="pick-college" onClick={() => form.update('college', 'Grainger')}>college</button>
      <span data-testid="interests">{form.profile.research_interests}</span>
      <button data-testid="parseA" onClick={() => form.handleResumeParsed(RESUME('computer vision, machine learning'))}>A</button>
      <button data-testid="parseB" onClick={() => form.handleResumeParsed(RESUME('robotics'))}>B</button>
      <button data-testid="set-gh" onClick={() => form.update('github_url', 'https://github.com/octocat')}>set</button>
      <button data-testid="set-skill" onClick={() => form.update('skills', [{ name: 'Rust', level: 'expert' }])}>skill</button>
      <button data-testid="make-valid" onClick={() => form.setProfile((p) => ({ ...p, college: 'Grainger', major: 'CS', grade: 'Junior' }))}>valid</button>
      <button data-testid="seed-required" onClick={() => form.setProfile((p) => ({ ...p, major: 'CS', grade: 'Junior' }))}>seed</button>
      <button data-testid="submit" onClick={() => { void form.handleSubmit(); }}>submit</button>
    </div>
  );
}

describe('useProfileForm — the very first visit is not stranded', () => {
  /**
   * FV-1. Found in a real browser, not here: on a first visit the college
   * dropdown enables as soon as the school catalog lands, which is BEFORE the
   * anonymous sign-in has resolved. A load issued in that window freezes a
   * screen origin holding the unresolved `{uid: null, epoch: 0}` token. The
   * first identity resolution then advances the epoch, `ownsScreen` rejects
   * that origin forever, and `update()` — which returns early on a null
   * editing origin — DROPS every keystroke in silence. The controlled input
   * shows the value for one paint and snaps back.
   *
   * Nothing of anyone else's is on screen in that window: there is no accepted
   * view and the held origin never named a real account. So the keystroke
   * belongs to whoever is at the keyboard, which is exactly what
   * `editingOrigin`'s own contract says about a screen with "no older rendered
   * document to speak for".
   */
  it('FV-1: an edit made before the first identity resolves survives the hydration that follows', async () => {
    render(<Suspense fallback={null}><FullHarness /></Suspense>);

    // The visitor types while the browser still has no identity — the exact
    // window the catalog opens the dropdown in.
    fireEvent.click(screen.getByTestId('pick-college'));
    expect(screen.getByTestId('college').textContent, 'accepted on the spot').toBe('Grainger');

    // The browser's first identity arrives and the row is hydrated behind it.
    await emitAuth(HOME_UID);
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });

    expect(
      screen.getByTestId('college').textContent,
      'the first thing a visitor types must not be thrown away',
    ).toBe('Grainger');
  });

  /**
   * FV-2, the control that keeps FV-1 honest. A screen whose owner really
   * moved on mid-flight must still fail closed — re-anchoring THERE is the
   * cross-account write the whole capability chain exists to prevent.
   */
  it('FV-2: a keystroke from a screen whose owner moved on is still refused', async () => {
    render(<Suspense fallback={null}><FullHarness /></Suspense>);
    await emitAuth(HOME_UID);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    // U1's screen, mid-typing, when the owner is replaced underneath it. No
    // hydration is allowed to land for U2 before the stale keystroke arrives:
    // that is the window the fence has to hold.
    await act(async () => { advanceOwnerEpoch('home-form-u2'); });
    const before = screen.getByTestId('college').textContent;
    fireEvent.click(screen.getByTestId('pick-college'));

    expect(
      screen.getByTestId('college').textContent,
      "a superseded screen may not write into the new owner's document",
    ).toBe(before);
  });
});

describe('useProfileForm — resume seeds the interests box (PR5 ①)', () => {
  it('prefills research_interests from the resume when the box is empty', async () => {
    render(<Suspense fallback={null}><FullHarness /></Suspense>);
    fireEvent.click(screen.getByTestId('parseA'));
    await waitFor(() =>
      expect(screen.getByTestId('interests').textContent).toBe('computer vision, machine learning'),
    );
  });

  it('does NOT overwrite interests the user already has', async () => {
    render(<Suspense fallback={null}><FullHarness /></Suspense>);
    fireEvent.click(screen.getByTestId('parseA')); // seeds it
    await waitFor(() =>
      expect(screen.getByTestId('interests').textContent).toBe('computer vision, machine learning'),
    );
    fireEvent.click(screen.getByTestId('parseB')); // must not clobber
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.getByTestId('interests').textContent).toBe('computer vision, machine learning');
  });
});

describe('useProfileForm — GitHub auto-import on submit (PR5 ②)', () => {
  it('imports an un-imported GitHub URL and merges its skills into the saved profile', async () => {
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [],
    });
    render(<Suspense fallback={null}><FullHarness /></Suspense>);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); }); // let the row settle
    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(parseGitHubProfile).toHaveBeenCalledWith('octocat');
    expect(commitProfilePatch).toHaveBeenCalledWith(
      expect.objectContaining({
        patch: expect.objectContaining({
          skills: expect.arrayContaining([expect.objectContaining({ name: 'Go' })]),
        }),
        token: expect.objectContaining({ uid: HOME_UID }),
      }),
    );
    expect(pushSpy).toHaveBeenCalledWith('/results');
  });

  it('submit-then-unmount keeps the imported skills (stale pending save must not clobber)', async () => {
    // Regression: editing github_url arms the debounced auto-save with the
    // PRE-import profile. handleSubmit cleared the timer but left the ref, so
    // the unmount flush re-saved that stale snapshot over the merged skills.
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [],
    });
    commitProfilePatch.mockClear();
    const { unmount } = render(<Suspense fallback={null}><FullHarness /></Suspense>);
    await act(async () => { await new Promise((r) => setTimeout(r, 550)); });
    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh')); // arms the debounced save WITHOUT Go
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 30));
    });
    unmount();
    const calls = commitProfilePatch.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const lastSaved = calls[calls.length - 1][0].patch as { skills: Array<{ name: string }> };
    expect(lastSaved.skills).toEqual(
      expect.arrayContaining([expect.objectContaining({ name: 'Go' })]),
    );
  });
});

describe('useProfileForm — skill levels persist through the save path', () => {
  it('handleSubmit saves skills with their levels to supabase and localStorage', async () => {
    commitProfilePatch.mockClear();
    render(<Suspense fallback={null}><FullHarness /></Suspense>);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); }); // let the row settle
    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-skill'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(commitProfilePatch).toHaveBeenCalledWith(
      expect.objectContaining({
        patch: expect.objectContaining({ skills: [{ name: 'Rust', level: 'expert' }] }),
        token: expect.objectContaining({ uid: HOME_UID }),
      }),
    );
    const stored = JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!);
    expect(stored.skills).toEqual([{ name: 'Rust', level: 'expert' }]);
    expect(pushSpy).toHaveBeenCalledWith('/results');
  });
});

function SchoolHarness() {
  const form = useProfileForm(stableT);
  return (
    <div>
      <span data-testid="home-school">{form.profile.home_school ?? ''}</span>
      <span data-testid="college">{form.profile.college}</span>
      <span data-testid="major">{form.profile.major}</span>
      <button data-testid="switch-ucb" onClick={() => form.update('home_school', 'ucb')}>switch</button>
      <button data-testid="switch-uiuc" onClick={() => form.update('home_school', 'uiuc')}>switch back</button>
      <button data-testid="switch-future" onClick={() => form.update('home_school', 'future-school')}>switch future</button>
      <button data-testid="set-college" onClick={() => form.update('college', 'College of Engineering')}>college</button>
      <button data-testid="set-major" onClick={() => form.update('major', 'EECS')}>major</button>
    </div>
  );
}

describe('useProfileForm — home_school (university switcher)', () => {
  it('defaults home_school to uiuc on a fresh profile', async () => {
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('home-school').textContent).toBe('uiuc'));
  });

  it('backward compat: a stored profile without home_school keeps working as uiuc', async () => {
    // Pre-switcher profile shape — no home_school key at all.
    mockLoadProfile = () => Promise.resolve(cloudRow({
      college: 'Grainger College of Engineering',
      major: 'Computer Science',
      grade: 'Freshman',
    }));
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('college').textContent).toBe('Grainger College of Engineering'));
    expect(screen.getByTestId('home-school').textContent).toBe('uiuc');
    expect(screen.getByTestId('major').textContent).toBe('Computer Science');
  });

  it('loads a stored home_school and persists a switch through the save path', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ home_school: 'ucb' }));
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('home-school').textContent).toBe('ucb'));
  });

  it('applies a campus chosen via the onboarding gate event after the form already mounted', async () => {
    // Reproduces the gate hand-off: the form mounts + loads (default uiuc)
    // before the tour finishes, so only the live window event updates it.
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('home-school').textContent).toBe('uiuc'));
    act(() => {
      window.dispatchEvent(new CustomEvent(HOME_SCHOOL_EVENT, { detail: 'ucb' }));
    });
    expect(screen.getByTestId('home-school').textContent).toBe('ucb');
  });

  it('switching schools updates home_school without clobbering college/major', async () => {
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('home-school').textContent).toBe('uiuc'));
    fireEvent.click(screen.getByTestId('set-college'));
    fireEvent.click(screen.getByTestId('set-major'));
    fireEvent.click(screen.getByTestId('switch-ucb'));
    expect(screen.getByTestId('home-school').textContent).toBe('ucb');
    expect(screen.getByTestId('college').textContent).toBe('College of Engineering');
    expect(screen.getByTestId('major').textContent).toBe('EECS');
  });

  it('college edits clear the major under any school catalog, not in free-text mode', async () => {
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('home-school').textContent).toBe('uiuc'));
    // Catalog mode (UIUC): picking a college resets the cascaded major.
    fireEvent.click(screen.getByTestId('set-major'));
    fireEvent.click(screen.getByTestId('set-college'));
    expect(screen.getByTestId('major').textContent).toBe('');
    // Catalog mode (UCB — shipped in this PR): same cascading reset.
    fireEvent.click(screen.getByTestId('switch-ucb'));
    fireEvent.click(screen.getByTestId('set-major'));
    fireEvent.click(screen.getByTestId('set-college'));
    expect(screen.getByTestId('major').textContent).toBe('');
    // Free-text mode (a school with no catalog yet): college keystrokes
    // must NOT wipe the major the user typed.
    fireEvent.click(screen.getByTestId('switch-future'));
    fireEvent.click(screen.getByTestId('set-major'));
    fireEvent.click(screen.getByTestId('set-college'));
    expect(screen.getByTestId('major').textContent).toBe('EECS');
  });
});

// R67 problem #4: when the auth session transitions on this device
// (anon → permanent via magic-link convert, or one signed-in account
// → a different signed-in account), the form must re-fetch the
// profile under the NEW auth.uid() so the user sees their own data,
// not a stale snapshot from before sign-in.// R67 problem #4 + C1-R2B: when the auth session transitions on this device
// (anon → permanent via magic-link convert, or one signed-in account
// → a different signed-in account), the form must re-fetch the profile
// under the NEW auth.uid() so the user sees their own data, not a stale
// snapshot from before sign-in — and nothing the previous identity left
// behind (profile fields, search weight, GitHub receipt, debounced save)
// may survive into the new one's session.
function IdentityHarness() {
  const form = useProfileForm(stableT);
  return (
    <div>
      <span data-testid="grade">{form.profile.grade}</span>
      <span data-testid="college">{form.profile.college}</span>
      <span data-testid="weight">{form.searchWeight}</span>
      <span data-testid="save-status">{form.saveStatus}</span>
      <span data-testid="hydration">{form.hydrationState}</span>
      <span data-testid="submitting">{form.isSubmitting ? 'yes' : 'no'}</span>
      <span data-testid="valid">{form.isValid ? 'yes' : 'no'}</span>
      <span data-testid="conflict-keys">{form.conflictKeys.join(',')}</span>
      <span data-testid="conflict-revs">
        {form.conflicts.map((c) => `${c.key}@${c.remoteRevision}`).join(',')}
      </span>
      <span data-testid="view-uid">{form.viewSnapshot ? String(form.viewSnapshot.token.uid) : 'none'}</span>
      <span data-testid="view-epoch">{form.viewSnapshot ? String(form.viewSnapshot.token.epoch) : 'none'}</span>
      <span data-testid="view-rev">{form.viewSnapshot ? String(form.viewSnapshot.revision) : 'none'}</span>
      <span data-testid="view-base-has-school">
        {form.viewSnapshot && form.viewSnapshot.baseProfile
          ? String(Object.hasOwn(form.viewSnapshot.baseProfile, 'home_school'))
          : 'none'}
      </span>
      <span data-testid="view-base-major">
        {form.viewSnapshot ? String(form.viewSnapshot.baseProfile?.major ?? 'absent') : 'none'}
      </span>
      <span data-testid="view-base-school">
        {form.viewSnapshot
          ? String(form.viewSnapshot.baseProfile?.home_school ?? 'absent')
          : 'none'}
      </span>
      <span data-testid="view-rendered-school">
        {form.viewSnapshot ? String(form.viewSnapshot.renderedProfile.home_school) : 'none'}
      </span>
      <span data-testid="view-rendered-weight">
        {form.viewSnapshot ? String(form.viewSnapshot.renderedProfile.search_weight) : 'none'}
      </span>
      <span data-testid="view-rendered-major">
        {form.viewSnapshot ? String(form.viewSnapshot.renderedProfile.major) : 'none'}
      </span>
      <span data-testid="view-base-skills">
        {form.viewSnapshot
          ? JSON.stringify(form.viewSnapshot.baseProfile?.skills ?? null)
          : 'none'}
      </span>
      <button data-testid="keep-mine" onClick={() => form.keepMyChanges()}>keep</button>
      <button data-testid="use-cloud" onClick={() => form.useCloudVersion()}>cloud</button>
      <button data-testid="keep-grade" onClick={() => form.keepMyChanges(['grade'])}>keep grade</button>
      <button data-testid="cloud-grade" onClick={() => form.useCloudVersion(['grade'])}>cloud grade</button>
      <span data-testid="coursework-view">{(form.profile.coursework ?? []).join(',')}</span>
      <button data-testid="set-coursework" onClick={() => form.update('coursework', ['CS 225'])}>cw</button>
      <span data-testid="gh-url">{form.profile.github_url ?? ''}</span>
      <span data-testid="shared-banner">{form.sharedBanner ?? ''}</span>
      <span data-testid="gh-status">{form.ghStatus ?? ''}</span>
      <span data-testid="gh-loading">{form.ghLoading ? 'yes' : 'no'}</span>
      <span data-testid="skills">{form.profile.skills.map((s) => s.name).join(',')}</span>
      <span data-testid="major">{form.profile.major}</span>
      <span data-testid="extra-majors">{(form.profile.additional_majors ?? []).join(',')}</span>
      <span data-testid="interests">{form.profile.research_interests}</span>
      <button data-testid="set-college" onClick={() => form.update('college', 'Grainger')}>c</button>
      <button data-testid="retry-sync" onClick={() => form.retryCloudSave()}>retry</button>
      <button data-testid="set-interests" onClick={() => form.update('research_interests', 'my interests')}>ri</button>
      <button data-testid="set-weight" onClick={() => form.setSearchWeight(90)}>w</button>
      <button data-testid="touch-weight" onClick={() => form.setSearchWeight(form.searchWeight)}>touch w</button>
      <button data-testid="set-gh" onClick={() => form.update('github_url', 'https://github.com/octocat')}>g</button>
      <button data-testid="set-gh2" onClick={() => form.update('github_url', 'https://github.com/hubot')}>g2</button>
      <button data-testid="clear-gh" onClick={() => form.update('github_url', '')}>clear g</button>
      <button data-testid="gh-import" onClick={() => { void form.handleGitHubImport(); }}>i</button>
      <button data-testid="make-valid" onClick={() => form.setProfile((p) => ({ ...p, college: 'Grainger', major: 'CS', grade: 'Junior' }))}>valid</button>
      <button data-testid="seed-required" onClick={() => form.setProfile((p) => ({ ...p, major: 'CS', grade: 'Junior' }))}>seed</button>
      <button data-testid="clear-major" onClick={() => form.update('major', '')}>clear major</button>
      <button data-testid="set-major-ece" onClick={() => form.update('major', 'ECE')}>ece</button>
      <button data-testid="set-major-physics" onClick={() => form.update('major', 'Physics')}>phys</button>
      <button data-testid="set-grade-senior" onClick={() => form.update('grade', 'Senior')}>senior</button>
      <button
        data-testid="switch-school"
        onClick={() => {
          // Exactly what AcademicProfileCard does: hand the ordered helper the
          // view snapshot this form published, and nothing else.
          handedToPersist = form.viewSnapshot;
          void persistHomeSchool('ucb', form.viewSnapshot!, { confirm: true });
        }}
      >switch</button>
      <button data-testid="submit" onClick={() => { void form.handleSubmit(); }}>s</button>
      <span data-testid="share-copied">{form.shareCopied ? 'yes' : 'no'}</span>
      <button data-testid="share" onClick={() => { void form.handleShare(); }}>share</button>
      <span data-testid="resume">{form.profile.resume_text ?? ''}</span>
      <button data-testid="remove-resume" onClick={() => form.handleResumeRemoved()}>rm</button>
      <button
        data-testid="replace-skills"
        onClick={() => form.update('skills', [{ name: 'Rust', level: 'expert' }])}
      >skills</button>
    </div>
  );
}

function GhLoadingHarness() {
  const form = useProfileForm(stableT);
  return (
    <div>
      <span data-testid="gh-loading">{form.ghLoading ? 'yes' : 'no'}</span>
      <span data-testid="skills">{form.profile.skills.map((s) => s.name).join(',')}</span>
      <button data-testid="set-gh" onClick={() => form.update('github_url', 'https://github.com/octocat')}>g</button>
      <button data-testid="set-gh2" onClick={() => form.update('github_url', 'https://github.com/hubot')}>g2</button>
      <button data-testid="gh-import" onClick={() => { void form.handleGitHubImport(); }}>i</button>
    </div>
  );
}

function ResumeRemovalHarness() {
  const form = useProfileForm(stableT);
  return (
    <div>
      <span data-testid="resume">{form.profile.resume_text ?? ''}</span>
      <span data-testid="coursework">{(form.profile.coursework ?? []).join(',')}</span>
      <span data-testid="skills">{form.profile.skills.map((s) => s.name).join(',')}</span>
      <span data-testid="interests">{form.profile.research_interests}</span>
      <span data-testid="save-status">{form.saveStatus}</span>
      <button data-testid="remove-resume" onClick={() => form.handleResumeRemoved()}>remove</button>
      <button data-testid="retry-sync" onClick={() => form.retryCloudSave()}>retry</button>
      <button data-testid="edit-interests" onClick={() => form.update('research_interests', 'later edit')}>edit</button>
    </div>
  );
}

function renderIdentityHarness() {
  return render(<Suspense fallback={null}><IdentityHarness /></Suspense>);
}

// Mirrors what a child component holds: the callback reference it was
// handed on the render it started its own async work under. "hold" is the
// moment the user dropped their PDF; "fire-held" is that parse resolving.
function ResumeIdentityHarness() {
  const form = useProfileForm(stableT);
  const [held, setHeld] = useState<((d: ReturnType<typeof RESUME>) => void) | null>(null);
  return (
    <div>
      <span data-testid="interests">{form.profile.research_interests}</span>
      <span data-testid="resume">{form.profile.resume_text ?? ''}</span>
      <span data-testid="generation">{form.identityGeneration}</span>
      <span data-testid="skills">{form.profile.skills.map((sk) => sk.name).join(',')}</span>
      <span data-testid="save-status">{form.saveStatus}</span>
      <span data-testid="view-rev">{form.viewSnapshot ? String(form.viewSnapshot.revision) : 'none'}</span>
      <button data-testid="hold" onClick={() => setHeld(() => form.handleResumeParsed)}>hold</button>
      <button data-testid="fire-held" onClick={() => held?.(RESUME('u1 interests'))}>fire held</button>
      <button data-testid="fire-current" onClick={() => form.handleResumeParsed(RESUME('u2 interests'))}>fire current</button>
      <button data-testid="fire-held-pytorch" onClick={() => held?.(RESUME('u1 interests', ['PyTorch']))}>fire held pytorch</button>
      <button data-testid="fire-current-keras" onClick={() => form.handleResumeParsed(RESUME('u2 interests', ['Keras']))}>fire current keras</button>
    </div>
  );
}

describe('useProfileForm — cross-device sync via onAuthChange', () => {
  it('subscribes to onAuthChange on mount and unsubscribes on unmount', async () => {
    mockLoadProfile = () => Promise.resolve(absentRow());
    const { unmount } = render(<Wrapped />);
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    expect(unsubSpy).not.toHaveBeenCalled();
    unmount();
    expect(unsubSpy).toHaveBeenCalledTimes(1);
  });

  it('treats the FIRST auth observation as a real identity event: a mount load still in flight is dropped and the live identity reloads', async () => {
    // The mount load starts before ANY identity is confirmed, so "the mount
    // effect already handled this uid" was never knowable. Here the first
    // live event announces a DIFFERENT identity than the one the mount load
    // is resolving under.
    const resolvers: Array<(v: LoadedProfile) => void> = [];
    mockLoadProfile = () => deferredLoad((settle) => resolvers.push(settle));
    await renderIdentityHarness();
    await waitFor(() => expect(resolvers).toHaveLength(1));

    await emitAuth('identity-u2');
    await waitFor(() => expect(resolvers).toHaveLength(2));

    // U1's load finally resolves — after the switch. It must write nothing.
    await act(async () => { resolvers[0](await cloudRow({ grade: 'Junior', college: 'U1 College' })); });
    expect(screen.getByTestId('grade').textContent).toBe('');
    expect(screen.getByTestId('college').textContent).toBe('');

    await act(async () => { resolvers[1](await cloudRow({ grade: 'Senior' })); });
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Senior'));
  });

  it('a first observation whose own load returns null still resets the form and reloads under the new identity', async () => {
    let calls = 0;
    mockLoadProfile = () => {
      calls += 1;
      return Promise.resolve(calls === 1 ? cloudRow({ grade: 'Junior', college: 'U1 College' }) : absentRow());
    };
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Junior'));

    // Confirmed-null new owner: the reload returns nothing, so ONLY the
    // synchronous reset stands between U1's profile and U2's screen.
    await emitAuth(null);
    await waitFor(() => expect(calls).toBe(2));
    expect(screen.getByTestId('grade').textContent).toBe('');
    expect(screen.getByTestId('college').textContent).toBe('');
  });

  it('resets profile, search weight, save status and GitHub status in the identity event\'s own tick', async () => {
    // Every reset assertion below has to be preceded by a REAL non-default
    // value, or dropping the corresponding reset would still look green.
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [],
    });
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    // Let the first load settle so edits actually arm a save (before that
    // they are buffered, by design — see the hydration tests).
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    fireEvent.click(screen.getByTestId('set-college'));
    fireEvent.click(screen.getByTestId('set-weight'));
    fireEvent.click(screen.getByTestId('set-gh'));
    await act(async () => { fireEvent.click(screen.getByTestId('gh-import')); });
    await waitFor(() => expect(screen.getByTestId('gh-status').textContent).toContain('githubImportSuccess'));
    // A real armed debounce, so 'saving' is genuinely on screen.
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saving'));
    expect(screen.getByTestId('college').textContent).toBe('Grainger');
    expect(screen.getByTestId('weight').textContent).toBe('90');

    await emitAuth('identity-u2');

    expect(screen.getByTestId('college').textContent).toBe('');
    expect(screen.getByTestId('weight').textContent).toBe('50');
    expect(screen.getByTestId('save-status').textContent).toBe('idle');
    expect(screen.getByTestId('gh-status').textContent).toBe('');
  });

  it('drops the previous identity\'s GitHub import receipt: the same URL is imported again for the new one', async () => {
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [],
    });
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    fireEvent.click(screen.getByTestId('set-gh'));
    await act(async () => { fireEvent.click(screen.getByTestId('gh-import')); });
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(1));

    await emitAuth('identity-u2');
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); }); // U2's row settles
    fireEvent.click(screen.getByTestId('make-valid'));

    // U2 pastes the SAME url: the receipt was U1's, so submit must import
    // it again instead of treating those skills as already merged.
    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(parseGitHubProfile).toHaveBeenCalledTimes(2);
  });

  it('U1 → U2 → U3: U2\'s late load never overwrites U3', async () => {
    const resolvers: Array<(v: LoadedProfile) => void> = [];
    mockLoadProfile = () => deferredLoad((settle) => resolvers.push(settle));
    await renderIdentityHarness();
    await waitFor(() => expect(resolvers).toHaveLength(1)); // mount

    await emitAuth('identity-u2');
    await waitFor(() => expect(resolvers).toHaveLength(2));
    await emitAuth('identity-u3');
    await waitFor(() => expect(resolvers).toHaveLength(3));

    await act(async () => { resolvers[2](await cloudRow({ grade: 'Freshman' })); }); // U3 lands first
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Freshman'));
    await act(async () => { resolvers[1](await cloudRow({ grade: 'PhD', college: 'U2 College' })); }); // U2 late
    expect(screen.getByTestId('grade').textContent).toBe('Freshman');
    expect(screen.getByTestId('college').textContent).toBe('');
  });

  it('reloads under the new identity with a DEFAULT merge, never carrying the previous identity\'s fields forward', async () => {
    let calls = 0;
    mockLoadProfile = () => {
      calls += 1;
      return Promise.resolve(
        calls === 1
          ? cloudRow({ grade: 'Junior', college: 'U1 College', research_interests: 'u1 interests' })
          : cloudRow({ grade: 'Senior' }),
      );
    };
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('college').textContent).toBe('U1 College'));

    await emitAuth('identity-u2');
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Senior'));
    // U2's own row defines only `grade`; every other field must be the
    // default, not whatever U1's row happened to hold.
    expect(screen.getByTestId('college').textContent).toBe('');
  });

  it('a same-uid re-observation (TOKEN_REFRESHED) is not a transition: no reset, no reload', async () => {
    let calls = 0;
    mockLoadProfile = () => { calls += 1; return Promise.resolve(absentRow()); };
    await renderIdentityHarness();
    await waitFor(() => expect(calls).toBe(1));
    await emitAuth('identity-u2');
    await waitFor(() => expect(calls).toBe(2));
    fireEvent.click(screen.getByTestId('set-college'));

    await emitAuth('identity-u2'); // token refresh for the SAME identity
    await new Promise((r) => setTimeout(r, 20));

    expect(calls).toBe(2);
    expect(screen.getByTestId('college').textContent).toBe('Grainger');
  });

  it('drops the previous identity\'s pending save: the unmount flush never persists it under the new owner', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    const { unmount } = await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 550)); });
    fireEvent.click(screen.getByTestId('set-college')); // arms the debounced save as U1
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saving'));

    await emitAuth('identity-u2');
    unmount();

    const savedColleges = commitProfilePatch.mock.calls.map(
      (c) => (c[0] as { college?: string }).college,
    );
    expect(savedColleges).not.toContain('Grainger');
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
  });

  it('a GitHub import that resolves after an identity switch writes no skills, no status and no import receipt', async () => {
    let resolveImport: ((v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void) | undefined;
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolveImport = resolve as never; }),
    );
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('gh-import'));
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(1));

    await emitAuth('identity-u2');
    await act(async () => {
      resolveImport?.({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
    });

    expect(screen.getByTestId('skills').textContent).toBe('');
    expect(screen.getByTestId('gh-status').textContent).toBe('');
    // The reset released the spinner: the request-id bump means the stale
    // import's own `finally` deliberately will not.
    expect(screen.getByTestId('gh-loading').textContent).toBe('no');
    // The receipt is the third write: had it landed, U2's own submit would
    // consider this URL already imported and silently skip it.
    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('submit'));
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(2));
  });
});

describe('useProfileForm — an edit is recorded against the view the user was LOOKING AT', () => {
  it('A shows rev7/CS, B lands rev8/Physics, A types ECE: the operation is based on CS at rev7', async () => {
    // Tab A hydrates: major 'CS' at revision 7.
    mockLoadProfile = () => Promise.resolve(cloudRow({ major: 'CS', grade: 'Junior' }, 7));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('major').textContent).toBe('CS'));
    expect(screen.getByTestId('view-rev').textContent).toBe('7');

    // Tab B saves 'Physics' at revision 8. A has NOT accepted it — nothing on
    // A's screen changed, and A is still looking at 'CS'.
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: { revision: 8, profile: { major: 'Physics', grade: 'Junior' } },
      pending: null,
      tombstone: null,
    }));

    // A now types over what A can see.
    act(() => { screen.getByTestId('set-major-ece').click(); });

    const op = await lastOpFor('major');
    expect(op, 'the edit was recorded durably').toBeTruthy();
    const field = op!.fields.find((f) => f.key === 'major')!;
    // The base is what A SAW. Taking it from the newest shared envelope would
    // record base 'Physics' at revision 8 — an operation that claims A was
    // editing B's value, which then CASes cleanly straight over B.
    expect(field.base).toEqual({ present: true, value: 'CS' });
    expect(field.desired).toEqual({ present: true, value: 'ECE' });
    expect(op!.baseRevision).toBe(7);
    expect(op!.baseRevision, 'never the revision A never saw').not.toBe(8);
  });
});

describe('useProfileForm — an edit belongs to the screen that made it', () => {
  it('the global owner moves to U2 before this hook hears about it: a click on the still-mounted U1 screen writes NOTHING', async () => {
    // U1's row is in a slow load, so no view has been accepted yet. Another
    // auth subscriber (the header, the account menu) advances the shared
    // owner primitive first; this hook's own callback has not run, so the U1
    // DOM is still mounted and still takes clicks.
    commitProfilePatch.mockClear();
    let resolveLoad: ((v: LoadedProfile) => void) | undefined;
    mockLoadProfile = () => deferredLoad((settle) => { resolveLoad = settle; });
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    expect(screen.getByTestId('view-uid').textContent).toBe('none');

    const before = rawJournalOpCount();
    act(() => { advanceOwnerEpoch('loading-origin-u2'); syncLocalIdentityOwner('loading-origin-u2'); });

    // The discrete edit lands on U1's screen.
    act(() => { screen.getByTestId('set-interests').click(); });

    // Nothing durable, nothing sent. Capturing the owner at click time would
    // return a perfectly valid U2 token and write U1's intent into U2's
    // journal, where every later preflight would wave it through.
    expect(rawJournalOpCount()).toBe(before);
    expect(commitProfilePatch).not.toHaveBeenCalled();
    // Even after the debounce would have fired.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).not.toHaveBeenCalled();
    resolveLoad?.(await cloudRow({ grade: 'Junior' }));
  });

  it('a stale origin performs ZERO reads — the refusal is before storage, not after it', async () => {
    let resolveLoad: ((v: LoadedProfile) => void) | undefined;
    mockLoadProfile = () => deferredLoad((settle) => { resolveLoad = settle; });
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    act(() => { advanceOwnerEpoch('loading-origin-noread'); syncLocalIdentityOwner('loading-origin-noread'); });

    // jsdom's Storage is a proxy that swallows a method spy — replace the
    // accessor to see the calls at all.
    const real = window.localStorage;
    let reads = 0;
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => { reads += 1; return real.getItem(k); },
        setItem: (k: string, v: string) => real.setItem(k, v),
        removeItem: (k: string) => real.removeItem(k),
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    try {
      act(() => { screen.getByTestId('set-interests').click(); });
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
    }
    // recordProfileIntent opens with ensureScope and an envelope read. A
    // superseded origin must be rejected before any of that: those reads are
    // the new owner's data being consulted on the old owner's behalf.
    expect(reads).toBe(0);
    resolveLoad?.(await cloudRow({ grade: 'Junior' }));
  });
});

describe('useProfileForm — a school switch mid-edit carries what is ON SCREEN', () => {
  it('hydrate rev7/CS, type ECE, switch campus before the debounce: the write keeps ECE', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(cloudRow(
      { major: 'CS', college: 'Grainger', grade: 'Junior', home_school: 'uiuc' }, 7,
    ));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('major').textContent).toBe('CS'));

    // The person types over it. Nothing has been debounced or sent yet.
    handedToPersist = null;
    act(() => { screen.getByTestId('set-major-ece').click(); });
    expect(screen.getByTestId('major').textContent).toBe('ECE');
    // (1) The published view follows the screen — same base, same revision,
    // new rendering.
    expect(screen.getByTestId('view-rendered-major').textContent).toBe('ECE');
    expect(screen.getByTestId('view-rev').textContent).toBe('7');

    // And immediately switches campus through the real ordered helper.
    await act(async () => {
      screen.getByTestId('switch-school').click();
      await new Promise((r) => setTimeout(r, 20));
    });

    // (2) The EXACT object the switcher handed over rendered ECE. This is the
    // assertion that fails the moment local edits stop refreshing the view.
    expect(handedToPersist, 'the switcher acted on a published view').toBeTruthy();
    expect(handedToPersist!.renderedProfile.major).toBe('ECE');
    // …and its BASE is still the hydrated row, because no save has confirmed
    // anything: only a real acknowledgement moves that half.
    expect(handedToPersist!.baseProfile!.major).toBe('CS');
    expect(handedToPersist!.revision).toBe(7);

    // (3) The authoritative view after the action renders both. The raw
    // STORAGE_KEYS.PROFILE mirror deliberately carries only what is staged —
    // patch-only writes pick just the key they changed — so the envelope, not
    // the mirror, is where "what this device believes" is read from.
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).home_school).toBe('ucb');
    const after = readProfileView(captureOwnerToken())!;
    expect(after.renderedProfile.home_school).toBe('ucb');
    expect(screen.getByTestId('major').textContent, 'still on screen').toBe('ECE');
    // The ECE intent is still durable and still owed.
    expect(await lastOpFor('major')!.fields.find((f) => f.key === 'major')!.desired)
      .toEqual({ present: true, value: 'ECE' });

    // (4) And when the edit's own debounce fires, BOTH reach the row.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(serverRow).toMatchObject({ home_school: 'ucb', major: 'ECE' });
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!)).toMatchObject({
      home_school: 'ucb', major: 'ECE',
    });
  });
});

describe('useProfileForm — the accepted baseline only moves forward, and only on a real answer', () => {
  it('a Generate with nothing to send leaves the accepted revision where it was', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow(
      { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 }, 7,
    ));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('7'));
    commitProfilePatch.mockClear();

    // Nothing was edited, so Generate sends nothing. The 'already-saved'
    // it reports is this form's own statement — there is no server revision
    // behind it, and treating its placeholder 0 as an acknowledgement would
    // reset the baseline every later edit is measured against.
    await act(async () => { screen.getByTestId('submit').click(); });
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(screen.getByTestId('view-rev').textContent).toBe('7');
  });

  it('a real save advances the baseline, so the NEXT edit is not a false conflict', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ major: 'CS', grade: 'Junior' }, 7));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('7'));

    act(() => { screen.getByTestId('set-major-ece').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('8'));

    // The second edit is based on what the server just confirmed, not on the
    // revision it replaced — otherwise the user's own consecutive keystrokes
    // manufacture a conflict.
    act(() => { screen.getByTestId('set-major-physics').click(); });
    const op = await lastOpFor('major');
    expect(op!.baseRevision).toBe(8);
    expect(op!.fields.find((f) => f.key === 'major')!.base)
      .toEqual({ present: true, value: 'ECE' });
  });
});

describe('useProfileForm — the published view is the accepted hydration', () => {
  it('a late U1 hydration resolving after U2 took over publishes NOTHING', async () => {
    const resolvers: Array<(v: LoadedProfile) => void> = [];
    mockLoadProfile = () => deferredLoad((settle) => resolvers.push(settle));
    await renderIdentityHarness();
    await waitFor(() => expect(resolvers).toHaveLength(1));

    // U1 is signed in and its row lands: a REAL view is published. Without
    // this, "none" below would be true simply because nothing had been
    // published yet, and dropping the clear entirely would still look green.
    await emitAuth('view-publish-u1');
    await waitFor(() => expect(resolvers).toHaveLength(2));
    await act(async () => { resolvers[1](await cloudRow({ grade: 'Junior' }, 3)); });
    await waitFor(() => expect(screen.getByTestId('view-uid').textContent).toBe('view-publish-u1'));
    expect(screen.getByTestId('view-rev').textContent).toBe('3');

    await emitAuth('view-publish-u2');
    await waitFor(() => expect(resolvers).toHaveLength(3));
    // The transition itself must already have retired U1's view: a surface
    // that is not keyed by identity is still on screen holding it.
    expect(screen.getByTestId('view-uid').textContent).toBe('none');

    // A read issued under U1 finally comes back. It is not this owner's row,
    // and a view published from it would hand U2's school switcher U1's
    // baseline.
    await act(async () => { resolvers[0](await cloudRow({ grade: 'Sophomore' }, 3)); });
    expect(screen.getByTestId('view-uid').textContent).toBe('none');

    // U2's own read is what publishes — and it publishes U2's identity and
    // U2's revision, not a rehabilitated version of U1's.
    await act(async () => { resolvers[2](await cloudRow({ grade: 'Senior' }, 12)); });
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Senior'));
    expect(screen.getByTestId('view-uid').textContent).toBe('view-publish-u2');
    expect(screen.getByTestId('view-rev').textContent).toBe('12');
  });

  it('an owner epoch that moves without an auth event still blocks the publish', async () => {
    // The hook's generation only advances when ITS onAuthChange callback
    // runs. The shared owner epoch advances the instant anything else calls
    // advanceOwnerEpoch — the header's sign-out, another subscriber that got
    // the event first. In that window the generation still matches while the
    // token this read was issued under is already dead, and publishing it
    // would hand the next owner a baseline from the last one.
    const resolvers: Array<(v: LoadedProfile) => void> = [];
    mockLoadProfile = () => deferredLoad((settle) => resolvers.push(settle));
    await renderIdentityHarness();
    await waitFor(() => expect(resolvers).toHaveLength(1));

    act(() => { advanceOwnerEpoch('epoch-moved-first'); });
    await act(async () => { resolvers[0](await cloudRow({ grade: 'Junior' }, 4)); });

    expect(screen.getByTestId('view-uid').textContent).toBe('none');
  });

  it('the baseline keeps a field the ROW does not have absent, even though the form shows a default for it', async () => {
    // A row with no home_school renders as UIUC because UIUC is the matcher's
    // default. If the baseline recorded that default, an explicit UIUC
    // confirmation would compare equal to it, read as a no-op, and never be
    // written at all.
    mockLoadProfile = () => Promise.resolve(cloudRow({ grade: 'Junior' }));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Junior'));
    // Own-key presence, not just a falsy read: `home_school: undefined` is a
    // PRESENT key and would behave differently in every merge below.
    expect(screen.getByTestId('view-base-has-school').textContent).toBe('false');
    expect(screen.getByTestId('view-base-school').textContent).toBe('absent');
    expect(screen.getByTestId('view-rendered-school').textContent).toBe('uiuc');
  });

  it('normalizing legacy string skills for display does not rewrite the baseline', async () => {
    // The form upgrades `skills: ['Rust']` to `[{name,level}]` so it can be
    // rendered. That upgrade used to run in place on the coordinator's own
    // object — which is also the confirmed row this hydration reports as its
    // baseline, so the baseline silently acquired a shape the row never had.
    mockLoadProfile = () => Promise.resolve(
      cloudRow({ grade: 'Junior', skills: ['Rust'] }),
    );
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('skills').textContent).toBe('Rust'));
    expect(screen.getByTestId('view-base-skills').textContent).toBe('["Rust"]');
  });
});

describe('useProfileForm — the PROFILE slot is owner-gated', () => {
  it('submit persists through the owner-gated writer and only then invalidates the cache and routes', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    fireEvent.click(screen.getByTestId('make-valid'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });
    const stored = JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!);
    expect(stored.college).toBe('Grainger');
    expect(pushSpy).toHaveBeenCalledWith('/results');
    expect(screen.getByTestId('save-status').textContent).not.toBe('error');
  });

  it('submit under an unconfirmed owner writes nothing, does not route, and reports the failure', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    fireEvent.click(screen.getByTestId('set-college'));

    // Signed out: the owner is null and local data is blocked until a
    // replacement identity confirms it.
    await emitAuth(null);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); }); // the (empty) row settles
    fireEvent.click(screen.getByTestId('make-valid'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(pushSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId('save-status').textContent).toBe('error');
  });

  it('the debounced autosave under an unconfirmed owner reports an error instead of "saved"', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await emitAuth(null);
    await act(async () => { await new Promise((r) => setTimeout(r, 600)); });
    fireEvent.click(screen.getByTestId('set-college'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(screen.getByTestId('save-status').textContent).toBe('error');
  });
});

describe('useProfileForm — in-flight work started by another identity', () => {
  it('a resume parse that resolves after an identity switch writes nothing, and the uploader subtree is re-keyed', async () => {
    mockLoadProfile = () => Promise.resolve(absentRow());
    render(<Suspense fallback={null}><ResumeIdentityHarness /></Suspense>);
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    // The uploader captured this callback when the user dropped their PDF.
    fireEvent.click(screen.getByTestId('hold'));
    const generationBefore = screen.getByTestId('generation').textContent;

    await emitAuth('identity-u2');

    await act(async () => { fireEvent.click(screen.getByTestId('fire-held')); });
    expect(screen.getByTestId('interests').textContent).toBe('');
    expect(screen.getByTestId('resume').textContent).toBe('');
    // The generation is what page.tsx keys the uploader subtree by, so the
    // previous identity's filename + "resume on file" badge are discarded
    // rather than re-labelled as this identity's.
    expect(screen.getByTestId('generation').textContent).not.toBe(generationBefore);

    // The CURRENT handler still works — the guard rejects staleness, not everything.
    await act(async () => { fireEvent.click(screen.getByTestId('fire-current')); });
    expect(screen.getByTestId('interests').textContent).toBe('u2 interests');
  });

  it('two imports for the SAME identity: the slower earlier one never overwrites the later one', async () => {
    const resolvers: Array<(v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void> = [];
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolvers.push(resolve as never); }),
    );
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());

    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('gh-import')); // A
    await waitFor(() => expect(resolvers).toHaveLength(1));
    fireEvent.click(screen.getByTestId('set-gh2'));
    fireEvent.click(screen.getByTestId('gh-import')); // B
    await waitFor(() => expect(resolvers).toHaveLength(2));

    await act(async () => {
      resolvers[1]({ username: 'hubot', extracted_skills: ['Rust'], topics: [], repo_count: 9, top_repos: [] });
    });
    await waitFor(() => expect(screen.getByTestId('skills').textContent).toBe('Rust'));
    const statusAfterB = screen.getByTestId('gh-status').textContent;

    await act(async () => {
      resolvers[0]({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
    });
    expect(screen.getByTestId('skills').textContent).toBe('Rust');
    expect(screen.getByTestId('gh-status').textContent).toBe(statusAfterB);
  });
});

describe('useProfileForm — unmount flush is owner-gated too', () => {
  it('an edit made while THIS owner\'s realm is unconfirmed persists nothing and says so', async () => {
    // The product guarantee, unchanged: signed out (or a clear that could not
    // be verified), the user types, the screen goes away — nothing reaches
    // storage or the network, and they were told. Distinct from the
    // owner-moved-on case below, which is a stronger token gate but a
    // different situation.
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    const { unmount } = await renderIdentityHarness();
    await emitAuth(null); // signed out: local data blocked until a new identity confirms it
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    const opsBefore = rawJournalOpCount();
    fireEvent.click(screen.getByTestId('set-college'));
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('error'));

    unmount();
    await act(async () => {});

    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(rawJournalOpCount()).toBe(opsBefore);
    expect(commitProfilePatch).not.toHaveBeenCalled();
  });

  it('an edit made under an unconfirmed owner is not persisted by the unmount flush', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    const { unmount } = await renderIdentityHarness();
    // The row settles under a CONFIRMED owner and the edit arms a real save.
    // Signing out first would fail the read instead, leaving nothing armed —
    // and a flush with nothing to flush proves nothing about the gate.
    await emitAuth(HOME_UID);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    fireEvent.click(screen.getByTestId('set-college'));
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saving'));

    // NOW local ownership goes: the shared owner moves on without this hook
    // hearing about it, so the armed save and its token are still sitting
    // there when the screen goes away.
    act(() => { advanceOwnerEpoch(null); });

    // Unmount BEFORE the 1.5s debounce fires: the flush is the only writer
    // that runs, and it must respect the same owner gate.
    unmount();
    await act(async () => {});

    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(commitProfilePatch).not.toHaveBeenCalled();
  });
});

describe('useProfileForm — submit routing gate', () => {
  it('routes on a successful local write when there is no cloud to write to (confirmed local-only device)', async () => {
    commitProfilePatch.mockClear();
    commitProfilePatch.mockResolvedValue({ status: 'local-only' });
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    fireEvent.click(screen.getByTestId('make-valid'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).college).toBe('Grainger');
    expect(pushSpy).toHaveBeenCalledWith('/results');

  });
});

describe('useProfileForm — the live auth stream owns loading', () => {
  it('a live observation in the mount tick cancels the fallback snapshot load entirely', async () => {
    // The subscription is registered BEFORE the fallback is even scheduled,
    // so an event arriving this early is not racing a load already in
    // flight — it replaces it.
    let calls = 0;
    mockLoadProfile = () => { calls += 1; return Promise.resolve(cloudRow({ grade: 'Senior' })); };
    await renderIdentityHarness();
    expect(authChangeCb).not.toBeNull();
    expect(calls).toBe(0); // scheduled, not fired

    await emitAuth('identity-u2');
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Senior'));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(calls).toBe(1);
  });

  it('a save that settles after an identity switch never relabels the new identity\'s form', async () => {
    let resolveSave: (() => void) | undefined;
    commitProfilePatch.mockClear();
    commitProfilePatch.mockImplementation(
      (intent) => new Promise<ProfilePatchOutcome>((resolve) => {
        resolveSave = () => resolve(applyIntent(intent));
      }),
    );
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    await seedCreatableProfile();
    fireEvent.click(screen.getByTestId('set-college'));
    await completeRequiredAfterCollegeChange();
    // Let the 1.5s debounce actually fire, so the save is in flight.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).toHaveBeenCalledTimes(1);

    await emitAuth('identity-u2');
    expect(screen.getByTestId('save-status').textContent).toBe('idle');

    await act(async () => { resolveSave?.(); });
    expect(screen.getByTestId('save-status').textContent).toBe('idle');


  });
});

describe('useProfileForm — submit commits nothing it cannot stand behind', () => {
  it('a submit superseded mid-GitHub-import commits nothing at all — not even its own failure', async () => {
    let resolveImport: ((v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void) | undefined;
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolveImport = resolve as never; }),
    );
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('submit'));
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(1));

    // Signed out mid-import: the PROFILE write below will legitimately fail,
    // but that failure belongs to the identity that pressed submit.
    await emitAuth(null);
    commitProfilePatch.mockClear();
    await act(async () => {
      resolveImport?.({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByTestId('save-status').textContent).toBe('idle');
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it('a cache invalidation that could not be verified blocks the navigation and reports it', async () => {
    cacheMocks.clearMatchCache.mockReturnValue(false);
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    fireEvent.click(screen.getByTestId('make-valid'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });

    // The save is deliberately FIRST: refusing to store the user's edit
    // because a cache key could not be removed would lose the edit to protect
    // a derived cache. What the unverifiable clear blocks is the NAVIGATION —
    // /results reads that cache, and it may still hold another profile's
    // matches.
    expect(screen.getByTestId('save-status').textContent).toBe('error');
    expect(commitProfilePatch).toHaveBeenCalledTimes(1);
    expect(serverRow).toMatchObject({ college: 'Grainger', major: 'CS', grade: 'Junior' });
    expect(pushSpy).not.toHaveBeenCalled();
  });
});

describe('useProfileForm — hydration is not an edit', () => {
  it('a loaded profile is never written back: no save, no PROFILE write, no "saved" badge', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(cloudRow({ grade: 'Junior', college: 'Loaded College', search_weight: 77 }));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('college').textContent).toBe('Loaded College'));
    expect(screen.getByTestId('weight').textContent).toBe('77');

    // Well past the 1.5s debounce.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(commitProfilePatch).not.toHaveBeenCalled();
    // The load DOES project the confirmed row into the local mirror — that is
    // how /results, /favorites and /compare see a profile at all on a device
    // that has only just signed in. What must not happen is a write-BACK:
    // nothing invented, nothing merged in, no revision moved, no badge.
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!))
      .toEqual({ grade: 'Junior', college: 'Loaded College', search_weight: 77 });
    expect(screen.getByTestId('save-status').textContent).toBe('idle');
  });

  it('an edit made while the load was still in flight is still saved once it lands', async () => {
    commitProfilePatch.mockClear();
    let resolveLoad: ((v: LoadedProfile) => void) | undefined;
    mockLoadProfile = () => deferredLoad((settle) => { resolveLoad = settle; });
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    await seedCreatableProfile();
    fireEvent.click(screen.getByTestId('set-weight')); // a real edit, mid-load
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).not.toHaveBeenCalled(); // buffered, not persisted
    await act(async () => { resolveLoad?.(await absentRow()); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(commitProfilePatch).toHaveBeenCalledTimes(1);
    expect((commitProfilePatch.mock.calls[0][0].patch as { search_weight?: number }).search_weight).toBe(90);
  });
});

describe('useProfileForm — GitHub spinner ownership', () => {
  it('an earlier import settling first leaves the still-pending later import\'s spinner on', async () => {
    const resolvers: Array<(v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void> = [];
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolvers.push(resolve as never); }),
    );
    mockLoadProfile = () => Promise.resolve(absentRow());
    render(<Suspense fallback={null}><GhLoadingHarness /></Suspense>);
    await waitFor(() => expect(authChangeCb).not.toBeNull());

    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('gh-import')); // A
    await waitFor(() => expect(resolvers).toHaveLength(1));
    fireEvent.click(screen.getByTestId('set-gh2'));
    fireEvent.click(screen.getByTestId('gh-import')); // B — now the owner
    await waitFor(() => expect(resolvers).toHaveLength(2));
    expect(screen.getByTestId('gh-loading').textContent).toBe('yes');

    await act(async () => {
      resolvers[0]({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
    });
    // A is done, B is not: the spinner belongs to B.
    expect(screen.getByTestId('gh-loading').textContent).toBe('yes');

    await act(async () => {
      resolvers[1]({ username: 'hubot', extracted_skills: ['Rust'], topics: [], repo_count: 9, top_repos: [] });
    });
    expect(screen.getByTestId('gh-loading').textContent).toBe('no');
  });
});

describe('useProfileForm — a load never overwrites an edit the user made while it was in flight', () => {
  it('an edit made while the row was loading is buffered and merged onto that row', async () => {
    commitProfilePatch.mockClear();
    let resolveLoad: ((v: LoadedProfile) => void) | undefined;
    mockLoadProfile = () => deferredLoad((settle) => { resolveLoad = settle; });
    const { unmount } = await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());

    fireEvent.click(screen.getByTestId('set-interests')); // edit mid-load
    // Well past the 1.5s debounce: NOTHING may be persisted yet, or the
    // half-empty form would overwrite the row still in flight.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();

    // The row says nothing about the edited field, so there is no
    // disagreement to resolve: the edit merges onto it and goes out.
    await act(async () => {
      resolveLoad?.(await cloudRow({ major: 'Cloud Major', grade: 'Senior' }));
    });
    expect(screen.getByTestId('interests').textContent).toBe('my interests');
    unmount();
    // The flush's cloud save goes through the owner write queue, so it
    // starts on the next microtask rather than inline with unmount.
    await act(async () => {});

    const stored = JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!);
    expect(stored.research_interests).toBe('my interests'); // the edit
    expect(stored.major).toBe('Cloud Major'); // never touched: still the row's
    expect(stored.grade).toBe('Senior');
    // patch-only: the edited field and nothing else is ever sent, and the
    // row's own fields survive because nothing was written over them.
    expect(await sentPatches().at(-1)).toEqual({ research_interests: 'my interests' });
    expect(serverRow).toMatchObject({
      research_interests: 'my interests', major: 'Cloud Major', grade: 'Senior',
    });
  });

  it('an edit made while the row was loading NEVER overwrites a different value the row turns out to hold', async () => {
    // The counterexample to the test above, and the reason the two are
    // separate: the base this edit was made against is UNKNOWN — the form had
    // not loaded, so the user typed over a field whose stored value they had
    // never seen. Picking either side automatically is a lost update.
    commitProfilePatch.mockClear();
    let resolveLoad: ((v: LoadedProfile) => void) | undefined;
    mockLoadProfile = () => deferredLoad((settle) => { resolveLoad = settle; });
    const first = await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());

    fireEvent.click(screen.getByTestId('set-interests'));
    // The 1.5s autosave debounce is driven on a fake clock — the contract is
    // that the save happens after it, not that the test sits through it. The
    // production interval itself is covered by its own timing test.
    vi.useFakeTimers();
    try {
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
      await act(async () => {
        resolveLoad?.(await cloudRow({ research_interests: 'cloud interests', major: 'Cloud Major', grade: 'Senior' }));
      });
      // Past the autosave debounce the row landing re-armed, then let the
      // request settle.
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    } finally {
      vi.useRealTimers();
    }
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('conflict'));

    // Zero overwrite: the row keeps its value, and the safe fields of this
    // write are unaffected either way.
    expect(serverRow).toMatchObject({
      research_interests: 'cloud interests', major: 'Cloud Major', grade: 'Senior',
    });
    expect(screen.getByTestId('conflict-keys').textContent).toBe('research_interests');
    first.unmount();

    // Durable: a remount still shows the user's own value, still locked, and
    // the row is still untouched. Nothing auto-resolves it — not the load,
    // not the recovery flush.
    mockLoadProfile = () => Promise.resolve({
      source: 'cloud', profile: { ...serverRow }, revision: serverRevision, token: captureOwnerToken(),
    });
    commitProfilePatch.mockClear();
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('my interests'));
    vi.useFakeTimers();
    try {
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    } finally {
      vi.useRealTimers();
    }
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(screen.getByTestId('conflict-keys').textContent).toBe('research_interests');
    expect((serverRow as { research_interests?: string }).research_interests).toBe('cloud interests');

    // Only an explicit choice closes it.
    await act(async () => {
      fireEvent.click(screen.getByTestId('use-cloud'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('conflict-keys').textContent).toBe('');
    expect(screen.getByTestId('interests').textContent).toBe('cloud interests');
    expect((serverRow as { research_interests?: string }).research_interests).toBe('cloud interests');
  });

  it('the search weight is dirty-tracked on its own: it survives, the untouched fields still come from the row', async () => {
    let resolveLoad: ((v: LoadedProfile) => void) | undefined;
    mockLoadProfile = () => deferredLoad((settle) => { resolveLoad = settle; });
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());

    fireEvent.click(screen.getByTestId('set-weight'));
    await act(async () => { resolveLoad?.(await cloudRow({ search_weight: 12, college: 'Cloud College' })); });

    expect(screen.getByTestId('weight').textContent).toBe('90');
    expect(screen.getByTestId('college').textContent).toBe('Cloud College');
  });
});

describe('useProfileForm — user-wins applies to the live-identity load too', () => {
  it('an edit made while the NEW identity\'s load is in flight is not overwritten by it', async () => {
    let resolveLive: ((v: LoadedProfile) => void) | undefined;
    let calls = 0;
    mockLoadProfile = () => {
      calls += 1;
      if (calls === 1) return Promise.resolve(absentRow());
      return new Promise((resolve) => { resolveLive = resolve; });
    };
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());

    await emitAuth('identity-u2');
    await waitFor(() => expect(calls).toBe(2));
    fireEvent.click(screen.getByTestId('set-college')); // U2 types while their own load runs
    await act(async () => { resolveLive?.(await cloudRow({ college: 'U2 Cloud College' })); });

    expect(screen.getByTestId('college').textContent).toBe('Grainger');
  });
});

describe('useProfileForm — an identity whose row has not loaded yet persists nothing', () => {
  it('edits made during the NEW identity\'s slow load are buffered past the debounce, then merged onto its row', async () => {
    commitProfilePatch.mockClear();
    let resolveU2: ((v: LoadedProfile) => void) | undefined;
    let calls = 0;
    mockLoadProfile = () => {
      calls += 1;
      if (calls === 1) return Promise.resolve(cloudRow({ college: 'U1 College' }));
      return new Promise((resolve) => { resolveU2 = resolve; });
    };
    const { unmount } = await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('college').textContent).toBe('U1 College'));

    await emitAuth('identity-u2');
    await waitFor(() => expect(calls).toBe(2));
    expect(screen.getByTestId('college').textContent).toBe(''); // cleared on the spot
    commitProfilePatch.mockClear();

    fireEvent.click(screen.getByTestId('set-interests'));
    // Past the 1.5s debounce, with U2's row STILL in flight.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();

    await act(async () => {
      resolveU2?.(await cloudRow({ research_interests: 'u2 cloud interests', major: 'U2 Major', grade: 'Masters' }));
    });
    expect(screen.getByTestId('interests').textContent).toBe('my interests');
    unmount();

    const stored = JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!);
    expect(stored).toMatchObject({ research_interests: 'my interests', major: 'U2 Major', grade: 'Masters' });
  });

  it('a second identity\'s empty row never clones the first identity\'s fields, and still takes the query prefill', async () => {
    searchRef.current = 'prefill_year=Senior';
    let calls = 0;
    mockLoadProfile = () => {
      calls += 1;
      return Promise.resolve(calls === 1 ? cloudRow({ college: 'private-u1-college' }) : absentRow());
    };
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('college').textContent).toBe('private-u1-college'));

    await emitAuth('identity-u2');
    await waitFor(() => expect(calls).toBe(2));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    expect(screen.getByTestId('college').textContent).toBe('');
    expect(screen.getByTestId('grade').textContent).toBe('Senior');
  });
});

describe('useProfileForm — a failed read is not an empty profile', () => {
  it('keeps buffering and says so: no full-row save, no "saved", after a load rejection', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.reject(new Error('Failed to load profile: network'));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('hydration').textContent).toBe('failed'));

    fireEvent.click(screen.getByTestId('set-college'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(screen.getByTestId('save-status').textContent).not.toBe('saved');
    expect(screen.getByTestId('hydration').textContent).toBe('failed');
  });

  it('a SAME-identity re-observation retries the read and merges the edits buffered since it failed', async () => {
    commitProfilePatch.mockClear();
    let attempt = 0;
    mockLoadProfile = () => {
      attempt += 1;
      if (attempt === 1) return Promise.reject(new Error('boom'));
      return Promise.resolve(cloudRow({ college: 'Cloud College', major: 'Cloud Major' }));
    };
    const { unmount } = await renderIdentityHarness();
    // The live observation owns the read (it cancels the mount fallback);
    // that read fails.
    await emitAuth('identity-u2');
    await waitFor(() => expect(attempt).toBe(1));
    await waitFor(() => expect(screen.getByTestId('hydration').textContent).toBe('failed'));
    fireEvent.click(screen.getByTestId('set-interests'));

    // TOKEN_REFRESHED for the SAME uid: not a transition, so nothing is
    // reset — but the row still has not loaded, so it is a free retry.
    await emitAuth('identity-u2');
    await waitFor(() => expect(attempt).toBe(2));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    unmount();

    // TWO layers, because they are two different guarantees.
    //
    // Synchronous, before anything is awaited: leaving the page writes the
    // edit to the journal inside the cleanup itself, so a crash at this exact
    // moment still has it.
    expect(
      await journalOps().some((o) => o.fields.some((f) => f.key === 'research_interests')),
      'the edit is crash-durable the moment the page is left',
    ).toBe(true);

    // Asynchronous: staging, the request and the mirror are continuations of
    // that cleanup, waited for rather than slept past.
    await waitFor(() => expect(
      sentPatches().some((q) => q.research_interests === 'my interests'),
      'and the edit buffered while the read was failing is sent',
    ).toBe(true));
    await waitFor(() => expect(
      JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!),
      'and the mirror ends up holding it beside the row',
    ).toMatchObject({ research_interests: 'my interests', major: 'Cloud Major' }));
  });
});

describe('useProfileForm — same-tick edit and load resolution', () => {
  it('an edit and the row landing in the SAME tick still merge on the edit, not on the pre-edit value', async () => {
    let resolveLoad: ((v: LoadedProfile) => void) | undefined;
    mockLoadProfile = () => deferredLoad((settle) => { resolveLoad = settle; });
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());

    // No React commit between the click and the resolution.
    await act(async () => {
      fireEvent.click(screen.getByTestId('set-college'));
      resolveLoad?.(await cloudRow({ college: 'Cloud College', major: 'Cloud Major' }));
    });

    expect(screen.getByTestId('college').textContent).toBe('Grainger');
  });
});

describe('useProfileForm — submit is gated on the same hydration as the autosave', () => {
  it('a submit made while the row is still loading writes nothing, clears nothing and does not navigate', async () => {
    commitProfilePatch.mockClear();
    let resolveLoad: ((v: LoadedProfile) => void) | undefined;
    mockLoadProfile = () => deferredLoad((settle) => { resolveLoad = settle; });
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());

    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-interests'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId('hydration').textContent).toBe('loading');

    // Once the row lands, the same submit sends the fields typed while it was
    // loading — and ONLY those. `grade` is the interesting one: the user
    // typed 'Junior' into a form that had not loaded yet, and the row turned
    // out to already say 'Cloud Grade'. Neither side is safe to pick
    // automatically (this device never saw the value it would be replacing),
    // so it locks. Everything else still saves.
    await act(async () => {
      resolveLoad?.(await cloudRow({ grade: 'Cloud Grade', skills: [{ name: 'Cloud Skill', level: 'expert' }] }));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent).toBe('conflict');
    expect(screen.getByTestId('conflict-keys').textContent).toBe('grade');
    expect(pushSpy).not.toHaveBeenCalled();
    const sent = await sentPatches().at(-1)!;
    expect(sent).toMatchObject({ research_interests: 'my interests', college: 'Grainger', major: 'CS' });
    expect(sent).not.toHaveProperty('grade');   // never sent behind the user
    expect(sent).not.toHaveProperty('skills');  // untouched: patch-only
    expect((serverRow as { grade?: string; skills?: unknown }).grade).toBe('Cloud Grade');
    expect((serverRow as { skills?: unknown }).skills).toEqual([{ name: 'Cloud Skill', level: 'expert' }]);

    // The user decides, and only then does it close.
    await act(async () => {
      fireEvent.click(screen.getByTestId('keep-mine'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('conflict-keys').textContent).toBe('');
    expect((serverRow as { grade?: string }).grade).toBe('Junior');
    expect(await sentPatches().at(-1)).toEqual({ grade: 'Junior' });
    const stored = JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!);
    expect(stored).toMatchObject({ research_interests: 'my interests', college: 'Grainger', grade: 'Junior' });
    expect(stored.skills).toEqual([{ name: 'Cloud Skill', level: 'expert' }]);
  });

  it('a submit superseded by the FIRST live observation commits nothing, even when the owner token stays valid', async () => {
    // Local-only device: the first live event resolves null, so the owner
    // token this submit captured is still perfectly valid — only the hook's
    // own generation says the form moved on.
    let resolveImport: ((v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void) | undefined;
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolveImport = resolve as never; }),
    );
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('submit'));
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(1));

    act(() => { authChangeCb?.({ user: null }); }); // first live observation, same (null) owner
    commitProfilePatch.mockClear();
    cacheMocks.clearMatchCache.mockClear();
    await act(async () => {
      resolveImport?.({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
      await new Promise((r) => setTimeout(r, 20));
    });

    // The edits themselves became durable when they were TYPED — that is what
    // the journal is, and this owner never changed. What this submit must not
    // do is COMMIT: nothing sent, nothing invalidated, nowhere navigated, and
    // not a trace of the import it was still waiting on.
    const mirror = JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!);
    expect(mirror.skills ?? []).toEqual([]);
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });
});

describe('useProfileForm — a cascading edit is an intent, not just a diff', () => {
  it('a college switch made during the load clears the row\'s major and additional majors when it lands', async () => {
    let resolveLoad: ((v: LoadedProfile) => void) | undefined;
    mockLoadProfile = () => deferredLoad((settle) => { resolveLoad = settle; });
    await renderIdentityHarness();
    await waitFor(() => expect(authChangeCb).not.toBeNull());

    // The form is still empty here, so a plain before/after diff would see
    // ONLY college change — and the row's major would come back.
    fireEvent.click(screen.getByTestId('set-college'));
    await act(async () => {
      resolveLoad?.(await cloudRow({
        college: 'Cloud College',
        major: 'Cloud Major',
        additional_majors: ['Cloud Second Major'],
      }));
    });

    expect(screen.getByTestId('college').textContent).toBe('Grainger');
    expect(screen.getByTestId('major').textContent).toBe('');
    expect(screen.getByTestId('extra-majors').textContent).toBe('');
  });
});

describe('useProfileForm — only the newest save owns the status', () => {
  it('a slow earlier save settling does not report "saved" while a newer edit is still queued', async () => {
    // Held open so both saves are in flight at once; each settles as the real
    // endpoint would — applying its own patch and answering with the revision
    // that produced.
    const resolvers: Array<() => void> = [];
    commitProfilePatch.mockReset();
    commitProfilePatch.mockImplementation(
      (intent) => new Promise<ProfilePatchOutcome>((resolve) => {
        resolvers.push(() => resolve(applyIntent(intent)));
      }),
    );
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    await seedCreatableProfile();

    fireEvent.click(screen.getByTestId('set-interests')); // A
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(resolvers).toHaveLength(1);

    fireEvent.click(screen.getByTestId('set-college'));

    await completeRequiredAfterCollegeChange(); // B, queued behind A
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(screen.getByTestId('save-status').textContent).toBe('saving');

    await act(async () => { resolvers[0](); }); // A finishes
    expect(screen.getByTestId('save-status').textContent).toBe('saving');

    await waitFor(() => expect(resolvers).toHaveLength(2));
    await act(async () => { resolvers[1](); }); // B finishes
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saved'));


  });
});

describe('useProfileForm — the remaining same-owner GitHub and submit races', () => {
  it('changing the URL while an import is in flight drops that import entirely: no skills, no status, no receipt', async () => {
    const resolvers: Array<(v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void> = [];
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolvers.push(resolve as never); }),
    );
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('gh-import')); // import for octocat
    await waitFor(() => expect(resolvers).toHaveLength(1));

    // The user retypes the URL. They do NOT press Import again.
    fireEvent.click(screen.getByTestId('set-gh2'));
    await act(async () => {
      resolvers[0]({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
    });

    expect(screen.getByTestId('skills').textContent).toBe('');
    expect(screen.getByTestId('gh-status').textContent).toBe('');
    // The receipt is the invisible one. Point the form BACK at the original
    // url and submit: if the dropped import had left its receipt behind,
    // submit would consider octocat already imported and fetch nothing.
    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('submit'));
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(2));
    expect(vi.mocked(parseGitHubProfile).mock.calls[1][0]).toBe('octocat');
    // Settle it, so no 3.5s submit race outlives this test. Submit merges
    // the import into the PAYLOAD (it is navigating away, not repainting
    // the form), so that is where the proof lives.
    await act(async () => {
      resolvers[1]({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
      await new Promise((r) => setTimeout(r, 20));
    });
    const submitted = JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!);
    expect(submitted.skills).toEqual([{ name: 'Go', level: 'experienced' }]);
  });

  it('a field edited during submit\'s GitHub await is what gets saved, not the snapshot submit started with', async () => {
    let resolveImport: ((v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void) | undefined;
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolveImport = resolve as never; }),
    );
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('submit'));
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('set-interests')); // same user, same identity
    fireEvent.click(screen.getByTestId('set-weight'));
    await act(async () => {
      resolveImport?.({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
      await new Promise((r) => setTimeout(r, 20));
    });

    const stored = JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!);
    expect(stored.research_interests).toBe('my interests');
    expect(stored.search_weight).toBe(90);
    expect(stored.skills).toEqual([{ name: 'Go', level: 'experienced' }]);
    expect(commitProfilePatch.mock.calls.at(-1)?.[0].patch).toMatchObject({
      research_interests: 'my interests',
      search_weight: 90,
    });
    expect(pushSpy).toHaveBeenCalledWith('/results');

    // The superseded debounce must not re-save the pre-import snapshot.
    commitProfilePatch.mockClear();
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).not.toHaveBeenCalled();
  });
});

describe('useProfileForm — a shared profile survives the first identity observation', () => {
  it('keeps the shared form and banner, saves nothing, and is only cleared by a real switch', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests', grade: 'Senior' });
    searchRef.current = `share=${share}`;
    let loads = 0;
    mockLoadProfile = () => { loads += 1; return Promise.resolve(cloudRow({ research_interests: 'my own row' })); };
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('shared interests'));
    expect(screen.getByTestId('shared-banner').textContent).toBe('home.sharedBanner');
    expect(loads).toBe(0); // the share branch never loads over the import

    await emitAuth('identity-u2'); // FIRST live observation
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(screen.getByTestId('interests').textContent).toBe('shared interests');
    expect(screen.getByTestId('shared-banner').textContent).toBe('home.sharedBanner');
    expect(loads).toBe(0);
    // And it is not treated as an edit: the banner promises the visitor's
    // own saved profile stays untouched until they generate.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();

    await emitAuth('identity-u3'); // a REAL switch
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(screen.getByTestId('interests').textContent).toBe('my own row');
    expect(screen.getByTestId('shared-banner').textContent).toBe('');
    expect(loads).toBe(1);
  });
});

describe('useProfileForm — a shared draft is never saved behind the visitor\'s back', () => {
  it('tweaks to a shared profile persist nothing until Generate, which saves once and routes', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(cloudRow({ research_interests: 'my own row' }));
    const { unmount } = await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('shared interests'));

    fireEvent.click(screen.getByTestId('set-weight'));
    fireEvent.click(screen.getByTestId('make-valid'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();

    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(commitProfilePatch).toHaveBeenCalledTimes(1);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).research_interests).toBe('shared interests');
    expect(pushSpy).toHaveBeenCalledWith('/results');

    // Ordinary editing resumes after the draft was deliberately committed.
    commitProfilePatch.mockClear();
    fireEvent.click(screen.getByTestId('set-interests'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).toHaveBeenCalledTimes(1);
    unmount();
  });

  it('an unmount during a shared draft flushes nothing', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(absentRow());
    const { unmount } = await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('shared interests'));

    fireEvent.click(screen.getByTestId('set-weight'));
    unmount();
    await act(async () => {});

    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
  });

  it('a real identity switch ends the draft: that identity\'s own edits save normally', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('shared interests'));

    await emitAuth('identity-u2'); // first observation: the draft is kept
    await emitAuth('identity-u3'); // a REAL switch: the draft is gone
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    // The switch reset the form, so THIS identity fills in its own required
    // fields before its first save can create a row.
    await seedCreatableProfile();
    fireEvent.click(screen.getByTestId('set-interests'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(commitProfilePatch).toHaveBeenCalledTimes(1);
    expect(JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!).research_interests).toBe('my interests');
  });
});

describe('useProfileForm — submit refuses to ship something the user did not mean', () => {
  it('a required field emptied during the GitHub await aborts the submit entirely', async () => {
    let resolveImport: ((v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void) | undefined;
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolveImport = resolve as never; }),
    );
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('submit'));
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('clear-major')); // no longer valid
    await act(async () => {
      resolveImport?.({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it('a GitHub link changed during the import aborts the submit and says why', async () => {
    let resolveImport: ((v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void) | undefined;
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolveImport = resolve as never; }),
    );
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('submit'));
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('set-gh2')); // the link on the form is now B
    await act(async () => {
      resolveImport?.({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId('gh-status').textContent).toContain('githubUrlChanged');

    // Pressing Generate again imports B and only then ships.
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 5));
    });
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(2));
    await act(async () => {
      resolveImport?.({ username: 'hubot', extracted_skills: ['Rust'], topics: [], repo_count: 9, top_repos: [] });
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).skills)
      .toEqual([{ name: 'Rust', level: 'experienced' }]);
    expect(pushSpy).toHaveBeenCalledWith('/results');
  });

  it('a double click runs one submit: one import, one save, one cache clear, one navigation', async () => {
    let resolveImport: ((v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void) | undefined;
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolveImport = resolve as never; }),
    );
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh'));

    fireEvent.click(screen.getByTestId('submit'));
    fireEvent.click(screen.getByTestId('submit')); // the impatient second click
    await act(async () => {
      resolveImport?.({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(parseGitHubProfile).toHaveBeenCalledTimes(1);
    expect(commitProfilePatch).toHaveBeenCalledTimes(1);
    expect(cacheMocks.clearMatchCache).toHaveBeenCalledTimes(1);
    expect(pushSpy).toHaveBeenCalledTimes(1);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).skills)
      .toEqual([{ name: 'Go', level: 'experienced' }]);
  });
});

// The share link stays in the URL for the whole visit, so anything that
// re-runs the import effect — a locale switch changing `t` was enough —
// used to re-decode it over whatever the visitor had done since.
function LocaleSwitchHarness({ t }: { t: (k: string) => string }) {
  const form = useProfileForm(t as never);
  return (
    <div>
      <span data-testid="interests">{form.profile.research_interests}</span>
      <span data-testid="weight">{form.searchWeight}</span>
      <span data-testid="shared-banner">{form.sharedBanner ?? ''}</span>
      <span data-testid="save-status">{form.saveStatus}</span>
      <button data-testid="set-interests" onClick={() => form.update('research_interests', 'my interests')}>ri</button>
      <button data-testid="set-college" onClick={() => form.update('college', 'Grainger')}>c</button>
      <button data-testid="retry-sync" onClick={() => form.retryCloudSave()}>retry</button>
      <button data-testid="make-valid" onClick={() => form.setProfile((p) => ({ ...p, college: 'Grainger', major: 'CS', grade: 'Junior' }))}>valid</button>
      <button data-testid="seed-required" onClick={() => form.setProfile((p) => ({ ...p, major: 'CS', grade: 'Junior' }))}>seed</button>
      <button data-testid="submit" onClick={() => { void form.handleSubmit(); }}>s</button>
    </div>
  );
}

describe('useProfileForm — a shared link is imported exactly once', () => {
  const zhT = (k: string) => `zh:${k}`;

  it('a locale switch does not re-import over the visitor\'s edits, and keeps the draft gate as it was', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(cloudRow({ research_interests: 'my own row' }));
    const { rerender } = render(
      <Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>,
    );
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('shared interests'));

    fireEvent.click(screen.getByTestId('set-interests'));
    rerender(<Suspense fallback={null}><LocaleSwitchHarness t={zhT} /></Suspense>);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    expect(screen.getByTestId('interests').textContent).toBe('my interests');
    // The banner is translated at render, so it follows the locale without
    // the import effect re-running.
    expect(screen.getByTestId('shared-banner').textContent).toBe('zh:home.sharedBanner');
    // Still a draft: nothing is persisted behind the visitor's back.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
  });

  it('a locale switch after Generate does not resurrect the draft', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(absentRow());
    const { rerender } = render(
      <Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>,
    );
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('shared interests'));
    fireEvent.click(screen.getByTestId('make-valid'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(commitProfilePatch).toHaveBeenCalledTimes(1);

    commitProfilePatch.mockClear();
    rerender(<Suspense fallback={null}><LocaleSwitchHarness t={zhT} /></Suspense>);
    fireEvent.click(screen.getByTestId('set-interests'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    // The draft gate is gone: this edit is the user's own profile now.
    expect(commitProfilePatch).toHaveBeenCalledTimes(1);
    expect(JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!).research_interests).toBe('my interests');
  });

  it('a locale switch after a real identity switch does not re-import the previous visitor\'s link', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(cloudRow({ research_interests: 'u3 own row' }));
    const { rerender } = render(
      <Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>,
    );
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('shared interests'));

    await emitAuth('identity-u2'); // first observation keeps the draft
    await emitAuth('identity-u3'); // a real switch ends it
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(screen.getByTestId('interests').textContent).toBe('u3 own row');

    rerender(<Suspense fallback={null}><LocaleSwitchHarness t={zhT} /></Suspense>);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    expect(screen.getByTestId('interests').textContent).toBe('u3 own row');
    expect(screen.getByTestId('shared-banner').textContent).toBe('');
    fireEvent.click(screen.getByTestId('set-interests'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).toHaveBeenCalledTimes(1); // ordinary saving, no draft gate
  });
});

describe('useProfileForm — the share import survives an unrelated query change', () => {
  it('re-running the import effect for the SAME share link does not re-import over the visitor\'s edits', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(cloudRow({ research_interests: 'my own row' }));
    const { rerender } = render(
      <Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>,
    );
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('shared interests'));
    fireEvent.click(screen.getByTestId('set-interests'));

    // Anything that adds a query param (a client-side router push, an
    // analytics tag) hands the effect a NEW searchParams object with the
    // same share value still in it.
    searchRef.current = `share=${share}&ref=newsletter`;
    rerender(<Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    expect(screen.getByTestId('interests').textContent).toBe('my interests');
    expect(screen.getByTestId('shared-banner').textContent).toBe('home.sharedBanner');
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).not.toHaveBeenCalled(); // still a draft, still not persisted
  });
});

describe('useProfileForm — removing the résumé removes it from the profile that gets matched', () => {
  it('clears resume_text and coursework, keeps skills and interests, and persists that', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(cloudRow({
      resume_text: 'the full text of my resume',
      coursework: ['ECE 220', 'CS 225'],
      skills: [{ name: 'Python', level: 'experienced' }],
      research_interests: 'robotics',
    }));
    const { unmount } = render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('the full text of my resume'));

    fireEvent.click(screen.getByTestId('remove-resume'));

    expect(screen.getByTestId('resume').textContent).toBe('');
    expect(screen.getByTestId('coursework').textContent).toBe('');
    expect(screen.getByTestId('skills').textContent).toBe('Python');
    expect(screen.getByTestId('interests').textContent).toBe('robotics');

    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    const saved = await sentPatches().at(-1) as Record<string, unknown>;
    expect(saved.resume_text).toBe('');
    expect(saved.coursework).toEqual([]);
    // patch-only: a field the user did not touch is NOT re-sent. Skills
    // survive because nothing was written over them — proven on the row the
    // server ends up holding, not by echoing them back in this patch.
    expect(saved).not.toHaveProperty('skills');
    expect(saved).not.toHaveProperty('research_interests');
    expect((serverRow as { skills?: unknown; research_interests?: unknown }).skills)
      .toEqual([{ name: 'Python', level: 'experienced' }]);
    expect((serverRow as { research_interests?: unknown }).research_interests).toBe('robotics');
    const stored = JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!);
    expect(stored.resume_text).toBe('');
    expect(stored.coursework).toEqual([]);
    unmount();
  });

  it('a removal made while the row was loading is not undone by the row landing', async () => {
    let resolveLoad: ((v: LoadedProfile) => void) | undefined;
    mockLoadProfile = () => deferredLoad((settle) => { resolveLoad = settle; });
    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(authChangeCb).not.toBeNull());

    fireEvent.click(screen.getByTestId('remove-resume'));
    await act(async () => {
      resolveLoad?.(await cloudRow({ resume_text: 'cloud resume text', coursework: ['CS 233'], skills: [] }));
    });

    expect(screen.getByTestId('resume').textContent).toBe('');
    expect(screen.getByTestId('coursework').textContent).toBe('');
  });
});

describe('useProfileForm — removing the résumé saves once, immediately', () => {
  it('persists on the spot and does not re-save the same snapshot when the debounce would have fired', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(cloudRow({ resume_text: 'old text', coursework: ['CS 225'] }));
    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('old text'));

    await act(async () => { fireEvent.click(screen.getByTestId('remove-resume')); });
    expect(commitProfilePatch).toHaveBeenCalledTimes(1); // not waiting 1.5s
    expect((commitProfilePatch.mock.calls[0][0].patch as { resume_text?: string }).resume_text).toBe('');

    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).toHaveBeenCalledTimes(1); // and not again

    // A later genuine edit still saves on its own.
    fireEvent.click(screen.getByTestId('edit-interests'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).toHaveBeenCalledTimes(2);
  });

  it('a cloud rejection is reported immediately, with a retry that replays the cleansed snapshot', async () => {
    // Both requests are HELD, so the test decides when each one answers. No
    // wait budget is involved: the status is asserted on the turn the
    // response is released, which is the only turn it can appear on.
    const held: Array<(o: ProfilePatchOutcome) => void> = [];
    commitProfilePatch.mockReset();
    commitProfilePatch.mockImplementation(
      () => new Promise<ProfilePatchOutcome>((resolve) => { held.push(resolve); }),
    );
    mockLoadProfile = () => Promise.resolve(cloudRow({ resume_text: 'old text', coursework: ['CS 225'] }));
    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('old text'));

    await act(async () => { fireEvent.click(screen.getByTestId('remove-resume')); });
    expect(held, 'the removal went out immediately').toHaveLength(1);
    await act(async () => {
      held[0]({ status: 'transport-error', message: 'Failed to sync profile: boom' });
    });
    expect(screen.getByTestId('save-status').textContent).toBe('cloud-failed');
    // The local copy IS clean — only the cloud one is stale.
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).resume_text).toBe('');

    await act(async () => { fireEvent.click(screen.getByTestId('retry-sync')); });
    expect(held, 'the retry re-sent it').toHaveLength(2);
    await act(async () => {
      held[1](await applyIntent(commitProfilePatch.mock.calls[1][0]));
    });
    expect(screen.getByTestId('save-status').textContent).toBe('saved');
    expect(commitProfilePatch.mock.calls).toHaveLength(2);
    expect((commitProfilePatch.mock.calls[1][0].patch as { resume_text?: string }).resume_text).toBe('');


  });
});

describe('useProfileForm — "saved on this device" is only claimed when there is nothing to sync to', () => {
  it('a confirmed local-only device reports device-only', async () => {
    commitProfilePatch.mockReset();
    commitProfilePatch.mockResolvedValue({ status: 'local-only' });
    mockStorageStatus = 'local-only';
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    await seedCreatableProfile();
    fireEvent.click(screen.getByTestId('set-interests'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(screen.getByTestId('save-status').textContent).toBe('device-only');

  });

  it('a cloud write that simply did not land is NOT device-only — it keeps the retry', async () => {
    commitProfilePatch.mockReset();
    // A cloud that IS there and did not answer. The difference from the test
    // above is the whole point: only `local-only` means "there is nothing to
    // sync to", and only that may be reported as saved-on-this-device.
    commitProfilePatch.mockResolvedValue({ status: 'transport-error', message: 'offline' });
    mockStorageStatus = 'unknown'; // e.g. the owner gate rejected the write
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    await seedCreatableProfile();
    fireEvent.click(screen.getByTestId('set-interests'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(screen.getByTestId('save-status').textContent).toBe('cloud-failed');

  });

  it('EN and ZH both have copy for every save state the UI can render', async () => {
    const { dictionaries } = await import('@/i18n/dictionaries');
    for (const locale of ['en', 'zh'] as const) {
      const actions = (dictionaries[locale].home as Record<string, unknown>).actions as Record<string, string>;
      for (const key of ['profileSaved', 'profileSaveFailed', 'profileCloudFailed', 'profileDeviceOnly', 'retrySync', 'profileLoading', 'profileLoadFailed', 'generating']) {
        expect(actions[key], `${locale}.home.actions.${key}`).toBeTruthy();
      }
    }
  });
});

describe('useProfileForm — the résumé really is gone from what a reload reads back', () => {
  it('a failed cloud removal SURVIVES the reload and is retried; the résumé never comes back', async () => {
    // A mutable stand-in for the profiles row: loadProfile reads it,
    // commitProfilePatch writes it, so "did the removal actually reach the cloud"
    // is answered by re-mounting rather than by counting mock calls.
    let remoteRow: Record<string, unknown> | null = {
      resume_text: 'the full text of my resume',
      coursework: ['ECE 220'],
      skills: [{ name: 'Python', level: 'experienced' }],
    };
    let rejectNextCloudWrite = true;
    let remoteRevision = 1;
    mockLoadProfile = () => Promise.resolve(
      remoteRow
        ? { source: 'cloud', profile: { ...remoteRow }, revision: remoteRevision, token: captureOwnerToken() }
        : absentRow(),
    );
    commitProfilePatch.mockReset();
    // A PATCH now, not a whole row: the fake merges it exactly as 027 does,
    // so "did the removal reach the cloud" is still answered by re-mounting.
    commitProfilePatch.mockImplementation(async (intent: ProfilePatchIntent) => {
      if (rejectNextCloudWrite) {
        rejectNextCloudWrite = false;
        return { status: 'transport-error', message: 'Failed to sync profile: boom' };
      }
      remoteRow = { ...(remoteRow ?? {}), ...intent.patch };
      remoteRevision += 1;
      return { status: 'saved', revision: remoteRevision, profile: remoteRow };
    });

    const first = render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('the full text of my resume'));
    await act(async () => { fireEvent.click(screen.getByTestId('remove-resume')); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('cloud-failed'));
    expect(remoteRow).toMatchObject({ resume_text: 'the full text of my resume' }); // cloud unchanged
    first.unmount();

    // Reload. The removal was made DURABLE before it was ever sent, so it is
    // still here — the cloud row's résumé does not reappear over an edit the
    // user made and never took back. Asking them to delete it twice is the
    // data loss this journal exists to stop.
    const second = render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe(''));
    expect(screen.getByTestId('coursework').textContent).toBe('');
    // …and it is retried on its own, without the user touching anything.
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saved'));
    expect(remoteRow).toMatchObject({ resume_text: '', coursework: [] });
    second.unmount();

    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('skills').textContent).toBe('Python'));
    expect(screen.getByTestId('resume').textContent).toBe('');
    expect(screen.getByTestId('coursework').textContent).toBe('');
    expect(remoteRow).toMatchObject({ resume_text: '', coursework: [] });


  });

  it('Retry after a failed removal writes the cleansed row, so a reload no longer revives it', async () => {
    let remoteRow: Record<string, unknown> | null = {
      resume_text: 'the full text of my resume',
      coursework: ['ECE 220'],
      skills: [],
    };
    let rejectNextCloudWrite = true;
    let remoteRevision = 1;
    mockLoadProfile = () => Promise.resolve(
      remoteRow
        ? { source: 'cloud', profile: { ...remoteRow }, revision: remoteRevision, token: captureOwnerToken() }
        : absentRow(),
    );
    commitProfilePatch.mockReset();
    // A PATCH now, not a whole row: the fake merges it exactly as 027 does,
    // so "did the removal reach the cloud" is still answered by re-mounting.
    // Each request is HELD, so the assertions below run on the turn the
    // response is released rather than polling a clock.
    const held: Array<(o: ProfilePatchOutcome) => void> = [];
    commitProfilePatch.mockImplementation(
      () => new Promise<ProfilePatchOutcome>((resolve) => { held.push(resolve); }),
    );
    const answer = (intent: ProfilePatchIntent): ProfilePatchOutcome => {
      if (rejectNextCloudWrite) {
        rejectNextCloudWrite = false;
        return { status: 'transport-error', message: 'Failed to sync profile: boom' };
      }
      remoteRow = { ...(remoteRow ?? {}), ...intent.patch };
      remoteRevision += 1;
      return { status: 'saved', revision: remoteRevision, profile: remoteRow };
    };

    const view = render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('the full text of my resume'));
    await act(async () => { fireEvent.click(screen.getByTestId('remove-resume')); });
    expect(held, 'the removal went out').toHaveLength(1);
    await act(async () => { held[0](answer(commitProfilePatch.mock.calls[0][0])); });
    expect(screen.getByTestId('save-status').textContent).toBe('cloud-failed');

    await act(async () => { fireEvent.click(screen.getByTestId('retry-sync')); });
    expect(held, 'the retry re-sent it').toHaveLength(2);
    await act(async () => { held[1](answer(commitProfilePatch.mock.calls[1][0])); });
    expect(screen.getByTestId('save-status').textContent).toBe('saved');
    expect(remoteRow).toMatchObject({ resume_text: '', coursework: [] });
    view.unmount();

    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    // Waited on the fact itself — the remount reading back an empty résumé —
    // rather than on a fixed slice of wall clock.
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe(''));


  });
});

describe('useProfileForm — the share receipt outlives the draft', () => {
  const withRef = (share: string) => `share=${share}&ref=newsletter`;

  it('a query change after Generate does not re-import the link or re-arm the draft gate', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(absentRow());
    const { rerender } = render(<Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('shared interests'));
    fireEvent.click(screen.getByTestId('make-valid'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(commitProfilePatch).toHaveBeenCalledTimes(1);

    commitProfilePatch.mockClear();
    searchRef.current = withRef(share);
    rerender(<Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    // Not re-imported (the edit below would otherwise be overwritten) and
    // not re-gated (it would otherwise never save).
    fireEvent.click(screen.getByTestId('set-interests'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(screen.getByTestId('interests').textContent).toBe('my interests');
    expect(commitProfilePatch).toHaveBeenCalledTimes(1);
  });

  it('a query change after a real account switch does not re-import the previous visitor\'s link', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(cloudRow({ research_interests: 'u3 own row' }));
    const { rerender } = render(<Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('shared interests'));

    await emitAuth('identity-u2');
    await emitAuth('identity-u3');
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe('u3 own row'));

    searchRef.current = withRef(share);
    rerender(<Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    expect(screen.getByTestId('interests').textContent).toBe('u3 own row');
    expect(screen.getByTestId('shared-banner').textContent).toBe('');
    fireEvent.click(screen.getByTestId('set-interests'));
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(commitProfilePatch).toHaveBeenCalledTimes(1); // saves normally, no draft gate
  });
});

describe('useProfileForm — a save that half-landed is never a dead end', () => {
  it('local write blocked + cloud rejected: reported as an error, and Retry still finishes the job', async () => {
    let rejectCloud = true;
    commitProfilePatch.mockReset();
    // A cloud write that does not land REPORTS that; commitProfilePatch
    // turns transport failures into a typed outcome rather than rejecting,
    // so a mock that rejects would be testing a shape production never
    // produces.
    commitProfilePatch.mockImplementation((intent) => (
      rejectCloud
        ? Promise.resolve<ProfilePatchOutcome>({ status: 'transport-error', message: 'boom' })
        : defaultCommit(intent)
    ));
    mockLoadProfile = () => Promise.resolve(cloudRow({ resume_text: 'old text', coursework: ['ECE 220'] }));
    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('old text'));

    // Storage is refusing writes (quota / private mode) — the identity is
    // unchanged, only the write fails.
    const setItemSpy = await registerSpy(vi.spyOn(window.localStorage, 'setItem')).mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    await act(async () => { fireEvent.click(screen.getByTestId('remove-resume')); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('error'));
    // Still the row as loaded: the removal reached neither the journal nor
    // the mirror, which is exactly why it is reported as a failure.
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).resume_text).toBe('old text');

    // Storage comes back and so does the network: the SAME cleansed
    // snapshot is replayed, both halves, under the SAME owner.
    setItemSpy.mockRestore();
    rejectCloud = false;
    await act(async () => { fireEvent.click(screen.getByTestId('retry-sync')); });

    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saved'));
    const stored = JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE)!);
    expect(stored.resume_text).toBe('');
    expect(stored.coursework).toEqual([]);

  });

  it('cloud saved but the local mirror did not: says so, and does not claim the cloud failed', async () => {
    commitProfilePatch.mockReset();
    let setItemSpy: { mockRestore: () => void } | null = null;
    // Storage dies WHILE the request is in flight — the removal reaches the
    // cloud, and this browser can no longer record that it did. That is the
    // only shape "half-landed" still has: a device that cannot write AT ALL
    // never gets as far as sending (the test below).
    commitProfilePatch.mockImplementation(async (intent) => {
      const outcome = await applyIntent(intent);
      // Installed once: spying twice would stack wrappers, and restoring the
      // outer one would leave a still-throwing setItem behind for whatever
      // test runs next.
      setItemSpy ??= await registerSpy(vi.spyOn(window.localStorage, 'setItem')).mockImplementation(() => {
        throw new Error('QuotaExceededError');
      });
      return outcome;
    });
    mockLoadProfile = () => Promise.resolve(cloudRow({ resume_text: 'old text', coursework: ['ECE 220'] }));
    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('old text'));

    await act(async () => { fireEvent.click(screen.getByTestId('remove-resume')); });

    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('device-failed'));
    // The cloud really does hold the cleansed row: the status is about this
    // device, and must not be read as "the removal did not happen".
    expect((serverRow as { resume_text?: string }).resume_text).toBe('');
    setItemSpy!.mockRestore();
  });

  it('a device that cannot write at all sends NOTHING and says the save failed', async () => {
    commitProfilePatch.mockReset();
    commitProfilePatch.mockImplementation(defaultCommit);
    mockLoadProfile = () => Promise.resolve(cloudRow({ resume_text: 'old text', coursework: ['ECE 220'] }));
    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('old text'));
    commitProfilePatch.mockClear();

    // The spy hands the test a handshake: it reports the first attempted write
    // before refusing it, so the assertion below waits on the thing that
    // actually has to happen rather than polling a clock.
    let attempted!: () => void;
    const firstWrite = new Promise<void>((resolve) => { attempted = resolve; });
    const setItemSpy = await registerSpy(vi.spyOn(window.localStorage, 'setItem')).mockImplementation(() => {
      attempted();
      throw new Error('QuotaExceededError');
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('remove-resume'));
      await firstWrite;
      await Promise.resolve();
    });

    // 'error', NOT 'device-failed': device-failed promises the cloud has it.
    expect(screen.getByTestId('save-status').textContent).toBe('error');
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect((serverRow as { resume_text?: string }).resume_text).toBe('old text');
  });
});

describe('useProfileForm — a retry only repeats the half that failed', () => {
  it('after a local-only failure the retry does not touch the cloud again', async () => {
    commitProfilePatch.mockReset();
    let cloudCalls = 0;
    let setItemSpy: { mockRestore: () => void } | null = null;
    commitProfilePatch.mockImplementation(async (intent) => {
      cloudCalls += 1;
      // The FIRST cloud write succeeds and storage dies as it lands, so the
      // confirmation cannot be recorded. A second write would be a duplicate
      // — and this one fails, turning a fixed problem into a false
      // "we couldn't sync".
      if (cloudCalls > 1) return { status: 'transport-error', message: 'duplicate' };
      const outcome = defaultCommit(intent);
      setItemSpy ??= await registerSpy(vi.spyOn(window.localStorage, 'setItem')).mockImplementation(() => {
        throw new Error('QuotaExceededError');
      });
      return outcome;
    });
    mockLoadProfile = () => Promise.resolve(cloudRow({ resume_text: 'old text', coursework: ['ECE 220'] }));
    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('old text'));

    await act(async () => { fireEvent.click(screen.getByTestId('remove-resume')); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('device-failed'));
    expect(cloudCalls).toBe(1);

    setItemSpy!.mockRestore();
    await act(async () => { fireEvent.click(screen.getByTestId('retry-sync')); });

    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saved'));
    expect(cloudCalls).toBe(1); // not re-sent
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).resume_text).toBe('');

  });

  it('after a cloud-only failure the retry re-sends only the cloud half', async () => {
    commitProfilePatch.mockReset();
    let cloudCalls = 0;
    commitProfilePatch.mockImplementation((intent) => {
      cloudCalls += 1;
      return cloudCalls === 1
        ? Promise.resolve<ProfilePatchOutcome>({ status: 'transport-error', message: 'boom' })
        : defaultCommit(intent);
    });
    mockLoadProfile = () => Promise.resolve(cloudRow({ resume_text: 'old text', coursework: ['ECE 220'] }));
    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('old text'));

    await act(async () => { fireEvent.click(screen.getByTestId('remove-resume')); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('cloud-failed'));
    const localAfterFirst = localStorage.getItem(STORAGE_KEYS.PROFILE);
    expect(JSON.parse(localAfterFirst!).resume_text).toBe('');

    await act(async () => { fireEvent.click(screen.getByTestId('retry-sync')); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saved'));
    expect(cloudCalls).toBe(2);
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBe(localAfterFirst);

  });
});

describe('useProfileForm — a retry belongs to the account that made the failed save', () => {
  async function failedRemovalUnder(uid: string) {
    commitProfilePatch.mockReset();
    commitProfilePatch.mockResolvedValue({ status: 'transport-error', message: 'boom' });
    mockLoadProfile = () => Promise.resolve(cloudRow({ resume_text: 'old text', coursework: ['ECE 220'] }));
    advanceOwnerEpoch(uid);
    await syncLocalIdentityOwner(uid);
    render(<Suspense fallback={null}><ResumeRemovalHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('resume').textContent).toBe('old text'));
    await act(async () => { fireEvent.click(screen.getByTestId('remove-resume')); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('cloud-failed'));
    commitProfilePatch.mockReset();
    commitProfilePatch.mockImplementation(defaultCommit);
  }

  it('drops the payload when the global owner moved on before this hook saw the auth event', async () => {
    await failedRemovalUnder('retry-scope-u1');
    // Another tab switched accounts: the global owner is U2, but no auth
    // event has reached this hook yet, so its generation is unchanged.
    advanceOwnerEpoch('retry-scope-u2');
    await syncLocalIdentityOwner('retry-scope-u2');

    const localBefore = localStorage.getItem(STORAGE_KEYS.PROFILE);
    const setItemSpy = await registerSpy(vi.spyOn(window.localStorage, 'setItem'));
    await act(async () => { fireEvent.click(screen.getByTestId('retry-sync')); });

    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(setItemSpy).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBe(localBefore);
    setItemSpy.mockRestore();

  });

  it('drops the payload across a sign-out and back in as the SAME account', async () => {
    await failedRemovalUnder('retry-scope-u1');
    advanceOwnerEpoch(null);
    advanceOwnerEpoch('retry-scope-u1'); // same uid, new epoch
    await syncLocalIdentityOwner('retry-scope-u1');

    const localBefore = localStorage.getItem(STORAGE_KEYS.PROFILE);
    const setItemSpy = await registerSpy(vi.spyOn(window.localStorage, 'setItem'));
    await act(async () => { fireEvent.click(screen.getByTestId('retry-sync')); });

    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(setItemSpy).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBe(localBefore);
    setItemSpy.mockRestore();

  });

  it('replays it when the same account is still active and storage recovered', async () => {
    await failedRemovalUnder('retry-scope-u1');

    await act(async () => { fireEvent.click(screen.getByTestId('retry-sync')); });

    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saved'));
    expect(commitProfilePatch).toHaveBeenCalledTimes(1);

  });
});

describe('useProfileForm — edge cases that used to write when they should not', () => {
  it('a ?share= arriving after the visitor already edited cancels their pending save', async () => {
    commitProfilePatch.mockClear();
    const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
    searchRef.current = '';
    mockLoadProfile = () => Promise.resolve(absentRow());
    const { rerender, unmount } = render(
      <Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>,
    );
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    fireEvent.click(screen.getByTestId('set-interests')); // arms a save of their OWN profile

    searchRef.current = `share=${share}`;
    rerender(<Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(screen.getByTestId('interests').textContent).toBe('shared interests');

    unmount();
    await act(async () => {});
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
  });

  it('whitespace-only required fields are not a valid profile', async () => {
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(cloudRow({ college: '   ', major: '\t', grade: ' ' }));
    await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });

    // The gate is `isValid`, and it is false: three fields that LOOK filled in
    // and trim to nothing.
    expect(screen.getByTestId('valid').textContent).toBe('no');
    // Untouched: exactly the row that was loaded, no submit-time write on top.
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!))
      .toEqual({ college: '   ', major: '\t', grade: ' ' });
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it('a submit whose GitHub import resolves after the page was left writes nothing and does not navigate', async () => {
    let resolveImport: ((v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void) | undefined;
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolveImport = resolve as never; }),
    );
    commitProfilePatch.mockClear();
    mockLoadProfile = () => Promise.resolve(absentRow());
    const { unmount } = await renderIdentityHarness();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    fireEvent.click(screen.getByTestId('make-valid'));
    fireEvent.click(screen.getByTestId('set-gh'));
    fireEvent.click(screen.getByTestId('submit'));
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(1));

    unmount();
    // The unmount flush legitimately persists the edit that was already
    // pending; what must NOT happen is the submit continuing afterwards.
    await act(async () => {});
    const afterUnmount = localStorage.getItem(STORAGE_KEYS.PROFILE);
    commitProfilePatch.mockClear();
    cacheMocks.clearMatchCache.mockClear();
    await act(async () => {
      resolveImport?.({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBe(afterUnmount);
    expect(JSON.parse(afterUnmount!).skills).toEqual([]);
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });
});

type Settle = {
  intent: ProfilePatchIntent;
  resolve: (v: ProfilePatchOutcome) => void;
  reject: (e: Error) => void;
};

describe('useProfileForm — arriving at a shared link fences everything the visitor had in flight', () => {
  // The three ways a save can come back: confirmed, refused, or — off
  // contract, but the coordinator must survive it — thrown.
  it.each([
    ['succeeds', (settle: Settle) => settle.resolve(applyIntent(settle.intent))],
    ['reports no cloud write', (settle: Settle) => settle.resolve({ status: 'transport-error', message: 'boom' })],
    ['rejects', (settle: Settle) => settle.reject(new Error('boom'))],
  ])(
    'cancels the pending save, and an earlier save that later %s cannot touch the draft UI',
    async (_label, settleIt) => {
      let settle: Settle | undefined;
      commitProfilePatch.mockReset();
      commitProfilePatch.mockImplementation(
        (intent) => new Promise<ProfilePatchOutcome>((resolve, reject) => {
          settle = { intent, resolve, reject };
        }),
      );
      const share = encodeProfile({ ...DEFAULT_PROFILE, research_interests: 'shared interests' });
      searchRef.current = '';
      mockLoadProfile = () => Promise.resolve(absentRow());
      const { rerender, unmount } = render(
        <Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>,
      );
      await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

      await seedCreatableProfile();
      fireEvent.click(screen.getByTestId('set-interests'));
      await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saving'));
      // Let that first save actually go out, so there IS a late outcome.
      await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
      expect(commitProfilePatch).toHaveBeenCalledTimes(1);
      fireEvent.click(screen.getByTestId('set-college')); // arms a SECOND, still-pending save

      searchRef.current = `share=${share}`;
      rerender(<Suspense fallback={null}><LocaleSwitchHarness t={stableT} /></Suspense>);
      await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
      expect(screen.getByTestId('interests').textContent).toBe('shared interests');
      expect(screen.getByTestId('save-status').textContent).toBe('idle');

      // The second save's debounce would have fired by now.
      await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
      expect(commitProfilePatch).toHaveBeenCalledTimes(1);

      // The first save's outcome lands late: whatever it says, it is about
      // a profile that is no longer on screen.
      await act(async () => { settleIt(settle!); await Promise.resolve(); });
      expect(screen.getByTestId('save-status').textContent).toBe('idle');

      // …and it left nothing for the visitor to "retry" into the draft.
      await act(async () => { fireEvent.click(screen.getByTestId('retry-sync')); });
      expect(commitProfilePatch).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId('save-status').textContent).toBe('idle');

      unmount();
      await act(async () => {});
      expect(commitProfilePatch).toHaveBeenCalledTimes(1); // no unmount flush either

    },
  );
});

describe('useProfileForm — leaving the page stops a submit that has nothing pending behind it', () => {
  it('a hydrated, unedited profile: submit → unmount → the import resolving writes nothing', async () => {
    let resolveImport: ((v: { username: string; extracted_skills: string[]; topics: string[]; repo_count: number; top_repos: [] }) => void) | undefined;
    vi.mocked(parseGitHubProfile).mockReset();
    vi.mocked(parseGitHubProfile).mockImplementation(
      () => new Promise((resolve) => { resolveImport = resolve as never; }),
    );
    commitProfilePatch.mockClear();
    // Everything comes from the row, so the user makes NO edit: there is
    // no pending save for the unmount flush to write.
    mockLoadProfile = () => Promise.resolve(cloudRow({
      college: 'Grainger', major: 'CS', grade: 'Junior',
      github_url: 'https://github.com/octocat',
    }));
    const { unmount } = await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('college').textContent).toBe('Grainger'));
    fireEvent.click(screen.getByTestId('submit'));
    await waitFor(() => expect(parseGitHubProfile).toHaveBeenCalledTimes(1));

    unmount();
    await act(async () => {
      resolveImport?.({ username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [] });
      await new Promise((r) => setTimeout(r, 20));
    });

    // The mirror holds the row the load projected, and nothing the abandoned
    // submit was carrying — no imported skills, no request, no navigation.
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!)).toEqual({
      college: 'Grainger', major: 'CS', grade: 'Junior',
      github_url: 'https://github.com/octocat',
    });
    expect(commitProfilePatch).not.toHaveBeenCalled();
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });
});

describe('useProfileForm — an unrelated success never retires somebody else\'s question', () => {
  it('a clean grade save leaves a journal-only disagreement about major exactly where it was', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow(
      { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 }, 8,
    ));
    const first = await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('8'));

    // Two tabs want different majors. Nothing locks in the outbox — this
    // disagreement lives entirely in the journal.
    act(() => { screen.getByTestId('set-major-ece').click(); });
    startDocumentForTests('other');
    recordProfileIntent(
      { ...DEFAULT_PROFILE, college: 'Grainger', major: 'Statistics', grade: 'Junior' },
      ['major'],
      captureOwnerToken(),
    );
    first.unmount();

    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('conflict-keys').textContent).toBe('major'));
    commitProfilePatch.mockClear();

    // A completely unrelated field, saved cleanly.
    act(() => { screen.getByTestId('set-grade-senior').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    waitFor(() => expect(sentPatches()).toContainEqual({ grade: 'Senior' }));

    // The success says nothing about major. Clearing the question here takes
    // a live disagreement off the screen while it is still in the journal,
    // unanswered and unanswerable.
    expect(screen.getByTestId('conflict-keys').textContent,
      'the question nobody answered is still there').toBe('major');
  });
});

describe('useProfileForm — the accepted base is a fail-closed gate, not an assignment', () => {
  it('an acknowledgement at the SAME revision but a different row is refused, not adopted', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow(
      { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 }, 8,
    ));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('8'));

    // A response that claims revision 8 — the revision already accepted —
    // while describing a different row. Under CAS that pair cannot exist, so
    // the only safe reading is that this device cannot tell which row is real.
    commitProfilePatch.mockClear();
    commitProfilePatch.mockImplementationOnce(async () => ({
      status: 'saved' as const,
      revision: 8,
      profile: { college: 'LAS', major: 'Bioengineering', grade: 'Junior', search_weight: 50 },
    }));
    act(() => { screen.getByTestId('set-major-ece').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    // The baseline does NOT quietly become the row it cannot account for.
    expect(screen.getByTestId('view-rev').textContent).toBe('8');
    expect(commitProfilePatch, 'the impossible answer really was delivered')
      .toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('view-base-major').textContent,
      'the accepted base is untouched').toBe('CS');
    // Fail-closed at the coordinator: the envelope refuses to record a
    // confirmation that does not advance the revision, so Home is never
    // handed a 'saved' it could adopt. Asserted here so a later change that
    // moves that gate cannot silently hand the row over instead.
    expect(screen.getByTestId('save-status').textContent,
      'and it is reported as a device failure, not a clean save').toBe('device-failed');
  });

  it('an acknowledgement at a LOWER revision cannot move the baseline back', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow(
      { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 }, 8,
    ));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('8'));

    commitProfilePatch.mockClear();
    commitProfilePatch.mockImplementationOnce(async () => ({
      status: 'already-saved' as const,
      revision: 7,
      profile: { college: 'Grainger', major: 'Older', grade: 'Junior', search_weight: 50 },
    }));
    act(() => { screen.getByTestId('set-major-ece').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(screen.getByTestId('view-rev').textContent, 'forward only').toBe('8');
  });
});

describe('useProfileForm — a generic conflict is reconciled canonically, never published raw', () => {
  const ROW = { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 };

  /** A conflict payload as the coordinator shapes one. */
  function question(key: string, revision: number, remote: unknown, mutationId = 'm1') {
    return {
      key,
      remote,
      remoteRevision: revision,
      mutationId,
      keyVersion: 1,
      candidates: [{ value: 'mine', lineage: 'lin-a', opIds: [`op-${key}-${revision}`] }],
    };
  }

  /** Puts a rev10 question about `major` on screen through the real handler. */
  async function currentQuestionAtRev10() {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['major'],
      conflicts: [await question('major', 10, 'Statistics')],
    });
    syncOverrides.refreshConflictQuestion = async () => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Statistics' },
      revision: 10,
      conflicts: [await question('major', 10, 'Statistics')],
      pendingKeys: ['major'],
      flushed: null,
    });
    act(() => { screen.getByTestId('set-major-ece').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('conflict-revs').textContent).toBe('major@10'));
    syncOverrides.refreshCalls = [];
  }

  it('a LATE lower-revision conflict is rebuilt canonically, not published', async () => {
    await currentQuestionAtRev10();

    // A handler result describing revision 9 — a row this device has moved
    // past. Publishing it puts a dead question on screen; the only sound
    // answer is to rebuild from the canonical state.
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 9,
      remote: { ...ROW, major: 'Older' },
      confirmed: { revision: 9, profile: { ...ROW, major: 'Older' } },
      conflictKeys: ['grade'],
      conflicts: [await question('grade', 9, 'Junior')],
    });
    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(syncOverrides.refreshCalls.length,
      'the canonical state is what decides, not the late payload')
      .toBeGreaterThan(0);
    expect([...syncOverrides.refreshCalls[0].keys].sort(),
      'and it asks about the union of what is shown and what arrived')
      .toEqual(['grade', 'major']);
    expect(screen.getByTestId('conflict-revs').textContent,
      'the canonical answer wins').toBe('major@10');
  });

  it('same-snapshot disjoint questions are BOTH visible, neither dropped', async () => {
    await currentQuestionAtRev10();

    // A second, disjoint disagreement about the same row.
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['grade'],
      conflicts: [await question('grade', 10, 'Junior')],
    });
    syncOverrides.refreshConflictQuestion = async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Statistics' },
      revision: 10,
      conflicts: [...keys].sort().map((k) => question(k, 10, k === 'major' ? 'Statistics' : 'Junior')),
      pendingKeys: [...keys],
      flushed: null,
    });
    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(screen.getByTestId('conflict-keys').textContent.split(',').sort(),
      'the arriving question does not evict the one already there')
      .toEqual(['grade', 'major']);
  });

  it('an owner that moves while the canonical rebuild is awaited applies nothing', async () => {
    await currentQuestionAtRev10();

    let release!: (v: unknown) => void;
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['grade'],
      conflicts: [await question('grade', 10, 'Junior')],
    });
    syncOverrides.refreshConflictQuestion = () => new Promise((resolve) => { release = resolve; });

    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(syncOverrides.refreshCalls.length, 'the rebuild is in flight').toBeGreaterThan(0);

    await act(async () => {
      advanceOwnerEpoch('rebuild-u2');
      release({
        status: 'current',
        profile: { ...ROW, major: 'Whatever' },
        baseProfile: { ...ROW, major: 'Whatever' },
        revision: 44,
        conflicts: [await question('grade', 44, 'Junior')],
        pendingKeys: [],
        flushed: null,
      });
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByTestId('conflict-revs').textContent,
      "nothing of the dead identity's rebuild is applied").toBe('major@10');
    expect(screen.getByTestId('view-rev').textContent).not.toBe('44');
  });

  it('the resolution latch is held until the canonical rebuild finishes', async () => {
    await currentQuestionAtRev10();

    // The button's answer is stale, so the stale branch rebuilds — and that
    // rebuild is held open by the test. The latch must survive it.
    let resolveCalls = 0;
    syncOverrides.resolveProfileConflict = (async () => {
      resolveCalls += 1;
      return { status: 'stale-conflict' as const };
    }) as never;
    let release!: (v: unknown) => void;
    syncOverrides.refreshConflictQuestion = (
      () => new Promise((resolve) => { release = resolve; })
    ) as never;

    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(resolveCalls, 'the first click owns the resolution').toBe(1);

    // A second click while that nested rebuild is still running.
    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(resolveCalls, 'the latch is still held, so nothing else may answer').toBe(1);

    await act(async () => {
      release({
        status: 'current',
        profile: { ...ROW, major: 'ECE' },
        baseProfile: { ...ROW, major: 'Statistics' },
        revision: 10,
        conflicts: [await question('major', 10, 'Statistics')],
        pendingKeys: ['major'],
        flushed: null,
      });
      await new Promise((r) => setTimeout(r, 20));
    });
    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(resolveCalls, 'once it is finished, the buttons work again').toBe(2);
  });

  it('a settled rebuild for an intent that no longer owns the status leaves Retry alone', async () => {
    await currentQuestionAtRev10();
    let release!: (v: unknown) => void;
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['grade'],
      conflicts: [await question('grade', 10, 'Junior')],
    });
    syncOverrides.refreshConflictQuestion = () => new Promise((resolve) => { release = resolve; });
    vi.useFakeTimers();
    try {
      act(() => { screen.getByTestId('set-interests').click(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });

      // A NEWER edit fails locally: it owns the status and the retry.
      syncOverrides.stageProfilePatch = async () => ({
        status: 'device-failed' as const, phase: 'stage' as const,
      });
      act(() => { screen.getByTestId('set-grade-senior').click(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    } finally {
      vi.useRealTimers();
    }
    expect(screen.getByTestId('save-status').textContent).toBe('error');

    // The OLD rebuild finally settles. Clearing the retry slot here disarms
    // the newer failure's only way back.
    await act(async () => {
      release({
        status: 'settled',
        profile: { ...ROW, major: 'ECE' },
        baseProfile: { ...ROW, major: 'Statistics' },
        revision: 10,
        conflicts: [],
        pendingKeys: [],
        flushed: null,
      });
      await new Promise((r) => setTimeout(r, 20));
    });

    // Retry must still be armed for the newer failure. Disarmed, the button
    // is a no-op and the form stays stuck on its own error with no way out.
    syncOverrides.flushPendingProfileWrite = async () => (
      { status: 'saved' as const, revision: 11, profile: { ...ROW, grade: 'Senior' } }
    );
    syncOverrides.flushCalls = 0;
    await act(async () => {
      screen.getByTestId('retry-sync').click();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(syncOverrides.flushCalls,
      'Retry replays the write that actually failed, exactly once').toBe(1);
    expect(screen.getByTestId('save-status').textContent).toBe('saved');
  });

  it('a rebuild that REJECTS reaches the owning catch, with nothing left unhandled', async () => {
    await currentQuestionAtRev10();
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['grade'],
      conflicts: [await question('grade', 10, 'Junior')],
    });
    syncOverrides.refreshConflictQuestion = () => Promise.reject(new Error('rebuild exploded'));

    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    // Reported through the chain's own catch — a detached rebuild would take
    // the process's unhandled-rejection path instead and say nothing.
    expect(screen.getByTestId('save-status').textContent).toBe('cloud-failed');
    expect(screen.getByTestId('conflict-revs').textContent,
      'and the question on screen is untouched').toBe('major@10');
  });

  it('disjoint questions are answered one at a time, and neither swallows the other', async () => {
    await currentQuestionAtRev10();
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['grade'],
      conflicts: [await question('grade', 10, 'Junior')],
    });
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Statistics' },
      revision: 10,
      conflicts: [...keys].sort().map((k) => question(k, 10, k === 'major' ? 'Statistics' : 'Junior')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;
    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(
      screen.getByTestId('conflict-keys').textContent.split(',').sort(),
    ).toEqual(['grade', 'major']));

    // Answer ONE of them. The other must survive the answer.
    const answered: string[][] = [];
    syncOverrides.resolveProfileConflict = (async (
      opts: { prompt: { conflicts: readonly { key: string }[] } },
    ) => {
      answered.push(opts.prompt.conflicts.map((c) => c.key));
      return { status: 'saved' as const, revision: 11, profile: { ...ROW, grade: 'Senior' } };
    }) as never;
    // The answer moved the row: the canonical state the remainder is rebuilt
    // from is revision 11 now.
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, grade: 'Senior', major: 'ECE' },
      baseProfile: { ...ROW, grade: 'Senior', major: 'Statistics' },
      revision: 11,
      conflicts: [...keys].map((k) => question(k, 11, 'Statistics')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;
    await act(async () => {
      screen.getByTestId('keep-grade').click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(answered, 'exactly the one field was answered').toEqual([['grade']]);
    expect(screen.getByTestId('conflict-keys').textContent,
      'and the other question is still there to answer').toBe('major');
    // Not a locally filtered leftover: the remaining disagreement is rebuilt
    // from the canonical state the answer left behind, at ITS revision.
    expect(syncOverrides.refreshCalls.at(-1)?.keys,
      'the remainder is rebuilt, not filtered').toEqual(['major']);
    expect(screen.getByTestId('conflict-revs').textContent,
      'and it describes the row as it stands after the answer').toBe('major@11');
  });

  /** Two open questions at revision 10, published canonically. */
  async function twoQuestionsAtRev10() {
    await currentQuestionAtRev10();
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['grade'],
      conflicts: [await question('grade', 10, 'Junior')],
    });
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Statistics' },
      revision: 10,
      conflicts: [...keys].sort().map((k) => question(k, 10, k === 'major' ? 'Statistics' : 'Junior')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;
    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(
      screen.getByTestId('conflict-keys').textContent.split(',').sort(),
    ).toEqual(['grade', 'major']));
  }

  it('a STALE answer about one field does not retire the field nobody asked about', async () => {
    await twoQuestionsAtRev10();
    syncOverrides.resolveProfileConflict = (async () => ({ status: 'stale-conflict' as const })) as never;
    // The rebuild must be asked about the WHOLE question on screen. Told only
    // about `grade`, it can say nothing about `major` — and its answer would
    // then decide a disagreement it never looked at.
    let askedKeys: string[] = [];
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => {
      askedKeys = [...keys].sort();
      return {
        status: 'current' as const,
        profile: { ...ROW, grade: 'Senior', major: 'ECE' },
        baseProfile: { ...ROW, grade: 'Senior', major: 'Statistics' },
        revision: 11,
        conflicts: askedKeys.includes('major') ? [await question('major', 11, 'Statistics')] : [],
        pendingKeys: ['major'],
        flushed: null,
      };
    }) as never;

    await act(async () => {
      screen.getByTestId('keep-grade').click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(askedKeys, 'the rebuild is about the whole question on screen')
      .toEqual(['grade', 'major']);
    expect(screen.getByTestId('conflict-revs').textContent,
      'and what is left comes back canonical').toBe('major@11');
  });

  it('a partial Use Cloud does not overwrite the other question or an unrelated edit', async () => {
    await twoQuestionsAtRev10();
    // Typed after the questions went up.
    act(() => { screen.getByTestId('set-gh').click(); });
    syncOverrides.resolveProfileConflict = (async () => ({
      status: 'saved' as const,
      revision: 11,
      profile: { ...ROW, grade: 'Senior', major: 'Statistics' },
    })) as never;
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, grade: 'Senior', major: 'ECE' },
      baseProfile: { ...ROW, grade: 'Senior', major: 'Statistics' },
      revision: 11,
      conflicts: [...keys].map((k) => question(k, 11, 'Statistics')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;

    await act(async () => {
      screen.getByTestId('cloud-grade').click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('grade').textContent,
      "the answered field takes the other device's value").toBe('Senior');
    expect(screen.getByTestId('gh-url').textContent,
      'and the edit made while the prompt was up survives').toBe('https://github.com/octocat');
    expect(screen.getByTestId('major').textContent,
      "the still-disputed field keeps this device's value").toBe('ECE');
    expect(screen.getByTestId('conflict-revs').textContent,
      'and its question is the canonical one').toBe('major@11');
  });

  it('a newer intent silences the wording, not the server facts a retry brought back', async () => {
    await currentQuestionAtRev10();
    let release!: (v: unknown) => void;
    syncOverrides.flushPendingProfileWrite = () => new Promise((resolve) => { release = resolve; });
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Newer' },
      revision: 12,
      conflicts: [...keys].map((k) => question(k, 12, 'Newer')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;

    await act(async () => {
      screen.getByTestId('retry-sync').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    // A newer edit arms while the retry is open.
    act(() => { screen.getByTestId('set-interests').click(); });

    await act(async () => {
      release({
        status: 'conflict',
        revision: 12,
        remote: { ...ROW, major: 'Newer' },
        confirmed: { revision: 12, profile: { ...ROW, major: 'Newer' } },
        conflictKeys: ['major'],
        conflicts: [await question('major', 12, 'Newer')],
      });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('conflict-revs').textContent,
      'the disagreement the server reported is still applied').toBe('major@12');
    expect(screen.getByTestId('view-rev').textContent,
      'and so is the row it described').toBe('12');
  });

  it('D1: an edit made during Submit keeps its facts but wins the navigation', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    cacheMocks.clearMatchCache.mockClear();
    pushSpy.mockClear();

    let release!: (v: unknown) => void;
    syncOverrides.stageProfilePatch = () => new Promise((resolve) => { release = resolve; });
    act(() => { screen.getByTestId('set-major-ece').click(); });
    await act(async () => { screen.getByTestId('submit').click(); });

    // The person keeps typing while the submit's write is open.
    act(() => { screen.getByTestId('set-interests').click(); });

    const laterPatches: { keys: string[]; interests: unknown }[] = [];
    syncOverrides.stageProfilePatch = (async (
      patch: Record<string, unknown>, keys: readonly string[],
    ) => {
      laterPatches.push({ keys: [...keys], interests: patch.research_interests });
      return {
        status: 'saved' as const,
        revision: 11,
        profile: { ...ROW, major: 'ECE', research_interests: 'my interests' },
      };
    }) as never;
    await act(async () => {
      release({ status: 'saved', revision: 10, profile: { ...ROW, major: 'ECE' } });
      await new Promise((r) => setTimeout(r, 50));
    });

    // The row IS at 10 — that is the server speaking, and the next edit has to
    // be measured against it.
    expect(screen.getByTestId('view-rev').textContent,
      'the server fact still lands').toBe('10');
    // But the form is no longer what was submitted. Clearing the cache and
    // navigating now takes the person to matches generated from a profile
    // they have already changed.
    expect(cacheMocks.clearMatchCache, 'no cache is cleared for a form that moved on')
      .not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();
    expect(screen.getByTestId('interests').textContent).toBe('my interests');

    // And the newer edit still saves on its own.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    const carried = laterPatches.find((c) => c.keys.includes('research_interests'));
    expect(carried, 'the newer edit is still persisted, as itself').toBeTruthy();
    expect(carried!.interests,
      'and with the value the person actually typed, not the submitted snapshot')
      .toBe('my interests');
  });

  it('D2: an edit made during a resolve is not overwritten by the old answer', async () => {
    await currentQuestionAtRev10();
    let release!: (v: unknown) => void;
    syncOverrides.resolveProfileConflict = (
      () => new Promise((resolve) => { release = resolve; })
    ) as never;
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Newer' },
      revision: 12,
      conflicts: [...keys].map((k) => question(k, 12, 'Newer')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;

    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    // The person changes the SAME field again while the answer is open.
    act(() => { screen.getByTestId('set-major-physics').click(); });

    await act(async () => {
      release({ status: 'saved', revision: 11, profile: { ...ROW, major: 'ECE' } });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('major').textContent,
      'what the person typed last is what they see').toBe('Physics');
    expect(screen.getByTestId('view-rev').textContent,
      'and the server fact still lands').toBe('11');
  });

  it('D3: a recovered flush that lands late keeps its facts and stays quiet', async () => {
    let release!: (v: unknown) => void;
    syncOverrides.hydrateProfile = (async () => ({
      profile: { ...ROW },
      baseProfile: { ...ROW },
      revision: 9,
      source: 'cloud' as const,
      token: captureOwnerToken(),
      hasPending: true,
      conflictKeys: [] as string[],
      conflicts: [],
      quarantineFailed: false,
    })) as never;
    syncOverrides.flushPendingProfileWrite = () => new Promise((resolve) => { release = resolve; });
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Newer' },
      revision: 12,
      conflicts: [...keys].map((k) => question(k, 12, 'Newer')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;

    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    // The recovery flush really was armed — a test that skipped when it was
    // not would pass by describing nothing.
    await waitFor(() => expect(syncOverrides.flushCalls).toBe(1));
    expect(release, 'and it is being held open here').toBeTypeOf('function');

    // A click alone only records an intent and arms a timer. The autosave has
    // to actually START — that is what takes the save intent, and without it
    // "the newer edit owns the wording" is not being tested at all.
    const stagesBefore = syncOverrides.stageCalls;
    // Deferred and never answered: the newer edit's write stays open, so the
    // save intent is genuinely taken while the old recovery lands. Real
    // timing on purpose — advancing a fake clock here would wait on that very
    // promise.
    syncOverrides.stageProfilePatch = () => new Promise(() => {});
    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1650)); });
    expect(syncOverrides.stageCalls, 'the newer edit is really in flight')
      .toBeGreaterThan(stagesBefore);
    expect(screen.getByTestId('save-status').textContent,
      'and it owns the wording before the old result arrives').toBe('saving');

    await act(async () => {
      release({
        status: 'conflict',
        revision: 12,
        remote: { ...ROW, major: 'Newer' },
        confirmed: { revision: 12, profile: { ...ROW, major: 'Newer' } },
        conflictKeys: ['major'],
        conflicts: [await question('major', 12, 'Newer')],
      });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('conflict-revs').textContent,
      "the recovered write's disagreement is still reported").toBe('major@12');
    expect(screen.getByTestId('view-rev').textContent,
      'and the row it described is the baseline now').toBe('12');
    expect(screen.getByTestId('save-status').textContent,
      'while the newer edit still owns the wording').toBe('saving');
    expect(screen.getByTestId('interests').textContent,
      'and the newer edit itself is untouched').toBe('my interests');
  });

  it('D1b: on a shared draft, where nothing bumps the save intent, the EDIT still wins', async () => {
    // A shared draft: the autosave effect deliberately persists nothing, so
    // the save intent never moves. The only thing that changes when the
    // person types is the edit count — which is exactly what this gate is.
    const share = encodeProfile({
      ...DEFAULT_PROFILE, college: 'Grainger', major: 'CS', grade: 'Junior',
    });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('valid').textContent).toBe('yes'));
    cacheMocks.clearMatchCache.mockClear();
    pushSpy.mockClear();

    let release!: (v: unknown) => void;
    syncOverrides.stageProfilePatch = () => new Promise((resolve) => { release = resolve; });
    await act(async () => { screen.getByTestId('submit').click(); });
    expect(release, "the submit's write is open").toBeTypeOf('function');
    const intentBefore = screen.getByTestId('save-status').textContent;

    // Typed while that write is open. On a shared draft this moves nothing
    // but the edit count.
    act(() => { screen.getByTestId('set-interests').click(); });

    await act(async () => {
      release({ status: 'saved', revision: 10, profile: { ...ROW, major: 'CS' } });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('save-status').textContent,
      'the old submit does not take the wording from a form that moved on')
      .toBe(intentBefore);
    expect(screen.getByTestId('interests').textContent).toBe('my interests');
    expect(cacheMocks.clearMatchCache, 'no cache is cleared').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();
  });

  it('D4: a field edited WHILE the rebuild runs is not painted over by it', async () => {
    await currentQuestionAtRev10();
    let release!: (v: unknown) => void;
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['major'],
      conflicts: [await question('major', 10, 'Statistics')],
    });
    syncOverrides.refreshCalls = [];
    syncOverrides.refreshConflictQuestion = (
      () => new Promise((resolve) => { release = resolve; })
    ) as never;

    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(syncOverrides.refreshCalls.length, 'the rebuild is in flight').toBeGreaterThan(0);

    // Typed WHILE the rebuild is running. The snapshot it read predates this.
    act(() => { screen.getByTestId('set-major-physics').click(); });

    await act(async () => {
      release({
        status: 'current',
        profile: { ...ROW, major: 'ECE' },
        baseProfile: { ...ROW, major: 'Newer' },
        revision: 12,
        conflicts: [await question('major', 12, 'Newer')],
        pendingKeys: ['major'],
        flushed: null,
      });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('major').textContent,
      'the keystroke that came after the read is not painted over').toBe('Physics');
    expect(screen.getByTestId('view-rev').textContent,
      'while the row the read described is still taken').toBe('12');
    // The question it found is about a value the person has already replaced:
    // its candidates come from before the keystroke. Hidden rather than
    // patched up — the write this edit arms will raise a fresh one if the
    // disagreement is still real.
    expect(screen.getByTestId('conflict-revs').textContent,
      'and the stale question about that field is not put on screen').toBe('');

    // Still OWED — durably, in the journal, not merely on screen. A rebuild
    // that cleared it would leave the keystroke visible and unsendable.
    const dirty = getDirtyProfileKeys(captureOwnerToken(), 'home-form');
    expect(dirty.ok && dirty.value, 'the edited field is still owed to the cloud')
      .toContain('major');
    // The newest operation in THIS document's own lineage — named, not
    // whichever the storage scan returned first.
    const newest = await lastOpFor('major', getJournalLineageId());
    expect(newest?.fields.find((f) => f.key === 'major')?.desired,
      'as what the person typed').toEqual({ present: true, value: 'Physics' });
  });

  it('D5: on a shared draft, an edit during the write survives the whole rebuild', async () => {
    const share = encodeProfile({
      ...DEFAULT_PROFILE, college: 'Grainger', major: 'ECE', grade: 'Junior',
    });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('valid').textContent).toBe('yes'));
    cacheMocks.clearMatchCache.mockClear();
    pushSpy.mockClear();

    let release!: (v: unknown) => void;
    syncOverrides.stageProfilePatch = () => new Promise((resolve) => { release = resolve; });
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      // The canonical read predates the keystroke below: it still says ECE.
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Newer' },
      revision: 12,
      conflicts: [...keys].map((k) => question(k, 12, 'Newer')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;

    await act(async () => { screen.getByTestId('submit').click(); });
    expect(release, "the submit's write is open").toBeTypeOf('function');
    const statusDuring = screen.getByTestId('save-status').textContent;

    // Typed while that write is open. A shared draft records no journal
    // operation and takes no save intent — the edit count is the only thing
    // that moves.
    act(() => { screen.getByTestId('set-major-physics').click(); });

    syncOverrides.refreshCalls = [];
    await act(async () => {
      release({
        status: 'conflict',
        revision: 10,
        remote: { ...ROW, major: 'Statistics' },
        confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
        conflictKeys: ['major'],
        conflicts: [await question('major', 10, 'Statistics')],
      });
      await new Promise((r) => setTimeout(r, 0));
    });
    // Waited on facts only the canonical helper can produce, so nothing below
    // can pass merely because the helper had not run yet.
    await waitFor(() => expect(syncOverrides.refreshCalls.length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('12'));

    expect(screen.getByTestId('major').textContent,
      'the keystroke stands, through the write AND the rebuild it caused')
      .toBe('Physics');
    expect(screen.getByTestId('conflict-keys').textContent,
      'and a question about the value it replaced is not put on screen').toBe('');
    expect(screen.getByTestId('save-status').textContent,
      'the old submit does not take the wording back').toBe(statusDuring);
    expect(cacheMocks.clearMatchCache, 'no cache is cleared').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();

    // The draft's own Generate still saves what is on screen now.
    const sent: { keys: string[]; major: unknown }[] = [];
    syncOverrides.stageProfilePatch = (async (
      patch: Record<string, unknown>, keys: readonly string[],
    ) => {
      sent.push({ keys: [...keys], major: patch.major });
      return { status: 'saved' as const, revision: 13, profile: { ...ROW, major: 'Physics' } };
    }) as never;
    await act(async () => { screen.getByTestId('submit').click(); });
    await waitFor(() => expect(sent.length).toBeGreaterThan(0));
    const carried = sent.find((c) => c.keys.includes('major'));
    expect(carried, 'the second Generate carries the field').toBeTruthy();
    expect(carried!.major, 'as what the person typed').toBe('Physics');
  });

  it('D6: an OPTIONAL field first set during a held Submit is not lost to it', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    expect(screen.getByTestId('coursework-view').textContent,
      'the field starts absent — it is not in the defaults at all').toBe('');

    let release!: (v: unknown) => void;
    syncOverrides.stageProfilePatch = () => new Promise((resolve) => { release = resolve; });
    syncOverrides.refreshCalls = [];
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      // The canonical read predates the keystroke: no coursework at all.
      profile: { ...ROW },
      baseProfile: { ...ROW, major: 'Newer' },
      revision: 12,
      conflicts: [...keys].map((k) => question(k, 12, 'Newer')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;

    act(() => { screen.getByTestId('set-major-ece').click(); });
    await act(async () => { screen.getByTestId('submit').click(); });
    expect(release, "the submit's write is open").toBeTypeOf('function');

    // FIRST appearance of an optional key, while that write is open. A
    // snapshot built from the defaults or from the current document would not
    // contain it, and its own keystroke would become the baseline.
    act(() => { screen.getByTestId('set-coursework').click(); });

    await act(async () => {
      release({
        status: 'conflict',
        revision: 10,
        remote: { ...ROW, major: 'Statistics' },
        confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
        conflictKeys: ['major', 'coursework'],
        conflicts: [await question('major', 10, 'Statistics'), await question('coursework', 10, undefined)],
      });
      await new Promise((r) => setTimeout(r, 0));
    });
    await waitFor(() => expect(syncOverrides.refreshCalls.length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('12'));

    expect(screen.getByTestId('coursework-view').textContent,
      'the optional field the person just set is still theirs').toBe('CS 225');
    expect(syncOverrides.refreshCalls.at(-1)?.keys,
      'and the rebuild was asked about it').toContain('coursework');

    // Still on screen is not enough — it has to be sendable.
    const sent: { keys: string[]; coursework: unknown }[] = [];
    syncOverrides.stageProfilePatch = (async (
      patch: Record<string, unknown>, keys: readonly string[],
    ) => {
      sent.push({ keys: [...keys], coursework: patch.coursework });
      return { status: 'saved' as const, revision: 13, profile: { ...ROW } };
    }) as never;
    await act(async () => { screen.getByTestId('submit').click(); });
    await waitFor(() => expect(sent.length).toBeGreaterThan(0));
    const carried = sent.find((c) => c.keys.includes('coursework'));
    expect(carried, 'the next Generate carries it').toBeTruthy();
    expect(carried!.coursework, 'as what the person set').toEqual(['CS 225']);
  });

  it('D7: an autosave in flight does not lose an edit the journal refused', async () => {
    // A REAL foreign operation: another surface's unsent `major` edit. This
    // form has no operation of its own for that field, so its own dirty set
    // will not contain it — exactly the case a snapshot built from a patch's
    // own keys would miss.
    const foreign = captureOwnerToken();
    const foreignOp = appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'CS' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 10,
      writer: 'results',
      mode: 'set',
    }, foreign);
    expect(foreignOp, 'the foreign operation was written').not.toBeNull();
    expect(
      await journalOps().some((o) => (
        o.writer === 'results'
        && o.fields.some((f) => (
          f.key === 'major' && f.desired.present && f.desired.value === 'ECE'
        ))
      )),
      'and it really is in the journal, owned by another surface',
    ).toBe(true);

    syncOverrides.hydrateProfile = (async () => ({
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Statistics' },
      revision: 10,
      source: 'cloud' as const,
      token: captureOwnerToken(),
      hasPending: false,
      conflictKeys: ['major'],
      conflicts: [await question('major', 10, 'Statistics')],
      quarantineFailed: false,
    })) as never;
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('conflict-revs').textContent).toBe('major@10'));
    expect(screen.getByTestId('view-rev').textContent).toBe('10');

    // Home's own autosave, for `github_url`. Its keys are captured and
    // checked: the claim that `major` is not in this patch is the point.
    const stageKeys: string[][] = [];
    let release!: (v: unknown) => void;
    syncOverrides.stageProfilePatch = ((_p: unknown, keys: readonly string[]) => {
      stageKeys.push([...keys]);
      return new Promise((resolve) => { release = resolve; });
    }) as never;
    syncOverrides.refreshCalls = [];
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      // Legitimately old: the keystroke below never reached the journal, so
      // no coordinator read can account for it.
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Newer' },
      revision: 12,
      conflicts: [...keys].map((k) => question(k, 12, 'Newer')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;

    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(release, 'that write is open').toBeTypeOf('function');
    expect(stageKeys.at(-1), "and it really is this form's own patch alone")
      .toEqual(['github_url']);

    // While it runs the person edits `major`, and the journal write for it
    // FAILS — nothing durable records the keystroke.
    let blockedAttempts = 0;
    const restore = await breakStorageFor((k) => {
      if (!k.startsWith(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_`)) return false;
      blockedAttempts += 1;
      return true;
    });
    try {
      act(() => { screen.getByTestId('set-major-physics').click(); });
    } finally {
      restore();
    }
    expect(blockedAttempts, 'the journal write was really attempted and refused')
      .toBeGreaterThan(0);
    expect(screen.getByTestId('major').textContent, 'it is on screen').toBe('Physics');
    expect(
      await journalOps().some((o) => o.fields.some(
        (f) => f.key === 'major' && f.desired.present && f.desired.value === 'Physics',
      )),
      'and nowhere in the journal',
    ).toBe(false);

    // The response is about the patch's own field. `major` enters the rebuild
    // from the question already on screen.
    await act(async () => {
      release({
        status: 'conflict',
        revision: 10,
        remote: { ...ROW, github_url: 'other' },
        confirmed: { revision: 10, profile: { ...ROW, github_url: 'other' } },
        conflictKeys: ['github_url'],
        conflicts: [await question('github_url', 10, 'other')],
      });
      await new Promise((r) => setTimeout(r, 0));
    });
    await waitFor(() => expect(syncOverrides.refreshCalls.length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('12'));

    // A snapshot taken from this patch's own keys would not contain `major`,
    // so its keystroke would become the baseline and the canonical read —
    // which legitimately cannot see it — would paint the old value back.
    expect(screen.getByTestId('major').textContent,
      'an edit the journal refused is still the person\'s').toBe('Physics');
    expect(screen.getByTestId('conflict-keys').textContent.split(',').filter(Boolean),
      'and no question is shown about a value no read could see')
      .not.toContain('major');
  });

  /** Types `major` while the journal refuses to record it, so the edit is real
   *  on screen and invisible to every coordinator read. */
  async function editMajorUnrecorded() {
    let blockedAttempts = 0;
    const restore = await breakStorageFor((k) => {
      if (!k.startsWith(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_`)) return false;
      blockedAttempts += 1;
      return true;
    });
    try {
      act(() => { screen.getByTestId('set-major-physics').click(); });
    } finally {
      restore();
    }
    expect(blockedAttempts, 'the journal write was attempted and refused').toBeGreaterThan(0);
    expect(screen.getByTestId('major').textContent, 'it is on screen').toBe('Physics');
    expect(
      await journalOps().some((o) => o.fields.some(
        (f) => f.key === 'major' && f.desired.present && f.desired.value === 'Physics',
      )),
      'and nowhere in the journal',
    ).toBe(false);
  }

  /** A canonical read that legitimately still says ECE — it cannot see an
   *  operation the journal refused. */
  const staleCanonicalAtRev12 = (async (keys: readonly string[]) => ({
    status: 'current' as const,
    profile: { ...ROW, major: 'ECE' },
    baseProfile: { ...ROW, major: 'Newer' },
    revision: 12,
    conflicts: [...keys].map((k) => question(k, 12, 'Newer')),
    pendingKeys: [...keys],
    flushed: null,
  })) as never;

  const conflictAtRev10 = {
    status: 'conflict' as const,
    revision: 10,
    remote: { ...ROW, major: 'Statistics' },
    confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
    conflictKeys: ['major'],
    conflicts: [question('major', 10, 'Statistics')],
  };

  it('A1: a recovered flush in flight does not lose an edit made after it started', async () => {
    let release!: (v: unknown) => void;
    syncOverrides.hydrateProfile = (async () => ({
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'ECE' },
      revision: 9,
      source: 'cloud' as const,
      token: captureOwnerToken(),
      hasPending: true,
      conflictKeys: [] as string[],
      conflicts: [],
      quarantineFailed: false,
    })) as never;
    syncOverrides.flushPendingProfileWrite = () => new Promise((resolve) => { release = resolve; });
    syncOverrides.refreshConflictQuestion = staleCanonicalAtRev12;

    await renderIdentityHarness();
    await waitFor(() => expect(syncOverrides.flushCalls).toBe(1));
    expect(release, 'the recovered write is open').toBeTypeOf('function');
    const during = screen.getByTestId('save-status').textContent;

    await editMajorUnrecorded();

    syncOverrides.refreshCalls = [];
    await act(async () => {
      release(conflictAtRev10);
      await new Promise((r) => setTimeout(r, 0));
    });
    await waitFor(() => expect(syncOverrides.refreshCalls.length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('12'));

    expect(screen.getByTestId('major').textContent,
      'the keystroke made during the recovery is not painted over').toBe('Physics');
    expect(screen.getByTestId('conflict-keys').textContent.split(',').filter(Boolean),
      'and no question is shown about a value no read could see').not.toContain('major');
    expect(screen.getByTestId('save-status').textContent,
      'nor does the old chain take the wording back').toBe(during);
  });

  it('A2: a retry in flight does not lose an edit made after it started', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW, major: 'ECE' }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));

    // A failed save arms Retry.
    syncOverrides.stageProfilePatch = async () => ({
      status: 'device-failed' as const, phase: 'stage' as const,
    });
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('error'));

    let release!: (v: unknown) => void;
    syncOverrides.flushPendingProfileWrite = () => new Promise((resolve) => { release = resolve; });
    syncOverrides.refreshCalls = [];
    syncOverrides.refreshConflictQuestion = staleCanonicalAtRev12;
    await act(async () => {
      screen.getByTestId('retry-sync').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(release, 'the retry is open').toBeTypeOf('function');
    const during = screen.getByTestId('save-status').textContent;

    await editMajorUnrecorded();

    await act(async () => {
      release(conflictAtRev10);
      await new Promise((r) => setTimeout(r, 0));
    });
    await waitFor(() => expect(syncOverrides.refreshCalls.length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('12'));

    expect(screen.getByTestId('major').textContent,
      'the keystroke made during the retry is not painted over').toBe('Physics');
    expect(screen.getByTestId('save-status').textContent,
      'nor does the old chain take the wording back').toBe(during);
  });

  it('A3: a recovered flush that REJECTS after an edit says nothing', async () => {
    let reject!: (e: unknown) => void;
    syncOverrides.hydrateProfile = (async () => ({
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'ECE' },
      revision: 9,
      source: 'cloud' as const,
      token: captureOwnerToken(),
      hasPending: true,
      conflictKeys: [] as string[],
      conflicts: [],
      quarantineFailed: false,
    })) as never;
    syncOverrides.flushPendingProfileWrite = () => new Promise((_r, rej) => { reject = rej; });
    await renderIdentityHarness();
    await waitFor(() => expect(syncOverrides.flushCalls).toBe(1));
    const during = screen.getByTestId('save-status').textContent;

    await editMajorUnrecorded();
    await act(async () => {
      reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByTestId('save-status').textContent,
      "a dead recovery does not label a form that has moved on").toBe(during);
  });

  it('A4: a retry that REJECTS after an edit says nothing', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW, major: 'ECE' }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    syncOverrides.stageProfilePatch = async () => ({
      status: 'device-failed' as const, phase: 'stage' as const,
    });
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('error'));

    let reject!: (e: unknown) => void;
    syncOverrides.flushPendingProfileWrite = () => new Promise((_r, rej) => { reject = rej; });
    await act(async () => {
      screen.getByTestId('retry-sync').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    const during = screen.getByTestId('save-status').textContent;

    await editMajorUnrecorded();
    await act(async () => {
      reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByTestId('save-status').textContent,
      'a dead retry does not label a form that has moved on').toBe(during);
  });

  /** An explicit touch of a field with the value it already has.
   *
   *  It goes through the ordinary edit entry point, so the edit counts move
   *  synchronously — but React bails out of a same-value primitive setState,
   *  the autosave effect's dependencies do not change, and no save intent is
   *  taken. That is what isolates the global clock from the intent gate. */
  function touchWeight() {
    act(() => { screen.getByTestId('touch-weight').click(); });
  }

  it('probe: a same-value weight touch moves no intent and starts no write', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    const before = screen.getByTestId('save-status').textContent;
    const stagesBefore = syncOverrides.stageCalls;
    const flushesBefore = syncOverrides.flushCalls;

    await touchWeight();
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(syncOverrides.stageCalls, 'no write was armed').toBe(stagesBefore);
    expect(syncOverrides.flushCalls, 'and none was flushed').toBe(flushesBefore);
    expect(screen.getByTestId('save-status').textContent,
      'and the status is untouched, so nothing took the save intent').toBe(before);
  });

  /** A recovered flush, held open, on a form with nothing else going on. */
  async function heldRecovery() {
    let release!: (v: unknown) => void;
    syncOverrides.hydrateProfile = (async () => ({
      profile: { ...ROW },
      baseProfile: { ...ROW },
      revision: 9,
      source: 'cloud' as const,
      token: captureOwnerToken(),
      hasPending: true,
      conflictKeys: [] as string[],
      conflicts: [],
      quarantineFailed: false,
    })) as never;
    syncOverrides.flushPendingProfileWrite = () => new Promise((resolve) => { release = resolve; });
    await renderIdentityHarness();
    await waitFor(() => expect(syncOverrides.flushCalls).toBe(1));
    return { release: () => release, during: screen.getByTestId('save-status').textContent };
  }

  /** A failed save with Retry armed, then a retry held open. */
  async function heldRetry() {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    syncOverrides.stageProfilePatch = async () => ({
      status: 'device-failed' as const, phase: 'stage' as const,
    });
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('error'));
    let release!: (v: unknown) => void;
    syncOverrides.flushPendingProfileWrite = () => new Promise((resolve) => { release = resolve; });
    await act(async () => {
      screen.getByTestId('retry-sync').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    return { release: () => release, during: screen.getByTestId('save-status').textContent };
  }

  const savedAtRev10 = { status: 'saved', revision: 10, profile: { ...ROW, major: 'ECE' } };

  it('A5-control: a recovered flush that completes IS reported', async () => {
    const { release } = await heldRecovery();
    await act(async () => {
      release()(savedAtRev10);
      await new Promise((r) => setTimeout(r, 20));
    });
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('10'));
    expect(screen.getByTestId('save-status').textContent,
      'an untouched form hears its own success').toBe('saved');
  });

  it('A5: a recovered flush cannot take the wording after an explicit touch', async () => {
    const { release, during } = await heldRecovery();
    await touchWeight();
    await act(async () => {
      release()(savedAtRev10);
      await new Promise((r) => setTimeout(r, 20));
    });
    // The FACT lands — proof the whole result chain really ran.
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('10'));
    expect(screen.getByTestId('save-status').textContent,
      'but the wording belongs to the form the person has touched since').toBe(during);
  });

  it('A6-control: a retry that completes IS reported', async () => {
    const { release } = await heldRetry();
    await act(async () => {
      release()(savedAtRev10);
      await new Promise((r) => setTimeout(r, 20));
    });
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('10'));
    expect(screen.getByTestId('save-status').textContent,
      'an untouched form hears its own success').toBe('saved');
  });

  it('A6: a retry cannot take the wording after an explicit touch', async () => {
    const { release, during } = await heldRetry();
    expect(during, 'the retry owns the wording while it runs').toBe('saving');
    await touchWeight();
    await act(async () => {
      release()(savedAtRev10);
      await new Promise((r) => setTimeout(r, 20));
    });
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('10'));
    expect(screen.getByTestId('save-status').textContent,
      'but the wording belongs to the form the person has touched since').toBe(during);
  });

  /** The same two, for a read that never answers. */
  async function heldRecoveryReject() {
    let reject!: (e: unknown) => void;
    syncOverrides.hydrateProfile = (async () => ({
      profile: { ...ROW },
      baseProfile: { ...ROW },
      revision: 9,
      source: 'cloud' as const,
      token: captureOwnerToken(),
      hasPending: true,
      conflictKeys: [] as string[],
      conflicts: [],
      quarantineFailed: false,
    })) as never;
    syncOverrides.flushPendingProfileWrite = () => new Promise((_r, rej) => { reject = rej; });
    await renderIdentityHarness();
    await waitFor(() => expect(syncOverrides.flushCalls).toBe(1));
    return { reject: () => reject, during: screen.getByTestId('save-status').textContent };
  }

  async function heldRetryReject() {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    syncOverrides.stageProfilePatch = async () => ({
      status: 'device-failed' as const, phase: 'stage' as const,
    });
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('error'));
    let reject!: (e: unknown) => void;
    syncOverrides.flushPendingProfileWrite = () => new Promise((_r, rej) => { reject = rej; });
    await act(async () => {
      screen.getByTestId('retry-sync').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    return { reject: () => reject, during: screen.getByTestId('save-status').textContent };
  }

  it('A7-control: a recovered flush that REJECTS with nothing typed IS reported', async () => {
    const { reject } = await heldRecoveryReject();
    await act(async () => {
      reject()(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent).toBe('cloud-failed');
  });

  it('A7: a recovered flush that REJECTS after a touch says nothing', async () => {
    const { reject, during } = await heldRecoveryReject();
    await touchWeight();
    await act(async () => {
      reject()(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent).toBe(during);
  });

  it('A8-control: a retry that REJECTS with nothing typed IS reported', async () => {
    const { reject } = await heldRetryReject();
    await act(async () => {
      reject()(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent).toBe('cloud-failed');
  });

  it('A8: a retry that REJECTS after a touch says nothing', async () => {
    const { reject, during } = await heldRetryReject();
    await touchWeight();
    await act(async () => {
      reject()(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent).toBe(during);
  });

  /** A shared draft with a question on screen, and a rebuild held open. On a
   *  shared draft an edit records nothing and bumps no save intent, so the
   *  form's edit count is the only thing that moves. */
  async function sharedDraftRebuildInFlight() {
    const share = encodeProfile({
      ...DEFAULT_PROFILE, college: 'Grainger', major: 'ECE', grade: 'Junior',
    });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('valid').textContent).toBe('yes'));
    let release!: (v: unknown) => void;
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['major'],
      conflicts: [await question('major', 10, 'Statistics')],
    });
    syncOverrides.refreshCalls = [];
    syncOverrides.refreshConflictQuestion = (
      () => new Promise((resolve) => { release = resolve; })
    ) as never;
    await act(async () => { screen.getByTestId('submit').click(); });
    await waitFor(() => expect(syncOverrides.refreshCalls.length).toBeGreaterThan(0));
    const during = screen.getByTestId('save-status').textContent;
    // Typed while the rebuild runs: no journal, no save intent, only the count.
    act(() => { screen.getByTestId('set-interests').click(); });
    return { release: () => release, during };
  }

  it('B1: a DEVICE-FAILED rebuild does not take the wording from a shared edit', async () => {
    const { release, during } = await sharedDraftRebuildInFlight();
    await act(async () => {
      release()({ status: 'device-failed', phase: 'lock', retryable: true });
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent,
      'the old chain does not report its failure over a form that moved on')
      .toBe(during);
  });

  it('B2: a SETTLED rebuild does not take the wording from a shared edit', async () => {
    const { release, during } = await sharedDraftRebuildInFlight();
    await act(async () => {
      release()({
        status: 'settled',
        profile: { ...ROW, major: 'ECE' },
        baseProfile: { ...ROW, major: 'Statistics' },
        revision: 12,
        conflicts: [],
        pendingKeys: [],
        flushed: null,
      });
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent,
      'nor its success').toBe(during);
  });

  it("B3: a saved rebuild's idle timer does not clear a shared edit's status", async () => {
    const { release, during } = await sharedDraftRebuildInFlight();
    await act(async () => {
      release()({
        status: 'settled',
        profile: { ...ROW, major: 'ECE' },
        baseProfile: { ...ROW, major: 'Statistics' },
        revision: 12,
        conflicts: [],
        pendingKeys: [],
        flushed: { status: 'saved', revision: 12, profile: { ...ROW, major: 'ECE' } },
      });
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent, 'not immediately').toBe(during);
    // And not two seconds later either, when the "back to idle" timer fires.
    await act(async () => { await new Promise((r) => setTimeout(r, 2100)); });
    expect(screen.getByTestId('save-status').textContent,
      'and not when its idle timer fires either').toBe(during);
  });

  /** An answer whose request is HELD. One deferred per call, so a newer
   *  answer cannot overwrite the rejecter this test is holding. */
  async function heldAnswer() {
    await currentQuestionAtRev10();
    const answers: { resolve: (v: unknown) => void; reject: (e: unknown) => void }[] = [];
    syncOverrides.resolveProfileConflict = (() => new Promise((resolve, reject) => {
      answers.push({ resolve, reject });
    })) as never;
    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(answers, 'the answer is in flight').toHaveLength(1);
    return { answers, during: screen.getByTestId('save-status').textContent };
  }

  it('RC-control: a rejected answer IS reported, and the buttons work again', async () => {
    const { answers } = await heldAnswer();
    await act(async () => {
      answers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent,
      'an untouched form hears about it').toBe('cloud-failed');

    // The latch released: a second answer is accepted.
    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(answers, 'so the next click owns its own resolution').toHaveLength(2);
  });

  it('RC-edit: a rejected answer says nothing after an explicit touch', async () => {
    const { answers, during } = await heldAnswer();
    expect(during, 'the answer owns the wording while it runs').toBe('saving');
    const stagesBefore = syncOverrides.stageCalls;
    const flushesBefore = syncOverrides.flushCalls;

    await touchWeight();
    // The touch takes no save intent — see the probe above — so the epoch is
    // the only thing that has moved.
    expect(syncOverrides.stageCalls).toBe(stagesBefore);
    expect(syncOverrides.flushCalls).toBe(flushesBefore);

    await act(async () => {
      answers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent,
      'a form the person has touched since is not labelled by it').toBe(during);
  });

  it('RC-owner: a rejected answer says nothing once the shared owner has moved', async () => {
    const { answers, during } = await heldAnswer();
    // ONLY the shared owner: this hook's auth callback never runs, so its
    // generation is unchanged and the origin token alone is dead.
    act(() => { advanceOwnerEpoch('resolve-owner-moved'); });

    await act(async () => {
      answers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent,
      "a dead token's failure is not this browser's news").toBe(during);
  });

  it('RC-generation: a rejected answer says nothing once the form was rebuilt', async () => {
    // A shared draft that has never seen a live auth event. Its first
    // observation rebuilds the screen and advances the hook's generation, and
    // that branch returns without touching the shared owner or the save
    // intent — the one place those three come apart.
    const share = encodeProfile({
      ...DEFAULT_PROFILE, college: 'Grainger', major: 'CS', grade: 'Junior',
    });
    searchRef.current = `share=${share}`;
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('valid').textContent).toBe('yes'));

    // A real question, raised by the draft's own Generate.
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['major'],
      conflicts: [await question('major', 10, 'Statistics')],
    });
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'CS' },
      baseProfile: { ...ROW, major: 'Statistics' },
      revision: 10,
      conflicts: [...keys].map((k) => question(k, 10, 'Statistics')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;
    await act(async () => { screen.getByTestId('submit').click(); });
    await waitFor(() => expect(screen.getByTestId('conflict-revs').textContent).toBe('major@10'));

    const answers: { resolve: (v: unknown) => void; reject: (e: unknown) => void }[] = [];
    syncOverrides.resolveProfileConflict = (() => new Promise((resolve, reject) => {
      answers.push({ resolve, reject });
    })) as never;
    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(answers, 'the answer is in flight').toHaveLength(1);
    const rejectFirst = answers[0].reject;
    const stagesBefore = syncOverrides.stageCalls;

    // ONLY the hook's own first observation. The shared owner is untouched.
    const stillOwner = captureOwnerToken();
    act(() => { authChangeCb?.({ user: null }); });
    expect(isOwnerTokenValid(stillOwner, stillOwner.uid),
      'the shared owner token is still perfectly valid').toBe(true);
    expect(syncOverrides.stageCalls, 'and no newer write took the save intent')
      .toBe(stagesBefore);
    const after = screen.getByTestId('save-status').textContent;

    await act(async () => {
      rejectFirst(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent,
      'a form that has been rebuilt is not labelled by it').toBe(after);
  });

  it('D2c: a field edited away and BACK is still the person\'s own last word', async () => {
    await currentQuestionAtRev10();
    let release!: (v: unknown) => void;
    syncOverrides.resolveProfileConflict = (
      () => new Promise((resolve) => { release = resolve; })
    ) as never;

    // Click-time value is ECE.
    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    // Typed away and typed back while the answer is open. The VALUE is what
    // it was; the person's intent is not — they touched this field after the
    // click, and this answer is older than that.
    act(() => { screen.getByTestId('set-major-physics').click(); });
    act(() => { screen.getByTestId('set-major-ece').click(); });

    await act(async () => {
      release({ status: 'saved', revision: 11, profile: { ...ROW, major: 'Statistics' } });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('major').textContent,
      "the last thing the person typed is what they see").toBe('ECE');
    expect(screen.getByTestId('view-rev').textContent,
      'while the row the server confirmed is still taken').toBe('11');
  });

  it('D2b: a STALE resolve landing late still applies canonical facts', async () => {
    await currentQuestionAtRev10();
    let release!: (v: unknown) => void;
    syncOverrides.resolveProfileConflict = (
      () => new Promise((resolve) => { release = resolve; })
    ) as never;
    // The rebuild reads the journal, so its working copy already carries the
    // edit made below — that is what "canonical" means here.
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'Physics' },
      baseProfile: { ...ROW, major: 'Newer' },
      revision: 12,
      conflicts: [...keys].map((k) => question(k, 12, 'Newer')),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;

    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    // The same field is typed again while the answer is open.
    act(() => { screen.getByTestId('set-major-physics').click(); });

    await act(async () => {
      release({ status: 'stale-conflict' });
      await new Promise((r) => setTimeout(r, 50));
    });

    // The edit reached the journal BEFORE this read went out, so the read
    // already accounts for it: its question is current, and it is published.
    // What must not happen is the read's own working copy being painted over
    // the keystroke — a different clock entirely.
    expect(screen.getByTestId('view-rev').textContent,
      'the canonical row is taken').toBe('12');
    expect(screen.getByTestId('conflict-revs').textContent,
      'and its question is current, because the read saw the edit').toBe('major@12');
    expect(screen.getByTestId('major').textContent,
      "while what the person typed is what they see").toBe('Physics');
  });

  it('a rebuild this device could not finish keeps the old question and stays retryable', async () => {
    await currentQuestionAtRev10();

    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['grade'],
      conflicts: [await question('grade', 10, 'Junior')],
    });
    syncOverrides.refreshConflictQuestion = async () => ({
      status: 'device-failed' as const, phase: 'lock' as const, retryable: true as const,
    });

    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(screen.getByTestId('conflict-revs').textContent,
      'the question that is on screen stays there').toBe('major@10');
    expect(screen.getByTestId('save-status').textContent,
      'and it is reported as retryable, not settled').toBe('error');
  });
});

describe("useProfileForm — Generate on a shared draft recomputes after reading the visitor's own row", () => {
  const ROW = { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 };

  /** A shared draft, valid, with the visitor's own row read HELD open. */
  async function heldOwnRowRead(opts: { withGithubUrl?: boolean } = {}) {
    const share = encodeProfile({
      ...DEFAULT_PROFILE, college: 'Grainger', major: 'CS', grade: 'Junior',
    });
    searchRef.current = `share=${share}`;
    // ONE deferred per call. A single pair of variables is overwritten by the
    // next read — an identity switch issues its own — and the test would then
    // be settling a promise it never meant to.
    const reads: { resolve: (v: unknown) => void; reject: (e: unknown) => void }[] = [];
    syncOverrides.hydrateProfile = (() => new Promise((resolve, reject) => {
      reads.push({ resolve, reject });
    })) as never;
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('valid').textContent).toBe('yes'));
    if (opts.withGithubUrl) act(() => { screen.getByTestId('set-gh').click(); });
    cacheMocks.clearMatchCache.mockClear();
    pushSpy.mockClear();
    const stages: { keys: string[]; patch: Record<string, unknown> }[] = [];
    syncOverrides.stageProfilePatch = (async (
      patch: Record<string, unknown>, keys: readonly string[],
    ) => {
      stages.push({ keys: [...keys], patch: { ...patch } });
      return { status: 'saved' as const, revision: 10, profile: { ...ROW, ...patch } };
    }) as never;
    await act(async () => { screen.getByTestId('submit').click(); });
    expect(reads, "the visitor's own row is being read").toHaveLength(1);
    expect(stages, 'and nothing has been staged yet').toHaveLength(0);
    const ownRow = {
      profile: { ...ROW },
      baseProfile: { ...ROW },
      revision: 9,
      source: 'cloud' as const,
      token: captureOwnerToken(),
      hasPending: false,
      conflictKeys: [] as string[],
      conflicts: [],
      quarantineFailed: false,
    };
    return {
      reads,
      release: () => reads[0].resolve,
      rejectRead: () => reads[0].reject,
      stages,
      ownRow,
    };
  }

  it('SH1: an OPTIONAL field added while the row is read is in the one write that follows', async () => {
    const { release, stages, ownRow } = await heldOwnRowRead();

    // First appearance of a field the shared link never carried.
    act(() => { screen.getByTestId('set-coursework').click(); });

    await act(async () => {
      release()(ownRow);
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(stages, 'exactly one write').toHaveLength(1);
    expect(stages[0].keys, 'and it names the field added during the read')
      .toContain('coursework');
    expect(stages[0].patch.coursework, 'with what the person set').toEqual(['CS 225']);
    // The acknowledgement is this write's OWN. Clocks captured before the row
    // was read belong to a document that no longer exists, and the edit made
    // during the read makes them look superseded — the save lands and says
    // nothing.
    expect(screen.getByTestId('save-status').textContent,
      'the write reports its own success').toBe('saved');
    expect(cacheMocks.clearMatchCache, 'the cache is cleared only after it lands')
      .toHaveBeenCalledTimes(1);
    expect(pushSpy, 'and only then does it navigate').toHaveBeenCalledTimes(1);
  });

  it('SH2: a REQUIRED field emptied while the row is read stops the whole thing', async () => {
    const { release, stages, ownRow } = await heldOwnRowRead();

    act(() => { screen.getByTestId('clear-major').click(); });

    await act(async () => {
      release()(ownRow);
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(stages, 'nothing is written').toHaveLength(0);
    expect(cacheMocks.clearMatchCache, 'nothing is cleared').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();
    expect(screen.getByTestId('valid').textContent,
      'the form says why it cannot go').toBe('no');
  });

  it('SH3-control: a failed own-row read with nothing typed IS reported', async () => {
    const held = await heldOwnRowRead();
    await act(async () => {
      held.rejectRead()(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent,
      'an untouched form hears about it').toBe('error');
  });

  it('SH3: a failed own-row read after a touch says nothing', async () => {
    const held = await heldOwnRowRead();
    const during = screen.getByTestId('save-status').textContent;
    act(() => { screen.getByTestId('touch-weight').click(); });
    await act(async () => {
      held.rejectRead()(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByTestId('save-status').textContent,
      'a touched one does not').toBe(during);
  });

  it('SH4: a failed own-row read after an identity switch touches nothing of the new one', async () => {
    const held = await heldOwnRowRead();
    // U1's own rejecter, pinned BEFORE the switch: U2 issues its own read,
    // and settling that one would be testing the wrong promise.
    const rejectU1 = held.rejectRead();
    expect(held.reads, "only U1's read is open").toHaveLength(1);

    await emitAuth('own-row-u2');
    // The new identity's own shared-draft screen issues no row read of its
    // own, so the only outstanding promise is still U1's — which is exactly
    // the one pinned above, and the only one this test settles.
    const readsAfterSwitch = held.reads.length;
    const statusAfterSwitch = screen.getByTestId('save-status').textContent;
    const gradeAfterSwitch = screen.getByTestId('grade').textContent;
    const stagesBefore = syncOverrides.stageCalls;

    await act(async () => {
      rejectU1(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(held.reads, "and U1's failure asks for nothing new")
      .toHaveLength(readsAfterSwitch);

    expect(screen.getByTestId('save-status').textContent,
      "U1's failure is not written onto U2's screen").toBe(statusAfterSwitch);
    expect(screen.getByTestId('grade').textContent, "nor is U1's data").toBe(gradeAfterSwitch);
    expect(syncOverrides.stageCalls, 'and nothing is written for anybody').toBe(stagesBefore);
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it('SH6: a link CLEARED while the row is read does not ship its import', async () => {
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
    });
    const { release, stages, ownRow } = await heldOwnRowRead({ withGithubUrl: true });
    expect(vi.mocked(parseGitHubProfile), 'an import really happened for that link')
      .toHaveBeenCalled();
    expect(await journalOps().some((o) => o.mode === 'add-skills'),
      'nothing is recorded while the row is still being read').toBe(false);

    // The link the import belonged to is REMOVED during the read.
    act(() => { screen.getByTestId('clear-gh').click(); });

    await act(async () => {
      release()(ownRow);
      await new Promise((r) => setTimeout(r, 20));
    });

    // Clearing the link is a valid edit, not a reason to abandon Generate:
    // the write goes out, carrying the cleared field and NOT the skills that
    // belonged to the link that is gone.
    expect(stages, 'exactly one write').toHaveLength(1);
    expect(stages[0].keys, 'and it carries the field the person cleared')
      .toContain('github_url');
    expect(stages[0].patch.github_url, 'as empty').toBe('');
    expect(stages[0].patch.skills ?? [], 'without the abandoned import')
      .not.toContainEqual(expect.objectContaining({ name: 'Go' }));
    expect(
      await journalOps().some((o) => o.mode === 'add-skills'),
      'skills imported for a link that is gone are not recorded',
    ).toBe(false);
    expect(screen.getByTestId('save-status').textContent,
      'and it reports its own success').toBe('saved');
    expect(cacheMocks.clearMatchCache).toHaveBeenCalledTimes(1);
    expect(pushSpy, 'and navigates once').toHaveBeenCalledTimes(1);
  });

  it('SH4-owner: a shared owner move alone stops the old read from reporting', async () => {
    const held = await heldOwnRowRead();
    const rejectU1 = held.rejectRead();
    // ONLY the shared owner moves — this hook's own auth callback never runs,
    // so its generation is unchanged and the token alone is what is dead.
    act(() => { advanceOwnerEpoch('own-row-owner-moved'); });
    const statusAfter = screen.getByTestId('save-status').textContent;

    await act(async () => {
      rejectU1(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByTestId('save-status').textContent,
      "a dead token's failure is not this browser's news").toBe(statusAfter);
  });

  it('SH4b: a generation change alone stops the old read from reporting', async () => {
    const held = await heldOwnRowRead();
    const rejectFirst = held.rejectRead();
    // The hook rebuilds for a new identity observation while the owner token
    // itself stays perfectly valid — the case only the generation catches.
    act(() => { authChangeCb?.({ user: null }); });
    const statusAfter = screen.getByTestId('save-status').textContent;

    await act(async () => {
      rejectFirst(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByTestId('save-status').textContent,
      'a submit from a form that has been rebuilt reports nothing').toBe(statusAfter);
  });

  it('SH5-control: an import whose link still matches DOES go out, once', async () => {
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
    });
    const share = encodeProfile({
      ...DEFAULT_PROFILE, college: 'Grainger', major: 'CS', grade: 'Junior',
    });
    searchRef.current = `share=${share}`;
    let release!: (v: unknown) => void;
    syncOverrides.hydrateProfile = (
      () => new Promise<unknown>((resolve) => { release = resolve; })
    ) as never;
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('valid').textContent).toBe('yes'));
    // The share payload carries no profile URLs, so the visitor types it.
    act(() => { screen.getByTestId('set-gh').click(); });
    cacheMocks.clearMatchCache.mockClear();
    pushSpy.mockClear();
    const stages: { keys: string[]; patch: Record<string, unknown> }[] = [];
    syncOverrides.stageProfilePatch = (async (
      patch: Record<string, unknown>, keys: readonly string[],
    ) => {
      stages.push({ keys: [...keys], patch: { ...patch } });
      return { status: 'saved' as const, revision: 10, profile: { ...ROW, ...patch } };
    }) as never;

    expect(screen.getByTestId('skills').textContent,
      'the draft carries no skills of its own').toBe('');
    await act(async () => { screen.getByTestId('submit').click(); });
    expect(release, "the visitor's own row is being read").toBeTypeOf('function');
    expect(await journalOps().some((o) => o.mode === 'add-skills'),
      'and nothing is recorded while it is still being read').toBe(false);
    // The link is NOT changed while the read runs.
    await act(async () => {
      release({
        profile: { ...ROW },
        baseProfile: { ...ROW },
        revision: 9,
        source: 'cloud' as const,
        token: captureOwnerToken(),
        hasPending: false,
        conflictKeys: [] as string[],
        conflicts: [],
        quarantineFailed: false,
      });
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(stages, 'exactly one write').toHaveLength(1);
    expect(stages[0].keys, 'and the imported skills are in it').toContain('skills');
    // The VALUE, not just the key: a merge that never happened would still
    // name `skills` and still record an addition, and the row would save an
    // empty list while the operation claimed otherwise.
    expect(stages[0].patch.skills, 'carrying what was actually imported')
      .toContainEqual({ name: 'Go', level: 'experienced' });
    expect(
      await journalOps().filter((o) => o.mode === 'add-skills'),
      'recorded durably as an ADDITION, exactly once, and only now',
    ).toHaveLength(1);
    expect(pushSpy, 'and it navigates once it lands').toHaveBeenCalledTimes(1);
  });

  it('SH5: a GitHub link changed while the row is read does not ship the old import', async () => {
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
    });
    const { release, stages, ownRow } = await heldOwnRowRead({ withGithubUrl: true });
    expect(vi.mocked(parseGitHubProfile), 'an import really happened for the first link')
      .toHaveBeenCalled();
    // TIMING, before anything else: the import is finished and the row is
    // still being read, so nothing about it may be durable yet.
    expect(await journalOps().some((o) => o.mode === 'add-skills'),
      'nothing is recorded while the row is still being read').toBe(false);

    // The link the import belonged to is replaced during the read.
    act(() => { screen.getByTestId('set-gh2').click(); });

    await act(async () => {
      release()(ownRow);
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(stages, 'the write does not go out against a link nobody imported')
      .toHaveLength(0);
    expect(
      await journalOps().some((o) => o.mode === 'add-skills'),
      'and no skills operation is recorded for the abandoned import',
    ).toBe(false);
    expect(pushSpy).not.toHaveBeenCalled();
  });
});

describe('useProfileForm — a collision that saved half of the write still moves the baseline', () => {
  it('grade lands at rev9 while major stays locked, and the NEXT edit is based on rev9', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow(
      { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 }, 8,
    ));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('8'));

    // One action, two fields. The other device has already moved `major`, so
    // the server takes `grade` and refuses the rest.
    act(() => {
      screen.getByTestId('set-major-ece').click();
      screen.getByTestId('set-grade-senior').click();
    });
    commitProfilePatch.mockClear();
    // The other device lands first, so the two-field write collides. The
    // coordinator locks `major`, re-bases the safe half and sends it alone.
    serverRow = { ...(serverRow ?? {}), major: 'Statistics' };
    serverRevision = 9;

    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('conflict-keys').textContent).toBe('major'));
    expect(await sentPatches(), 'the safe half really was sent on its own')
      .toContainEqual({ grade: 'Senior' });
    const lockedOp = await lastOpFor('major')!;

    // The safe half IS on the row now, at revision 10. A baseline left at 8
    // measures every later edit against a revision that is gone.
    expect(screen.getByTestId('view-rev').textContent,
      'the accepted baseline moved to what the server confirmed').toBe('10');
    expect(screen.getByTestId('grade').textContent, 'and the saved half stands').toBe('Senior');
    expect(screen.getByTestId('major').textContent,
      'while the disputed field keeps THIS device\'s value').toBe('ECE');

    // A field nobody is arguing about and nobody is mid-edit on, typed next.
    commitProfilePatch.mockClear();
    act(() => { screen.getByTestId('set-interests').click(); });
    const fresh = await lastOpFor('research_interests')!;
    expect(fresh.baseRevision, 'based on the revision the server confirmed').toBe(10);

    // And a college switch, which cascades into the still-disputed major. A
    // locked chain has already been shown to the person and refused; a new
    // action on that field REPLACES it rather than continuing it, so this
    // operation is frozen against the row the server confirmed — not against
    // the revision-8 snapshot the collision was discovered on, which would
    // compare unequal and manufacture a second conflict out of nothing.
    act(() => { screen.getByTestId('set-college').click(); });
    const cascade = await lastOpFor('college')!;
    expect(cascade.baseRevision, 'the new action begins at the confirmed revision').toBe(10);
    expect(cascade.fields.find((f) => f.key === 'college')!.base)
      .toEqual({ present: true, value: 'Grainger' });
    expect(cascade.fields.find((f) => f.key === 'major')!.base,
      'and the disputed field is measured from the confirmed row too')
      .toEqual({ present: true, value: 'Statistics' });
    expect(cascade.supersedes ?? [], 'because it explicitly replaces the refused chain')
      .toContain(lockedOp.opId);
    expect(screen.getByTestId('conflict-keys').textContent,
      'the disagreement itself is still there until somebody answers it').toBe('major');

    // DURABLE, not just an in-memory ledger patch: a reload rebuilds the plan
    // from the journal alone, and a superseded ancestor must not drag the base
    // back to the revision it began at.
    resetProfileDirtyLedger();
    const rebuilt = planKeysFromJournalForTests(await outstandingOps(), ['major', 'college']);
    const collegePlan = rebuilt.get('college');
    if (collegePlan?.kind !== 'value') throw new Error('college has no value plan after a reload');
    expect(collegePlan.baseRevision, 'college, after a reload').toBe(10);
  });
});

describe('useProfileForm — an edit typed while the rebased safe half is in flight', () => {
  it('survives the response, is sent afterwards, and leaves only major in dispute', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow(
      { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 }, 8,
    ));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('8'));

    act(() => {
      screen.getByTestId('set-major-ece').click();
      screen.getByTestId('set-grade-senior').click();
    });
    serverRow = { ...(serverRow ?? {}), major: 'Statistics' };
    serverRevision = 9;

    // The rebased safe half is HELD open — no timing guesswork, the test
    // decides when the server answers.
    let release!: (outcome: ProfilePatchOutcome) => void;
    let calls = 0;
    commitProfilePatch.mockImplementation(async (intent: ProfilePatchIntent) => {
      calls += 1;
      if (calls !== 2) return defaultCommit(intent);
      return new Promise<ProfilePatchOutcome>((resolve) => { release = resolve; });
    });

    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(calls).toBe(2));

    // Typed while that request is open.
    act(() => { screen.getByTestId('set-interests').click(); });

    await act(async () => {
      serverRow = { ...(serverRow ?? {}), grade: 'Senior' };
      serverRevision = 10;
      release({ status: 'saved', revision: 10, profile: serverRow });
    });
    // Barrier, not a sleep: wait for the concrete state the response produces.
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('10'));

    // IMMEDIATELY — before the unrelated edit's debounce fires. The newer edit
    // owns the spinner, but what the server said about the row is a fact and
    // does not belong to whoever is typing now.
    expect(screen.getByTestId('conflict-keys').textContent,
      'the disagreement the server reported is on screen').toBe('major');
    expect(await sentPatches(), 'and nothing new has been sent yet').toEqual([
      { major: 'ECE', grade: 'Senior' },
      { grade: 'Senior' },
    ]);
    expect(screen.getByTestId('interests').textContent,
      'the edit made during the round trip is still there').toBe('my interests');
    expect(screen.getByTestId('major').textContent, "with this device's disputed value")
      .toBe('ECE');
    expect(screen.getByTestId('save-status').textContent,
      'and the newer edit still owns the status text').toBe('saving');

    // Now let that edit's own debounce fire.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    waitFor(() => expect(sentPatches())
      .toContainEqual({ research_interests: 'my interests' }));
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('11'));
    expect(screen.getByTestId('conflict-keys').textContent,
      'and major is still the only thing in dispute').toBe('major');
    expect(screen.getByTestId('interests').textContent).toBe('my interests');
  });
});

describe('useProfileForm — a stale answer is refreshed, and the refresh is a transaction', () => {
  /**
   * Puts the form into a REAL conflict: this device edits `major` while
   * another one moves the same field, so the CAS comes back with a collision
   * and the key is locked.
   */
  async function conflictOnMajor() {
    mockLoadProfile = () => Promise.resolve(cloudRow(
      { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 }, 7,
    ));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('7'));

    act(() => { screen.getByTestId('set-major-ece').click(); });
    // The other device lands first.
    serverRow = { ...(serverRow ?? {}), major: 'Statistics' };
    serverRevision = 8;
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('conflict-keys').textContent).toBe('major'));
  }

  /** Another tab answering the EXACT question on screen, durably, and dying
   *  before it could deliver it. Both target forms, because the question has
   *  operations behind it AND belongs to a pending write. */
  function answerFromAnotherTab(choice: 'local' | 'cloud', mine = 'ECE') {
    const token = captureOwnerToken();
    const shown = readCurrentConflicts(['major'], token);
    const pending = readProfileSyncEnvelope()!.pending!;
    expect(shown).toHaveLength(1);
    return appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: shown[0].remote },
        desired: { present: true, value: choice === 'local' ? mine : shown[0].remote },
      }],
      baseRevision: shown[0].remoteRevision,
      writer: 'default',
      mode: 'resolve',
      resolves: shown[0].candidates.flatMap((c) => c.opIds),
      resolvesPending: {
        mutationId: shown[0].mutationId!,
        keyVersions: { major: shown[0].keyVersion ?? pending.keyVersions.major },
      },
      decisions: { major: choice },
    }, token);
  }

  function breakStorage(fail: (key: string) => boolean) {
    const real = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => real.getItem(k),
        setItem: (k: string, v: string) => {
          if (fail(k)) throw new Error('quota');
          real.setItem(k, v);
        },
        removeItem: (k: string) => {
          if (fail(k)) throw new Error('quota');
          real.removeItem(k);
        },
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    return () => Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
  }

  it('a refresh this device could not finish KEEPS the buttons and stays retryable', async () => {
    await conflictOnMajor();
    // Another tab answered it, so this click is stale and the refresh runs.
    expect(await answerFromAnotherTab('local')).toBeTruthy();
    commitProfilePatch.mockClear();

    const restore = await breakStorage((k) => k === STORAGE_KEYS.PROFILE_SYNC);
    try {
      await act(async () => {
        screen.getByTestId('use-cloud').click();
        await new Promise((r) => setTimeout(r, 50));
      });
    } finally {
      restore();
    }

    // The question was NOT retired on the way in. Retiring first and asking
    // afterwards leaves a screen with no controls and a disagreement that is
    // still on disk.
    expect(screen.getByTestId('conflict-keys').textContent,
      'the disagreement is still on screen').toBe('major');
    expect(screen.getByTestId('save-status').textContent,
      'and it is reported as this device failing, not as settled').toBe('error');
    expect(commitProfilePatch,
      'nothing was sent past the failing boundary').not.toHaveBeenCalled();
    expect(await outstandingOps().some((op) => op.mode === 'resolve'),
      "and the other tab's proof is untouched").toBe(true);
  });

  it('LW-refresh: an authoritative rebuild does not roll back an untouched live weight', async () => {
    await conflictOnMajor();
    // Moved AFTER the question went up, on a field the question is not about.
    act(() => { screen.getByTestId('set-weight').click(); });
    expect(screen.getByTestId('view-rendered-weight').textContent,
      'the published document shows what the person set').toBe('90');
    // Another tab answers it durably, so this click refreshes canonically
    // rather than resolving — the path that adopts a baseline read under the
    // shared lock and rebuilds the rendered half beside it.
    expect(await answerFromAnotherTab('cloud')).toBeTruthy();

    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('weight').textContent,
      'the slider the answer was never about is untouched').toBe('90');
    expect(screen.getByTestId('view-rendered-weight').textContent,
      'and the rebuilt document is still the one on screen').toBe('90');
  });

  it("a cloud answer found by the refresh shows up, keeps an unrelated edit, and is not sent back", async () => {
    await conflictOnMajor();
    expect(await answerFromAnotherTab('cloud')).toBeTruthy();

    // Typed AFTER the prompt went up, on a field the question is not about.
    act(() => { screen.getByTestId('set-interests').click(); });
    commitProfilePatch.mockClear();

    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('conflict-keys').textContent,
      'the question is gone').toBe('');
    expect(screen.getByTestId('major').textContent,
      "the other tab's answer is what the form shows").toBe('Statistics');
    expect(screen.getByTestId('interests').textContent,
      'and the edit made while the prompt was up survives it').toBe('my interests');
    expect(screen.getByTestId('view-rev').textContent,
      'the accepted baseline moved to the row that answer is about').toBe('8');

    // The next edit is measured against revision 8 and the answered value —
    // not against the revision the prompt was rendered at.
    act(() => { screen.getByTestId('set-major-physics').click(); });
    const op = await lastOpFor('major')!;
    expect(op.baseRevision).toBe(8);
    expect(op.fields.find((f) => f.key === 'major')!.base)
      .toEqual({ present: true, value: 'Statistics' });
    expect(await sentPatches(), 'and the answer was never sent back at the server')
      .not.toContainEqual({ major: 'Statistics' });
  });

  it('a question settled somewhere else lands in a state the UI actually renders', async () => {
    await conflictOnMajor();
    expect(await answerFromAnotherTab('cloud')).toBeTruthy();
    commitProfilePatch.mockClear();

    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Not 'idle', and not a silent nothing: the click WAS about a question
    // that had already been decided, and SubmitRow has a branch for exactly
    // that (see its own test).
    expect(screen.getByTestId('save-status').textContent).toBe('conflict-stale');
    expect(screen.getByTestId('conflict-keys').textContent).toBe('');

    // Past the autosave debounce, so a transient 'conflict-stale' that a
    // re-armed save immediately paints over cannot pass as visible.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(screen.getByTestId('save-status').textContent,
      'and it STAYS the visible outcome').toBe('conflict-stale');
    expect(commitProfilePatch, 'with nothing sent, then or since').not.toHaveBeenCalled();
  });

  it('an unrelated edit made during the prompt is still SENT after the refresh paints over it', async () => {
    await conflictOnMajor();
    expect(await answerFromAnotherTab('cloud')).toBeTruthy();
    act(() => { screen.getByTestId('set-interests').click(); });
    commitProfilePatch.mockClear();

    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 50));
    });
    // The debounce the edit armed still has to fire. Marking the whole merged
    // document hydrated would have blessed this edit as already-persisted and
    // it would never go out.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(await sentPatches(), 'the edit is not blessed as already-persisted: it goes out')
      .toContainEqual({ research_interests: 'my interests' });
    expect(await sentPatches(), 'and the answer the refresh painted is not re-sent')
      .not.toContainEqual({ major: 'Statistics' });
  });

  it("another tab's OWN value, still owed, is displayed here and then sent from here", async () => {
    await conflictOnMajor();
    // Keep Mine in a tab whose value this one has never seen.
    expect(await answerFromAnotherTab('local', 'Bioengineering')).toBeTruthy();
    commitProfilePatch.mockClear();

    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('major').textContent,
      "the other tab's answer is what this one shows, even though it is still unsent").toBe('Bioengineering');
    expect(await sentPatches(), 'and it is treated as owed, so this tab delivers it')
      .toContainEqual({ major: 'Bioengineering' });
    expect(screen.getByTestId('conflict-keys').textContent, 'with the question closed').toBe('');
  });

  it('two opposite clicks in the same tick: only the first owns the resolution', async () => {
    await conflictOnMajor();
    expect(await answerFromAnotherTab('cloud')).toBeTruthy();
    commitProfilePatch.mockClear();
    const receiptsBefore = new Set(
      await outstandingOps().filter((o) => o.mode === 'resolve').map((o) => o.opId),
    );

    await act(async () => {
      screen.getByTestId('keep-mine').click();
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Receipts are RETIRED as they are honoured, so the count can only fall.
    // What must not happen is a NEW one appearing for the second click.
    const after = await outstandingOps().filter((o) => o.mode === 'resolve');
    expect(after.filter((o) => !receiptsBefore.has(o.opId)).map((o) => o.opId),
      'the second click wrote no receipt of its own').toEqual([]);
    expect(screen.getByTestId('major').textContent,
      "and the answer that was already on disk stands").toBe('Statistics');
    expect(commitProfilePatch, 'and it sent nothing').not.toHaveBeenCalled();
  });

  it('a second click DURING the refresh cannot take the resolution off the first', async () => {
    await conflictOnMajor();
    // Another tab kept ITS value, so the refresh has something to deliver and
    // the request it makes is the barrier this test holds open.
    expect(await answerFromAnotherTab('local', 'Bioengineering')).toBeTruthy();
    commitProfilePatch.mockClear();

    let release!: (outcome: ProfilePatchOutcome) => void;
    let calls = 0;
    commitProfilePatch.mockImplementation(async (intent: ProfilePatchIntent) => {
      calls += 1;
      if (calls !== 1) return defaultCommit(intent);
      return new Promise<ProfilePatchOutcome>((resolve) => { release = resolve; });
    });

    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 50));
    });
    // The refresh is mid-flight, holding the resolution.
    expect(calls, 'the refresh is delivering the other tab\'s answer').toBe(1);

    // A second, opposite click lands while it is still running. Releasing the
    // latch before the refresh finishes lets this one own the resolution, and
    // the first click's outcome is dropped by the intent fence it bumps.
    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 20));
    });

    await act(async () => {
      serverRow = { ...(serverRow ?? {}), major: 'Bioengineering' };
      serverRevision = 10;
      release({ status: 'saved', revision: 10, profile: serverRow });
      await new Promise((r) => setTimeout(r, 50));
    });

    // The first click's own result is what lands: its continued flush reached
    // revision 10, and its refresh is what applies that. Freeing the latch
    // early lets the second click bump the save intent, and the first chain's
    // whole application — baseline, question, outcome — is dropped by the
    // fence it just moved.
    expect(screen.getByTestId('view-rev').textContent,
      "the first click's own result is what lands").toBe('10');
    expect(screen.getByTestId('major').textContent).toBe('Bioengineering');
    expect(calls, 'and the second click sent nothing of its own').toBe(1);
  });

  it('an answer that already matches the screen is sent ONCE, not again by the autosave', async () => {
    await conflictOnMajor();
    // The other tab kept the same value this one is showing.
    expect(await answerFromAnotherTab('local', 'ECE')).toBeTruthy();
    commitProfilePatch.mockClear();

    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.getByTestId('major').textContent, 'nothing on screen moved').toBe('ECE');
    expect(await sentPatches(), 'and the answer went out').toEqual([{ major: 'ECE' }]);

    // Past the debounce window, in case anything re-armed behind it.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(screen.getByTestId('save-status').textContent,
      'no autosave was armed for a value that is already saved').not.toBe('saving');
    expect(await sentPatches(), 'and it was sent exactly once').toEqual([{ major: 'ECE' }]);
  });

  it('an owner epoch that moves without this hook\'s auth event stops the refresh dead', async () => {
    await conflictOnMajor();
    expect(await answerFromAnotherTab('cloud')).toBeTruthy();
    commitProfilePatch.mockClear();
    const shownBefore = screen.getByTestId('major').textContent;
    const revBefore = screen.getByTestId('view-rev').textContent;

    await act(async () => {
      screen.getByTestId('use-cloud').click();
      // Another subscriber gets the auth event first: the shared owner moves
      // while this hook's generation has not.
      advanceOwnerEpoch('fence-u2');
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('major').textContent, 'nothing is applied').toBe(shownBefore);
    expect(screen.getByTestId('view-rev').textContent).toBe(revBefore);
    expect(commitProfilePatch, 'and nothing is sent').not.toHaveBeenCalled();
  });

  it('an authoritative EMPTY row clears the asked field and nothing else', async () => {
    await conflictOnMajor();
    // Another tab answers, so this click is stale and the refresh runs.
    expect(await answerFromAnotherTab('cloud')).toBeTruthy();
    // Typed after the prompt went up, on a field the question is not about.
    act(() => { screen.getByTestId('set-interests').click(); });
    const revBefore = screen.getByTestId('view-rev').textContent;

    // The row is gone: no confirmed base, no outbox, no fence. The refresh's
    // authoritative answer for `major` is absence itself.
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1, confirmed: null, pending: null, tombstone: null,
    }));
    commitProfilePatch.mockClear();

    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('major').textContent,
      'the asked field is emptied, not left showing a value no row holds').toBe('');
    expect(screen.getByTestId('interests').textContent,
      'and the unrelated edit is untouched').toBe('my interests');
    expect(screen.getByTestId('conflict-keys').textContent, 'the question is gone').toBe('');
    // The BASE moves with the display or they describe two different moments,
    // and the next edit is measured against a row this account no longer has
    // — a conflict manufactured out of nothing.
    expect(screen.getByTestId('view-base-major').textContent,
      'the accepted baseline is the same absence the screen shows').toBe('absent');
    expect(screen.getByTestId('view-rev').textContent,
      'at the revision the authoritative read reported').toBe('0');
    expect(revBefore, 'which is NOT where it was').not.toBe('0');
    expect(commitProfilePatch, 'and the empty answer is not sent back').not.toHaveBeenCalled();
  });

  // What actually protects this is the fire-time dirty read, not the clean
  // marker: the timer re-reads the journal when it fires, and the refresh has
  // already settled the operation and dropped the field intent. Kept because
  // the duplicate send it rules out is a real hazard, not because it proves
  // anything about the marker.
  it('an autosave already armed when a matching answer lands does not send it twice', async () => {
    await conflictOnMajor();
    // The other tab kept the same value this one is showing.
    expect(await answerFromAnotherTab('local', 'ECE')).toBeTruthy();

    // An autosave is ARMED and has not fired: the person touched the field
    // again, on a clock the test controls.
    vi.useFakeTimers();
    try {
      act(() => { screen.getByTestId('set-major-ece').click(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(500); });
      commitProfilePatch.mockClear();

      // The answer lands BEFORE that timer fires.
      await act(async () => {
        screen.getByTestId('use-cloud').click();
        await vi.advanceTimersByTimeAsync(50);
      });
      const afterRefresh = await sentPatches().length;

      // Now the armed timer fires.
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
      expect(await sentPatches().length,
        'the armed autosave adds nothing: the answer is already on the row')
        .toBe(afterRefresh);
    } finally {
      vi.useRealTimers();
    }
  });

  it('an owner that moves while the refresh\'s own send is in flight applies nothing', async () => {
    await conflictOnMajor();
    // Keep Mine in another tab, so the refresh has something to deliver and
    // its request is the barrier this test holds open.
    expect(await answerFromAnotherTab('local', 'Bioengineering')).toBeTruthy();
    commitProfilePatch.mockClear();

    let release!: (outcome: ProfilePatchOutcome) => void;
    let calls = 0;
    commitProfilePatch.mockImplementation(async (intent: ProfilePatchIntent) => {
      calls += 1;
      if (calls !== 1) return defaultCommit(intent);
      return new Promise<ProfilePatchOutcome>((resolve) => { release = resolve; });
    });

    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(calls, 'the refresh is delivering the answer').toBe(1);
    const shownBefore = screen.getByTestId('major').textContent;
    const revBefore = screen.getByTestId('view-rev').textContent;

    // Another subscriber gets the auth event first: the shared owner moves
    // while THIS hook's generation has not, and the request is still open.
    await act(async () => {
      advanceOwnerEpoch('inflight-u2');
      release({ status: 'saved', revision: 10, profile: { major: 'Bioengineering' } });
      await new Promise((r) => setTimeout(r, 50));
    });

    // The refresh comes back with a result — its send was abandoned, not its
    // read — and every part of applying it belongs to an account that is no
    // longer here.
    expect(screen.getByTestId('conflict-keys').textContent,
      'the question is not retired on a dead identity').toBe('major');
    expect(screen.getByTestId('major').textContent).toBe(shownBefore);
    expect(screen.getByTestId('view-rev').textContent).toBe(revBefore);
  });

  it('an identity switch during the refresh applies nothing to the new account', async () => {
    await conflictOnMajor();
    expect(await answerFromAnotherTab('cloud')).toBeTruthy();
    commitProfilePatch.mockClear();

    await act(async () => {
      screen.getByTestId('use-cloud').click();
      // The account changes before the refresh can come back.
      await emitAuth('refresh-u2');
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId('conflict-keys').textContent,
      "U1's question is not published onto U2's screen").toBe('');
    expect(screen.getByTestId('view-uid').textContent).not.toBe(UID_FOR_CONFLICT);
  });
});

const UID_FOR_CONFLICT = 'never-matches';

describe('useProfileForm — every action is bound to the capability the screen was issued for', () => {
  const ROW = { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 };
  const U2 = 'screen-origin-u2';

  function question(key: string, revision: number, remote: unknown, mutationId = 'm1') {
    return {
      key,
      remote,
      remoteRevision: revision,
      mutationId,
      keyVersion: 1,
      candidates: [{ value: 'mine', lineage: 'lin-a', opIds: [`op-${key}-${revision}`] }],
    };
  }

  /** A hydrated, valid U1 form at revision 9. */
  async function hydratedU1() {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
  }

  /**
   * The shared owner moves to `uid` and the browser is CLAIMED for them —
   * what another tab's account switch actually does — while this hook's own
   * auth callback is never delivered. Its generation does not move: the
   * screen still renders U1's row and still takes clicks.
   *
   * The claim is not decoration. Advancing the epoch alone leaves EVERY
   * identity's local realm blocked, so a stale write would fail at the
   * storage gate for a reason that has nothing to do with who owns the
   * screen — and the test would pass against code that never checked.
   */
  async function moveOwnerTo(uid: string) {
    await act(async () => {
      advanceOwnerEpoch(uid);
      await syncLocalIdentityOwner(uid);
    });
  }

  /** The same person at a NEW epoch — a real sign-out/sign-in cycle. A bare
   *  advanceOwnerEpoch(HOME_UID) is a no-op: the epoch only moves on a
   *  genuine change, so the cycle has to go through null. */
  async function reclaimSameUid() {
    await act(async () => {
      advanceOwnerEpoch(null);
      advanceOwnerEpoch(HOME_UID);
      await syncLocalIdentityOwner(HOME_UID);
    });
  }

  /** Whole-accessor storage recorder. jsdom's Storage proxy swallows a spy on
   *  the prototype method, so a spy would silently record nothing. */
  function recordStorage() {
    const real = window.localStorage;
    const calls = {
      get: [] as string[], set: [] as string[], remove: [] as string[], enumerate: 0,
    };
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => { calls.get.push(k); return real.getItem(k); },
        setItem: (k: string, v: string) => { calls.set.push(k); real.setItem(k, v); },
        removeItem: (k: string) => { calls.remove.push(k); real.removeItem(k); },
        clear: () => real.clear(),
        // Scanning the keyspace IS a private read: the journal lives under a
        // prefix, so enumeration is how one identity finds another's lanes.
        key: (i: number) => { calls.enumerate += 1; return real.key(i); },
        get length() { calls.enumerate += 1; return real.length; },
      },
    });
    const restore = () => Object.defineProperty(
      window, 'localStorage', { configurable: true, value: real },
    );
    registerSpy({ mockRestore: restore });
    return { calls, restore };
  }

  /** Every byte this browser holds, order-independent. */
  function storageBytes(): string {
    const out: [string, string][] = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const k = localStorage.key(i)!;
      out.push([k, localStorage.getItem(k) ?? '']);
    }
    out.sort((a, b) => (a[0] < b[0] ? -1 : 1));
    return JSON.stringify(out);
  }

  /** Only the account-private keys — the marker itself is device state. */
  function privateOf(keys: readonly string[]): string[] {
    return keys.filter(isUserScopedStorageKey);
  }

  /** The cache invalidation answers honestly for the token it is handed, so a
   *  dead-token refusal is a real refusal rather than a rigged `true`. */
  function honestCache() {
    cacheMocks.clearMatchCache.mockReset();
    cacheMocks.clearMatchCache.mockImplementation(
      (t) => (t ? isOwnerTokenValid(t, t.uid) : false),
    );
  }

  it('O1: a Submit clicked after the owner moved writes nothing and goes nowhere', async () => {
    await hydratedU1();
    await moveOwnerTo(U2);

    await honestCache();
    pushSpy.mockClear();
    commitProfilePatch.mockClear();
    const stagesBefore = syncOverrides.stageCalls;
    const statusBefore = screen.getByTestId('save-status').textContent;
    const bytes = storageBytes();
    const rec = recordStorage();

    await act(async () => {
      screen.getByTestId('submit').click();
      await new Promise((r) => setTimeout(r, 40));
    });

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    rec.restore();

    expect(syncOverrides.stageCalls, 'nothing is staged').toBe(stagesBefore);
    expect(commitProfilePatch, "and U1's form is not written into U2's row")
      .not.toHaveBeenCalled();
    expect(writes, 'no private key is written').toEqual([]);
    expect(removes, 'and none is removed').toEqual([]);
    expect(reads, "nor is U2's private data read on U1's behalf").toEqual([]);
    expect(storageBytes(), "so U2's bytes are exactly as they were").toBe(bytes);
    expect(cacheMocks.clearMatchCache, 'no cache is invalidated').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();
    expect(screen.getByTestId('save-status').textContent,
      'the old screen claims no success').toBe(statusBefore);
  });

  it('O2: an un-imported link on a stale screen is never fetched, marked or recorded', async () => {
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
    });
    await hydratedU1();
    // A COMPLETED U1 import: the receipt exists and its skills are marked.
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => {
      screen.getByTestId('gh-import').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    await waitFor(() => expect(screen.getByTestId('skills').textContent).toBe('Go'));
    // A SECOND link, pasted and NOT imported — the one Submit auto-imports.
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'hubot', extracted_skills: ['Zig'], topics: [], repo_count: 1, top_repos: [],
    });
    act(() => { screen.getByTestId('set-gh2').click(); });

    await moveOwnerTo(U2);
    vi.mocked(parseGitHubProfile).mockClear();
    await honestCache();
    pushSpy.mockClear();
    const stagesBefore = syncOverrides.stageCalls;
    const bytes = storageBytes();
    const rec = recordStorage();

    await act(async () => {
      screen.getByTestId('submit').click();
      await new Promise((r) => setTimeout(r, 60));
    });

    const writes = privateOf(rec.calls.set);
    rec.restore();

    expect(parseGitHubProfile, 'the stale screen does not even fetch the link')
      .not.toHaveBeenCalled();
    expect(writes, 'and writes nothing private').toEqual([]);
    expect(await journalOps().filter((o) => o.mode === 'add-skills'),
      "so no skills operation exists under U2's identity").toHaveLength(0);
    expect(storageBytes(), "U2's journal bytes are unchanged").toBe(bytes);
    expect(syncOverrides.stageCalls).toBe(stagesBefore);
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();

    // The ledger probe, through ordinary public semantics: U2 arrives for
    // real, reads their own row, and imports their OWN link. What that write
    // carries is what the skill ledger actually holds for them.
    mockLoadProfile = () => Promise.resolve(
      cloudRow({ college: 'Siebel', major: 'Stats', grade: 'Senior' }, 3),
    );
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'u2', extracted_skills: ['Rust'], topics: [], repo_count: 1, top_repos: [],
    });
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('3'));
    commitProfilePatch.mockClear();
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => {
      screen.getByTestId('gh-import').click();
      await new Promise((r) => setTimeout(r, 1700));
    });

    const names = await sentPatches().flatMap(
      (p) => ((p.skills ?? []) as { name: string }[]).map((s) => s.name),
    );
    expect(names, "U2's own import is what goes out").toContain('Rust');
    expect(names, "and nothing the stale screen ever imported").not.toContain('Zig');
    expect(names, 'nor anything U1 imported before it').not.toContain('Go');
  });

  it('O2b-github-control: an import resolving under its own owner DOES report', async () => {
    await hydratedU1();
    let release!: (v: unknown) => void;
    vi.mocked(parseGitHubProfile).mockImplementation(
      (() => new Promise((resolve) => { release = resolve; })) as never,
    );
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { screen.getByTestId('submit').click(); });
    expect(release, 'the link is being fetched').toBeTypeOf('function');
    await honestCache();
    pushSpy.mockClear();

    await act(async () => {
      release({
        username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
      });
      await new Promise((r) => setTimeout(r, 60));
    });

    // A barrier on the outcome, not a sleep: the write behind it runs through
    // the real coordinator, and how long that takes is the machine's business.
    await waitFor(() => expect(pushSpy, 'the submit it belonged to lands')
      .toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('gh-status').textContent,
      'the import reports its own success').toContain('githubImportSuccess');
    expect(screen.getByTestId('gh-loading').textContent, 'the spinner goes off').toBe('no');
  });

  it('O2b-github: an import resolving after the owner moved writes no receipt, status or spinner', async () => {
    await hydratedU1();
    let release!: (v: unknown) => void;
    vi.mocked(parseGitHubProfile).mockImplementation(
      (() => new Promise((resolve) => { release = resolve; })) as never,
    );
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { screen.getByTestId('submit').click(); });
    expect(release, 'the link is being fetched').toBeTypeOf('function');
    const spinnerDuring = screen.getByTestId('gh-loading').textContent;
    expect(spinnerDuring, 'and the spinner is on').toBe('yes');

    await moveOwnerTo(U2);
    await honestCache();
    pushSpy.mockClear();
    const stagesBefore = syncOverrides.stageCalls;
    const bytes = storageBytes();
    const rec = recordStorage();

    await act(async () => {
      release({
        username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
      });
      await new Promise((r) => setTimeout(r, 60));
    });

    const writes = privateOf(rec.calls.set);
    rec.restore();

    expect(screen.getByTestId('gh-status').textContent, 'no status line is written').toBe('');
    expect(screen.getByTestId('gh-loading').textContent,
      'and no spinner state either').toBe(spinnerDuring);
    expect(screen.getByTestId('skills').textContent,
      'the skills it resolved are not merged').toBe('');
    expect(writes, 'nothing durable is written').toEqual([]);
    expect(storageBytes()).toBe(bytes);
    expect(syncOverrides.stageCalls, 'and nothing is staged').toBe(stagesBefore);
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it('O2b-stage: a save landing after the owner moved paints neither success nor error', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    let release!: (v: unknown) => void;
    syncOverrides.stageProfilePatch = (
      () => new Promise((resolve) => { release = resolve; })
    ) as never;
    await act(async () => { screen.getByTestId('submit').click(); });
    expect(release, 'the write is in flight').toBeTypeOf('function');
    const during = screen.getByTestId('save-status').textContent;
    expect(during, 'and it owns the wording while it runs').toBe('saving');

    await moveOwnerTo(U2);
    await honestCache();
    pushSpy.mockClear();

    await act(async () => {
      release({
        status: 'saved', revision: 10,
        profile: { ...ROW, research_interests: 'my interests' },
      });
      await new Promise((r) => setTimeout(r, 60));
    });

    expect(screen.getByTestId('save-status').textContent,
      "a dead token's outcome is neither this browser's success nor its error").toBe(during);
    expect(cacheMocks.clearMatchCache,
      "and the new owner's cache is not touched").not.toHaveBeenCalled();
    expect(pushSpy, 'nothing navigates').not.toHaveBeenCalled();

    // The refs that dead write left behind are the other half: U2 arrives for
    // real and saves something of their own, and nothing of U1's rides out
    // with it — not as an extra write, and not on the way out either.
    mockLoadProfile = () => Promise.resolve(
      cloudRow({ college: 'Siebel', major: 'Stats', grade: 'Senior' }, 3),
    );
    syncOverrides.stageProfilePatch = null;
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('3'));
    const stagesBefore = syncOverrides.stageCalls;
    const flushesBefore = syncOverrides.flushCalls;
    commitProfilePatch.mockClear();

    act(() => { screen.getByTestId('set-coursework').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(syncOverrides.stageCalls,
      "U2's own edit is written").toBe(stagesBefore + 1));
    expect(syncOverrides.flushCalls, "and U1's leftovers flush nothing")
      .toBe(flushesBefore);
    expect(await sentPatches().some((p) => 'research_interests' in p),
      "nor does U1's field ride out with it").toBe(false);

    const stagesAfterEdit = syncOverrides.stageCalls;
    cleanup();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(syncOverrides.stageCalls, 'and leaving the page writes nothing more')
      .toBe(stagesAfterEdit);
  });

  it('O3: the same person at a new epoch is a different capability', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-coursework').click(); });
    await reclaimSameUid();

    await honestCache();
    pushSpy.mockClear();
    commitProfilePatch.mockClear();
    const stagesBefore = syncOverrides.stageCalls;
    const statusBefore = screen.getByTestId('save-status').textContent;
    const bytes = storageBytes();
    const rec = recordStorage();

    await act(async () => {
      screen.getByTestId('submit').click();
      await new Promise((r) => setTimeout(r, 40));
    });

    const writes = privateOf(rec.calls.set);
    const reads = privateOf(rec.calls.get);
    rec.restore();

    expect(syncOverrides.stageCalls, 'nothing is staged').toBe(stagesBefore);
    expect(commitProfilePatch, 'and nothing is sent').not.toHaveBeenCalled();
    expect(writes, 'no private key is written').toEqual([]);
    expect(reads, 'and none is read').toEqual([]);
    expect(storageBytes(), 'the bytes are as they were').toBe(bytes);
    expect(cacheMocks.clearMatchCache, 'no cache is invalidated').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();
    expect(screen.getByTestId('save-status').textContent,
      'the screen from the previous epoch claims nothing').toBe(statusBefore);
  });

  it('O4-control: a current origin stages once, and only then clears and navigates', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    const stages: { keys: string[]; patch: Record<string, unknown> }[] = [];
    syncOverrides.stageProfilePatch = (async (
      patch: Record<string, unknown>, keys: readonly string[],
    ) => {
      stages.push({ keys: [...keys], patch: { ...patch } });
      // The side effects must follow the write, never precede it.
      expect(cacheMocks.clearMatchCache, 'the cache is still intact when the write goes out')
        .not.toHaveBeenCalled();
      expect(pushSpy, 'and nothing has navigated yet').not.toHaveBeenCalled();
      return { status: 'saved' as const, revision: 10, profile: { ...ROW, ...patch } };
    }) as never;
    await honestCache();
    pushSpy.mockClear();

    await act(async () => {
      screen.getByTestId('submit').click();
      await new Promise((r) => setTimeout(r, 60));
    });

    await waitFor(() => expect(pushSpy, 'it navigates once it lands')
      .toHaveBeenCalledWith('/results'));
    expect(stages, 'exactly one write').toHaveLength(1);
    expect(stages[0].keys, 'carrying what the person changed').toContain('research_interests');
    expect(screen.getByTestId('save-status').textContent, 'it reports its success').toBe('saved');
    expect(cacheMocks.clearMatchCache, 'the cache is cleared once').toHaveBeenCalledTimes(1);
  });

  /** A shared draft whose Generate is waiting on the visitor's own row. */
  async function heldOwnRow() {
    const share = encodeProfile({
      ...DEFAULT_PROFILE, college: 'Grainger', major: 'CS', grade: 'Junior',
    });
    searchRef.current = `share=${share}`;
    const reads: { resolve: (v: unknown) => void }[] = [];
    syncOverrides.hydrateProfile = (() => new Promise((resolve) => {
      reads.push({ resolve });
    })) as never;
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('valid').textContent).toBe('yes'));
    await honestCache();
    pushSpy.mockClear();
    const stages: { keys: string[]; patch: Record<string, unknown> }[] = [];
    syncOverrides.stageProfilePatch = (async (
      patch: Record<string, unknown>, keys: readonly string[],
    ) => {
      stages.push({ keys: [...keys], patch: { ...patch } });
      return { status: 'saved' as const, revision: 10, profile: { ...ROW, ...patch } };
    }) as never;
    // The capability the request STARTED under — what an own-row read must
    // come back attributed to.
    const atRequest = captureOwnerToken();
    await act(async () => { screen.getByTestId('submit').click(); });
    expect(reads, "the visitor's own row is being read").toHaveLength(1);
    expect(stages, 'and nothing has been staged yet').toHaveLength(0);
    const row = (token: typeof atRequest) => ({
      profile: { ...ROW },
      baseProfile: { ...ROW },
      revision: 9,
      source: 'cloud' as const,
      token,
      hasPending: false,
      conflictKeys: [] as string[],
      conflicts: [],
      quarantineFailed: false,
    });
    return { reads, stages, atRequest, row };
  }

  it('O3b-control: an own-row read attributed to the request origin is accepted', async () => {
    const { reads, stages, atRequest, row } = await heldOwnRow();

    await act(async () => {
      reads[0].resolve(row(atRequest));
      await new Promise((r) => setTimeout(r, 40));
    });

    await waitFor(() => expect(pushSpy, 'it navigates once it lands')
      .toHaveBeenCalledTimes(1));
    expect(stages, 'the draft is committed').toHaveLength(1);
  });

  it('O3b: an own-row read attributed to a different capability is refused', async () => {
    const { reads, stages, atRequest, row } = await heldOwnRow();
    // The global owner is NOT moved. The row simply comes back carrying a
    // capability this screen does not hold — the one thing a base may never
    // be accepted from.
    const foreign = { ...atRequest, epoch: atRequest.epoch + 1 };
    const bytes = storageBytes();
    const rec = recordStorage();

    await act(async () => {
      reads[0].resolve(row(foreign));
      await new Promise((r) => setTimeout(r, 40));
    });

    const writes = privateOf(rec.calls.set);
    rec.restore();

    expect(stages, 'nothing is staged against a base this screen cannot claim')
      .toHaveLength(0);
    expect(writes, 'and nothing durable is written').toEqual([]);
    expect(storageBytes()).toBe(bytes);
    expect(cacheMocks.clearMatchCache, 'no cache is cleared').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();
    expect(screen.getByTestId('view-rev').textContent,
      'nor is its revision adopted').toBe('none');
  });

  it('O-manual-control: a manual import under its own owner runs and reports', async () => {
    await hydratedU1();
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
    });
    act(() => { screen.getByTestId('set-gh').click(); });
    vi.mocked(parseGitHubProfile).mockClear();

    await act(async () => {
      screen.getByTestId('gh-import').click();
      await new Promise((r) => setTimeout(r, 40));
    });

    expect(parseGitHubProfile, 'the link is fetched').toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('gh-status').textContent,
      'and the result is reported').toContain('githubImportSuccess');
    expect(screen.getByTestId('skills').textContent, 'the skills land on the form').toBe('Go');
  });

  it('O-manual: a manual import clicked after the owner moved never starts', async () => {
    await hydratedU1();
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
    });
    act(() => { screen.getByTestId('set-gh').click(); });
    await moveOwnerTo(U2);
    vi.mocked(parseGitHubProfile).mockClear();
    const statusBefore = screen.getByTestId('gh-status').textContent;
    const spinnerBefore = screen.getByTestId('gh-loading').textContent;
    const skillsBefore = screen.getByTestId('skills').textContent;
    const bytes = storageBytes();
    const rec = recordStorage();

    await act(async () => {
      screen.getByTestId('gh-import').click();
      await new Promise((r) => setTimeout(r, 40));
    });

    const writes = privateOf(rec.calls.set);
    rec.restore();

    expect(parseGitHubProfile, 'the request never goes out').not.toHaveBeenCalled();
    expect(screen.getByTestId('gh-loading').textContent,
      'the spinner is never turned on').toBe(spinnerBefore);
    expect(screen.getByTestId('gh-status').textContent,
      'and the status line is never cleared or written').toBe(statusBefore);
    expect(screen.getByTestId('skills').textContent, 'nothing is merged').toBe(skillsBefore);
    expect(writes, 'and nothing durable is written').toEqual([]);
    expect(storageBytes()).toBe(bytes);
  });

  it('O-manual-held: an owner move during a manual import marks and merges nothing', async () => {
    await hydratedU1();
    let release!: (v: unknown) => void;
    vi.mocked(parseGitHubProfile).mockImplementation(
      (() => new Promise((resolve) => { release = resolve; })) as never,
    );
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { screen.getByTestId('gh-import').click(); });
    expect(release, 'the import is in flight').toBeTypeOf('function');
    const spinnerDuring = screen.getByTestId('gh-loading').textContent;

    await moveOwnerTo(U2);
    const bytes = storageBytes();
    const rec = recordStorage();

    await act(async () => {
      release({
        username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
      });
      await new Promise((r) => setTimeout(r, 40));
    });

    const writes = privateOf(rec.calls.set);
    rec.restore();

    expect(screen.getByTestId('skills').textContent,
      'the skills it resolved reach no form').toBe('');
    expect(screen.getByTestId('gh-status').textContent, 'no status is written').toBe('');
    expect(screen.getByTestId('gh-loading').textContent,
      'and no spinner state').toBe(spinnerDuring);
    expect(writes, 'nothing is marked or recorded').toEqual([]);
    expect(storageBytes()).toBe(bytes);
  });

  /**
   * A commit the test settles by hand, plus a promise that resolves the
   * moment the request is actually MADE. Awaiting that handshake is not a
   * window: it cannot expire, so evidence can never fail before the request
   * it is about has started.
   */
  function heldCommit() {
    let announce!: () => void;
    const requested = new Promise<void>((resolve) => { announce = resolve; });
    const settlers: { resolve: (v: unknown) => void; reject: (e: unknown) => void }[] = [];
    commitProfilePatch.mockImplementation((() => new Promise((resolve, reject) => {
      settlers.push({ resolve, reject });
      announce();
    })) as never);
    return { requested, settlers };
  }

  /** Waits for the request itself, but never forever: a build that sends
   *  nothing must fail on an assertion about the send, not on a clock. */
  async function awaitRequest(
    held: ReturnType<typeof heldCommit>, settleMs = 0,
  ) {
    await act(async () => {
      if (settleMs > 0) await new Promise((r) => setTimeout(r, settleMs));
      await Promise.race([held.requested, new Promise((r) => setTimeout(r, 300))]);
    });
    expect(held.settlers.length, 'the write really went out').toBeGreaterThan(0);
  }

  /** Every promise rejection nobody handled, collected the way the runtime
   *  itself sees them. Production hands `handleSubmit` to `onClick`, which
   *  discards the promise, so a rejection escaping it has no handler at all —
   *  a crash in the page, not a status on the form. */
  function captureUnhandled() {
    const reasons: unknown[] = [];
    const onUnhandled = async (reason: unknown) => { reasons.push(reason); };
    process.on('unhandledRejection', onUnhandled);
    registerSpy({ mockRestore: () => process.off('unhandledRejection', onUnhandled) });
    return reasons;
  }

  /** Skill-operation names on the durable pending write, or a hard failure. */
  function pendingSkillNames(): string[] {
    const pending = readProfileSyncEnvelope()?.pending;
    if (!pending) throw new Error('no pending write on disk');
    return pending.skillOps.map((op) => (op.kind === 'add' && op.skill ? op.skill.name : '<replace>'));
  }

  /** Frozen counters, taken the instant an owner-only transition is done. */
  function freeze() {
    return {
      stages: syncOverrides.stageCalls,
      flushes: syncOverrides.flushCalls,
      commits: commitProfilePatch.mock.calls.length,
      bytes: storageBytes(),
    };
  }

  /** Everything a stale action must not have done. */
  function expectNoEffect(
    before: ReturnType<typeof freeze>,
    rec: ReturnType<typeof recordStorage>,
  ) {
    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();
    expect(reads, 'no private key is read').toEqual([]);
    expect(writes, 'none is written').toEqual([]);
    expect(removes, 'and none is removed').toEqual([]);
    expect(enumerated, 'the keyspace is not even scanned').toBe(0);
    expect(storageBytes(), 'so the bytes are exactly as they were').toBe(before.bytes);
    expect(syncOverrides.stageCalls, 'nothing is staged').toBe(before.stages);
    expect(syncOverrides.flushCalls, 'nothing is flushed').toBe(before.flushes);
    expect(commitProfilePatch.mock.calls.length, 'and nothing is sent').toBe(before.commits);
    expect(cacheMocks.clearMatchCache, 'no cache is invalidated').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();
  }

  /** The real U2, arriving properly, with a row of their own. */
  async function u2Arrives(row: Record<string, unknown> = {
    college: 'Siebel', major: 'Stats', grade: 'Senior',
  }) {
    mockLoadProfile = () => Promise.resolve(cloudRow(row, 3));
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('3'));
  }

  it('E1-control: a real skills edit carries one replace into the write', async () => {
    await hydratedU1();
    const held = await heldCommit();
    act(() => { screen.getByTestId('replace-skills').click(); });
    await waitFor(() => expect(screen.getByTestId('skills').textContent).toBe('Rust'));

    await awaitRequest(held, 1700);

    expect(await pendingSkillNames(), 'the hand edit is the intent from here on')
      .toEqual(['<replace>']);
    await act(async () => {
      held.settlers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
  });

  it('E1: a skills edit on a stale screen never reaches the new ledger', async () => {
    await hydratedU1();
    await moveOwnerTo(U2);
    await honestCache();
    pushSpy.mockClear();
    const before = freeze();
    const skillsBefore = screen.getByTestId('skills').textContent;
    const statusBefore = screen.getByTestId('save-status').textContent;
    const rec = recordStorage();

    act(() => { screen.getByTestId('replace-skills').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(screen.getByTestId('skills').textContent, 'nothing paints').toBe(skillsBefore);
    expect(screen.getByTestId('save-status').textContent, 'nothing is claimed')
      .toBe(statusBefore);
    expectNoEffect(before, rec);

    // The ledger is STICKY: a replace suppresses every later addition. So the
    // proof is U2's own additive import, read off their durable write.
    await u2Arrives();
    const held = await heldCommit();
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'u2', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
    });
    act(() => { screen.getByTestId('set-gh').click(); });
    act(() => { screen.getByTestId('gh-import').click(); });
    await awaitRequest(held, 1700);

    const names = await pendingSkillNames();
    expect(names, "U2's own addition is what their write carries").toContain('Go');
    expect(names, "and no replace the old screen made").not.toContain('<replace>');
    await act(async () => {
      held.settlers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
  });

  it('E2-control: a current-owner edit paints and saves', async () => {
    await hydratedU1();
    await honestCache();
    act(() => { screen.getByTestId('set-interests').click(); });
    expect(screen.getByTestId('interests').textContent, 'it paints at once')
      .toBe('my interests');
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    waitFor(() => expect(sentPatches().some((q) => q.research_interests === 'my interests'),
      'and it is sent').toBe(true));
  });

  it('E2: a generic edit on a stale screen paints nothing and saves nothing', async () => {
    await hydratedU1();
    await moveOwnerTo(U2);
    await honestCache();
    pushSpy.mockClear();
    const before = freeze();
    const interestsBefore = screen.getByTestId('interests').textContent;
    const statusBefore = screen.getByTestId('save-status').textContent;
    const rec = recordStorage();

    act(() => { screen.getByTestId('set-interests').click(); });
    // Past the debounce horizon: the passive save this edit would have armed
    // has had its whole window and must still have done nothing.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(screen.getByTestId('interests').textContent, 'the value does not paint')
      .toBe(interestsBefore);
    expect(screen.getByTestId('save-status').textContent, 'and the status does not move')
      .toBe(statusBefore);
    expectNoEffect(before, rec);
  });

  it('E3: an edit made under U1 is never re-authorized as U2 by the passive effect', async () => {
    await hydratedU1();
    await honestCache();
    pushSpy.mockClear();

    // ONE act, and the recorder is installed INSIDE it: React flushes the
    // passive effect on the way out, so anything armed there is captured.
    let before!: ReturnType<typeof freeze>;
    let rec!: ReturnType<typeof recordStorage>;
    let statusBefore!: string | null;
    let seeded = false;
    await act(async () => {
      screen.getByTestId('set-interests').click();
      advanceOwnerEpoch(U2);
      await syncLocalIdentityOwner(U2);
      // U2 has a home-form operation of their own, so an old token is no
      // defence: a stale save would find a dirty set and send U1's document.
      seeded = recordProfileIntent(
        { ...DEFAULT_PROFILE, college: 'Siebel' } as never, ['college'], captureOwnerToken(),
        { writer: HOME_FORM_WRITER, observedBase: { profile: {} as never, revision: 0 } },
      );
      statusBefore = screen.getByTestId('save-status').textContent;
      before = freeze();
      rec = recordStorage();
    });
    expect(seeded, "U2's own operation is on disk").toBe(true);

    // …and again through the whole timer phase.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();
    expect(reads, "U2's journal is not read on U1's behalf").toEqual([]);
    expect(writes, 'and not written').toEqual([]);
    expect(removes, 'nor removed').toEqual([]);
    expect(enumerated, 'nor scanned').toBe(0);
    expect(storageBytes(), "so U2's bytes are exactly as they were").toBe(before.bytes);
    expect(screen.getByTestId('save-status').textContent,
      'and nothing is claimed on the old screen').toBe(statusBefore);
    expect(syncOverrides.stageCalls, 'nothing is staged').toBe(before.stages);
    expect(commitProfilePatch.mock.calls.length, 'and nothing is sent').toBe(before.commits);
    expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();

    // And the real arrival is clean.
    await u2Arrives();
    expect(screen.getByTestId('interests').textContent,
      "U2's form carries nothing of U1's").toBe('');
  });

  it('E3-timer: an armed save revalidates its owner when the timer fires', async () => {
    await hydratedU1();
    await honestCache();
    pushSpy.mockClear();
    // A wholly legitimate U1 edit whose passive effect has already run: the
    // timer is armed and the wording is taken. Everything after this is the
    // 1.5s callback and nothing else.
    act(() => { screen.getByTestId('set-interests').click(); });
    expect(screen.getByTestId('save-status').textContent,
      'the save is armed and waiting out its debounce').toBe('saving');

    await moveOwnerTo(U2);
    const u2Token = captureOwnerToken();
    expect(recordProfileIntent(
      { ...DEFAULT_PROFILE, college: 'Siebel' } as never, ['college'], u2Token,
      { writer: HOME_FORM_WRITER, observedBase: { profile: {} as never, revision: 0 } },
    ), "U2's own operation is on disk").toBe(true);
    const before = freeze();
    const statusBefore = screen.getByTestId('save-status').textContent;
    const rec = recordStorage();

    // The timer fires inside this window.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();
    expect(reads, "the timer does not read U2's journal").toEqual([]);
    expect(writes, 'nor write it').toEqual([]);
    expect(removes, 'nor remove from it').toEqual([]);
    expect(enumerated, 'nor scan the keyspace').toBe(0);
    expect(storageBytes(), 'the bytes are as they were').toBe(before.bytes);
    expect(screen.getByTestId('save-status').textContent,
      'and the old screen is told nothing new').toBe(statusBefore);
    expect(syncOverrides.stageCalls, 'nothing is staged').toBe(before.stages);
    expect(commitProfilePatch.mock.calls.length, 'and nothing is sent')
      .toBe(before.commits);
  });

  it('E3-unmount: leaving the page does not flush a U1 edit under U2 either', async () => {
    await hydratedU1();
    await honestCache();
    pushSpy.mockClear();
    // A wholly legitimate U1 edit, with its save ARMED — the passive effect
    // has run and taken the wording, so what follows is the cleanup path and
    // nothing else.
    act(() => { screen.getByTestId('set-interests').click(); });
    expect(screen.getByTestId('save-status').textContent,
      'the save is armed and waiting out its debounce').toBe('saving');

    await moveOwnerTo(U2);
    const u2Token = captureOwnerToken();
    expect(recordProfileIntent(
      { ...DEFAULT_PROFILE, college: 'Siebel' } as never, ['college'], u2Token,
      { writer: HOME_FORM_WRITER, observedBase: { profile: {} as never, revision: 0 } },
    ), "U2's own operation is on disk").toBe(true);
    const before = freeze();
    const rec = recordStorage();

    // Before the 1.5s timer can fire: the page is left, and the cleanup's own
    // flush is the only thing that could still send this.
    cleanup();
    await act(async () => { await new Promise((r) => setTimeout(r, 40)); });

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();
    expect(reads, "U2's journal is not read by the cleanup").toEqual([]);
    expect(writes, 'not written').toEqual([]);
    expect(removes, 'not removed').toEqual([]);
    expect(enumerated, 'and not scanned').toBe(0);
    expect(storageBytes(), 'the bytes are as they were').toBe(before.bytes);
    expect(syncOverrides.stageCalls, 'the unmount flush stages nothing')
      .toBe(before.stages);
    expect(commitProfilePatch.mock.calls.length, 'and sends nothing')
      .toBe(before.commits);
  });

  it('E4: a resume parse resolving on a stale screen paints and marks nothing', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    render(<Suspense fallback={null}><ResumeIdentityHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    act(() => { fireEvent.click(screen.getByTestId('hold')); });

    await moveOwnerTo(U2);
    const STALE_SKILL = 'PyTorch';
    await honestCache();
    pushSpy.mockClear();
    const before = freeze();
    const interestsBefore = screen.getByTestId('interests').textContent;
    const resumeBefore = screen.getByTestId('resume').textContent;
    const skillsBefore = screen.getByTestId('skills').textContent;
    const statusBefore = screen.getByTestId('save-status').textContent;
    const rec = recordStorage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('fire-held-pytorch'));
      await new Promise((r) => setTimeout(r, 1700));
    });

    expect(screen.getByTestId('interests').textContent, 'no interests paint')
      .toBe(interestsBefore);
    expect(screen.getByTestId('resume').textContent, 'no résumé').toBe(resumeBefore);
    expect(screen.getByTestId('skills').textContent, 'no skills').toBe(skillsBefore);
    expect(screen.getByTestId('save-status').textContent, 'and no status')
      .toBe(statusBefore);
    expectNoEffect(before, rec);

    // The ledger is in memory, so the proof is what U2's OWN additive action
    // carries into their durable write.
    mockLoadProfile = () => Promise.resolve(
      cloudRow({ college: 'Siebel', major: 'Stats', grade: 'Senior' }, 3),
    );
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('3'));
    const held = await heldCommit();
    act(() => { fireEvent.click(screen.getByTestId('fire-current-keras')); });
    await awaitRequest(held, 1700);

    const names = await pendingSkillNames();
    expect(names, "U2's own addition is what their write carries").toContain('Keras');
    expect(names, "and nothing the stale parse resolved").not.toContain(STALE_SKILL);
    expect(names, 'nor a replace it never made').not.toContain('<replace>');
    await act(async () => {
      held.settlers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
  });

  it('E4-control-ledger: a current-owner parse really does add its skill', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    render(<Suspense fallback={null}><ResumeIdentityHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    await honestCache();
    act(() => { fireEvent.click(screen.getByTestId('hold')); });
    const held = await heldCommit();

    act(() => { fireEvent.click(screen.getByTestId('fire-held-pytorch')); });
    await awaitRequest(held, 1700);

    expect(screen.getByTestId('skills').textContent, 'the skill lands on the form')
      .toContain('PyTorch');
    expect(await pendingSkillNames(), 'and on the write, as an addition')
      .toContain('PyTorch');
    await act(async () => {
      held.settlers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });
  });

  it('E4-control: U2\'s own parse reaches U2\'s write', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    render(<Suspense fallback={null}><ResumeIdentityHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    await honestCache();

    await act(async () => {
      fireEvent.click(screen.getByTestId('fire-current'));
      await new Promise((r) => setTimeout(r, 1700));
    });

    expect(screen.getByTestId('interests').textContent,
      'the current parse paints').toBe('u2 interests');
    waitFor(() => expect(sentPatches().some((q) => q.resume_text === 'resume body'),
      'and is sent').toBe(true));
  });

  const RESUME_ROW = {
    ...ROW,
    resume_text: 'u1 distinctive resume',
    coursework: ['ECE 385'],
    research_interests: 'u1 distinctive research',
  };

  it('E5-control: a current-owner removal persists exactly the résumé bundle', async () => {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...RESUME_ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('resume').textContent)
      .toBe('u1 distinctive resume'));
    await honestCache();
    commitProfilePatch.mockClear();

    await act(async () => {
      screen.getByTestId('remove-resume').click();
      await new Promise((r) => setTimeout(r, 60));
    });

    waitFor(() => expect(sentPatches().length, 'the removal is sent at once')
      .toBeGreaterThan(0));
    const patch = await sentPatches()[0];
    expect(Object.keys(patch).sort(), 'and it is exactly the résumé bundle')
      .toEqual(['coursework', 'resume_text']);
    expect(patch.resume_text).toBe('');
  });

  async function staleResumeRemoval(move: () => Promise<void>) {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...RESUME_ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('resume').textContent)
      .toBe('u1 distinctive resume'));
    // Awaited: the identity transition now completes under the private-storage
    // lock, and everything below is about what the screen does AFTER the
    // browser has actually changed hands.
    await move();
    await honestCache();
    pushSpy.mockClear();
    // HELD: a stale removal that does send would otherwise have its write
    // acknowledged and consumed, and the contamination would be gone by the
    // time this test looked for it.
    const held = await heldCommit();
    const before = freeze();
    const resumeBefore = screen.getByTestId('resume').textContent;
    const statusBefore = screen.getByTestId('save-status').textContent;
    const rec = recordStorage();

    await act(async () => {
      screen.getByTestId('remove-resume').click();
      await new Promise((r) => setTimeout(r, 60));
    });

    const seen = {
      reads: privateOf(rec.calls.get),
      writes: privateOf(rec.calls.set),
      removes: privateOf(rec.calls.remove),
      enumerate: rec.calls.enumerate,
    };
    rec.restore();

    // THE LEAK PROBE FIRST, so it is what fails when the source contaminates:
    // a write standing in the new owner's envelope, carrying U1's document.
    const pending = readProfileSyncEnvelope()?.pending;
    const desired = (pending?.desiredProfile ?? {}) as Record<string, unknown>;
    expect(desired.research_interests, "U1's research is in no write of the new owner's")
      .not.toBe('u1 distinctive research');
    expect(desired.coursework, "nor U1's coursework").toBeUndefined();
    expect(pending, 'in fact the stale removal leaves no write at all').toBeFalsy();

    expect(screen.getByTestId('resume').textContent, 'the form is untouched')
      .toBe(resumeBefore);
    expect(screen.getByTestId('save-status').textContent, 'and says nothing')
      .toBe(statusBefore);
    expect(seen.reads, 'no private key is read').toEqual([]);
    expect(seen.writes, 'none is written').toEqual([]);
    expect(seen.removes, 'and none is removed').toEqual([]);
    expect(seen.enumerate, 'the keyspace is not even scanned').toBe(0);
    expect(storageBytes(), 'so the bytes are exactly as they were').toBe(before.bytes);
    expect(syncOverrides.stageCalls, 'nothing is staged').toBe(before.stages);
    expect(commitProfilePatch.mock.calls.length, 'and nothing is sent').toBe(before.commits);
    expect(cacheMocks.clearMatchCache, 'no cache is invalidated').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();
    if (held.settlers.length > 0) {
      await act(async () => {
        held.settlers[0].reject(new Error('offline'));
        await new Promise((r) => setTimeout(r, 20));
      });
    }
  }

  it('E5: a removal clicked on a stale screen writes nothing anywhere', async () => {
    await staleResumeRemoval(() => moveOwnerTo(U2));
    await u2Arrives();
    expect(screen.getByTestId('resume').textContent, "U2's own row is clean").toBe('');
  });

  it('E5-epoch: the same person at a new epoch cannot remove it either', async () => {
    await staleResumeRemoval(() => reclaimSameUid());
  });

  it('E6: a search-weight change on a stale screen changes nothing', async () => {
    await hydratedU1();
    await moveOwnerTo(U2);
    await honestCache();
    pushSpy.mockClear();
    const before = freeze();
    const weightBefore = screen.getByTestId('weight').textContent;
    const rec = recordStorage();

    act(() => { screen.getByTestId('set-weight').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(screen.getByTestId('weight').textContent, 'the slider does not move')
      .toBe(weightBefore);
    expectNoEffect(before, rec);
  });

  it('E6-alias: the public setProfile alias is gated too', async () => {
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('hydration').textContent).toBe('ready'));
    await moveOwnerTo(U2);
    await honestCache();
    pushSpy.mockClear();
    const before = freeze();
    const majorBefore = screen.getByTestId('major').textContent;
    const collegeBefore = screen.getByTestId('college').textContent;
    const validBefore = screen.getByTestId('valid').textContent;
    const statusBefore = screen.getByTestId('save-status').textContent;
    const rec = recordStorage();

    act(() => { screen.getByTestId('make-valid').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    expect(screen.getByTestId('major').textContent, 'nothing paints').toBe(majorBefore);
    expect(screen.getByTestId('college').textContent, 'nothing at all').toBe(collegeBefore);
    expect(screen.getByTestId('valid').textContent,
      'so the form does not become submittable either').toBe(validBefore);
    expect(screen.getByTestId('save-status').textContent, 'and says nothing')
      .toBe(statusBefore);
    expectNoEffect(before, rec);
  });

  it('E6-control: the public setProfile alias still paints and saves', async () => {
    mockLoadProfile = () => Promise.resolve(absentRow());
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('hydration').textContent).toBe('ready'));
    await honestCache();

    act(() => { screen.getByTestId('make-valid').click(); });
    expect(screen.getByTestId('major').textContent, 'it paints').toBe('CS');
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    waitFor(() => expect(sentPatches().some((q) => q.major === 'CS'),
      'and is sent').toBe(true));
  });

  it('E7-control: a completed submit hands the button back', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    await honestCache();
    pushSpy.mockClear();
    const held = await heldCommit();

    act(() => { screen.getByTestId('submit').click(); });
    await awaitRequest(held);
    expect(screen.getByTestId('submitting').textContent, 'the button is busy').toBe('yes');

    // Answered the way the server answers: the row that THIS patch produces,
    // not a hand-written document that disagrees with what was sent.
    const intent = commitProfilePatch.mock.calls[0][0];
    await act(async () => {
      held.settlers[0].resolve(await applyIntent(intent));
      await new Promise((r) => setTimeout(r, 60));
    });

    await waitFor(() => expect(screen.getByTestId('submitting').textContent,
      'and it comes back').toBe('no'));
  });

  /** A held flush, with a handshake for the request it makes. */
  function heldFlush() {
    let announce!: () => void;
    const requested = new Promise<void>((resolve) => { announce = resolve; });
    const settlers: { resolve: (v: unknown) => void; reject: (e: unknown) => void }[] = [];
    syncOverrides.flushPendingProfileWrite = (() => new Promise((resolve, reject) => {
      settlers.push({ resolve, reject });
      announce();
    })) as never;
    return { requested, settlers };
  }

  /** A held stage whose RESULT (not rejection) the test chooses. */
  function heldStage() {
    let announce!: () => void;
    const requested = new Promise<void>((resolve) => { announce = resolve; });
    const settlers: { resolve: (v: unknown) => void }[] = [];
    syncOverrides.stageProfilePatch = (() => new Promise((resolve) => {
      settlers.push({ resolve });
      announce();
    })) as never;
    return { requested, settlers };
  }

  /** Same person, same epoch, but this browser can no longer vouch for them. */
  function unconfirmRealm() {
    const stillOwner = captureOwnerToken();
    localStorage.removeItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER);
    expect(isTokenOwnerStillCurrent(stillOwner),
      'they are still the owner of this browser').toBe(true);
    expect(isOwnerTokenValid(stillOwner, stillOwner.uid),
      'but their local data is no longer confirmed for them').toBe(false);
    return stillOwner;
  }

  it.each([
    ['blocked', { status: 'blocked' }],
    ['abandoned', { status: 'abandoned' }],
  ] as const)(
    'R-realm-failure-%s: a failure result reaches the owner whose realm is unconfirmed',
    async (_label, outcome) => {
      await hydratedU1();
      act(() => { screen.getByTestId('set-interests').click(); });
      await honestCache();
      const held = await heldStage();
      act(() => { screen.getByTestId('submit').click(); });
      await act(async () => { await held.requested; });
      expect(held.settlers.length, 'the write really went out').toBe(1);
      expect(screen.getByTestId('save-status').textContent, 'and owns the wording')
        .toBe('saving');

      await unconfirmRealm();

      // Snapshotted the instant BEFORE settlement: what is asserted is this
      // result's delta, not anything the submit already did on its way here.
      const revBefore = screen.getByTestId('view-rev').textContent;
      const conflictsBefore = screen.getByTestId('conflict-keys').textContent;
      const bytesBefore = storageBytes();
      const cacheBefore = cacheMocks.clearMatchCache.mock.calls.length;
      const navBefore = pushSpy.mock.calls.length;
      const rec = recordStorage();

      await act(async () => { held.settlers[0].resolve(outcome); });
      await settle();

      // LEAK FIRST: a browser that cannot vouch for its own data must not go
      // looking through it either.
      const reads = privateOf(rec.calls.get);
      const writes = privateOf(rec.calls.set);
      const removes = privateOf(rec.calls.remove);
      const enumerated = rec.calls.enumerate;
      rec.restore();
      expect(reads, 'nothing private is read').toEqual([]);
      expect(writes, 'nothing written').toEqual([]);
      expect(removes, 'nothing removed').toEqual([]);
      expect(enumerated, 'and the keyspace is not scanned').toBe(0);

      // Never left saying "saving", whatever the outcome was: this browser
      // cannot confirm anything locally, which is what device-failed means.
      expect(screen.getByTestId('save-status').textContent,
        'their own unconfirmable write is still their news').toBe('device-failed');
      expect(screen.getByTestId('view-rev').textContent,
        'while nothing about the row is treated as fact').toBe(revBefore);
      expect(screen.getByTestId('conflict-keys').textContent,
        'and no question is published from it').toBe(conflictsBefore);
      expect(storageBytes(), 'nothing private moves').toBe(bytesBefore);
      expect(cacheMocks.clearMatchCache.mock.calls.length, 'nothing is invalidated')
        .toBe(cacheBefore);
      expect(pushSpy.mock.calls.length, 'and nothing navigates').toBe(navBefore);

      // Retry is really armed: once this browser can vouch for them again, the
      // same unsent write goes out — proven by the request, by assertion.
      await syncLocalIdentityOwner(HOME_UID);
      const flush = await heldFlush();
      act(() => { screen.getByTestId('retry-sync').click(); });
      await settle();
      expect(flush.settlers.length, 'Retry issues the write that did not land').toBe(1);
      await act(async () => { flush.settlers[0].reject(new Error('offline')); });
      await settle();
    },
  );

  it('R-realm-success: a success may NOT be applied while the realm is unconfirmed', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    await honestCache();
    const held = await heldStage();
    act(() => { screen.getByTestId('submit').click(); });
    await act(async () => { await held.requested; });

    await unconfirmRealm();

    // Snapshotted the instant BEFORE the result, so what is asserted is the
    // delta this result caused and not anything the submit already did.
    const revBefore = screen.getByTestId('view-rev').textContent;
    const conflictsBefore = screen.getByTestId('conflict-keys').textContent;
    const bytesBefore = storageBytes();
    const cacheBefore = cacheMocks.clearMatchCache.mock.calls.length;
    const navBefore = pushSpy.mock.calls.length;
    const rec = recordStorage();

    await act(async () => {
      held.settlers[0].resolve({
        status: 'saved', revision: 12, profile: { ...ROW, research_interests: 'my interests' },
      });
    });
    await settle();

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();
    expect(reads, 'nothing private is read').toEqual([]);
    expect(writes, 'nothing written').toEqual([]);
    expect(removes, 'nothing removed').toEqual([]);
    expect(enumerated, 'and the keyspace is not scanned').toBe(0);
    expect(screen.getByTestId('conflict-keys').textContent,
      'no question is published from it').toBe(conflictsBefore);

    expect(screen.getByTestId('view-rev').textContent,
      'a row this browser cannot vouch for does not move the baseline')
      .toBe(revBefore);
    // Never left saying "saving": the cloud may well have the row, but this
    // browser cannot confirm it locally, and that is exactly what
    // `device-failed` means. It is reported, and it is retryable.
    expect(screen.getByTestId('save-status').textContent,
      'the honest state is that this device could not confirm it')
      .toBe('device-failed');
    expect(storageBytes(), 'nothing private moves').toBe(bytesBefore);
    expect(cacheMocks.clearMatchCache.mock.calls.length, 'nothing is invalidated')
      .toBe(cacheBefore);
    expect(pushSpy.mock.calls.length, 'and nothing navigates').toBe(navBefore);

    // And once the browser can vouch for them again, Retry really runs.
    await syncLocalIdentityOwner(HOME_UID);
    const flush = await heldFlush();
    act(() => { screen.getByTestId('retry-sync').click(); });
    await settle();
    expect(flush.settlers.length, 'Retry issues the write that could not be confirmed')
      .toBe(1);
    await act(async () => { flush.settlers[0].reject(new Error('offline')); });
    await settle();
  });

  it('R-realm-recovers-in-await-gap: a refused result stays refused', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    await honestCache();
    pushSpy.mockClear();
    const held = await heldStage();
    act(() => { screen.getByTestId('submit').click(); });
    await act(async () => { await held.requested; });

    await unconfirmRealm();
    const revBefore = screen.getByTestId('view-rev').textContent;
    const conflictsBefore = screen.getByTestId('conflict-keys').textContent;
    const cacheBefore = cacheMocks.clearMatchCache.mock.calls.length;
    const navBefore = pushSpy.mock.calls.length;
    // Scoped to the account-private keys, NOT a whole-storage byte compare:
    // the recovery below legitimately rewrites the shared ownership marker,
    // which is device state and belongs to nobody's row. Comparing every byte
    // would fail on the repair itself rather than on anything this result did.
    const rec = recordStorage();

    await act(async () => {
      // The result is handled while the realm is invalid; the browser can
      // vouch for them again one microtask later — inside the very gap the
      // submit's own continuation waits in.
      held.settlers[0].resolve({
        status: 'saved', revision: 12, profile: { ...ROW, research_interests: 'my interests' },
      });
      queueMicrotask(() => { syncLocalIdentityOwner(HOME_UID); });
    });
    await settle();

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();

    // The disposition was taken when the result was handled. A recovery in
    // the gap does not retroactively make it a success.
    expect(isOwnerTokenValid(captureOwnerToken(), HOME_UID),
      'the browser can vouch for them again by now').toBe(true);
    expect(screen.getByTestId('save-status').textContent,
      'but the result was refused when it was handled, and stays refused')
      .toBe('device-failed');
    expect(screen.getByTestId('view-rev').textContent,
      'the baseline never moved').toBe(revBefore);
    expect(screen.getByTestId('conflict-keys').textContent,
      'no question was published').toBe(conflictsBefore);
    expect(reads, 'no account-private key was read').toEqual([]);
    expect(writes, 'none was written').toEqual([]);
    expect(removes, 'and none removed').toEqual([]);
    expect(enumerated, 'nor was the keyspace scanned').toBe(0);
    expect(cacheMocks.clearMatchCache.mock.calls.length,
      'nothing was invalidated on the strength of a recovered realm')
      .toBe(cacheBefore);
    expect(pushSpy.mock.calls.length, 'and nothing navigated').toBe(navBefore);

    // Retry is still the real, armed path.
    const flush = await heldFlush();
    act(() => { screen.getByTestId('retry-sync').click(); });
    await settle();
    expect(flush.settlers.length, 'Retry issues the write that did not land').toBe(1);
    await act(async () => { flush.settlers[0].reject(new Error('offline')); });
    await settle();
  });

  it('R-abandoned-recovered: a repaired browser does not make an abandoned write a success', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    await honestCache();
    pushSpy.mockClear();
    const held = await heldStage();
    act(() => { screen.getByTestId('submit').click(); });
    await act(async () => { await held.requested; });

    // The marker goes and comes back BEFORE the result is handled, so by the
    // time it arrives this browser can vouch for itself again.
    await unconfirmRealm();
    await syncLocalIdentityOwner(HOME_UID);
    expect(isOwnerTokenValid(captureOwnerToken(), HOME_UID),
      'the browser can vouch for them again').toBe(true);

    const revBefore = screen.getByTestId('view-rev').textContent;
    const cacheBefore = cacheMocks.clearMatchCache.mock.calls.length;
    const navBefore = pushSpy.mock.calls.length;

    await act(async () => { held.settlers[0].resolve({ status: 'abandoned' }); });
    await settle();

    // `abandoned` is this write saying the device never confirmed it. A
    // healthy marker is not a substitute for that confirmation.
    expect(screen.getByTestId('save-status').textContent,
      'a write the device never confirmed is still unconfirmed').toBe('device-failed');
    expect(screen.getByTestId('view-rev').textContent, 'no baseline moved')
      .toBe(revBefore);
    expect(cacheMocks.clearMatchCache.mock.calls.length, 'nothing invalidated')
      .toBe(cacheBefore);
    expect(pushSpy.mock.calls.length, 'and nothing navigated').toBe(navBefore);

    const flush = await heldFlush();
    act(() => { screen.getByTestId('retry-sync').click(); });
    await settle();
    expect(flush.settlers.length, 'and Retry is real').toBe(1);
    await act(async () => { flush.settlers[0].reject(new Error('offline')); });
    await settle();
  });

  it('R-realm-stale: a result for a moved owner stays silent', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    await honestCache();
    const held = await heldStage();
    act(() => { screen.getByTestId('submit').click(); });
    await act(async () => { await held.requested; });
    const during = screen.getByTestId('save-status').textContent;

    await moveOwnerTo(U2);

    await act(async () => {
      held.settlers[0].resolve({ status: 'blocked' });
    });
    await settle();

    expect(screen.getByTestId('save-status').textContent,
      "a dead token's outcome is not written").toBe(during);
  });

  it('D-plus-control: a load that resolved its OWN first identity may report its failure', async () => {
    const held = await heldNullLoad();
    // The read resolves the first identity inside itself, exactly as
    // loadProfile does, and only THEN fails.
    await act(async () => {
      advanceOwnerEpoch(FIRST_UID);
      await syncLocalIdentityOwner(FIRST_UID);
    });
    const resolved = captureOwnerToken();

    await act(async () => {
      // The REAL capability from the layer that resolved the identity.
      held.reads[0].reject(new OwnerScopedLoadError(resolved, new Error('select failed')));
    });
    await settle();

    expect(screen.getByTestId('hydration').textContent,
      'the person is told their own read failed, not left loading forever')
      .toBe('failed');

    // …and the identity that read resolved is now THIS screen's, frozen: an
    // edit belongs to it, is reported as unsaveable, and touches nothing
    // private. A "just show failed" fix leaves the screen with no origin at
    // all and the edit goes nowhere.
    const before = freeze();
    const rec = recordStorage();
    act(() => { screen.getByTestId('set-interests').click(); });
    await settle();
    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();

    expect(screen.getByTestId('interests').textContent,
      'the edit is visible on the screen that read failed').toBe('my interests');
    expect(screen.getByTestId('save-status').textContent,
      'and honestly reported as not saveable yet').toBe('error');
    // The baseline this edit would be recorded AGAINST was never read, so it
    // stays in the form and in memory. Writing it down now would freeze an
    // operation against a row nobody has seen.
    expect(reads, 'while nothing private is read').toEqual([]);
    expect(writes, 'nothing written').toEqual([]);
    expect(removes, 'nothing removed').toEqual([]);
    expect(enumerated, 'nothing scanned').toBe(0);
    expect(storageBytes(), 'and the bytes are as they were').toBe(before.bytes);
    expect(syncOverrides.stageCalls, 'nothing staged').toBe(before.stages);
    expect(syncOverrides.flushCalls, 'nothing flushed').toBe(before.flushes);
    expect(commitProfilePatch.mock.calls.length, 'and nothing sent')
      .toBe(before.commits);
    expect(cacheMocks.clearMatchCache, 'nothing invalidated').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigated').not.toHaveBeenCalled();
  });

  /** A screen whose own read failed, so nothing may be persisted yet. */
  async function failedRead() {
    syncOverrides.hydrateProfile = (() => Promise.reject(new Error('offline'))) as never;
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('hydration').textContent).toBe('failed'));
    await honestCache();
  }

  it('B-loading-control: an edit made while the load is still in flight IS recorded', async () => {
    // A read still in flight, not a failed one: the established contract is
    // that this edit is durable at once, against an explicitly unknown base.
    const held = await heldHydrate();
    await renderIdentityHarness();
    await act(async () => { await held.requested; });
    expect(screen.getByTestId('hydration').textContent, 'the load is still running')
      .toBe('loading');

    act(() => { screen.getByTestId('set-interests').click(); });
    await settle();

    expect(screen.getByTestId('interests').textContent, 'the edit is visible')
      .toBe('my interests');
    expect(
      await journalOps().some((o) => o.fields.some((f) => f.key === 'research_interests')),
      'and it survives a crash, exactly as it did before',
    ).toBe(true);
  });

  it('B-failed-private: the same edit on a FAILED read writes nothing private', async () => {
    await failedRead();
    const before = freeze();
    const rec = recordStorage();

    act(() => { screen.getByTestId('set-interests').click(); });
    await settle();

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();

    expect(screen.getByTestId('interests').textContent, 'the edit is still visible')
      .toBe('my interests');
    expect(reads, 'but nothing private is read').toEqual([]);
    expect(writes, 'nothing written').toEqual([]);
    expect(removes, 'nothing removed').toEqual([]);
    expect(enumerated, 'nothing scanned').toBe(0);
    expect(storageBytes(), 'and the bytes are as they were').toBe(before.bytes);
  });

  it('W-loading-control: the SLIDER moved while the load is in flight is recorded at once', async () => {
    // The slider has its own entry, so it needs its own proof: the profile
    // fields' loading contract says nothing about a control that writes
    // through a different function.
    const held = await heldHydrate();
    await renderIdentityHarness();
    await act(async () => { await held.requested; });
    expect(screen.getByTestId('hydration').textContent, 'the load is still running')
      .toBe('loading');

    act(() => { screen.getByTestId('set-weight').click(); });
    await settle();

    expect(screen.getByTestId('weight').textContent, 'the slider moved').toBe('90');
    const ops = await journalOps().filter((o) => o.fields.some((f) => f.key === 'search_weight'));
    expect(ops.length,
      'and it is durable at once, against an explicitly unknown base').toBe(1);
    expect(ops[0].fields.find((f) => f.key === 'search_weight')?.desired)
      .toMatchObject({ present: true, value: 90 });
  });

  it('W-failed-private: the SLIDER moved on a FAILED read touches nothing private', async () => {
    await failedRead();
    const before = freeze();
    const rec = recordStorage();

    act(() => { screen.getByTestId('set-weight').click(); });
    await settle();
    // Past the autosave debounce as well: a read that failed arms nothing,
    // now or 1.5 seconds from now.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();

    expect(screen.getByTestId('weight').textContent, 'the slider still shows the new value')
      .toBe('90');
    expect(reads, 'but nothing private is read').toEqual([]);
    expect(writes, 'nothing written').toEqual([]);
    expect(removes, 'nothing removed').toEqual([]);
    expect(enumerated, 'nothing scanned').toBe(0);
    expect(storageBytes(), 'and the bytes are as they were').toBe(before.bytes);
    expect(syncOverrides.stageCalls, 'nothing was staged').toBe(before.stages);
    expect(syncOverrides.flushCalls, 'and nothing flushed').toBe(before.flushes);
    expect(commitProfilePatch.mock.calls.length, 'nothing was sent').toBe(before.commits);
  });

  it('W-identity-owed: a slider owed by U1 is never written down or sent for U2', async () => {
    await failedRead();
    act(() => { screen.getByTestId('set-weight').click(); });
    act(() => { screen.getByTestId('set-interests').click(); });
    await settle();
    expect(await journalOps().length, 'U1 owes both and has written neither').toBe(0);

    // A real transition. U2's row lands, which is exactly the moment the
    // outstanding buffer would be flushed against a baseline — and every key
    // in it belongs to somebody else.
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 4));
    syncOverrides.hydrateProfile = null;
    commitProfilePatch.mockClear();
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-uid').textContent).toBe(U2));

    // U2 makes an edit of their OWN and it saves. This is the moment that
    // matters: the send path writes down everything still owed before it
    // builds its patch, so a buffer that survived the transition would be
    // journalled and shipped here under U2's token. Without a U2 save
    // nothing ever reads the buffer, and the test would pass on any code.
    act(() => { screen.getByTestId('set-coursework').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(await sentPatches().some((p) => Array.isArray(p.coursework)),
      "U2's own edit really did go out").toBe(true);

    expect(await journalOps().some((o) => o.fields.some(
      (f) => f.key === 'search_weight' || f.key === 'research_interests',
    )), "U1's owed keys are not recorded under U2").toBe(false);
    expect(await sentPatches().some((p) => 'search_weight' in p || 'research_interests' in p),
      'nor sent for them').toBe(false);
  });

  it('B-rehydrate-unmount: an edit buffered by a failed read is durable the instant its row lands', async () => {
    // A read that fails, an edit that therefore stays in memory, and then a
    // same-identity retry that succeeds — with the page left in the very
    // window between the row being accepted and React getting round to
    // anything about it.
    const held = await heldHydrate();
    await renderIdentityHarness();
    // The live stream owns this screen from the start, so the retry below is
    // a genuine SAME-identity re-observation rather than a first one (which
    // would be a transition, and would reset everything).
    await emitAuth(HOME_UID);
    await act(async () => { await held.requested; });
    expect(held.reads.length, 'exactly one read is in flight').toBe(1);
    await act(async () => { held.reads[0].reject(new Error('offline')); });
    await waitFor(() => expect(screen.getByTestId('hydration').textContent).toBe('failed'));

    act(() => { screen.getByTestId('set-interests').click(); });
    expect(screen.getByTestId('interests').textContent, 'the edit is on screen')
      .toBe('my interests');
    expect(
      await journalOps().some((o) => o.fields.some((f) => f.key === 'research_interests')),
      'and deliberately nowhere else yet — the row was never read',
    ).toBe(false);

    // The same identity re-observed: not a transition, so nothing resets, but
    // the row still has not loaded, which makes it a free retry.
    await emitAuth(HOME_UID);
    await waitFor(() => expect(held.reads.length, 'the retry really went out').toBe(2));

    const order: string[] = [];
    await act(async () => {
      // The hook attached its reaction to this promise before the test did,
      // so the callback below is GUARANTEED to run after the hook's has
      // finished — that is the ordering, not a delay.
      const after = held.promises[1].then(() => {
        order.push('after hydration reaction');
        // Proof the window is genuinely open: React has not flushed its
        // passive work, so nothing that runs in an effect has run yet.
        expect(screen.getByTestId('hydration').textContent,
          'React has not flushed the hydration yet').toBe('failed');
        cleanup();
        order.push('unmounted');
      });
      held.reads[1].resolve({
        profile: { ...ROW },
        baseProfile: { ...ROW },
        revision: 9,
        source: 'cloud' as const,
        token: captureOwnerToken(),
        hasPending: false,
        conflictKeys: [] as string[],
        conflicts: [],
        quarantineFailed: false,
      });
      await after;
    });

    expect(order, 'the page was left before any effect could run')
      .toEqual(['after hydration reaction', 'unmounted']);
    // THE POINT: accepting the row is the moment the edit finally has a
    // baseline, so it is written down there — not in an effect that may never
    // run, and not by a timer nobody waited for.
    const ops = await journalOps().filter(
      (o) => o.fields.some((f) => f.key === 'research_interests'),
    );
    expect(ops.length, 'the edit is durable the instant its row is accepted').toBe(1);
    expect(ops[0].fields.find((f) => f.key === 'research_interests')?.desired,
      'carrying what the person actually typed')
      .toMatchObject({ present: true, value: 'my interests' });
  });

  it("B-rehydrate-weight: a slider moved while the read failed keeps the person's value", async () => {
    const held = await heldHydrate();
    await renderIdentityHarness();
    await emitAuth(HOME_UID);
    await act(async () => { await held.requested; });
    await act(async () => { held.reads[0].reject(new Error('offline')); });
    await waitFor(() => expect(screen.getByTestId('hydration').textContent).toBe('failed'));

    act(() => { screen.getByTestId('set-weight').click(); });
    expect(screen.getByTestId('weight').textContent, 'the slider moved').toBe('90');
    expect(await journalOps().some((o) => o.fields.some((f) => f.key === 'search_weight')),
      'and is deliberately nowhere else yet').toBe(false);

    await emitAuth(HOME_UID);
    await waitFor(() => expect(held.reads.length, 'the retry went out').toBe(2));

    // Captured INSIDE the hydration reaction, before React flushes anything.
    let sameTickOps: ReturnType<typeof journalOps> = [];
    await act(async () => {
      const after = held.promises[1].then(() => {
        sameTickOps = journalOps();
      });
      // The row the cloud holds says 50 — the value the person replaced.
      held.reads[1].resolve({
        profile: { ...ROW, search_weight: 50 },
        baseProfile: { ...ROW, search_weight: 50 },
        revision: 9,
        source: 'cloud' as const,
        token: captureOwnerToken(),
        hasPending: false,
        conflictKeys: [] as string[],
        conflicts: [],
        quarantineFailed: false,
      });
      await after;
    });

    const ops = sameTickOps.filter((o) => o.fields.some((f) => f.key === 'search_weight'));
    expect(ops.length, 'the slider is written down once, in that same tick').toBe(1);
    const field = ops[0].fields.find((f) => f.key === 'search_weight');
    expect(field?.desired, 'carrying what the PERSON set, not the row they replaced')
      .toMatchObject({ present: true, value: 90 });
    expect(field?.base, 'against the row that was actually read')
      .toMatchObject({ present: true, value: 50 });

    // And the view published from that same acceptance describes the same
    // screen — anything building a whole document from it must not reach for
    // the weight the person replaced.
    expect(screen.getByTestId('view-rendered-weight').textContent,
      'the published view renders what the person set').toBe('90');
    expect(screen.getByTestId('view-rev').textContent,
      'while the confirmed row is still the row').toBe('9');
    expect(screen.getByTestId('weight').textContent, 'and so does the form').toBe('90');

    // And the document the hydration settled the form onto is that same one.
    // A hydration that settled the profile half from the row and the weight
    // half from the slider leaves the two disagreeing from the first tick,
    // and the very next unrelated edit republishes the row's value over the
    // person's — with no slider move in between to paper over it.
    act(() => { screen.getByTestId('set-interests').click(); });
    expect(screen.getByTestId('weight').textContent,
      'the slider is untouched by an unrelated edit').toBe('90');
    expect(screen.getByTestId('view-rendered-weight').textContent,
      'and so is the document that edit republished').toBe('90');
  });

  it('LW-edit: an unrelated edit never republishes the weight the person replaced', async () => {
    await hydratedU1();
    expect(screen.getByTestId('view-rendered-weight').textContent,
      'the screen starts on the value the row holds').toBe('50');

    act(() => { screen.getByTestId('set-weight').click(); });
    expect(screen.getByTestId('weight').textContent, 'the slider moved').toBe('90');
    expect(screen.getByTestId('view-rendered-weight').textContent,
      'and the document every full-document action is built from says so').toBe('90');

    // A DIFFERENT field. Nothing about typing an interest is about the
    // weight, and the document it republishes must not carry the screen back
    // to the value the person already replaced.
    act(() => { screen.getByTestId('set-interests').click(); });

    expect(screen.getByTestId('interests').textContent,
      'the unrelated edit is on screen').toBe('my interests');
    expect(screen.getByTestId('weight').textContent,
      'the slider is untouched').toBe('90');
    expect(screen.getByTestId('view-rendered-weight').textContent,
      'and so is the published document — one live profile, not two').toBe('90');
    expect(screen.getByTestId('view-rev').textContent,
      'while the CONFIRMED row has not moved').toBe('9');

    // The journal agrees with the screen: what the person set, measured
    // against what the row actually held.
    const ops = await journalOps().filter((o) => o.fields.some((f) => f.key === 'search_weight'));
    expect(ops.length, 'the slider was written down exactly once').toBe(1);
    const field = ops[0].fields.find((f) => f.key === 'search_weight');
    expect(field?.desired, 'carrying the value the person chose')
      .toMatchObject({ present: true, value: 90 });
    expect(field?.base, 'against the row that was read')
      .toMatchObject({ present: true, value: 50 });
  });

  it('LW-same-tick: a slider and an edit in ONE tick still describe one document', async () => {
    await hydratedU1();
    // No React flush in between. The refs are this hook's synchronous source
    // of truth precisely because two actions can land before a render: an
    // edit that read the profile out of React state instead would build its
    // document from the weight the person had already replaced.
    act(() => {
      screen.getByTestId('set-weight').click();
      screen.getByTestId('set-interests').click();
    });

    expect(screen.getByTestId('weight').textContent).toBe('90');
    expect(screen.getByTestId('interests').textContent).toBe('my interests');
    expect(screen.getByTestId('view-rendered-weight').textContent,
      'the second action saw the first one').toBe('90');
  });

  it('LW-ack: an acknowledgement moves the base, never the live weight', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-weight').click(); });
    act(() => { screen.getByTestId('set-interests').click(); });

    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent,
      'the server confirmed the write').toBe('10'));

    expect(await sentPatches().some((p) => p.search_weight === 90),
      'and 90 is what actually went out').toBe(true);
    expect(screen.getByTestId('weight').textContent,
      'the slider still shows what the person set').toBe('90');
    expect(screen.getByTestId('view-rendered-weight').textContent,
      'and the acknowledgement did not rebuild the view from a stale half').toBe('90');
  });

  /** Two disagreements on screen at once, raised through the real handlers. */
  async function twoQuestionsOnScreen() {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    const remote = { ...ROW, major: 'Statistics', grade: 'Senior' };
    const ask = (key: string) => (key === 'grade'
      ? question('grade', 10, 'Senior', 'm-grade')
      : question('major', 10, 'Statistics', 'm-major'));
    syncOverrides.stageProfilePatch = (async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote,
      confirmed: { revision: 10, profile: remote },
      conflictKeys: ['grade', 'major'],
      conflicts: ['grade', 'major'].map(ask),
    })) as never;
    syncOverrides.refreshConflictQuestion = (async (keys: readonly string[]) => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: remote,
      revision: 10,
      conflicts: [...keys].map(ask),
      pendingKeys: [...keys],
      flushed: null,
    })) as never;
    act(() => { screen.getByTestId('set-major-ece').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(
      screen.getByTestId('conflict-keys').textContent!.split(',').sort().join(','),
    ).toBe('grade,major'));
  }

  it('T-status-timer-control: with nothing after it, the saved badge really does clear on time', async () => {
    // The positive control for the two tests below: it proves the 2s timer
    // genuinely comes due inside the window they advance through, so a later
    // status surviving that window is the gate working and not the clock
    // failing to arrive.
    await hydratedU1();
    await honestCache();
    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(screen.getByTestId('save-status').textContent,
      'the write landed').toBe('saved');

    await act(async () => { await new Promise((r) => setTimeout(r, 2200)); });
    expect(screen.getByTestId('save-status').textContent,
      'and its badge cleared itself').toBe('idle');
  });

  it('T-status-cache: a saved badge never turns a later submit failure back into idle', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    // The row is written — so the save inside this submit says 'saved' and
    // arms its 2s badge — but this browser cannot remove the stale match
    // cache, and a submit that cannot do that is a submit that failed.
    cacheMocks.clearMatchCache.mockReset();
    cacheMocks.clearMatchCache.mockReturnValue(false);
    pushSpy.mockClear();

    await act(async () => {
      screen.getByTestId('submit').click();
      await new Promise((r) => setTimeout(r, 80));
    });

    expect(pushSpy, 'nobody is sent to matches').not.toHaveBeenCalled();
    expect(screen.getByTestId('save-status').textContent,
      'and the person is told the submit failed').toBe('error');

    await act(async () => { await new Promise((r) => setTimeout(r, 2200)); });

    expect(screen.getByTestId('save-status').textContent,
      'the failure is still the last thing that happened').toBe('error');
  });

  it('T-status-remainder: an answered question\'s badge does not erase the one still open', async () => {
    await twoQuestionsOnScreen();
    // KEEP MINE on `grade` only: the row comes back holding the value already
    // on screen, so answering moves no field and arms no new save. What is
    // under test is the badge, not the merge.
    syncOverrides.resolveProfileConflict = (async () => ({
      status: 'saved' as const,
      revision: 11,
      profile: { ...ROW, major: 'ECE' },
    })) as never;

    await act(async () => {
      screen.getByTestId('keep-grade').click();
      await new Promise((r) => setTimeout(r, 80));
    });

    expect(screen.getByTestId('conflict-keys').textContent,
      'the question nobody answered is still on screen').toBe('major');
    expect(screen.getByTestId('save-status').textContent,
      'and the form still says there is a disagreement').toBe('conflict');

    // The answered half's own 2s badge now comes due. It belongs to a status
    // the remainder rebuild has already replaced.
    await act(async () => { await new Promise((r) => setTimeout(r, 2200)); });

    expect(screen.getByTestId('conflict-keys').textContent,
      'the open question has not moved').toBe('major');
    expect(screen.getByTestId('save-status').textContent,
      'and the form still says so').toBe('conflict');
  });

  it('B-failed-control: an edit on a failed read still paints and is reported', async () => {
    await failedRead();
    act(() => { screen.getByTestId('set-interests').click(); });
    expect(screen.getByTestId('interests').textContent, 'the edit is visible')
      .toBe('my interests');
    await settle();
    expect(screen.getByTestId('save-status').textContent,
      'and the person is told it cannot be saved yet').toBe('error');
  });

  it('B-failed: a failed read does not report onto a screen whose owner moved', async () => {
    await failedRead();
    let before!: ReturnType<typeof freeze>;
    let rec!: ReturnType<typeof recordStorage>;
    let statusBefore!: string | null;
    await act(async () => {
      screen.getByTestId('set-interests').click();
      advanceOwnerEpoch(U2);
      await syncLocalIdentityOwner(U2);
      statusBefore = screen.getByTestId('save-status').textContent;
      before = freeze();
      rec = recordStorage();
    });
    await settle();

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();
    expect(screen.getByTestId('save-status').textContent,
      "a dead screen's failed read is not the new owner's error").toBe(statusBefore);
    expect(reads, 'nothing private is read').toEqual([]);
    expect(writes, 'nothing written').toEqual([]);
    expect(removes, 'nothing removed').toEqual([]);
    expect(enumerated, 'nothing scanned').toBe(0);
    expect(storageBytes(), 'and the bytes are as they were').toBe(before.bytes);
    expect(syncOverrides.stageCalls, 'nothing is staged').toBe(before.stages);
    expect(commitProfilePatch.mock.calls.length, 'nothing sent').toBe(before.commits);
  });

  /** A published question with its answer HELD at the coordinator. */
  async function heldAnswerHere() {
    await questionOnScreen();
    const answers: { resolve: (v: unknown) => void; reject: (e: unknown) => void }[] = [];
    syncOverrides.resolveProfileConflict = (() => new Promise((resolve, reject) => {
      answers.push({ resolve, reject });
    })) as never;
    await act(async () => {
      screen.getByTestId('keep-mine').click();
    });
    await settle();
    expect(answers.length, 'the answer is in flight').toBe(1);
    return answers;
  }

  it('C-realm: an answer refused while local data is unconfirmed is still reported', async () => {
    const answers = await heldAnswerHere();
    const stillOwner = captureOwnerToken();
    localStorage.removeItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER);
    expect(isTokenOwnerStillCurrent(stillOwner),
      'they are still the owner of this browser').toBe(true);
    expect(isOwnerTokenValid(stillOwner, stillOwner.uid),
      'but their local data is no longer confirmed for them').toBe(false);

    await act(async () => {
      answers[0].reject(new Error('offline'));
    });
    await settle();
    expect(screen.getByTestId('save-status').textContent,
      'their own failed answer is still their news').toBe('cloud-failed');

    // …and the latch really was released, so they can answer again.
    await syncLocalIdentityOwner(HOME_UID);
    await act(async () => {
      screen.getByTestId('use-cloud').click();
    });
    await settle();
    expect(answers.length, 'the next click owns its own resolution').toBe(2);
  });

  it('C-epoch: an answer refused after a same-uid epoch change says nothing', async () => {
    const answers = await heldAnswerHere();
    const during = screen.getByTestId('save-status').textContent;
    await reclaimSameUid();

    await act(async () => {
      answers[0].reject(new Error('offline'));
    });
    await settle();
    expect(screen.getByTestId('save-status').textContent,
      'a new epoch is a different capability').toBe(during);
  });

  /** A load issued while this browser has no identity at all. */
  async function heldNullLoad() {
    act(() => { advanceOwnerEpoch(null); });
    const held = await heldHydrate();
    await renderIdentityHarness();
    await act(async () => { await held.requested; });
    expect(held.reads.length, 'the load really went out').toBeGreaterThan(0);
    return held;
  }

  const FIRST_UID = 'first-anon-uid';

  it('D-null-control: the first identity resolved inside the read is accepted', async () => {
    const held = await heldNullLoad();
    // Typed before this browser had any identity at all.
    act(() => { screen.getByTestId('set-interests').click(); });

    // The one legitimate first resolution, exactly as loadProfile performs it.
    await act(async () => {
      advanceOwnerEpoch(FIRST_UID);
      await syncLocalIdentityOwner(FIRST_UID);
    });
    const resolved = captureOwnerToken();
    await act(async () => {
      held.reads[0].resolve({
        profile: { ...ROW },
        baseProfile: { ...ROW },
        revision: 9,
        source: 'cloud' as const,
        token: resolved,
        hasPending: false,
        conflictKeys: [] as string[],
        conflicts: [],
        quarantineFailed: false,
      });
    });
    await settle();

    expect(screen.getByTestId('view-uid').textContent,
      "the row is accepted for the identity the read resolved").toBe(FIRST_UID);
    expect(screen.getByTestId('grade').textContent, 'and it is on screen').toBe('Junior');
    expect(screen.getByTestId('interests').textContent,
      'with what was typed before it still on top').toBe('my interests');
  });

  it('D-null-reject-control: a still-unresolved load that fails reports it', async () => {
    const held = await heldNullLoad();
    await act(async () => {
      held.reads[0].reject(new Error('offline'));
    });
    await settle();
    expect(screen.getByTestId('hydration').textContent,
      'a read that failed with nobody signed in is still this screen\'s')
      .toBe('failed');
  });

  it('D-plus-forged: a failure merely SHAPED like a scoped one grants nothing', async () => {
    const held = await heldNullLoad();
    await act(async () => {
      advanceOwnerEpoch(FIRST_UID);
      await syncLocalIdentityOwner(FIRST_UID);
    });
    // Everything a real scoped failure has, and none of its provenance.
    const forged = Object.assign(new Error('select failed'), {
      name: 'OwnerScopedLoadError',
      ownerToken: captureOwnerToken(),
    });
    const hydrationBefore = screen.getByTestId('hydration').textContent;

    await act(async () => { held.reads[0].reject(forged); });
    await settle();

    expect(screen.getByTestId('hydration').textContent,
      'a shape is not a capability, so this screen learns nothing')
      .toBe(hydrationBefore);
    expect(screen.getByTestId('view-uid').textContent,
      'and adopts nobody').toBe('none');

    // Nor is an origin frozen from it: an edit is still not this screen's.
    const before = freeze();
    const rec = recordStorage();
    act(() => { screen.getByTestId('set-interests').click(); });
    await settle();
    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();
    expect(screen.getByTestId('interests').textContent,
      'the edit is not admitted').toBe('');
    expect(reads, 'nothing private is read').toEqual([]);
    expect(writes, 'nothing written').toEqual([]);
    expect(removes, 'nothing removed').toEqual([]);
    expect(enumerated, 'nothing scanned').toBe(0);
    expect(storageBytes(), 'the bytes are as they were').toBe(before.bytes);
    expect(syncOverrides.stageCalls, 'nothing staged').toBe(before.stages);
    expect(syncOverrides.flushCalls, 'nothing flushed').toBe(before.flushes);
    expect(commitProfilePatch.mock.calls.length, 'nothing sent').toBe(before.commits);
    expect(cacheMocks.clearMatchCache, 'nothing invalidated').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigated').not.toHaveBeenCalled();
  });

  it('D-null-reject-stale: a load failing after an identity arrives labels nothing', async () => {
    const held = await heldNullLoad();
    const hydrationBefore = screen.getByTestId('hydration').textContent;
    // A real identity now owns the browser, and this hook has not heard.
    await act(async () => {
      advanceOwnerEpoch(FIRST_UID);
      await syncLocalIdentityOwner(FIRST_UID);
    });

    await act(async () => {
      held.reads[0].reject(new Error('offline'));
    });
    await settle();

    expect(screen.getByTestId('hydration').textContent,
      "the unresolved screen's failure is not the new identity's news")
      .toBe(hydrationBefore);
  });

  /**
   * A clipboard the test settles by hand. `whenCalled(n)` resolves the moment
   * the n-th request is actually made, so nothing here waits on a clock.
   */
  async function heldClipboard() {
    const calls: { text: string; resolve: () => void; reject: (e: unknown) => void }[] = [];
    const waiters: { n: number; go: () => void }[] = [];
    const notify = async () => {
      for (let i = waiters.length - 1; i >= 0; i -= 1) {
        if (waiters[i].n <= calls.length) waiters.splice(i, 1)[0].go();
      }
    };
    const had = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: (text: string) => new Promise<void>((resolve, reject) => {
          calls.push({ text, resolve, reject });
          notify();
        }),
      },
    });
    await registerSpy({
      mockRestore: () => {
        if (had) Object.defineProperty(navigator, 'clipboard', had);
        else delete (navigator as { clipboard?: unknown }).clipboard;
      },
    });
    return {
      calls,
      whenCalled: (n: number) => (calls.length >= n
        ? Promise.resolve()
        : new Promise<void>((go) => { waiters.push({ n, go }); })),
    };
  }

  /** What a share URL actually discloses, decoded rather than inferred. */
  function sharedProfile(url: string): Record<string, unknown> {
    const param = new URL(url, 'https://joinalab.test').searchParams.get('share');
    expect(param, 'the URL carries a share payload').toBeTruthy();
    const decoded = decodeProfileWithKeys(param!);
    expect(decoded, 'and it decodes').toBeTruthy();
    return decoded!.profile as unknown as Record<string, unknown>;
  }

  /** jsdom's prompt throws "not implemented"; the fallback path calls it. */
  async function watchPrompt() {
    return await registerSpy(vi.spyOn(window, 'prompt').mockReturnValue(null));
  }

  /** React's own complaint about writing into a tree that is gone. */
  async function watchConsole() {
    return await registerSpy(vi.spyOn(console, 'error').mockImplementation(() => {}));
  }

  /**
   * Records every timer armed from here on and fires them BY HAND, so a
   * horizon is asserted exactly rather than waited out. Installed only after
   * the screen has settled, and never while a `waitFor` is running.
   */
  async function timerHarness() {
    type Armed = { id: number; ms: number; fn: () => void; cleared: boolean };
    const armed: Armed[] = [];
    const realSet = globalThis.setTimeout;
    const realClear = globalThis.clearTimeout;
    // NEGATIVE handles: a real timer id can never collide with one of these,
    // so the multiplexer below can always tell whose handle it was handed.
    let next = -1;
    globalThis.setTimeout = ((fn: () => void, ms?: number) => {
      const id = next; next -= 1;
      armed.push({ id, ms: ms ?? 0, fn, cleared: false });
      return id;
    }) as never;
    // Stays installed across restoreForWait: the source may legitimately
    // clear one of OUR handles long after the clock has been handed back,
    // and delegating that to the real clearTimeout would silently lose it.
    const multiplex = ((id: unknown) => {
      const found = armed.find((a) => a.id === id);
      if (found) { found.cleared = true; return; }
      (realClear as (h: unknown) => void)(id);
    }) as never;
    globalThis.clearTimeout = multiplex;
    const restoreAll = async () => {
      globalThis.setTimeout = realSet;
      globalThis.clearTimeout = realClear;
    };
    await registerSpy({ mockRestore: restoreAll });
    return {
      armed,
      /** Hands back only the CLOCK — `waitFor` must not run under the fake
       *  setTimeout — while retirement is still observed. */
      restoreForWait: () => { globalThis.setTimeout = realSet; },
      live: (ms: number) => armed.filter((a) => !a.cleared && a.ms === ms),
      // A real scheduler: a timer that was retired does not run, exactly as
      // the browser's own would not. Firing it by hand regardless would
      // execute work the source correctly cancelled.
      fire: async (entry: Armed) => {
        if (entry.cleared) return;
        entry.cleared = true;
        await act(async () => { entry.fn(); });
      },
    };
  }

  /** Lets React observe what has already settled. No clock involved. */
  async function settle() {
    await act(async () => {});
  }

  const U1_SHARE = 'u1 share sentinel';
  const U2_SHARE = 'u2 share sentinel';
  const U2_ROW_SHARE = {
    college: 'Siebel', major: 'Stats', grade: 'Senior', research_interests: U2_SHARE,
  };

  async function hydratedWithSentinel(sentinel = U1_SHARE) {
    mockLoadProfile = () => Promise.resolve(
      cloudRow({ ...ROW, research_interests: sentinel }, 9),
    );
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('interests').textContent).toBe(sentinel));
    return sentinel;
  }

  /** Exactly what a share disclosed: the screen it was made on, and no other. */
  async function assertDisclosed(text: string, present: string) {
    const shared = await sharedProfile(text);
    expect(shared.research_interests, 'the payload is this screen').toBe(present);
    expect(JSON.stringify(shared), 'and carries nothing of the other account')
      .not.toContain(present === U1_SHARE ? U2_SHARE : U1_SHARE);
  }

  it('S-control-success: a share under its own owner copies once and clears itself', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    await watchPrompt();

    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });
    expect(clip.calls.length, 'the clipboard really was asked').toBe(1);
    await assertDisclosed(clip.calls[0].text, U1_SHARE);

    const timers = await timerHarness();
    await act(async () => { clip.calls[0].resolve(); });
    await settle();
    expect(screen.getByTestId('share-copied').textContent, 'it says so').toBe('yes');

    // The badge's OWN horizon, fired by hand rather than waited out.
    const badge = timers.live(2000);
    expect(badge.length, 'exactly one badge timer is armed').toBe(1);
    await timers.fire(badge[0]);
    expect(screen.getByTestId('share-copied').textContent, 'and stops saying so')
      .toBe('no');
  });

  it('S-control-reject: a share whose clipboard refuses offers the URL once', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    const prompt = await watchPrompt();

    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });
    await act(async () => { clip.calls[0].reject(new Error('denied')); });
    await settle();

    expect(prompt, 'the fallback is offered exactly once').toHaveBeenCalledTimes(1);
    await assertDisclosed(String(prompt.mock.calls[0][1]), U1_SHARE);
    expect(screen.getByTestId('share-copied').textContent,
      'and nothing claims it was copied').toBe('no');
  });

  it('S-stale: a share clicked after the owner moved discloses nothing', async () => {
    await hydratedWithSentinel();
    await moveOwnerTo(U2);
    const clip = await heldClipboard();
    const prompt = await watchPrompt();
    const before = freeze();
    const copiedBefore = screen.getByTestId('share-copied').textContent;
    const rec = recordStorage();

    await act(async () => { screen.getByTestId('share').click(); });
    await settle();

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();
    expect(clip.calls.length, 'the clipboard is never asked').toBe(0);
    expect(prompt, 'and no URL is put in front of the new owner').not.toHaveBeenCalled();
    expect(screen.getByTestId('share-copied').textContent, 'nothing is claimed')
      .toBe(copiedBefore);
    expect(reads, 'nothing private is read').toEqual([]);
    expect(writes, 'nothing written').toEqual([]);
    expect(removes, 'nothing removed').toEqual([]);
    expect(enumerated, 'and the keyspace is not scanned').toBe(0);
    expect(storageBytes(), 'and the bytes are as they were').toBe(before.bytes);
  });

  it('S-stale-epoch: the same person at a new epoch cannot share it either', async () => {
    await hydratedWithSentinel();
    await reclaimSameUid();
    const clip = await heldClipboard();
    const prompt = await watchPrompt();

    await act(async () => { screen.getByTestId('share').click(); });
    await settle();

    expect(clip.calls.length, 'the clipboard is never asked').toBe(0);
    expect(prompt, 'and nothing is offered').not.toHaveBeenCalled();
  });

  it('S-held-resolve: a copy confirmed after the owner moved claims nothing', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    await watchPrompt();
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });
    await assertDisclosed(clip.calls[0].text, U1_SHARE);

    await moveOwnerTo(U2);
    const copiedBefore = screen.getByTestId('share-copied').textContent;

    await act(async () => { clip.calls[0].resolve(); });
    await settle();

    expect(screen.getByTestId('share-copied').textContent,
      "a dead screen's confirmation is not written").toBe(copiedBefore);
  });

  it('S-held-reject: a copy refused after the owner moved offers nothing', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    const prompt = await watchPrompt();
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });

    await moveOwnerTo(U2);

    await act(async () => { clip.calls[0].reject(new Error('denied')); });
    await settle();

    expect(prompt, "a dead screen's URL is not put in front of the new owner")
      .not.toHaveBeenCalled();
  });

  /** Two shares issued back to back, both still with the clipboard. */
  async function twoHeldShares() {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    const prompt = await watchPrompt();
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(2);
    });
    expect(clip.calls.length, 'both shares really went out').toBe(2);
    return { clip, prompt };
  }

  it('S-ooo-resolve: a superseded share cannot claim the screen when it answers', async () => {
    const { clip } = await twoHeldShares();

    // The OLDER request answers first. It has already been replaced, so it
    // speaks for nothing — the badge belongs to the share still in flight.
    await act(async () => { clip.calls[0].resolve(); });
    await settle();
    expect(screen.getByTestId('share-copied').textContent,
      'a superseded share does not claim the badge').toBe('no');

    // Only the share that is actually current may.
    await act(async () => { clip.calls[1].resolve(); });
    await settle();
    expect(screen.getByTestId('share-copied').textContent,
      'and the newest one does').toBe('yes');
  });

  it('S-ooo-reject: an older share refusing last cannot open a prompt', async () => {
    const { clip, prompt } = await twoHeldShares();

    await act(async () => { clip.calls[1].resolve(); });
    await settle();
    expect(screen.getByTestId('share-copied').textContent, 'the newest share lands')
      .toBe('yes');

    await act(async () => { clip.calls[0].reject(new Error('denied')); });
    await settle();

    expect(prompt, 'the superseded share does not put a URL in front of anybody')
      .not.toHaveBeenCalled();
    expect(screen.getByTestId('share-copied').textContent,
      'nor take the badge away from the share that did land').toBe('yes');
  });

  it('S-auth-resolve: a share confirming after an identity change claims nothing', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    await watchPrompt();
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });

    mockLoadProfile = () => Promise.resolve(cloudRow({ ...U2_ROW_SHARE }, 3));
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('3'));

    await act(async () => { clip.calls[0].resolve(); });
    await settle();

    expect(screen.getByTestId('share-copied').textContent,
      "the new screen is not told the old one's copy landed").toBe('no');
    expect(clip.calls.length, 'and no share of theirs was ever made').toBe(1);
    await assertDisclosed(clip.calls[0].text, U1_SHARE);
  });

  it('S-auth-reject: a share refused after an identity change offers nothing', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    const prompt = await watchPrompt();
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });

    mockLoadProfile = () => Promise.resolve(cloudRow({ ...U2_ROW_SHARE }, 3));
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('3'));

    await act(async () => { clip.calls[0].reject(new Error('denied')); });
    await settle();

    expect(prompt, "the previous identity's URL is not offered to this one")
      .not.toHaveBeenCalled();
  });

  it('S-unmount-resolve: a share confirming after the page is left arms nothing', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    await watchPrompt();
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });

    const timers = await timerHarness();
    cleanup();
    await act(async () => { clip.calls[0].resolve(); });
    await settle();

    expect(timers.live(2000).length,
      'no badge continuation is scheduled for a page that is gone').toBe(0);
  });

  it('S-unmount-reject: a share refused after the page is left offers nothing', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    const prompt = await watchPrompt();
    const errors = await watchConsole();
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });

    cleanup();
    await act(async () => { clip.calls[0].reject(new Error('denied')); });
    await settle();

    expect(prompt, 'nobody is shown a URL for a page that is gone')
      .not.toHaveBeenCalled();
    expect(errors.mock.calls.flat().join(' '),
      'and React is not written to either').not.toContain('unmounted');
  });

  it('S-double: the first share\'s timer cannot clear the second share\'s success', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    await watchPrompt();

    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });
    const timers = await timerHarness();
    await act(async () => { clip.calls[0].resolve(); });
    await settle();
    expect(screen.getByTestId('share-copied').textContent, 'the first lands').toBe('yes');
    const firstBadge = timers.live(2000);
    expect(firstBadge.length, 'the first share arms a badge timer').toBe(1);

    // A second share, while the first badge's timer is still outstanding.
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(2);
    });
    await act(async () => { clip.calls[1].resolve(); });
    await settle();
    expect(screen.getByTestId('share-copied').textContent, 'and so does the second')
      .toBe('yes');

    expect(firstBadge[0].cleared,
      "the first share's timer is retired when the second is issued").toBe(true);
    // …and firing it changes nothing, because a retired timer does not run.
    await timers.fire(firstBadge[0]);
    expect(screen.getByTestId('share-copied').textContent,
      "the older share's timer does not clear the newer one").toBe('yes');
  });

  it('S-latest: starting a second share clears the first result and retires its timer', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    const prompt = await watchPrompt();
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });
    const timers = await timerHarness();
    await act(async () => { clip.calls[0].resolve(); });
    await settle();
    expect(screen.getByTestId('share-copied').textContent, 'the first share lands')
      .toBe('yes');
    const firstBadge = timers.live(2000);
    expect(firstBadge.length, 'and arms its badge timer').toBe(1);

    // A second share BEGINS. The previous result stops being the answer the
    // moment a new question is asked.
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(2);
    });
    expect(screen.getByTestId('share-copied').textContent,
      'the old result stops being shown as soon as a new share starts').toBe('no');
    expect(firstBadge[0].cleared,
      "and the old share's timer is retired with it").toBe(true);

    await act(async () => { clip.calls[1].reject(new Error('denied')); });
    await settle();

    expect(screen.getByTestId('share-copied').textContent,
      'a refusal claims nothing').toBe('no');
    expect(prompt, 'and the fallback is offered exactly once').toHaveBeenCalledTimes(1);
    await assertDisclosed(String(prompt.mock.calls[0][1]), U1_SHARE);
  });

  it('S-identity: an identity transition retires the share it never made', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    await watchPrompt();
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });
    const timers = await timerHarness();
    await act(async () => { clip.calls[0].resolve(); });
    await settle();
    expect(screen.getByTestId('share-copied').textContent).toBe('yes');
    const badge = timers.live(2000);
    expect(badge.length, 'the share armed its badge timer').toBe(1);

    mockLoadProfile = () => Promise.resolve(cloudRow({ ...U2_ROW_SHARE }, 3));
    // The harness owns the clock here, so the transition is observed rather
    // than waited for.
    timers.restoreForWait();
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('3'));
    expect(screen.getByTestId('share-copied').textContent,
      "the new screen inherits nothing of the old one's share").toBe('no');
    expect(badge[0].cleared,
      "and the old screen's badge timer is retired, not left to fire").toBe(true);
  });

  it('S-unmount-active: leaving the page retires a badge timer already running', async () => {
    await hydratedWithSentinel();
    const clip = await heldClipboard();
    await watchPrompt();
    await act(async () => {
      screen.getByTestId('share').click();
      await clip.whenCalled(1);
    });
    const timers = await timerHarness();
    await act(async () => { clip.calls[0].resolve(); });
    await settle();
    const badge = timers.live(2000);
    expect(badge.length, 'the share armed its badge timer').toBe(1);

    cleanup();
    await settle();

    expect(badge[0].cleared,
      'leaving the page retires the timer it left behind').toBe(true);
  });

  /** The screen's own load, held open, with a handshake for its issue. */
  function heldHydrate() {
    let announce!: () => void;
    const requested = new Promise<void>((resolve) => { announce = resolve; });
    const reads: { resolve: (v: unknown) => void; reject: (e: unknown) => void }[] = [];
    // The promise objects themselves, so a test can attach its OWN reaction
    // after the hook's and be guaranteed to run once the hook's has finished.
    const promises: Promise<unknown>[] = [];
    syncOverrides.hydrateProfile = (() => {
      const p = new Promise((resolve, reject) => {
        reads.push({ resolve, reject });
        announce();
      });
      promises.push(p);
      return p;
    }) as never;
    return { requested, reads, promises };
  }

  const U1_PRIVATE = {
    college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50,
    research_interests: 'u1 private research',
  };

  /** A held load, issued, with the row it would answer with. */
  async function heldLoad(opts: { hasPending?: boolean } = {}) {
    const held = await heldHydrate();
    await renderIdentityHarness();
    await act(async () => { await held.requested; });
    expect(held.reads.length, 'the load really went out').toBeGreaterThan(0);
    const row = {
      profile: { ...U1_PRIVATE },
      baseProfile: { ...U1_PRIVATE },
      revision: 9,
      source: 'cloud' as const,
      token: captureOwnerToken(),
      hasPending: opts.hasPending ?? false,
      conflictKeys: [] as string[],
      conflicts: [],
      quarantineFailed: false,
    };
    return { held, row };
  }

  it('L1-control: a load resolving under its own owner IS accepted', async () => {
    const { held, row } = await heldLoad();
    await act(async () => {
      held.reads[0].resolve(row);
    });
    await settle();
    expect(screen.getByTestId('view-uid').textContent, 'the view is published')
      .toBe(HOME_UID);
    expect(screen.getByTestId('interests').textContent, 'and the row is on screen')
      .toBe('u1 private research');
  });

  it('L1: a load resolving after the owner moved paints no private row', async () => {
    const { held, row } = await heldLoad();
    await moveOwnerTo(U2);
    await honestCache();
    pushSpy.mockClear();
    const before = freeze();
    const gradeBefore = screen.getByTestId('grade').textContent;
    const interestsBefore = screen.getByTestId('interests').textContent;
    const statusBefore = screen.getByTestId('save-status').textContent;
    const rec = recordStorage();

    await act(async () => {
      held.reads[0].resolve(row);
      await new Promise((r) => setTimeout(r, 60));
    });

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const enumerated = rec.calls.enumerate;
    rec.restore();
    expect(screen.getByTestId('interests').textContent,
      "U1's row is not drawn on a screen the new owner is looking at")
      .toBe(interestsBefore);
    expect(screen.getByTestId('grade').textContent, 'none of it').toBe(gradeBefore);
    expect(screen.getByTestId('view-uid').textContent, 'and no view is accepted')
      .toBe('none');
    expect(screen.getByTestId('save-status').textContent, 'nothing is claimed')
      .toBe(statusBefore);
    expect(reads, 'nothing private is read').toEqual([]);
    expect(writes, 'nothing written').toEqual([]);
    expect(enumerated, 'nothing scanned').toBe(0);
    expect(storageBytes(), 'the bytes are as they were').toBe(before.bytes);
    expect(syncOverrides.stageCalls, 'and nothing is staged').toBe(before.stages);
  });

  it('L2-control: a load that fails under its own owner says so', async () => {
    const { held } = await heldLoad();
    await act(async () => {
      held.reads[0].reject(new Error('offline'));
    });
    await settle();
    expect(screen.getByTestId('hydration').textContent, 'the read reports its failure')
      .toBe('failed');
  });

  it('L2: a load that fails after the owner moved reports nothing', async () => {
    const { held } = await heldLoad();
    await moveOwnerTo(U2);
    const hydrationBefore = screen.getByTestId('hydration').textContent;

    await act(async () => {
      held.reads[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 60));
    });

    expect(screen.getByTestId('hydration').textContent,
      "a dead screen's failed read is not the new owner's news").toBe(hydrationBefore);
  });

  it('L3-control: a recovered outbox that fails under its own owner says so', async () => {
    const { held, row } = await heldLoad({ hasPending: true });
    const flushes: { reject: (e: unknown) => void }[] = [];
    syncOverrides.flushPendingProfileWrite = (
      () => new Promise((_resolve, reject) => { flushes.push({ reject }); })
    ) as never;
    await act(async () => {
      held.reads[0].resolve(row);
    });
    await settle();
    expect(flushes.length, 'the recovered write really went out').toBeGreaterThan(0);

    await act(async () => {
      flushes[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(screen.getByTestId('save-status').textContent,
      'the recovery reports its own failure').toBe('cloud-failed');
  });

  it('L3: a recovered outbox failing after the owner moved reports nothing', async () => {
    const { held, row } = await heldLoad({ hasPending: true });
    const flushes: { reject: (e: unknown) => void }[] = [];
    syncOverrides.flushPendingProfileWrite = (
      () => new Promise((_resolve, reject) => { flushes.push({ reject }); })
    ) as never;
    await act(async () => {
      held.reads[0].resolve(row);
    });
    await settle();
    expect(flushes.length, 'the recovered write really went out').toBeGreaterThan(0);
    const statusDuring = screen.getByTestId('save-status').textContent;

    await moveOwnerTo(U2);
    await act(async () => {
      flushes[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 60));
    });

    expect(screen.getByTestId('save-status').textContent,
      "a dead screen's recovery is not the new owner's news").toBe(statusDuring);
  });

  it('L4-control: a saved status returns to idle on its own screen', async () => {
    await hydratedU1();
    await honestCache();
    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saved'));

    await act(async () => { await new Promise((r) => setTimeout(r, 2100)); });
    expect(screen.getByTestId('save-status').textContent,
      'the badge clears itself').toBe('idle');
  });

  it('L4: the saved badge does not clear itself on a screen whose owner moved', async () => {
    await hydratedU1();
    await honestCache();
    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saved'));

    await moveOwnerTo(U2);
    await act(async () => { await new Promise((r) => setTimeout(r, 2100)); });

    expect(screen.getByTestId('save-status').textContent,
      "a dead screen's timer does not write onto it").toBe('saved');
  });

  /** A legitimate U1 write of `kind`, issued and held at the server. */
  async function heldOwnWrite(kind: 'autosave' | 'removal' | 'retry') {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...RESUME_ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    await honestCache();
    pushSpy.mockClear();
    if (kind === 'retry') {
      // A first attempt that fails, so Retry has something to repeat.
      commitProfilePatch.mockRejectedValue(new Error('offline'));
      act(() => { screen.getByTestId('set-interests').click(); });
      await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
      await waitFor(() => expect(screen.getByTestId('save-status').textContent)
        .toBe('cloud-failed'));
    }
    const held = await heldCommit();
    if (kind === 'autosave') {
      act(() => { screen.getByTestId('set-interests').click(); });
      await awaitRequest(held, 1700);
    } else if (kind === 'removal') {
      act(() => { screen.getByTestId('remove-resume').click(); });
      await awaitRequest(held);
    } else {
      act(() => { screen.getByTestId('retry-sync').click(); });
      await awaitRequest(held);
    }
    const during = screen.getByTestId('save-status').textContent;
    expect(during, 'the write owns the wording while it runs').toBe('saving');
    return { held, during };
  }

  it.each(['autosave', 'removal', 'retry'] as const)(
    'E8-control-%s: a refusal under its own owner is reported and stays retryable',
    async (kind) => {
      const { held } = await heldOwnWrite(kind);
      await act(async () => {
        held.settlers[0].reject(new Error('offline'));
        await new Promise((r) => setTimeout(r, 60));
      });
      expect(screen.getByTestId('save-status').textContent,
        'their own failed write is their news').toBe('cloud-failed');

      commitProfilePatch.mockRejectedValue(new Error('offline'));
      const sentBefore = commitProfilePatch.mock.calls.length;
      await act(async () => {
        screen.getByTestId('retry-sync').click();
        await new Promise((r) => setTimeout(r, 40));
      });
      expect(commitProfilePatch.mock.calls.length, 'and Retry repeats it')
        .toBeGreaterThan(sentBefore);
    },
  );

  it.each(['autosave', 'removal', 'retry'] as const)(
    'E8-%s: a refusal landing after the owner moved is written nowhere',
    async (kind) => {
      const { held, during } = await heldOwnWrite(kind);
      await moveOwnerTo(U2);
      const before = freeze();
      const rec = recordStorage();

      await act(async () => {
        held.settlers[0].reject(new Error('offline'));
        await new Promise((r) => setTimeout(r, 60));
      });

      const reads = privateOf(rec.calls.get);
      const writes = privateOf(rec.calls.set);
      const enumerated = rec.calls.enumerate;
      rec.restore();
      expect(screen.getByTestId('save-status').textContent,
        "a dead token's refusal is not written").toBe(during);
      expect(reads, "and U2's data is not read for it").toEqual([]);
      expect(writes, 'nor written').toEqual([]);
      expect(enumerated, 'nor scanned').toBe(0);
      expect(storageBytes(), 'the bytes are as they were').toBe(before.bytes);
      expect(cacheMocks.clearMatchCache).not.toHaveBeenCalled();
      expect(pushSpy).not.toHaveBeenCalled();

      // Nor was a retry armed for the old screen: pressing it reaches nothing.
      const sentBefore = commitProfilePatch.mock.calls.length;
      await act(async () => {
        screen.getByTestId('retry-sync').click();
        await new Promise((r) => setTimeout(r, 40));
      });
      expect(commitProfilePatch.mock.calls.length,
        'and no retry was armed on a screen that is gone').toBe(sentBefore);
    },
  );

  /** A screen whose very first load has NOT been issued yet: the mount
   *  effect's fallback is scheduled but has not run, so this form has never
   *  been given an origin by anything. Deliberately not awaited. */
  async function screenBeforeAnyLoad(row: Record<string, unknown> = { ...ROW }, revision = 9) {
    const loads = { count: 0 };
    // The token is captured when the mock is INVOKED, exactly as a real read
    // resolves: a load issued after the owner moved comes back attributed to
    // whoever owns the browser then.
    mockLoadProfile = () => {
      loads.count += 1;
      return Promise.resolve(cloudRow(row, revision));
    };
    await renderIdentityHarness();
    expect(screen.getByTestId('view-uid').textContent,
      'no view has been published').toBe('none');
    expect(loads.count, 'and no load has been issued').toBe(0);
    return loads;
  }

  it('E9-control: the first edit on a screen with no origin yet is its own', async () => {
    const loads = await screenBeforeAnyLoad();
    act(() => { screen.getByTestId('set-college').click(); });
    expect(screen.getByTestId('college').textContent, 'it paints').toBe('Grainger');
    act(() => { screen.getByTestId('set-interests').click(); });
    expect(screen.getByTestId('interests').textContent,
      'and so does the next one, under the same screen').toBe('my interests');
    // The screen's own load still happens, and its edits reach the row.
    await act(async () => { await new Promise((r) => setTimeout(r, 60)); });
    expect(loads.count, 'the load this screen was waiting for is issued').toBe(1);
  });

  const U2_ROW = {
    college: 'Siebel', major: 'Stats', grade: 'Senior', research_interests: 'u2 row research',
  };

  it('E9-fallback-control: the load a screen is waiting for still lands, with its edits', async () => {
    const loads = await screenBeforeAnyLoad(U2_ROW, 3);
    await honestCache();
    act(() => { screen.getByTestId('set-college').click(); });

    // Phase one: the queued load, and React's own flush of what it produced.
    await act(async () => { await new Promise((r) => setTimeout(r, 40)); });

    expect(loads.count, 'the load is issued').toBe(1);
    expect(screen.getByTestId('view-uid').textContent, 'and accepted').toBe(HOME_UID);
    expect(screen.getByTestId('view-rev').textContent, 'at its own revision').toBe('3');
    // A field the college cascade does NOT invalidate, so what lands is the
    // row and not an artefact of the edit made during it.
    expect(screen.getByTestId('interests').textContent, 'the row lands')
      .toBe('u2 row research');
    expect(screen.getByTestId('college').textContent,
      'with the edit made while it was in flight kept').toBe('Grainger');

    // Phase two: the debounce the hydration armed behind it.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(syncOverrides.stageCalls,
      "and that edit is written for, under this screen's own capability")
      .toBeGreaterThan(0));
  });

  it('E9-fallback: the queued load may not be re-issued for an owner this screen never had', async () => {
    const loads = await screenBeforeAnyLoad(U2_ROW, 3);
    await honestCache();
    pushSpy.mockClear();
    // The first edit is legitimate and freezes this screen's origin to U1.
    act(() => { screen.getByTestId('set-college').click(); });
    expect(screen.getByTestId('college').textContent, 'it paints').toBe('Grainger');

    await moveOwnerTo(U2);
    const before = freeze();
    const statusBefore = screen.getByTestId('save-status').textContent;
    // Armed BEFORE anything is allowed to run.
    const rec = recordStorage();

    // The mount fallback fires in here, and so would the debounce behind it.
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    const enumerated = rec.calls.enumerate;
    rec.restore();

    expect(loads.count, "no load is issued on the new owner's behalf").toBe(0);
    expect(screen.getByTestId('view-uid').textContent,
      'so no row of theirs is accepted').toBe('none');
    expect(screen.getByTestId('major').textContent, 'and none of it is on screen')
      .toBe('');
    expect(screen.getByTestId('interests').textContent, 'none at all').toBe('');
    expect(screen.getByTestId('college').textContent,
      "while U1's own buffered edit is still exactly what it was").toBe('Grainger');
    expect(screen.getByTestId('save-status').textContent, 'nothing is claimed')
      .toBe(statusBefore);
    expect(reads, 'nothing private is read').toEqual([]);
    expect(writes, 'nothing written').toEqual([]);
    expect(removes, 'nothing removed').toEqual([]);
    expect(enumerated, 'nothing scanned').toBe(0);
    expect(storageBytes(), 'and the bytes are as they were').toBe(before.bytes);
    expect(syncOverrides.stageCalls, 'nothing is staged').toBe(before.stages);
    expect(commitProfilePatch.mock.calls.length, 'and nothing is sent')
      .toBe(before.commits);
  });

  it('E9: a screen that captured its own origin may not capture a second one', async () => {
    const loads = await screenBeforeAnyLoad();
    // The first edit is legitimate and binds this screen to U1.
    act(() => { screen.getByTestId('set-college').click(); });
    expect(screen.getByTestId('college').textContent, 'the first edit paints')
      .toBe('Grainger');

    await moveOwnerTo(U2);
    const before = freeze();
    const collegeBefore = screen.getByTestId('college').textContent;
    const rec = recordStorage();

    act(() => { screen.getByTestId('set-interests').click(); });
    // …and the load this screen never issued is given its chance too: the
    // fallback timer fires here. It must not recapture the new owner and
    // carry the buffered U1 edits into their row.
    await act(async () => { await new Promise((r) => setTimeout(r, 60)); });

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const enumerated = rec.calls.enumerate;
    rec.restore();
    expect(loads.count, "no load is issued on the new owner's behalf").toBe(0);
    expect(screen.getByTestId('interests').textContent,
      'the second edit does not paint').toBe('');
    expect(screen.getByTestId('college').textContent, 'and the first is untouched')
      .toBe(collegeBefore);
    expect(reads, 'nothing private is read').toEqual([]);
    expect(writes, 'nothing written').toEqual([]);
    expect(enumerated, 'nothing scanned').toBe(0);
    expect(storageBytes(), 'and the bytes are as they were').toBe(before.bytes);
    expect(syncOverrides.stageCalls, 'nothing is staged').toBe(before.stages);
  });

  it('E7-realm: the SAME owner with unconfirmed local data still hears its failure', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    await honestCache();
    pushSpy.mockClear();
    const held = await heldCommit();

    act(() => { screen.getByTestId('submit').click(); });
    await awaitRequest(held);
    const uidBefore = screen.getByTestId('view-uid').textContent;
    const epochBefore = screen.getByTestId('view-epoch').textContent;
    expect(screen.getByTestId('submitting').textContent, 'the button is busy').toBe('yes');

    // The owner does NOT move. What goes is this browser's proof that its
    // local data belongs to them — another tab's sweep, a marker that cannot
    // be read back. Same person, same epoch, unusable storage.
    const stillOwner = captureOwnerToken();
    localStorage.removeItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER);

    // The precondition itself, proven rather than assumed: the two checks
    // this test exists to tell apart genuinely disagree right now.
    expect(stillOwner.uid, 'the same person').toBe(HOME_UID);
    expect(screen.getByTestId('view-uid').textContent, 'and the same screen')
      .toBe(uidBefore);
    expect(screen.getByTestId('view-epoch').textContent, 'at the same epoch')
      .toBe(epochBefore);
    expect(isTokenOwnerStillCurrent(stillOwner),
      'they are still the owner of this browser').toBe(true);
    expect(isOwnerTokenValid(stillOwner, stillOwner.uid),
      'but their local data is no longer confirmed for them').toBe(false);

    await act(async () => {
      held.settlers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 60));
    });

    expect(screen.getByTestId('save-status').textContent,
      'their own failed write is still their news').toBe('cloud-failed');
    expect(screen.getByTestId('submitting').textContent,
      'and the button is theirs again').toBe('no');
    expect(cacheMocks.clearMatchCache, 'nothing is invalidated').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();

    // Retry was really armed: once the browser can vouch for them again, the
    // same write goes out.
    await syncLocalIdentityOwner(HOME_UID);
    commitProfilePatch.mockRejectedValue(new Error('offline'));
    const sentBefore = commitProfilePatch.mock.calls.length;
    await act(async () => {
      screen.getByTestId('retry-sync').click();
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(commitProfilePatch.mock.calls.length,
      'Retry sends the write that did not land').toBeGreaterThan(sentBefore);
  });

  it('E7: a submit that completes after the owner moved keeps its screen exactly as it was', async () => {
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    await honestCache();
    pushSpy.mockClear();
    const held = await heldCommit();

    act(() => { screen.getByTestId('submit').click(); });
    await awaitRequest(held);
    const statusDuring = screen.getByTestId('save-status').textContent;
    const busyDuring = screen.getByTestId('submitting').textContent;
    expect(busyDuring, 'the button is busy while it runs').toBe('yes');

    await moveOwnerTo(U2);
    const before = freeze();

    await act(async () => {
      held.settlers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 60));
    });

    expect(screen.getByTestId('save-status').textContent,
      "a dead token's refusal is not written").toBe(statusDuring);
    expect(screen.getByTestId('submitting').textContent,
      'and its completion does not hand the old screen back').toBe(busyDuring);
    expect(cacheMocks.clearMatchCache, 'no cache is cleared').not.toHaveBeenCalled();
    expect(pushSpy, 'nothing navigates').not.toHaveBeenCalled();

    // A second press on the dead screen reaches nothing either.
    await act(async () => {
      screen.getByTestId('submit').click();
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(syncOverrides.stageCalls, 'and a second press stages nothing')
      .toBe(before.stages);

    // The identity event is what gives the form back.
    await u2Arrives();
    expect(screen.getByTestId('submitting').textContent,
      "U2's form is not locked").toBe('no');
  });

  it('O-submit-transport: a write the network refuses says so and stays retryable', async () => {
    const unhandled = captureUnhandled();
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    await honestCache();
    pushSpy.mockClear();
    // HELD, not eagerly rejected: the refusal is delivered inside an `act`,
    // so everything that follows it is microtask-bound and the assertions
    // below need no window at all — the button hands its promise to onClick,
    // which drops it, so the test has nothing of its own to await.
    const held = await heldCommit();

    act(() => { screen.getByTestId('submit').click(); });
    await awaitRequest(held);

    await act(async () => {
      held.settlers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 40));
    });

    expect(screen.getByTestId('save-status').textContent,
      'the person is told the write did not land').toBe('cloud-failed');
    expect(screen.getByTestId('submitting').textContent,
      'and the button is theirs again').toBe('no');
    expect(readProfileSyncEnvelope()?.pending,
      'the write itself is still in the outbox').toBeTruthy();
    expect(cacheMocks.clearMatchCache, 'nothing is invalidated').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();

    // Armed, not merely worded: Retry sends the very same write again. The
    // mock stops HOLDING first — a request left permanently in flight is a
    // lock this test never gives back, and the next test would queue behind
    // it forever.
    commitProfilePatch.mockRejectedValue(new Error('offline'));
    const sentBefore = commitProfilePatch.mock.calls.length;
    await act(async () => {
      screen.getByTestId('retry-sync').click();
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(commitProfilePatch.mock.calls.length,
      'Retry sends the write that did not land').toBeGreaterThan(sentBefore);

    // Let anything still queued settle before the runtime is asked.
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(unhandled, 'and nothing rejected into the page').toEqual([]);
  });

  it('O-submit-transport-stale: a refusal landing after a touch is not written', async () => {
    const unhandled = captureUnhandled();
    await hydratedU1();
    act(() => { screen.getByTestId('set-interests').click(); });
    await honestCache();
    const held = await heldCommit();

    act(() => { screen.getByTestId('submit').click(); });
    await awaitRequest(held);
    const during = screen.getByTestId('save-status').textContent;
    expect(during, 'and it owns the wording while it runs').toBe('saving');

    // A same-value touch: it moves the form's edit count and takes no save
    // intent, so the intent check alone could not tell the difference.
    await touchWeightHere();

    await act(async () => {
      held.settlers[0].reject(new Error('offline'));
      await new Promise((r) => setTimeout(r, 60));
    });

    expect(screen.getByTestId('save-status').textContent,
      'a form the person has touched since is not labelled by it').toBe(during);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(unhandled, 'and nothing rejected into the page').toEqual([]);
  });

  function touchWeightHere() {
    act(() => { screen.getByTestId('touch-weight').click(); });
  }

  /** A manual import under hydrated U1 whose request is HELD open. */
  async function heldManualImport() {
    await hydratedU1();
    let reject!: (e: unknown) => void;
    let started = false;
    vi.mocked(parseGitHubProfile).mockImplementation((() => {
      started = true;
      return new Promise((_resolve, rej) => { reject = rej; });
    }) as never);
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { screen.getByTestId('gh-import').click(); });
    expect(started, 'the request really went out').toBe(true);
    return {
      reject: () => reject,
      spinnerDuring: screen.getByTestId('gh-loading').textContent,
      statusDuring: screen.getByTestId('gh-status').textContent,
    };
  }

  it('O2b-github-failure-control: a failed import under its own owner IS reported', async () => {
    const held = await heldManualImport();
    expect(held.spinnerDuring, 'the spinner is on while it runs').toBe('yes');
    await honestCache();
    pushSpy.mockClear();
    const stagesBefore = syncOverrides.stageCalls;

    await act(async () => {
      held.reject()(new Error('offline'));
      await new Promise((r) => setTimeout(r, 20));
    });

    await waitFor(() => expect(screen.getByTestId('gh-status').textContent,
      'the failure is published').toContain('githubImportFail'));
    expect(screen.getByTestId('gh-loading').textContent,
      'and the spinner goes off').toBe('no');
    expect(screen.getByTestId('skills').textContent,
      'a failed import adds no skills').toBe('');
    expect(await journalOps().filter((o) => o.mode === 'add-skills'),
      'and marks none').toHaveLength(0);
    expect(syncOverrides.stageCalls, 'nothing is staged by a failure')
      .toBe(stagesBefore);
    expect(cacheMocks.clearMatchCache, 'no cache is cleared').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();
  });

  it('O2b-github-failure: a failure landing after the owner moved is written nowhere', async () => {
    const held = await heldManualImport();
    expect(held.spinnerDuring, 'the spinner is on while it runs').toBe('yes');

    await moveOwnerTo(U2);
    await honestCache();
    pushSpy.mockClear();
    const stagesBefore = syncOverrides.stageCalls;
    const bytes = storageBytes();
    const rec = recordStorage();

    await act(async () => {
      held.reject()(new Error('offline'));
      await new Promise((r) => setTimeout(r, 40));
    });

    const reads = privateOf(rec.calls.get);
    const writes = privateOf(rec.calls.set);
    const removes = privateOf(rec.calls.remove);
    rec.restore();

    expect(screen.getByTestId('gh-status').textContent,
      "a dead screen's failure is not written").toBe(held.statusDuring);
    expect(screen.getByTestId('gh-loading').textContent,
      'and its finally does not touch the spinner either').toBe(held.spinnerDuring);
    expect(reads, "no private data is read on the old screen's behalf").toEqual([]);
    expect(writes, 'none is written').toEqual([]);
    expect(removes, 'and none is removed').toEqual([]);
    expect(await journalOps().filter((o) => o.mode === 'add-skills'),
      'the skill ledger is untouched').toHaveLength(0);
    expect(storageBytes(), "so U2's bytes are exactly as they were").toBe(bytes);
    expect(syncOverrides.stageCalls, 'nothing is staged').toBe(stagesBefore);
    expect(cacheMocks.clearMatchCache, 'no cache is cleared').not.toHaveBeenCalled();
    expect(pushSpy, 'and nothing navigates').not.toHaveBeenCalled();
  });

  /**
   * A manual import resolved with the owner moving in the microtask GAP: the
   * helper's own continuation is enqueued first (by resolving the request),
   * the owner move immediately after it, and the caller's continuation last.
   * The helper therefore finishes legitimately — its own origin check passes —
   * and the only thing that can differ by then is a token re-captured after
   * the await.
   *
   * Returns U2's durable pending write, so what the skill ledger actually
   * carried into their account is read from storage rather than inferred.
   */
  async function importThenGapMove(move: boolean) {
    await hydratedU1();
    let release!: (v: unknown) => void;
    vi.mocked(parseGitHubProfile).mockImplementation(
      (() => new Promise((resolve) => { release = resolve; })) as never,
    );
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => { screen.getByTestId('gh-import').click(); });
    expect(release, 'the import is in flight').toBeTypeOf('function');

    await act(async () => {
      release({
        username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 1, top_repos: [],
      });
      if (move) {
        queueMicrotask(async () => {
          advanceOwnerEpoch(U2);
          await syncLocalIdentityOwner(U2);
        });
      }
      await new Promise((r) => setTimeout(r, 40));
    });

    // U2 arrives for real, reads their own row, imports their OWN link, and
    // presses Generate. The write is refused by the server, so the pending
    // write it staged stays on disk to be read.
    mockLoadProfile = () => Promise.resolve(
      cloudRow({ college: 'Siebel', major: 'Stats', grade: 'Senior' }, 3),
    );
    if (!move) {
      await act(async () => {
        advanceOwnerEpoch(U2);
        await syncLocalIdentityOwner(U2);
      });
    }
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('3'));
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'u2', extracted_skills: ['Rust'], topics: [], repo_count: 1, top_repos: [],
    });
    act(() => { screen.getByTestId('set-gh').click(); });
    await act(async () => {
      screen.getByTestId('gh-import').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    await waitFor(() => expect(screen.getByTestId('skills').textContent).toBe('Rust'));
    commitProfilePatch.mockRejectedValue(new Error('offline'));
    await act(async () => {
      screen.getByTestId('submit').click();
      await new Promise((r) => setTimeout(r, 60));
    });
    await waitFor(() => expect(readProfileSyncEnvelope()?.pending,
      "U2's own write is on disk").toBeTruthy());
    const pending = readProfileSyncEnvelope()!.pending!;
    return pending.skillOps.flatMap(
      (op) => (op.kind === 'add' && op.skill ? [op.skill.name] : ['<replace>']),
    );
  }

  it('O-manual-gap-control: an import whose owner never moves marks its own ledger', async () => {
    const names = await importThenGapMove(false);
    expect(names, "U2's own import is in U2's ledger").toContain('Rust');
  });

  it('O-manual-gap: an owner move in the gap after an import does not poison the new ledger', async () => {
    const names = await importThenGapMove(true);
    expect(names, "U2's own import is still in U2's ledger").toContain('Rust');
    expect(names, "and U1's import never entered it").not.toContain('Go');
  });

  /** Puts `research_interests` into the hook's unrecorded buffer: the journal
   *  append fails, so the edit is on screen and nowhere else. */
  async function unrecordedEdit() {
    await hydratedU1();
    const restore = await breakStorageFor((k) => k.startsWith(STORAGE_KEYS.PROFILE_JOURNAL_PREFIX));
    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    restore();
    return { restore };
  }

  it('O5-control: an edit the journal refused is recovered for its OWN owner', async () => {
    await unrecordedEdit();
    commitProfilePatch.mockClear();
    await honestCache();
    pushSpy.mockClear();

    await act(async () => {
      screen.getByTestId('submit').click();
      await new Promise((r) => setTimeout(r, 60));
    });

    await waitFor(() => expect(
      sentPatches().some((p) => p.research_interests === 'my interests'),
      'the same person gets their edit back',
    ).toBe(true));
  });

  it('O5: an edit the journal refused for U1 is never resent under U2', async () => {
    await unrecordedEdit();
    mockLoadProfile = () => Promise.resolve(
      cloudRow({ college: 'Siebel', major: 'Stats', grade: 'Senior' }, 3),
    );
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('3'));
    commitProfilePatch.mockClear();
    await honestCache();
    pushSpy.mockClear();

    await act(async () => {
      screen.getByTestId('submit').click();
      await new Promise((r) => setTimeout(r, 60));
    });

    expect(await sentPatches().some((p) => 'research_interests' in p),
      "U1's un-journalled key is not U2's to send").toBe(false);
    expect(await journalOps().some((o) => o.fields.some((f) => f.key === 'research_interests')),
      'and it is not recorded for them either').toBe(false);

    // A U2-native edit still saves normally.
    commitProfilePatch.mockClear();
    act(() => { screen.getByTestId('set-coursework').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    expect(await sentPatches().some((p) => Array.isArray(p.coursework)),
      "U2's own edit goes out").toBe(true);
  });

  /** A rev10 question about `major`, raised through the real handler. */
  async function questionOnScreen() {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    await renderIdentityHarness();
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    syncOverrides.stageProfilePatch = async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['major'],
      conflicts: [await question('major', 10, 'Statistics')],
    });
    syncOverrides.refreshConflictQuestion = async () => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Statistics' },
      revision: 10,
      conflicts: [await question('major', 10, 'Statistics')],
      pendingKeys: ['major'],
      flushed: null,
    });
    act(() => { screen.getByTestId('set-major-ece').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('conflict-revs').textContent).toBe('major@10'));
  }

  it('R1: an answer clicked after the owner moved never becomes a request', async () => {
    await questionOnScreen();
    let asked = 0;
    syncOverrides.resolveProfileConflict = (() => {
      asked += 1;
      return new Promise(() => {});
    }) as never;
    await moveOwnerTo(U2);
    const statusBefore = screen.getByTestId('save-status').textContent;
    const bytes = storageBytes();
    const rec = recordStorage();

    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 40));
    });

    const writes = privateOf(rec.calls.set);
    const reads = privateOf(rec.calls.get);
    rec.restore();

    expect(asked, 'the resolver is never called').toBe(0);
    expect(reads, "and U2's private data is never consulted").toEqual([]);
    expect(writes, 'nor written').toEqual([]);
    expect(storageBytes()).toBe(bytes);
    expect(screen.getByTestId('save-status').textContent,
      'the screen is not even told it is saving').toBe(statusBefore);
    expect(screen.getByTestId('conflict-keys').textContent,
      'and the question is left exactly where it was').toBe('major');
  });

  it('O7a: a stale answer leaves the latch free and the next owner clean', async () => {
    await questionOnScreen();
    let asked = 0;
    syncOverrides.resolveProfileConflict = (() => {
      asked += 1;
      return new Promise(() => {});
    }) as never;
    // Owner-only move: the shared owner and U2's realm move, this hook's auth
    // callback is never delivered, so the generation does not move and U1's
    // question is still rendered and still takes clicks.
    await moveOwnerTo(U2);

    await act(async () => {
      screen.getByTestId('keep-mine').click();
      await new Promise((r) => setTimeout(r, 40));
    });

    expect(asked, 'the resolver is never reached').toBe(0);
    expect(screen.getByTestId('save-status').textContent,
      'and the screen is never even told it is saving').toBe('conflict');

    // Now the real transition arrives. U2's own row lands and the form is
    // theirs: no question of U1's, no value of U1's, nothing being saved.
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW, major: 'U2-ROW' }, 4));
    syncOverrides.stageProfilePatch = null;
    await emitAuth(U2);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('4'));
    expect(screen.getByTestId('conflict-keys').textContent,
      "U1's question did not follow them").toBe('');
    expect(screen.getByTestId('major').textContent, "nor did U1's value").toBe('U2-ROW');
    expect(screen.getByTestId('save-status').textContent,
      'and nothing is claimed to be in flight').toBe('idle');

    // THE LATCH. The stale click must not have taken it: if it had, U2 could
    // never answer a question of their own. Proven by raising a real one.
    syncOverrides.stageProfilePatch = (async () => ({
      status: 'conflict' as const,
      revision: 5,
      remote: { ...ROW, major: 'Other' },
      confirmed: { revision: 5, profile: { ...ROW, major: 'Other' } },
      conflictKeys: ['major'],
      conflicts: [await question('major', 5, 'Other')],
    })) as never;
    syncOverrides.refreshConflictQuestion = (async () => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Other' },
      revision: 5,
      conflicts: [await question('major', 5, 'Other')],
      pendingKeys: ['major'],
      flushed: null,
    })) as never;
    act(() => { screen.getByTestId('set-major-ece').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('conflict-keys').textContent).toBe('major'));

    let u2Asked = 0;
    syncOverrides.resolveProfileConflict = (async () => {
      u2Asked += 1;
      return { status: 'saved' as const, revision: 6, profile: { ...ROW, major: 'Other' } };
    }) as never;
    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 60));
    });
    expect(u2Asked, "U2's own answer is taken — the latch was never stranded").toBe(1);
  });

  it('R2-control: an answer under its own owner moves the field and retires the question', async () => {
    await questionOnScreen();
    syncOverrides.resolveProfileConflict = (async () => ({
      status: 'saved' as const, revision: 11, profile: { ...ROW, major: 'Statistics' },
    })) as never;

    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 60));
    });

    await waitFor(() => expect(screen.getByTestId('major').textContent,
      'the answer is what the person sees').toBe('Statistics'));
    expect(screen.getByTestId('conflict-keys').textContent,
      'and the question is gone').toBe('');
  });

  it('R2: an answer landing after the owner moved changes nothing on the old screen', async () => {
    await questionOnScreen();
    let release!: (v: unknown) => void;
    syncOverrides.resolveProfileConflict = (
      () => new Promise((resolve) => { release = resolve; })
    ) as never;
    await act(async () => {
      screen.getByTestId('use-cloud').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(release, 'the answer is in flight').toBeTypeOf('function');
    const during = screen.getByTestId('save-status').textContent;
    const majorDuring = screen.getByTestId('major').textContent;

    await moveOwnerTo(U2);

    await act(async () => {
      release({ status: 'saved', revision: 11, profile: { ...ROW, major: 'Statistics' } });
      await new Promise((r) => setTimeout(r, 60));
    });

    expect(screen.getByTestId('major').textContent,
      "a dead token's answer is not drawn onto the form").toBe(majorDuring);
    expect(screen.getByTestId('conflict-keys').textContent,
      'the question it answered is not retired').toBe('major');
    expect(screen.getByTestId('save-status').textContent,
      'and it takes no wording').toBe(during);
  });
});

// The REAL status row, wired exactly as app/page.tsx wires it. The identity
// harness above renders its own always-present buttons, which is the right
// tool for testing the hook — and exactly the wrong one for asking whether a
// person can still act on what is on screen. These tests click the shipped UI.
function SubmitRowHarness() {
  const form = useProfileForm(stableT);
  return (
    <div>
      <span data-testid="save-status">{form.saveStatus}</span>
      <span data-testid="conflict-keys">{form.conflictKeys.join(',')}</span>
      <span data-testid="view-rev">
        {form.viewSnapshot ? String(form.viewSnapshot.revision) : 'none'}
      </span>
      <span data-testid="major">{form.profile.major}</span>
      <span data-testid="grade">{form.profile.grade}</span>
      <button data-testid="set-major-ece" onClick={() => form.update('major', 'ECE')}>ece</button>
      <button
        data-testid="set-interests"
        onClick={() => form.update('research_interests', 'my interests')}
      >ri</button>
      <SubmitRow
        isValid={form.isValid}
        shareCopied={form.shareCopied}
        saveStatus={form.saveStatus}
        hydrationState={form.hydrationState}
        isSubmitting={form.isSubmitting}
        hasConflict={form.conflicts.length > 0}
        canRetrySync={form.canRetrySync}
        onRetrySync={form.retryCloudSave}
        onKeepMyChanges={form.keepMyChanges}
        onUseCloudVersion={form.useCloudVersion}
        onSubmit={form.handleSubmit}
        onShare={form.handleShare}
        t={stableT}
      />
    </div>
  );
}

describe('useProfileForm — a question stays answerable in the UI the person is looking at', () => {
  const ROW = { college: 'Grainger', major: 'CS', grade: 'Junior', search_weight: 50 };

  function question(key: string, revision: number, remote: unknown, mutationId = 'm1') {
    return {
      key,
      remote,
      remoteRevision: revision,
      mutationId,
      keyVersion: 1,
      candidates: [{ value: 'mine', lineage: 'lin-a', opIds: [`op-${key}-${revision}`] }],
    };
  }

  /** A real `major` disagreement, rendered by the real SubmitRow. */
  async function questionInTheUi() {
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 9));
    render(<Suspense fallback={null}><SubmitRowHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('9'));
    syncOverrides.stageProfilePatch = (async () => ({
      status: 'conflict' as const,
      revision: 10,
      remote: { ...ROW, major: 'Statistics' },
      confirmed: { revision: 10, profile: { ...ROW, major: 'Statistics' } },
      conflictKeys: ['major'],
      conflicts: [await question('major', 10, 'Statistics')],
    })) as never;
    syncOverrides.refreshConflictQuestion = (async () => ({
      status: 'current' as const,
      profile: { ...ROW, major: 'ECE' },
      baseProfile: { ...ROW, major: 'Statistics' },
      revision: 10,
      conflicts: [await question('major', 10, 'Statistics')],
      pendingKeys: ['major'],
      flushed: null,
    })) as never;
    act(() => { screen.getByTestId('set-major-ece').click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 1700)); });
    await waitFor(() => expect(screen.getByTestId('conflict-keys').textContent).toBe('major'));
    expect(screen.getByTestId('conflict-keep-mine'), 'the choice is on screen').toBeTruthy();
  }

  /** A clean save, immediately — Generate, so no debounce is involved. */
  async function cleanSaveOverTheQuestion() {
    syncOverrides.stageProfilePatch = (async () => ({
      status: 'saved' as const, revision: 11, profile: { ...ROW, major: 'ECE' },
    })) as never;
    act(() => { screen.getByTestId('set-interests').click(); });
    await act(async () => {
      screen.getByTestId('generate-matches').click();
      await new Promise((r) => setTimeout(r, 60));
    });
    await waitFor(() => expect(screen.getByTestId('save-status').textContent).toBe('saved'));
  }

  it('UI-conflict-outlives-save: a clean save does not take the choice away', async () => {
    await questionInTheUi();
    // Saved cleanly. The disagreement about `major` is untouched by it —
    // nobody has answered that question, and a write that succeeded is no
    // verdict on one that was never asked.
    await cleanSaveOverTheQuestion();

    expect(screen.getByTestId('conflict-keys').textContent,
      'the question is still open').toBe('major');
    expect(screen.queryByTestId('conflict-keep-mine'),
      'and the way out of it is still on screen').not.toBeNull();

    let asked = 0;
    syncOverrides.resolveProfileConflict = (() => {
      asked += 1;
      return new Promise(() => {});
    }) as never;
    await act(async () => {
      screen.getByTestId('conflict-use-cloud').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(asked, 'and it can still be answered').toBe(1);
  });

  it('UI-conflict-outlives-idle: nor does that save\'s badge clearing itself two seconds later', async () => {
    await questionInTheUi();
    await cleanSaveOverTheQuestion();

    await act(async () => { await new Promise((r) => setTimeout(r, 2200)); });
    expect(screen.getByTestId('save-status').textContent,
      'the badge cleared itself, as it should').toBe('idle');
    expect(screen.getByTestId('conflict-keys').textContent,
      'the question has still not been answered').toBe('major');
    expect(screen.queryByTestId('conflict-keep-mine'),
      'so the controls for it are still there').not.toBeNull();
    expect(screen.queryByTestId('conflict-use-cloud')).not.toBeNull();
  });

  it('UI-conflict-rejection: a rejected answer leaves the question answerable, not a dead Retry', async () => {
    await questionInTheUi();
    syncOverrides.resolveProfileConflict = (
      () => Promise.reject(new Error('offline'))
    ) as never;

    await act(async () => {
      screen.getByTestId('conflict-keep-mine').click();
      await new Promise((r) => setTimeout(r, 60));
    });

    expect(screen.getByTestId('save-status').textContent,
      'the transport failure is reported').toBe('cloud-failed');
    expect(screen.queryByTestId('retry-sync'),
      'with no Retry that cannot unlock a conflicted key anyway').toBeNull();
    expect(screen.getByTestId('conflict-keys').textContent,
      'the question is exactly where it was').toBe('major');

    // And the person can choose again — the latch the failed answer took must
    // have been released with it.
    let asked = 0;
    syncOverrides.resolveProfileConflict = (() => {
      asked += 1;
      return new Promise(() => {});
    }) as never;
    await act(async () => {
      screen.getByTestId('conflict-use-cloud').click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(asked, 'the second choice really is taken').toBe(1);
  });

  it('UI-conflict-identity: the next account never inherits the controls', async () => {
    // Now that the controls are driven by the question rather than by the
    // status word, an identity transition that forgot to retire the question
    // would hand U2 two buttons bound to U1's disagreement.
    await questionInTheUi();
    mockLoadProfile = () => Promise.resolve(cloudRow({ ...ROW }, 4));
    syncOverrides.stageProfilePatch = null;

    await emitAuth('ui-conflict-u2');
    await waitFor(() => expect(screen.getByTestId('view-rev').textContent).toBe('4'));

    expect(screen.getByTestId('conflict-keys').textContent,
      "U1's question left with U1").toBe('');
    expect(screen.queryByTestId('conflict-keep-mine'),
      'and so did the controls for it').toBeNull();
    expect(screen.queryByTestId('conflict-use-cloud')).toBeNull();
    expect(screen.queryByTestId('retry-sync'),
      "nor does U2 inherit U1's retry").toBeNull();
  });

  it('UI-conflict-answered: answering it IS what takes the controls away', async () => {
    // The complement, so the two tests above cannot pass on a component that
    // simply renders the controls forever.
    await questionInTheUi();
    syncOverrides.resolveProfileConflict = (async () => ({
      status: 'saved' as const, revision: 11, profile: { ...ROW, major: 'Statistics' },
    })) as never;

    await act(async () => {
      screen.getByTestId('conflict-use-cloud').click();
      await new Promise((r) => setTimeout(r, 60));
    });

    await waitFor(() => expect(screen.getByTestId('conflict-keys').textContent).toBe(''));
    expect(screen.queryByTestId('conflict-keep-mine'),
      'a settled question leaves no controls behind').toBeNull();
    expect(screen.queryByTestId('conflict-use-cloud')).toBeNull();
  });
});
