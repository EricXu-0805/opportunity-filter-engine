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
const {
  mockGetSession,
  mockUpdateUser,
  mockSignInWithOtp,
  mockSignInWithOAuth,
  mockLinkIdentity,
  mockSignOut,
  mockSignInAnonymously,
} = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockGetSession: vi.fn(),
    mockUpdateUser: vi.fn(),
    mockSignInWithOtp: vi.fn(),
    mockSignInWithOAuth: vi.fn(),
    mockLinkIdentity: vi.fn(),
    mockSignOut: vi.fn(),
    mockSignInAnonymously: vi.fn(),
  };
});

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: mockGetSession,
      updateUser: mockUpdateUser,
      signInWithOtp: mockSignInWithOtp,
      signInWithOAuth: mockSignInWithOAuth,
      linkIdentity: mockLinkIdentity,
      signOut: mockSignOut,
      signInAnonymously: mockSignInAnonymously,
      onAuthStateChange: vi.fn(() => ({
        data: { subscription: { unsubscribe: vi.fn() } },
      })),
    },
    from: vi.fn(),
    storage: { from: vi.fn() },
  }),
}));

import {
  isAnonymousUser,
  signInExistingEmail,
  signInExistingOAuth,
  signInOrLinkEmail,
  signInWithOAuthProvider,
  signOutOfAccount,
} from './supabase';
import { STORAGE_KEYS } from './storage-keys';

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

  it('maps email_address_invalid to invalid-email, NOT email-taken', async () => {
    // A validation rejection (malformed / disposable / blocked domain) is
    // unrelated to account existence — it must not get the "sign in instead"
    // CTA, which would re-submit the same bad address in a loop.
    mockGetSession.mockResolvedValueOnce(noSession());
    mockSignInWithOtp.mockResolvedValueOnce({
      data: null,
      error: { message: 'Email address is invalid', code: 'email_address_invalid' },
    });

    const result = await signInOrLinkEmail('eric@x.invalid', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('invalid-email');
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

// Google OAuth remains part of the release. Microsoft school OAuth is
// source-frozen and must fail closed in this helper too — hiding its
// AuthModal button is not enough because callers can invoke the helper
// directly.
//
// Branching matrix mirrors signInOrLinkEmail: an ANON session must take
// linkIdentity (attaches the OAuth identity to the current anonymous
// user — same auth.uid(), so all RLS-owned rows survive), while no
// session / a permanent session takes plain signInWithOAuth.
describe('signInWithOAuthProvider', () => {
  beforeEach(() => {
    mockGetSession.mockReset();
    mockSignInWithOAuth.mockReset();
    mockLinkIdentity.mockReset();
    sessionStorage.clear();
  });

  it('no session + google → signInWithOAuth with the callback redirect and no scopes', async () => {
    mockGetSession.mockResolvedValueOnce(noSession());
    mockSignInWithOAuth.mockResolvedValueOnce({
      data: { provider: 'google', url: 'https://accounts.google.com/x' },
      error: null,
    });

    const result = await signInWithOAuthProvider('google', REDIRECT);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.mode).toBe('sign-in');
    expect(mockSignInWithOAuth).toHaveBeenCalledWith({
      provider: 'google',
      options: { redirectTo: REDIRECT, scopes: undefined },
    });
    expect(mockLinkIdentity).not.toHaveBeenCalled();
  });

  it('direct azure call is rejected before reading a session or starting OAuth', async () => {
    const result = await signInWithOAuthProvider('azure', REDIRECT);

    expect(result).toEqual({
      ok: false,
      reason: 'feature-disabled',
      message: 'Microsoft school sign-in is not available in this release.',
    });
    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockSignInWithOAuth).not.toHaveBeenCalled();
    expect(mockLinkIdentity).not.toHaveBeenCalled();
  });

  it('permanent session → plain signInWithOAuth (sign-in, not link)', async () => {
    mockGetSession.mockResolvedValueOnce(permanentSession());
    mockSignInWithOAuth.mockResolvedValueOnce({ data: {}, error: null });

    const result = await signInWithOAuthProvider('google', REDIRECT);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.mode).toBe('sign-in');
    expect(mockSignInWithOAuth).toHaveBeenCalled();
    expect(mockLinkIdentity).not.toHaveBeenCalled();
  });

  it('anon session + google → linkIdentity (preserves auth.uid), NOT signInWithOAuth', async () => {
    mockGetSession.mockResolvedValueOnce(anonSession());
    mockLinkIdentity.mockResolvedValueOnce({
      data: { provider: 'google', url: 'https://accounts.google.com/x' },
      error: null,
    });

    const result = await signInWithOAuthProvider('google', REDIRECT);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.mode).toBe('link-anon');
    expect(mockLinkIdentity).toHaveBeenCalledWith({
      provider: 'google',
      options: { redirectTo: REDIRECT, scopes: undefined },
    });
    expect(mockSignInWithOAuth).not.toHaveBeenCalled();
  });

  it('direct azure call cannot link an anonymous session', async () => {
    const result = await signInWithOAuthProvider('azure', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('feature-disabled');
    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockLinkIdentity).not.toHaveBeenCalled();
    expect(mockSignInWithOAuth).not.toHaveBeenCalled();
  });

  it('anon session → stashes the provider for the callback conflict fallback', async () => {
    mockGetSession.mockResolvedValueOnce(anonSession());
    mockLinkIdentity.mockResolvedValueOnce({ data: {}, error: null });

    await signInWithOAuthProvider('google', REDIRECT);

    expect(sessionStorage.getItem('ofe_oauth_link_provider')).toBe('google');
  });

  it('maps linkIdentity error code identity_already_exists → identity-taken', async () => {
    mockGetSession.mockResolvedValueOnce(anonSession());
    mockLinkIdentity.mockResolvedValueOnce({
      data: { provider: 'google', url: null },
      error: {
        message: 'Identity is already linked to another user',
        code: 'identity_already_exists',
      },
    });

    const result = await signInWithOAuthProvider('google', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('identity-taken');
    expect(mockSignInWithOAuth).not.toHaveBeenCalled();
  });

  it('maps an "already linked" message → identity-taken even without a code', async () => {
    mockGetSession.mockResolvedValueOnce(anonSession());
    mockLinkIdentity.mockResolvedValueOnce({
      data: { provider: 'google', url: null },
      error: { message: 'Identity is already linked' },
    });

    const result = await signInWithOAuthProvider('google', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('identity-taken');
  });

  it('clears the provider stash when linkIdentity errors before the redirect', async () => {
    // The redirect never happened, so a surviving stash would leak into a
    // later flow's callback and misroute a non-OAuth email_exists conflict.
    mockGetSession.mockResolvedValueOnce(anonSession());
    mockLinkIdentity.mockResolvedValueOnce({
      data: { provider: 'google', url: null },
      error: { message: 'Identity is already linked', code: 'identity_already_exists' },
    });

    await signInWithOAuthProvider('google', REDIRECT);

    expect(sessionStorage.getItem('ofe_oauth_link_provider')).toBeNull();
  });

  it('maps provider errors through mapAuthError', async () => {
    mockGetSession.mockResolvedValueOnce(noSession());
    mockSignInWithOAuth.mockResolvedValueOnce({
      data: null,
      error: { message: 'For security purposes, too many requests' },
    });

    const result = await signInWithOAuthProvider('google', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('rate-limited');
  });
});

// OAuth twin of signInExistingEmail: after an identity_already_exists
// conflict, the recovery action must be a PLAIN signInWithOAuth — never
// another linkIdentity attempt (which would just conflict again), and
// never a session read (the anon session must not re-route us).
describe('signInExistingOAuth — forced sign-in-to-existing path', () => {
  beforeEach(() => {
    mockGetSession.mockReset();
    mockSignInWithOAuth.mockReset();
    mockLinkIdentity.mockReset();
  });

  it('always calls signInWithOAuth — never linkIdentity, never reads session', async () => {
    mockSignInWithOAuth.mockResolvedValueOnce({ data: {}, error: null });

    const result = await signInExistingOAuth('google', REDIRECT);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.mode).toBe('sign-in');
    expect(mockSignInWithOAuth).toHaveBeenCalledWith({
      provider: 'google',
      options: { redirectTo: REDIRECT, scopes: undefined },
    });
    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockLinkIdentity).not.toHaveBeenCalled();
  });

  it('direct azure recovery call is rejected before OAuth', async () => {
    const result = await signInExistingOAuth('azure', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('feature-disabled');
    expect(mockSignInWithOAuth).not.toHaveBeenCalled();
    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockLinkIdentity).not.toHaveBeenCalled();
  });

  it('maps errors through mapAuthError', async () => {
    mockSignInWithOAuth.mockResolvedValueOnce({
      data: null,
      error: { message: 'For security purposes, too many requests' },
    });

    const result = await signInExistingOAuth('google', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('rate-limited');
  });
});

// What supabase-js does with this browser's session when the logout request
// itself fails. Pinned against the real library, with only the network faked,
// because signOutOfAccount's verdict rests on it: on these failures the
// account session is still stored, so a re-anon afterwards reads the old
// account back instead of creating a guest.
describe('supabase-js 2.105.4 signOut({ scope: "local" }) against a failing logout request', () => {
  const STORAGE_KEY = 'ofe_auth_signout_characterization';

  async function signOutAgainst(logout: () => Promise<Response>) {
    const { createClient: realCreateClient } = await vi.importActual<typeof import('@supabase/supabase-js')>('@supabase/supabase-js');
    const session = {
      access_token: 'header.payload.signature',
      refresh_token: 'refresh-token',
      token_type: 'bearer',
      expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: 'perm-uid', aud: 'authenticated', role: 'authenticated', email: 'eric@illinois.edu', is_anonymous: false },
    };
    const store = new Map<string, string>([[STORAGE_KEY, JSON.stringify(session)]]);
    const requests: string[] = [];
    vi.stubGlobal('BroadcastChannel', undefined);
    try {
      const client = realCreateClient('https://test.supabase.co', 'test-anon-key', {
        auth: {
          storageKey: STORAGE_KEY,
          storage: {
            getItem: (key: string) => store.get(key) ?? null,
            setItem: (key: string, value: string) => { store.set(key, value); },
            removeItem: (key: string) => { store.delete(key); },
          },
          persistSession: true,
          autoRefreshToken: false,
          detectSessionInUrl: false,
        },
        global: {
          fetch: async (input: RequestInfo | URL) => {
            const url = String(input);
            requests.push(url);
            if (url.includes('/auth/v1/logout')) return logout();
            throw new Error(`unexpected request ${url}`);
          },
        },
      });
      const { error } = await client.auth.signOut({ scope: 'local' });
      const { data } = await client.auth.getSession();
      return { error, sessionUser: data.session?.user.id ?? null, stored: store.has(STORAGE_KEY), requests };
    } finally {
      vi.unstubAllGlobals();
    }
  }

  const json = (status: number) => () => Promise.resolve(new Response(JSON.stringify({ msg: `status ${status}` }), {
    status,
    headers: { 'content-type': 'application/json' },
  }));

  it.each([
    ['a network failure', () => Promise.reject(new TypeError('Failed to fetch')), 'AuthRetryableFetchError', 0],
    ['a 503', json(503), 'AuthRetryableFetchError', 503],
    ['a 500', json(500), 'AuthApiError', 500],
  ])('keeps the account session in storage on %s and returns the error', async (_name, logout, errorName, status) => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const out = await signOutAgainst(logout);
    expect(out.requests).toEqual(['https://test.supabase.co/auth/v1/logout?scope=local']);
    expect(out.error).toMatchObject({ name: errorName, status });
    expect(out.stored).toBe(true);
    expect(out.sessionUser).toBe('perm-uid');
  });

  it.each([401, 403, 404])('drops the session and returns no error on a %s (the server no longer has it)', async (status) => {
    const out = await signOutAgainst(json(status));
    expect(out.error).toBeNull();
    expect(out.stored).toBe(false);
    expect(out.sessionUser).toBeNull();
  });
});

describe('signOutOfAccount', () => {
  beforeEach(() => {
    mockGetSession.mockReset();
    mockSignOut.mockReset();
    mockSignInAnonymously.mockReset().mockResolvedValue({
      data: { user: { id: 'new-anon-uid' } },
      error: null,
    });
    localStorage.clear();
    sessionStorage.clear();
  });

  function stashPendingFlows() {
    localStorage.setItem(
      STORAGE_KEYS.MERGE_GRANT,
      JSON.stringify({ token: 'grant-token', minted_at: Date.now() }),
    );
    sessionStorage.setItem(STORAGE_KEYS.OAUTH_LINK_PROVIDER, 'google');
  }

  it('signs out with scope:"local" — other devices keep their sessions — then re-anons', async () => {
    mockSignOut.mockResolvedValueOnce({ error: null });
    mockGetSession.mockResolvedValueOnce(noSession());

    await expect(signOutOfAccount()).resolves.toBe(true);

    expect(mockSignOut).toHaveBeenCalledWith({ scope: 'local' });
    expect(mockSignInAnonymously).toHaveBeenCalledTimes(1);
  });

  // The failures supabase-js answers by keeping the account session stored
  // (pinned above). A re-anon after one of them reads that session straight
  // back, so "signed out" would be reported for an account still here.
  it.each([
    ['a network failure', { name: 'AuthRetryableFetchError', status: 0, message: 'Failed to fetch' }],
    ['a 503', { name: 'AuthRetryableFetchError', status: 503, message: 'Service Unavailable' }],
    ['a 500', { name: 'AuthApiError', status: 500, message: 'Internal Server Error' }],
  ])('reports failure on %s, makes no guest session and keeps the pending sign-in flows', async (_name, error) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    stashPendingFlows();
    mockSignOut.mockResolvedValueOnce({ error });
    mockGetSession.mockResolvedValue(permanentSession());

    await expect(signOutOfAccount()).resolves.toBe(false);

    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockSignInAnonymously).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).not.toBeNull();
    expect(sessionStorage.getItem(STORAGE_KEYS.OAUTH_LINK_PROVIDER)).toBe('google');
  });

  it('reports failure when the sign-out call itself throws, touching nothing else', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    stashPendingFlows();
    mockSignOut.mockRejectedValueOnce(new Error('Acquiring an exclusive Navigator LockManager lock timed out'));

    await expect(signOutOfAccount()).resolves.toBe(false);

    expect(mockSignInAnonymously).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).not.toBeNull();
    expect(sessionStorage.getItem(STORAGE_KEYS.OAUTH_LINK_PROVIDER)).toBe('google');
  });

  it.each([401, 403, 404])('treats a %s as signed out: the server no longer has the session', async (status) => {
    stashPendingFlows();
    mockSignOut.mockResolvedValueOnce({ error: { name: 'AuthApiError', status, message: 'invalid JWT' } });
    mockGetSession.mockResolvedValueOnce(noSession());

    await expect(signOutOfAccount()).resolves.toBe(true);

    expect(mockSignInAnonymously).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
    expect(sessionStorage.getItem(STORAGE_KEYS.OAUTH_LINK_PROVIDER)).toBeNull();
  });

  it('drops a stashed Flow B merge grant — signing out abandons the pending merge (W14)', async () => {
    localStorage.setItem(
      STORAGE_KEYS.MERGE_GRANT,
      JSON.stringify({ token: 'grant-token', minted_at: Date.now() }),
    );
    mockSignOut.mockResolvedValueOnce({ error: null });
    mockGetSession.mockResolvedValueOnce(noSession());

    await signOutOfAccount();

    // If the stash survived, it would defer identity-owner's user-scoped
    // clear for the NEXT identity on this browser (up to the 60-min expiry).
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });
});
