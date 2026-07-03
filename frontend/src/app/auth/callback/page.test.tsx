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
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGetAuthState = vi.fn();
const mockGetDataInventory = vi.fn();
const mockRedeemMerge = vi.fn();
const mockExchangeCodeForSession = vi.fn();
const mockVerifyOtp = vi.fn();
const mockOAuthExisting = vi.fn();
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

import CallbackPage from './page';

afterEach(() => {
  cleanup();
});

beforeEach(() => {
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
  mockRedeemMerge.mockResolvedValue(null);
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
      merged: true,
      favorites: 2,
      interactions: 1,
      savedSearches: 0,
      attachmentsNotMoved: 1,
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
    mockRedeemMerge.mockResolvedValue(null);

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText('auth.callback.successTitle')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('callback-merge-line')).not.toBeInTheDocument();
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
