/*
 * Branching matrix for `signInOrLinkEmail` (R65 P1 Flow A).
 *
 * The helper picks between three Supabase APIs based on the current
 * session shape. Verifying the routing logic here protects against
 * regressions where someone "fixes" the order of the branches or
 * forgets that anon sessions need `updateUser` (not signInWithOtp).
 *
 * We mock the supabase client at the module boundary instead of
 * spinning up a real client because the goal is to test OUR code, not
 * Supabase's network behavior.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

// vi.mock is hoisted to the top of the file at compile time, so any
// references it makes to module-level `const`s would be evaluated
// before those constants are initialized. We use vi.hoisted to declare
// the mocks BEFORE the mock factory so both share a single hoisting
// frame — this is the only correct way to share mock functions between
// the factory and the test body.
//
// We also set the env vars inside the hoisted block. ESM `import`
// statements are hoisted above any top-level statements, so a plain
// `process.env.X = ...` followed by `import { ... } from './supabase'`
// would NOT work: the import (and thus the module's top-level
// SUPABASE_CONFIGURED check) runs before the assignment. vi.hoisted
// runs before all imports — exactly what we need.
const { mockGetSession, mockUpdateUser, mockSignInWithOtp } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockGetSession: vi.fn(),
    mockUpdateUser: vi.fn(),
    mockSignInWithOtp: vi.fn(),
  };
});

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: mockGetSession,
      updateUser: mockUpdateUser,
      signInWithOtp: mockSignInWithOtp,
      signOut: vi.fn().mockResolvedValue({ error: null }),
      signInAnonymously: vi.fn().mockResolvedValue({
        data: { user: { id: 'new-anon-uid' } },
        error: null,
      }),
      onAuthStateChange: vi.fn(() => ({
        data: { subscription: { unsubscribe: vi.fn() } },
      })),
    },
    from: vi.fn(),
    storage: { from: vi.fn() },
  }),
}));

import { isAnonymousUser, signInExistingEmail, signInOrLinkEmail } from './supabase';

const REDIRECT = 'https://app.test/auth/callback';

function anonSession() {
  return {
    data: {
      session: {
        user: { id: 'anon-uid', is_anonymous: true, email: null },
      },
    },
  };
}

function permanentSession() {
  return {
    data: {
      session: {
        user: { id: 'perm-uid', is_anonymous: false, email: 'eric@illinois.edu' },
      },
    },
  };
}

function noSession() {
  return { data: { session: null } };
}

describe('isAnonymousUser', () => {
  it('returns false for null session', () => {
    expect(isAnonymousUser(null)).toBe(false);
  });

  it('reads the is_anonymous claim off session.user', () => {
    const session = { user: { id: 'x', is_anonymous: true } } as never;
    expect(isAnonymousUser(session)).toBe(true);
  });

  it('returns false when is_anonymous is missing (defensive default)', () => {
    const session = { user: { id: 'x' } } as never;
    expect(isAnonymousUser(session)).toBe(false);
  });
});

describe('signInOrLinkEmail — branching', () => {
  beforeEach(() => {
    mockGetSession.mockReset();
    mockUpdateUser.mockReset();
    mockSignInWithOtp.mockReset();
  });

  it('rejects malformed emails before any network call', async () => {
    mockGetSession.mockResolvedValueOnce(anonSession());
    const result = await signInOrLinkEmail('not-an-email', REDIRECT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('invalid-email');
    expect(mockUpdateUser).not.toHaveBeenCalled();
    expect(mockSignInWithOtp).not.toHaveBeenCalled();
  });

  it('anon session → updateUser (in-place conversion preserves auth.uid)', async () => {
    mockGetSession.mockResolvedValueOnce(anonSession());
    mockUpdateUser.mockResolvedValueOnce({ data: { user: {} }, error: null });

    const result = await signInOrLinkEmail('eric@illinois.edu', REDIRECT);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.mode).toBe('link-anon');
    expect(mockUpdateUser).toHaveBeenCalledWith(
      { email: 'eric@illinois.edu' },
      { emailRedirectTo: REDIRECT },
    );
    expect(mockSignInWithOtp).not.toHaveBeenCalled();
  });

  it('no session → signInWithOtp with shouldCreateUser:true', async () => {
    mockGetSession.mockResolvedValueOnce(noSession());
    mockSignInWithOtp.mockResolvedValueOnce({ data: {}, error: null });

    const result = await signInOrLinkEmail('eric@illinois.edu', REDIRECT);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.mode).toBe('sign-in');
    expect(mockSignInWithOtp).toHaveBeenCalledWith({
      email: 'eric@illinois.edu',
      options: { emailRedirectTo: REDIRECT, shouldCreateUser: true },
    });
    expect(mockUpdateUser).not.toHaveBeenCalled();
  });

  it('permanent session → no-op success (UI should not have shown the form)', async () => {
    mockGetSession.mockResolvedValueOnce(permanentSession());

    const result = await signInOrLinkEmail('eric@illinois.edu', REDIRECT);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.mode).toBe('sign-in');
    expect(mockUpdateUser).not.toHaveBeenCalled();
    expect(mockSignInWithOtp).not.toHaveBeenCalled();
  });

  it('lowercases + trims the email before sending it on', async () => {
    mockGetSession.mockResolvedValueOnce(anonSession());
    mockUpdateUser.mockResolvedValueOnce({ data: { user: {} }, error: null });

    await signInOrLinkEmail('  Eric@ILLINOIS.edu  ', REDIRECT);

    expect(mockUpdateUser).toHaveBeenCalledWith(
      { email: 'eric@illinois.edu' },
      { emailRedirectTo: REDIRECT },
    );
  });
});

describe('signInOrLinkEmail — error mapping', () => {
  beforeEach(() => {
    mockGetSession.mockReset();
    mockUpdateUser.mockReset();
    mockSignInWithOtp.mockReset();
  });

  it('maps "already registered" updateUser error to email-taken', async () => {
    mockGetSession.mockResolvedValueOnce(anonSession());
    mockUpdateUser.mockResolvedValueOnce({
      data: null,
      error: { message: 'A user with this email address has already been registered' },
    });

    const result = await signInOrLinkEmail('eric@illinois.edu', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('email-taken');
  });

  it('maps rate-limit errors to rate-limited', async () => {
    mockGetSession.mockResolvedValueOnce(noSession());
    mockSignInWithOtp.mockResolvedValueOnce({
      data: null,
      error: { message: 'For security purposes, please wait — too many requests' },
    });

    const result = await signInOrLinkEmail('eric@illinois.edu', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('rate-limited');
  });

  it('falls through unknown errors as unknown (preserves Supabase message)', async () => {
    mockGetSession.mockResolvedValueOnce(noSession());
    mockSignInWithOtp.mockResolvedValueOnce({
      data: null,
      error: { message: 'Database connection lost' },
    });

    const result = await signInOrLinkEmail('eric@illinois.edu', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe('unknown');
      expect(result.message).toBe('Database connection lost');
    }
  });
});

// R67 problem #2: `signInExistingEmail` is the dedicated "I already have
// an account" path. It MUST always call signInWithOtp with
// shouldCreateUser:false regardless of current session, so the user who
// just hit "email-taken" on the link-anon path can recover in-modal.
describe('signInExistingEmail — forced sign-in-to-existing path', () => {
  beforeEach(() => {
    mockGetSession.mockReset();
    mockUpdateUser.mockReset();
    mockSignInWithOtp.mockReset();
  });

  it('rejects malformed emails before any network call', async () => {
    const result = await signInExistingEmail('not-an-email', REDIRECT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('invalid-email');
    expect(mockSignInWithOtp).not.toHaveBeenCalled();
  });

  it('always calls signInWithOtp with shouldCreateUser:false (does NOT read session)', async () => {
    mockSignInWithOtp.mockResolvedValueOnce({ data: {}, error: null });

    const result = await signInExistingEmail('eric@illinois.edu', REDIRECT);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.mode).toBe('sign-in');
    expect(mockSignInWithOtp).toHaveBeenCalledWith({
      email: 'eric@illinois.edu',
      options: { emailRedirectTo: REDIRECT, shouldCreateUser: false },
    });
    // Crucially, we do NOT branch on session state — that's the bug we
    // were working around in signInOrLinkEmail.
    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockUpdateUser).not.toHaveBeenCalled();
  });

  it('lowercases + trims the email before sending', async () => {
    mockSignInWithOtp.mockResolvedValueOnce({ data: {}, error: null });

    await signInExistingEmail('  Eric@ILLINOIS.edu  ', REDIRECT);

    expect(mockSignInWithOtp).toHaveBeenCalledWith({
      email: 'eric@illinois.edu',
      options: { emailRedirectTo: REDIRECT, shouldCreateUser: false },
    });
  });

  it('maps Supabase errors through the same mapAuthError pipeline', async () => {
    mockSignInWithOtp.mockResolvedValueOnce({
      data: null,
      error: { message: 'For security purposes, too many requests' },
    });

    const result = await signInExistingEmail('eric@illinois.edu', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('rate-limited');
  });
});
