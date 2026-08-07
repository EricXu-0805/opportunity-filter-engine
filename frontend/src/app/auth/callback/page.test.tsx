/*
 * /auth/callback tests — focused on R68's idempotency guard.
 *
 * The PKCE code_verifier is single-use: a successful first
 * exchangeCodeForSession() consumes and clears it. Re-landing on
 * /auth/callback with the same `?code=` (reload, back/forward, re-click
 * email link) then fires the wrong error: "PKCE code verifier not found
 * in storage" — even though the user IS signed in. These tests verify
 * that the page short-circuits to success on a permanent preflight
 * session and never even calls exchangeCodeForSession in that case.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGetAuthState = vi.fn();
const mockGetDataInventory = vi.fn();
const mockRedeemMerge = vi.fn();
const mockExchangeCodeForSession = vi.fn();
const mockVerifyOtp = vi.fn();
const mockOAuthExisting = vi.fn();
const mockHydrateProfile = vi.fn();
const replaceSpy = vi.fn();
const searchRef = { current: '?code=stub-code' };

vi.mock('@/lib/supabase', () => ({
  getAuthState: () => mockGetAuthState(),
  getDataInventory: () => mockGetDataInventory(),
  redeemPendingMerge: () => mockRedeemMerge(),
  signInExistingOAuth: (provider: string, redirect: string) => mockOAuthExisting(provider, redirect),
  supabase: {
    auth: {
      exchangeCodeForSession: (code: string) => mockExchangeCodeForSession(code),
      verifyOtp: (opts: { token_hash: string; type: string }) => mockVerifyOtp(opts),
    },
  },
}));

// Mocked (not the real profile-sync module) purely so the
// syncLocalIdentityOwner-boolean test below can OBSERVE whether it was
// called; every other test's default resolved value keeps prior assertions
// about the claim/clear decision (which is syncLocalIdentityOwner's job,
// not hydrateProfile's) unaffected.
vi.mock('@/lib/profile-sync', () => ({
  hydrateProfile: () => mockHydrateProfile(),
}));

// Cache URLSearchParams + stable t so every render returns the SAME
// reference. Otherwise `useEffect([params, t])` re-fires on every
// render, exhausting `mockResolvedValueOnce` queues and surfacing
// `Cannot read properties of undefined` after the queue runs out.
let cachedParams: URLSearchParams | null = null;
let cachedParamsKey: string | null = null;
const stableT = (key: string, vars?: Record<string, string | number>) => {
  if (vars && Object.keys(vars).length) {
    return `${key}:${Object.values(vars).join(',')}`;
  }
  return key;
};
const stableTApi = { t: stableT };

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: replaceSpy, refresh: vi.fn(), push: vi.fn() }),
  useSearchParams: () => {
    if (cachedParamsKey !== searchRef.current) {
      cachedParams = new URLSearchParams(searchRef.current);
      cachedParamsKey = searchRef.current;
    }
    return cachedParams!;
  },
}));

vi.mock('@/i18n/client', () => ({
  useT: () => stableTApi,
}));

import { STORAGE_KEYS } from '@/lib/storage-keys';
import { advanceOwnerEpoch, getLocalOwnerState, syncLocalIdentityOwner } from '@/lib/identity-owner';

import CallbackPage from './page';
/** The marker is a versioned record now — {v:2, uid, generation, phase} — so
 *  these assert who owns the browser, not the encoding. */
function markerUid(): string | null {
  const raw = localStorage.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER);
  if (!raw) return null;
  return raw.startsWith('{') ? (JSON.parse(raw) as { uid: string }).uid : raw;
}


afterEach(async () => {
  cleanup();
});

beforeEach(async () => {
  // resetAllMocks (not clearAllMocks) wipes BOTH calls and any
  // mockResolvedValueOnce queue + mockResolvedValue implementations
  // from prior tests. Without this, a default `mockResolvedValue`
  // set in one test leaks into the next test's queue fallback.
  vi.resetAllMocks();
  searchRef.current = '?code=stub-code';
  cachedParams = null;
  cachedParamsKey = null;
  sessionStorage.clear();
  mockGetDataInventory.mockResolvedValue(null);
  mockRedeemMerge.mockResolvedValue({ kind: 'none' });
  mockHydrateProfile.mockResolvedValue(undefined);
  // identity-owner's module-level owner state is a singleton shared across
  // every test in this file (no per-test module reset) — force it back to
  // a known null baseline so a prior test's real uid transition can't leak
  // into the next test's own advanceOwnerEpochIfUnchanged CAS.
  advanceOwnerEpoch(null);
});

describe('CallbackPage — R68 idempotency guard', () => {
  it('skips exchange when already signed in as a permanent user (reload after success)', async () => {
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'p' } },
      user: { id: 'p' },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
    });
    expect(mockExchangeCodeForSession).not.toHaveBeenCalled();
    expect(mockVerifyOtp).not.toHaveBeenCalled();
  });

  it('still performs the exchange when only an anonymous session is present', async () => {
    mockGetAuthState
      // preflight
      .mockResolvedValueOnce({
        session: { user: { id: 'a' } },
        user: { id: 'a' },
        isAnonymous: true,
        email: null,
      })
      // post-exchange auth state read
      .mockResolvedValueOnce({
        session: { user: { id: 'p' } },
        user: { id: 'p' },
        isAnonymous: false,
        email: 'eric@illinois.edu',
      });
    mockExchangeCodeForSession.mockResolvedValue({ error: null });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(mockExchangeCodeForSession).toHaveBeenCalledWith('stub-code');
    });
    await waitFor(() => {
      expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
    });
  });

  it('recovers when the exchange returns a stale-verifier error but the session is now permanent', async () => {
    mockGetAuthState
      // preflight: still anon (no race yet)
      .mockResolvedValueOnce({
        session: { user: { id: 'a' } },
        user: { id: 'a' },
        isAnonymous: true,
        email: null,
      })
      // post-exchange recovery check: an out-of-band onAuthStateChange
      // upgraded the session between preflight and exchange.
      .mockResolvedValueOnce({
        session: { user: { id: 'p' } },
        user: { id: 'p' },
        isAnonymous: false,
        email: 'eric@illinois.edu',
      });
    mockExchangeCodeForSession.mockResolvedValue({
      error: { message: 'PKCE code verifier not found in storage' },
    });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
    });
    // We did try the exchange — only the post-check rescued us.
    expect(mockExchangeCodeForSession).toHaveBeenCalled();
  });

  it('renders the Flow B merge line when a pending merge moved data', async () => {
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'p' } },
      user: { id: 'p' },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });
    mockRedeemMerge.mockResolvedValue({
      kind: 'success',
      summary: {
        merged: true,
        favorites: 2,
        interactions: 1,
        savedSearches: 0,
        attachmentsNotMoved: 1,
      },
    });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByTestId('callback-merge-line')).toBeInTheDocument();
    });
    // prefix + the two non-zero counts + the attachments caveat
    expect(screen.getByTestId('callback-merge-line').textContent).toContain('auth.callback.mergePrefix');
    expect(screen.getByTestId('callback-merge-line').textContent).toContain('auth.callback.invFavorites:2');
    expect(screen.getByTestId('callback-merge-line').textContent).toContain('auth.callback.mergeAttachmentsCaveat:1');
  });

  it('shows NO merge line when there was no pending merge', async () => {
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'p' } },
      user: { id: 'p' },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });
    mockRedeemMerge.mockResolvedValue({ kind: 'none' });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('callback-merge-line')).not.toBeInTheDocument();
  });

  // W6 wiring: the callback page calls the REAL identity-owner module (only
  // @/lib/supabase is mocked here), so these two pin the claim/clear decision
  // it makes after redeeming (or failing to redeem) a Flow B merge grant.
  it('claims the guest\'s local data for the new uid after a successful merge', async () => {
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, 'anon-uid');
    localStorage.setItem(STORAGE_KEYS.CUSTOM_IMPORTS, '[{"id":"custom-1"}]');
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'p' } },
      user: { id: 'p' },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });
    mockRedeemMerge.mockResolvedValue({
      kind: 'success',
      summary: {
        merged: true,
        favorites: 0,
        interactions: 0,
        savedSearches: 0,
        attachmentsNotMoved: 0,
      },
    });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
    });
    expect(markerUid()).toBe('p');
    expect(localStorage.getItem(STORAGE_KEYS.CUSTOM_IMPORTS)).toBe('[{"id":"custom-1"}]');
  });

  it('clears the previous identity\'s local data on a plain (non-merge) sign-in', async () => {
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, 'anon-uid');
    localStorage.setItem(STORAGE_KEYS.CUSTOM_IMPORTS, '[{"id":"custom-1"}]');
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'p' } },
      user: { id: 'p' },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });
    mockRedeemMerge.mockResolvedValue({ kind: 'none' });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
    });
    expect(markerUid()).toBe('p');
    expect(localStorage.getItem(STORAGE_KEYS.CUSTOM_IMPORTS)).toBeNull();
  });

  // B3-B7 hardening: a redemption outcome that could not be CONFIRMED
  // (network drop mid-RPC) must never be silently treated the same as
  // "nothing to merge" — the old code collapsed both into `null` and
  // always showed success.
  it('shows merge-failed (never a silent success) when redemption could not be confirmed, and Retry re-attempts with a fresh identity read', async () => {
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'p' } },
      user: { id: 'p' },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });
    mockRedeemMerge.mockResolvedValueOnce({ kind: 'failed' });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.mergeFailedTitle')).toBeInTheDocument();
    });
    expect(screen.queryByText('auth.callback.successTitle')).not.toBeInTheDocument();

    mockRedeemMerge.mockResolvedValueOnce({ kind: 'none' });
    fireEvent.click(screen.getByTestId('callback-merge-retry'));

    await waitFor(() => {
      expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
    });
    expect(mockRedeemMerge).toHaveBeenCalledTimes(2);
  });

  it('retrying after the user got signed out in between shows the generic error, not another silent success', async () => {
    mockGetAuthState.mockResolvedValueOnce({
      session: { user: { id: 'p' } },
      user: { id: 'p' },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });
    mockRedeemMerge.mockResolvedValueOnce({ kind: 'failed' });

    render(<CallbackPage />);
    await waitFor(() => {
      expect(screen.getByText('auth.callback.mergeFailedTitle')).toBeInTheDocument();
    });

    mockGetAuthState.mockResolvedValueOnce({
      session: null, user: null, isAnonymous: false, email: null,
    });
    fireEvent.click(screen.getByTestId('callback-merge-retry'));

    await waitFor(() => {
      expect(screen.getByText('auth.callback.errTitle')).toBeInTheDocument();
    });
    expect(screen.queryByText('auth.callback.successTitle')).not.toBeInTheDocument();
    // No second redeem attempt without a real identity to attach it to.
    expect(mockRedeemMerge).toHaveBeenCalledTimes(1);
  });

  it('does not call hydrateProfile when syncLocalIdentityOwner cannot verify local ownership after a merge, even though the account itself genuinely signed in', async () => {
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'p' } },
      user: { id: 'p' },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });
    mockRedeemMerge.mockResolvedValue({
      kind: 'success',
      summary: { merged: true, favorites: 1, interactions: 0, savedSearches: 0, attachmentsNotMoved: 0 },
    });

    // Force syncLocalIdentityOwner to fail closed: the marker write can
    // never be confirmed (setItem throws), same fail-closed contract every
    // other write-verification in this session relies on.
    const original = window.localStorage;
    const store = new Map<string, string>();
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: () => { throw new Error('storage broken'); },
        removeItem: (k: string) => { store.delete(k); },
        clear: () => store.clear(),
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        get length() { return store.size; },
      },
      configurable: true,
    });
    try {
      render(<CallbackPage />);
      // The ACCOUNT sign-in genuinely succeeded — the success screen still
      // shows. Only the local-cache claim is degraded.
      await waitFor(() => {
        expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
      });
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
    expect(mockHydrateProfile).not.toHaveBeenCalled();
  });

  it('a live identity event racing while the merge RPC is in flight is NOT clobbered by finishSignedIn\'s own stale uid resolution', async () => {
    let resolveRedeem!: (v: { kind: 'none' }) => void;
    mockRedeemMerge.mockReturnValueOnce(new Promise((r) => { resolveRedeem = r; }));
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'p' } },
      user: { id: 'p' },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });

    render(<CallbackPage />);
    await waitFor(() => expect(mockRedeemMerge).toHaveBeenCalled());

    // A live event elsewhere advances the REAL shared owner to a DIFFERENT
    // uid while this page's own redeem RPC is still pending.
    await act(async () => {
      advanceOwnerEpoch('live-other-uid');
      await syncLocalIdentityOwner('live-other-uid');
    });

    resolveRedeem({ kind: 'none' });
    await waitFor(() => {
      expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
    });

    // finishSignedIn's own stale resolution ('p') must NOT have rolled the
    // shared owner back over the live event's — 'live-other-uid' is still
    // the confirmed, ready owner.
    expect(getLocalOwnerState()).toEqual({ uid: 'live-other-uid', status: 'ready' });
  });

  it('shows the error page when exchange fails AND no session is established', async () => {
    mockGetAuthState
      .mockResolvedValueOnce({
        session: null,
        user: null,
        isAnonymous: false,
        email: null,
      })
      .mockResolvedValueOnce({
        session: null,
        user: null,
        isAnonymous: false,
        email: null,
      });
    mockExchangeCodeForSession.mockResolvedValue({
      error: { message: 'PKCE code verifier not found in storage' },
    });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.errTitle')).toBeInTheDocument();
    });
    expect(screen.getByText('PKCE code verifier not found in storage')).toBeInTheDocument();
  });

  it('takes the verifyOtp branch when token_hash + type are present (default email template)', async () => {
    searchRef.current = '?token_hash=abcdef&type=magiclink';
    mockGetAuthState
      .mockResolvedValueOnce({
        session: null,
        user: null,
        isAnonymous: false,
        email: null,
      })
      .mockResolvedValueOnce({
        session: { user: { id: 'p' } },
        user: { id: 'p' },
        isAnonymous: false,
        email: 'eric@illinois.edu',
      });
    mockVerifyOtp.mockResolvedValue({ error: null });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(mockVerifyOtp).toHaveBeenCalledWith({
        token_hash: 'abcdef',
        type: 'magiclink',
      });
    });
    await waitFor(() => {
      expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
    });
    expect(mockExchangeCodeForSession).not.toHaveBeenCalled();
  });

  it('shows the missing-code error when neither shape is present in the URL', async () => {
    searchRef.current = '';
    mockGetAuthState.mockResolvedValueOnce({
      session: null,
      user: null,
      isAnonymous: false,
      email: null,
    });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.errTitle')).toBeInTheDocument();
    });
    expect(screen.getByText('auth.callback.errMissingCode')).toBeInTheDocument();
  });
});

// linkIdentity conflict: GoTrue detects "this OAuth identity already
// belongs to ANOTHER user" only after the provider consent, so the
// failure lands on /auth/callback as error query params with
// error_code=identity_already_exists — not as a rejected linkIdentity()
// call in the modal. The callback must show the dedicated recovery
// screen (sign in to the existing account via plain OAuth) instead of
// the generic magic-link error copy.
describe('CallbackPage — linkIdentity conflict (identity_already_exists)', () => {
  const CONFLICT_QS =
    '?error=server_error&error_code=identity_already_exists' +
    '&error_description=Identity+is+already+linked+to+another+user';

  it('shows the identity-conflict screen instead of the generic error', async () => {
    searchRef.current = CONFLICT_QS;

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.identityTakenTitle')).toBeInTheDocument();
    });
    expect(screen.queryByText('auth.callback.errTitle')).toBeNull();
    expect(mockExchangeCodeForSession).not.toHaveBeenCalled();
    expect(mockVerifyOtp).not.toHaveBeenCalled();
  });

  it('offers plain sign-in with the provider stashed before the link redirect', async () => {
    sessionStorage.setItem('ofe_oauth_link_provider', 'google');
    searchRef.current = CONFLICT_QS;
    mockOAuthExisting.mockResolvedValue({ ok: true, mode: 'sign-in', message: 'redirecting' });

    render(<CallbackPage />);

    const btn = await screen.findByTestId('callback-oauth-signin-existing');
    fireEvent.click(btn);
    await waitFor(() => {
      expect(mockOAuthExisting).toHaveBeenCalledWith('google', 'http://localhost:3000/auth/callback');
    });
  });

  it('hides the sign-in CTA when no provider was stashed (still shows the explanation)', async () => {
    searchRef.current = CONFLICT_QS;

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.identityTakenTitle')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('callback-oauth-signin-existing')).toBeNull();
  });

  it('discards a stale azure stash and cannot offer Microsoft OAuth recovery', async () => {
    sessionStorage.setItem('ofe_oauth_link_provider', 'azure');
    searchRef.current = CONFLICT_QS;

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.identityTakenTitle')).toBeInTheDocument();
    });
    expect(sessionStorage.getItem('ofe_oauth_link_provider')).toBeNull();
    expect(screen.queryByTestId('callback-oauth-signin-existing')).toBeNull();
    expect(mockOAuthExisting).not.toHaveBeenCalled();
  });

  it('ignores a hand-written provider=azure callback parameter', async () => {
    searchRef.current = `${CONFLICT_QS}&provider=azure`;

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.identityTakenTitle')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('callback-oauth-signin-existing')).toBeNull();
    expect(mockOAuthExisting).not.toHaveBeenCalled();
  });

  it('keeps the generic error screen for non-conflict OAuth errors (behavior pin)', async () => {
    searchRef.current = '?error=access_denied&error_description=User+denied+access';

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.errTitle')).toBeInTheDocument();
    });
    expect(screen.getByText('User denied access')).toBeInTheDocument();
    expect(screen.queryByTestId('callback-oauth-signin-existing')).toBeNull();
  });
});

// email_exists conflict: a guest's anonymous session tries to link an
// OAuth identity whose EMAIL already belongs to an existing email-based
// account (GoTrue rejects with error_code=email_exists, "A user with
// this email address has already been registered"). Same recovery as
// identity_already_exists — but only when an OAuth provider was stashed
// before the redirect, because email_exists can also arise outside the
// OAuth flow, where the identity-conflict copy would mislead.
describe('CallbackPage — linkIdentity conflict (email_exists)', () => {
  const EMAIL_EXISTS_QS =
    '?error=invalid_request&error_code=email_exists' +
    '&error_description=A+user+with+this+email+address+has+already+been+registered';

  it('shows the identity-conflict screen with the sign-in CTA when a provider was stashed', async () => {
    sessionStorage.setItem('ofe_oauth_link_provider', 'google');
    searchRef.current = EMAIL_EXISTS_QS;
    mockOAuthExisting.mockResolvedValue({ ok: true, mode: 'sign-in', message: 'redirecting' });

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.identityTakenTitle')).toBeInTheDocument();
    });
    expect(screen.queryByText('auth.callback.errTitle')).toBeNull();

    const btn = screen.getByTestId('callback-oauth-signin-existing');
    fireEvent.click(btn);
    await waitFor(() => {
      expect(mockOAuthExisting).toHaveBeenCalledWith('google', 'http://localhost:3000/auth/callback');
    });
  });

  it('keeps the generic error screen when no provider was stashed (non-OAuth email_exists)', async () => {
    searchRef.current = EMAIL_EXISTS_QS;

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.errTitle')).toBeInTheDocument();
    });
    expect(screen.queryByText('auth.callback.identityTakenTitle')).toBeNull();
    expect(screen.queryByTestId('callback-oauth-signin-existing')).toBeNull();
  });
});
