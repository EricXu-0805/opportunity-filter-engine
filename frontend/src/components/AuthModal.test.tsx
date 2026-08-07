/*
 * AuthModal phase machine tests.
 *
 * We don't test the full signInOrLinkEmail branching here — that lives
 * in src/lib/supabase-auth.test.ts. These tests focus on the visual
 * phase transitions (signin → sent on successful submit, account →
 * signout-confirm on Sign-out click) and the gated rendering (modal
 * doesn't render at all when open=false).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockSignIn = vi.fn();
const mockSignInExisting = vi.fn();
const mockSignOut = vi.fn();
const mockGetAuthState = vi.fn();
const mockOnAuthChange = vi.fn((_cb: (s: unknown) => void) => () => {});
const mockOAuth = vi.fn();
const mockOAuthExisting = vi.fn();

vi.mock('@/lib/supabase', () => ({
  getAuthState: () => mockGetAuthState(),
  onAuthChange: (cb: (s: unknown) => void) => mockOnAuthChange(cb),
  signInOrLinkEmail: (email: string, redirect: string) => mockSignIn(email, redirect),
  signInExistingEmail: (email: string, redirect: string) => mockSignInExisting(email, redirect),
  signInWithOAuthProvider: (provider: string, redirect: string) => mockOAuth(provider, redirect),
  signInExistingOAuth: (provider: string, redirect: string) => mockOAuthExisting(provider, redirect),
  signOutOfAccount: () => mockSignOut(),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    locale: 'en',
    t: (key: string, vars?: Record<string, string>) => {
      if (vars?.email) return `${key}:${vars.email}`;
      return key;
    },
  }),
}));

// Closure-bound auth modal context state. Each test resets via
// vi.clearAllMocks + sets initial phase via the wrapper.
let modalState: { open: boolean; phase: string } = { open: true, phase: 'auto' };
const setPhaseMock = vi.fn((p: string) => { modalState = { ...modalState, phase: p }; });
const closeModalMock = vi.fn(() => { modalState = { ...modalState, open: false }; });

vi.mock('@/lib/auth-modal-context', () => ({
  useAuthModal: () => ({
    open: modalState.open,
    phase: modalState.phase,
    reason: null,
    openModal: vi.fn(),
    closeModal: closeModalMock,
    setPhase: setPhaseMock,
  }),
}));

import AuthModal from './AuthModal';

const ANON: unknown = {
  session: { user: { id: 'a', is_anonymous: true } },
  user: { id: 'a', is_anonymous: true },
  isAnonymous: true,
  email: null,
};

const PERMANENT: unknown = {
  session: { user: { id: 'p', is_anonymous: false, email: 'eric@illinois.edu' } },
  user: { id: 'p', is_anonymous: false },
  isAnonymous: false,
  email: 'eric@illinois.edu',
};

beforeEach(() => {
  modalState = { open: true, phase: 'auto' };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe('AuthModal — gating', () => {
  it('renders nothing when the provider says open=false', async () => {
    modalState = { open: false, phase: 'auto' };
    mockGetAuthState.mockResolvedValue(ANON);
    const { container } = render(<AuthModal />);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });
});

describe('AuthModal — auto phase resolution', () => {
  it('resolves auto → signin when user is anonymous', async () => {
    mockGetAuthState.mockResolvedValue(ANON);
    render(<AuthModal />);
    await waitFor(() => {
      expect(screen.getByText('auth.modal.signin.headline')).toBeInTheDocument();
    });
  });

  it('resolves auto → account when user is permanent', async () => {
    mockGetAuthState.mockResolvedValue(PERMANENT);
    render(<AuthModal />);
    await waitFor(() => {
      expect(screen.getByText('auth.modal.account.title')).toBeInTheDocument();
    });
  });
});

describe('AuthModal — signin phase', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue(ANON);
  });

  it('shows the form and a privacy line', async () => {
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    expect(screen.getByText('auth.modal.signin.trust')).toBeInTheDocument();
  });

  it('transitions to the sent phase on successful submit', async () => {
    mockSignIn.mockResolvedValue({ ok: true, mode: 'link-anon', message: 'check inbox' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    const input = screen.getByLabelText('auth.modal.signin.emailLabel') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => {
      expect(setPhaseMock).toHaveBeenCalledWith('sent');
    });
  });

  it('does NOT transition phase when sign-in returns ok:false', async () => {
    mockSignIn.mockResolvedValue({ ok: false, reason: 'email-taken', message: 'taken' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    const input = screen.getByLabelText('auth.modal.signin.emailLabel') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => {
      expect(mockSignIn).toHaveBeenCalled();
    });
    // setPhase should NOT have been called with 'sent'
    const sentCalls = setPhaseMock.mock.calls.filter(c => c[0] === 'sent');
    expect(sentCalls).toHaveLength(0);
  });

  // R67 problem #2: when the user types an already-registered email,
  // signInOrLinkEmail returns `email-taken`. The modal must render an
  // in-place "Sign in with this email instead" button (not a dead-end
  // text message), and clicking it must call signInExistingEmail and
  // transition to 'sent' on success.
  it('renders Sign-in-existing button when outcome.reason is email-taken', async () => {
    mockSignIn.mockResolvedValue({ ok: false, reason: 'email-taken', message: 'taken' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    const input = screen.getByLabelText('auth.modal.signin.emailLabel') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => {
      expect(screen.getByTestId('auth-modal-signin-existing')).toBeInTheDocument();
    });
  });

  it('does NOT render Sign-in-existing button for other error reasons', async () => {
    mockSignIn.mockResolvedValue({ ok: false, reason: 'rate-limited', message: 'wait' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    const input = screen.getByLabelText('auth.modal.signin.emailLabel') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => {
      expect(mockSignIn).toHaveBeenCalled();
    });
    expect(screen.queryByTestId('auth-modal-signin-existing')).toBeNull();
  });

  it('Sign-in-existing button calls signInExistingEmail and transitions to sent on ok', async () => {
    mockSignIn.mockResolvedValue({ ok: false, reason: 'email-taken', message: 'taken' });
    mockSignInExisting.mockResolvedValue({ ok: true, mode: 'sign-in', message: 'check inbox' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    const input = screen.getByLabelText('auth.modal.signin.emailLabel') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    const btn = await screen.findByTestId('auth-modal-signin-existing');
    btn.click();
    await waitFor(() => {
      expect(mockSignInExisting).toHaveBeenCalledWith(
        'eric@illinois.edu',
        expect.stringContaining('/auth/callback'),
      );
    });
    await waitFor(() => {
      expect(setPhaseMock).toHaveBeenCalledWith('sent');
    });
  });
});

describe('AuthModal — school detection chip', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue(ANON);
  });

  async function typeEmail(value: string) {
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    const input = screen.getByLabelText('auth.modal.signin.emailLabel');
    fireEvent.change(input, { target: { value } });
  }

  it('shows the known-school chip (name + auto-set line) for a mapped domain', async () => {
    await typeEmail('eric@illinois.edu');
    expect(screen.getByTestId('school-chip')).toBeInTheDocument();
    expect(screen.getByText('University of Illinois Urbana-Champaign')).toBeInTheDocument();
    expect(screen.getByText('auth.modal.chip.known')).toBeInTheDocument();
    expect(screen.queryByTestId('edu-chip')).toBeNull();
  });

  it('matches subdomains of a mapped domain (cs.berkeley.edu)', async () => {
    await typeEmail('oski@cs.berkeley.edu');
    expect(screen.getByTestId('school-chip')).toBeInTheDocument();
    expect(screen.getByText('University of California, Berkeley')).toBeInTheDocument();
  });

  it('shows the neutral student-email chip for an unmapped .edu domain', async () => {
    await typeEmail('x@somewhere.edu');
    expect(screen.getByTestId('edu-chip')).toBeInTheDocument();
    expect(screen.getByText('auth.modal.chip.edu.title')).toBeInTheDocument();
    expect(screen.queryByTestId('school-chip')).toBeNull();
  });

  it('shows no chip for a non-.edu email', async () => {
    await typeEmail('eric@gmail.com');
    expect(screen.queryByTestId('school-chip')).toBeNull();
    expect(screen.queryByTestId('edu-chip')).toBeNull();
  });

  it('swaps chips live as the domain changes', async () => {
    await typeEmail('eric@illinois.edu');
    const input = screen.getByLabelText('auth.modal.signin.emailLabel');
    fireEvent.change(input, { target: { value: 'eric@somewhere.edu' } });
    expect(screen.queryByTestId('school-chip')).toBeNull();
    expect(screen.getByTestId('edu-chip')).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'eric@gmail.com' } });
    expect(screen.queryByTestId('edu-chip')).toBeNull();
  });
});

describe('AuthModal — OAuth provider gating', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue(ANON);
  });

  it('renders no provider buttons (and no divider) when the env flag is absent', async () => {
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    expect(screen.queryByTestId('auth-provider-google')).toBeNull();
    expect(screen.queryByTestId('auth-provider-azure')).toBeNull();
    expect(screen.queryByText('auth.modal.divider')).toBeNull();
  });

  it('renders no provider buttons when the env flag is empty', async () => {
    vi.stubEnv('NEXT_PUBLIC_AUTH_PROVIDERS', '');
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    expect(screen.queryByTestId('auth-provider-google')).toBeNull();
    expect(screen.queryByTestId('auth-provider-azure')).toBeNull();
  });

  it('cannot expose Microsoft school auth through the env allowlist', async () => {
    vi.stubEnv('NEXT_PUBLIC_AUTH_PROVIDERS', 'google,azure');
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    expect(screen.getByTestId('auth-provider-google')).toBeInTheDocument();
    expect(screen.queryByTestId('auth-provider-azure')).toBeNull();
    expect(screen.getByText('auth.modal.divider')).toBeInTheDocument();
  });

  it('renders only Google with "google"', async () => {
    vi.stubEnv('NEXT_PUBLIC_AUTH_PROVIDERS', 'google');
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    expect(screen.getByTestId('auth-provider-google')).toBeInTheDocument();
    expect(screen.queryByTestId('auth-provider-azure')).toBeNull();
  });

  it('tolerates whitespace/case and ignores unknown provider names', async () => {
    vi.stubEnv('NEXT_PUBLIC_AUTH_PROVIDERS', ' Google , apple , AZURE ');
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    expect(screen.getByTestId('auth-provider-google')).toBeInTheDocument();
    expect(screen.queryByTestId('auth-provider-azure')).toBeNull();
  });
});

describe('AuthModal — OAuth click flow', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue(ANON);
    vi.stubEnv('NEXT_PUBLIC_AUTH_PROVIDERS', 'google,azure');
  });

  it('Google button calls signInWithOAuthProvider with the callback redirect', async () => {
    mockOAuth.mockResolvedValue({ ok: true, mode: 'sign-in', message: 'redirecting' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    fireEvent.click(screen.getByTestId('auth-provider-google'));
    await waitFor(() => {
      expect(mockOAuth).toHaveBeenCalledWith('google', 'http://localhost:3000/auth/callback');
    });
  });

  it('surfaces the error message and re-enables the form when OAuth fails', async () => {
    mockOAuth.mockResolvedValue({ ok: false, reason: 'unknown', message: 'oauth exploded' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    fireEvent.click(screen.getByTestId('auth-provider-google'));
    await waitFor(() => {
      expect(screen.getByText('oauth exploded')).toBeInTheDocument();
    });
    expect(screen.getByTestId('auth-provider-google')).not.toBeDisabled();
  });

  it('does not transition to the sent phase on OAuth success (browser navigates instead)', async () => {
    mockOAuth.mockResolvedValue({ ok: true, mode: 'sign-in', message: 'redirecting' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    fireEvent.click(screen.getByTestId('auth-provider-google'));
    await waitFor(() => expect(mockOAuth).toHaveBeenCalled());
    expect(setPhaseMock).not.toHaveBeenCalledWith('sent');
  });
});

// Identity conflict: the user's Google/Microsoft identity already
// belongs to ANOTHER account, so it can't be linked to the anon user.
// Mirrors the email-taken fallback: a clear i18n message + an in-place
// "sign in to that account instead" button that forces the plain
// signInWithOAuth path via signInExistingOAuth.
describe('AuthModal — OAuth identity-taken fallback', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue(ANON);
    vi.stubEnv('NEXT_PUBLIC_AUTH_PROVIDERS', 'google,azure');
  });

  it('renders the i18n conflict message + fallback button (not the raw lib message)', async () => {
    mockOAuth.mockResolvedValue({ ok: false, reason: 'identity-taken', message: 'raw lib message' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    fireEvent.click(screen.getByTestId('auth-provider-google'));
    await waitFor(() => {
      expect(screen.getByTestId('auth-modal-oauth-signin-existing')).toBeInTheDocument();
    });
    expect(screen.getByText('auth.modal.signin.identityTakenMsg')).toBeInTheDocument();
    expect(screen.queryByText('raw lib message')).toBeNull();
    // The email-taken button is a different recovery path — must not appear.
    expect(screen.queryByTestId('auth-modal-signin-existing')).toBeNull();
  });

  it('fallback button calls signInExistingOAuth with the same accepted provider that conflicted', async () => {
    mockOAuth.mockResolvedValue({ ok: false, reason: 'identity-taken', message: 'taken' });
    mockOAuthExisting.mockResolvedValue({ ok: true, mode: 'sign-in', message: 'redirecting' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    fireEvent.click(screen.getByTestId('auth-provider-google'));
    const btn = await screen.findByTestId('auth-modal-oauth-signin-existing');
    fireEvent.click(btn);
    await waitFor(() => {
      expect(mockOAuthExisting).toHaveBeenCalledWith('google', 'http://localhost:3000/auth/callback');
    });
  });

  it('does NOT render the OAuth fallback button for other error reasons', async () => {
    mockOAuth.mockResolvedValue({ ok: false, reason: 'unknown', message: 'oauth exploded' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    fireEvent.click(screen.getByTestId('auth-provider-google'));
    await waitFor(() => {
      expect(screen.getByText('oauth exploded')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('auth-modal-oauth-signin-existing')).toBeNull();
  });
});

describe('AuthModal — chrome', () => {
  it('closes on Escape', async () => {
    mockGetAuthState.mockResolvedValue(ANON);
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(closeModalMock).toHaveBeenCalled();
  });
});

describe('AuthModal — account phase', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue(PERMANENT);
  });

  it('shows the email and the Sign out button', async () => {
    render(<AuthModal />);
    await waitFor(() => {
      expect(screen.getByText('auth.modal.account.title')).toBeInTheDocument();
      expect(screen.getByText('eric@illinois.edu')).toBeInTheDocument();
      expect(screen.getByText('auth.modal.account.signOut')).toBeInTheDocument();
    });
  });

  it('moves to signout-confirm phase when Sign out is clicked', async () => {
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.account.signOut'));
    screen.getByText('auth.modal.account.signOut').click();
    expect(setPhaseMock).toHaveBeenCalledWith('signout-confirm');
  });
});

describe('AuthModal — signout-confirm phase', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue(PERMANENT);
    modalState = { open: true, phase: 'signout-confirm' };
  });

  it('shows both safety reassurance lines', async () => {
    render(<AuthModal />);
    await waitFor(() => {
      expect(screen.getByText('auth.modal.signOutConfirm.bodySafe')).toBeInTheDocument();
      expect(screen.getByText('auth.modal.signOutConfirm.bodyGuest')).toBeInTheDocument();
    });
  });

  it('cancel returns to the account phase, not closeModal', async () => {
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signOutConfirm.bodySafe'));
    screen.getByText('common.cancel').click();
    expect(setPhaseMock).toHaveBeenCalledWith('account');
    expect(closeModalMock).not.toHaveBeenCalled();
  });

  it('confirm calls signOut + closes the modal', async () => {
    mockSignOut.mockResolvedValue('new-anon-uid');
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signOutConfirm.confirm'));
    screen.getByText('auth.modal.signOutConfirm.confirm').click();
    await waitFor(() => {
      expect(mockSignOut).toHaveBeenCalled();
      expect(closeModalMock).toHaveBeenCalled();
    });
  });

  it('sets the just-signed-out flag on confirm', async () => {
    mockSignOut.mockResolvedValue('new-anon-uid');
    sessionStorage.clear();
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signOutConfirm.confirm'));
    screen.getByText('auth.modal.signOutConfirm.confirm').click();
    await waitFor(() => {
      expect(sessionStorage.getItem('ofe_just_signed_out')).toBe('1');
    });
  });
});
