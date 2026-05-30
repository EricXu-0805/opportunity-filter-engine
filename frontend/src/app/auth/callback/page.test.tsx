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
import { cleanup, render, screen, waitFor } from '@testing-library/react';

const mockGetAuthState = vi.fn();
const mockGetDataInventory = vi.fn();
const mockExchangeCodeForSession = vi.fn();
const mockVerifyOtp = vi.fn();
const replaceSpy = vi.fn();
const searchRef = { current: '?code=stub-code' };

vi.mock('@/lib/supabase', () => ({
  getAuthState: () => mockGetAuthState(),
  getDataInventory: () => mockGetDataInventory(),
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
  mockGetDataInventory.mockResolvedValue(null);
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
