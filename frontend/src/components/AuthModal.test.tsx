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
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockSignIn = vi.fn();
const mockSignInExisting = vi.fn();
const mockSignOut = vi.fn();
const mockGetAuthState = vi.fn();
const mockOnAuthChange = vi.fn((_cb: (s: unknown) => void) => () => {});
const mockOAuth = vi.fn();
const mockOAuthExisting = vi.fn();

vi.mock('@/lib/supabase', () => ({
  getAuthState: (...args: unknown[]) => mockGetAuthState(...args),
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
let modalState: { open: boolean; phase: string; reason?: string } = { open: true, phase: 'auto' };
const setPhaseMock = vi.fn((p: string) => { modalState = { ...modalState, phase: p }; });
const closeModalMock = vi.fn(() => { modalState = { ...modalState, open: false }; });

vi.mock('@/lib/auth-modal-context', () => ({
  useAuthModal: () => ({
    open: modalState.open,
    phase: modalState.phase,
    reason: modalState.reason ?? null,
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
  mockOnAuthChange.mockImplementation(() => () => {});
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

  it('sends a real existing-account sign-in link for a forced formal-session sign-in', async () => {
    modalState = { open: true, phase: 'signin' };
    mockGetAuthState.mockResolvedValue(PERMANENT);
    mockSignInExisting.mockResolvedValue({ ok: true, mode: 'sign-in', message: 'check inbox' });
    render(<AuthModal />);
    await waitFor(() => expect(mockGetAuthState).toHaveBeenCalled());
    const input = screen.getByLabelText('auth.modal.signin.emailLabel');
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => expect(mockSignInExisting).toHaveBeenCalledWith('eric@illinois.edu', expect.stringContaining('/auth/callback')));
    expect(mockSignIn).not.toHaveBeenCalled(); expect(setPhaseMock).toHaveBeenCalledWith('sent');
  });

  it('does not claim a link was sent when contact reauthentication fails', async () => {
    modalState = { open: true, phase: 'signin', reason: 'contact-reveal' };
    mockGetAuthState.mockReturnValue(new Promise(() => {}));
    mockSignInExisting.mockResolvedValue({ ok: false, reason: 'rate-limited', message: 'Please wait' });
    render(<AuthModal />);
    const input = screen.getByLabelText('auth.modal.signin.emailLabel');
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => expect(mockSignInExisting).toHaveBeenCalled());
    expect(mockSignIn).not.toHaveBeenCalled(); expect(setPhaseMock).not.toHaveBeenCalledWith('sent');
  });

  it('uses the current auth state rather than the earlier modal snapshot for forced sign-in', async () => {
    modalState = { open: true, phase: 'signin' };
    mockGetAuthState.mockResolvedValueOnce(PERMANENT).mockResolvedValue(ANON);
    mockSignIn.mockResolvedValue({ ok: true, mode: 'link-anon', message: 'check inbox' });
    render(<AuthModal />);
    await waitFor(() => expect(mockGetAuthState).toHaveBeenCalledTimes(1));
    const input = screen.getByLabelText('auth.modal.signin.emailLabel');
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => expect(mockSignIn).toHaveBeenCalled());
    expect(mockSignInExisting).not.toHaveBeenCalled();
  });

  it('restores the submit button after a rejected reauthentication request without claiming success', async () => {
    modalState = { open: true, phase: 'signin', reason: 'contact-reveal' };
    mockGetAuthState.mockResolvedValue(PERMANENT);
    mockSignInExisting.mockRejectedValueOnce(new Error('connection lost')).mockResolvedValue({ ok: true, mode: 'sign-in', message: 'check inbox' });
    render(<AuthModal />);
    const input = screen.getByLabelText('auth.modal.signin.emailLabel');
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    expect(await screen.findByText('auth.modal.signin.sendUnconfirmed')).toBeInTheDocument();
    expect(screen.getByText('auth.modal.signin.submit')).not.toBeDisabled();
    expect(setPhaseMock).not.toHaveBeenCalledWith('sent');
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => expect(setPhaseMock).toHaveBeenCalledWith('sent'));
    expect(mockSignInExisting).toHaveBeenCalledTimes(2);
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

  // Signing a guest in to an account it already has merges its rows but not
  // its tracker files; the only notice used to come after the merge.
  it('says guest tracker files stay behind before offering the existing account', async () => {
    mockSignIn.mockResolvedValue({ ok: false, reason: 'email-taken', message: 'taken' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.headline'));
    const input = screen.getByLabelText('auth.modal.signin.emailLabel') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    await screen.findByTestId('auth-modal-signin-existing');
    expect(screen.getByText('auth.modal.signin.guestFilesStay')).toBeInTheDocument();
  });

  // The contact-reveal sign-in on a detail page goes straight to the
  // existing-account link, so a guest never reaches the email-taken
  // recovery above, yet the same merge leaves its tracker files behind.
  async function settledAuth() {
    await waitFor(() => expect(mockGetAuthState).toHaveBeenCalled());
    await act(async () => { await Promise.resolve(); });
  }

  it('tells a guest before the contact sign-in that its tracker files stay behind', async () => {
    modalState = { open: true, phase: 'signin', reason: 'contact-reveal' };
    mockSignInExisting.mockResolvedValue({ ok: true, mode: 'sign-in', message: 'check inbox' });
    render(<AuthModal />);
    await settledAuth();
    expect(screen.getByText('auth.modal.signin.guestFilesStay')).toBeInTheDocument();
    const input = screen.getByLabelText('auth.modal.signin.emailLabel');
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => expect(mockSignInExisting).toHaveBeenCalled());
    expect(mockSignIn).not.toHaveBeenCalled();
  });

  it.each([
    ['an account session on the contact sign-in', { open: true, phase: 'signin', reason: 'contact-reveal' }, PERMANENT],
    // The guest's own "Sign in to reveal" links this session, keeping its files.
    ['a guest on the contact sign-in that links the guest session', { open: true, phase: 'auto', reason: 'contact-reveal' }, ANON],
    ['a guest on a forced sign-in for something else', { open: true, phase: 'signin' }, ANON],
  ])('says nothing about tracker files up front for %s', async (_name, state, auth) => {
    modalState = state;
    mockGetAuthState.mockResolvedValue(auth);
    render(<AuthModal />);
    await settledAuth();
    expect(screen.getByLabelText('auth.modal.signin.emailLabel')).toBeInTheDocument();
    expect(screen.queryByText('auth.modal.signin.guestFilesStay')).toBeNull();
  });

  // Only a guest session has tracker files to leave behind. Before the sign-in
  // check answers, or when it fails, nothing says this visitor is a guest.
  it.each([
    ['before the sign-in check answers', () => mockGetAuthState.mockReturnValue(new Promise(() => {}))],
    ['when the sign-in check fails', () => mockGetAuthState.mockRejectedValue(new Error('auth down'))],
    ['with no session', () => mockGetAuthState.mockResolvedValue({ session: null, user: null, isAnonymous: false, email: null })],
  ])('says nothing about tracker files on the contact sign-in %s', async (name, arrange) => {
    modalState = { open: true, phase: 'signin', reason: 'contact-reveal' };
    arrange();
    render(<AuthModal />);
    await settledAuth();
    if (name === 'when the sign-in check fails') await screen.findByTestId('auth-state-error');
    expect(screen.getByLabelText('auth.modal.signin.emailLabel')).toBeInTheDocument();
    expect(screen.queryByText('auth.modal.signin.guestFilesStay')).toBeNull();
  });

  it('shows the tracker-file notice once when the guest contact sign-in meets an identity conflict', async () => {
    vi.stubEnv('NEXT_PUBLIC_AUTH_PROVIDERS', 'google');
    modalState = { open: true, phase: 'signin', reason: 'contact-reveal' };
    mockOAuth.mockResolvedValue({ ok: false, reason: 'identity-taken', message: 'raw lib message' });
    render(<AuthModal />);
    await settledAuth();
    fireEvent.click(screen.getByTestId('auth-provider-google'));
    await screen.findByTestId('auth-modal-oauth-signin-existing');
    expect(screen.getAllByText('auth.modal.signin.guestFilesStay')).toHaveLength(1);
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
    expect(screen.queryByText('auth.modal.signin.guestFilesStay')).toBeNull();
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
    expect(screen.getByText('auth.modal.signin.guestFilesStay')).toBeInTheDocument();
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


function heldAuth<T = unknown>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe('AuthModal — auth snapshot recovery', () => {
  it('reports a failed strict auth read and recovers on explicit retry', async () => {
    mockGetAuthState.mockRejectedValueOnce(new Error('private SDK details')).mockResolvedValue(PERMANENT);
    render(<AuthModal />);
    expect(await screen.findByTestId('auth-state-error')).toHaveTextContent('auth.modal.signin.stateReadError');
    expect(screen.queryByText('private SDK details')).toBeNull();
    expect(mockGetAuthState).toHaveBeenCalledWith({ throwOnError: true });
    fireEvent.click(screen.getByTestId('auth-state-retry'));
    expect(await screen.findByText('auth.modal.account.title')).toBeInTheDocument();
    expect(screen.queryByTestId('auth-state-error')).toBeNull();
  });

  it.each(['success', 'failure'] as const)('a live auth event wins over late initial %s', async kind => {
    const initial = heldAuth(); let notify!: (value: unknown) => void;
    mockGetAuthState.mockReturnValue(initial.promise);
    mockOnAuthChange.mockImplementation(cb => { notify = cb; return () => {}; });
    render(<AuthModal />);
    act(() => notify(PERMANENT));
    expect(screen.getByText('auth.modal.account.title')).toBeInTheDocument();
    await act(async () => { if (kind === 'success') initial.resolve(ANON); else initial.reject(new Error('stale failure')); });
    expect(screen.getByText('auth.modal.account.title')).toBeInTheDocument();
    expect(screen.queryByTestId('auth-state-error')).toBeNull();
  });

  it('does not show the previous account snapshot while reopening', async () => {
    mockGetAuthState.mockResolvedValueOnce(PERMANENT);
    const view = render(<AuthModal />);
    expect(await screen.findByText('auth.modal.account.title')).toBeInTheDocument();
    modalState = { open: false, phase: 'auto' }; view.rerender(<AuthModal />);
    const next = heldAuth(); mockGetAuthState.mockReturnValue(next.promise);
    modalState = { open: true, phase: 'auto' }; view.rerender(<AuthModal />);
    expect(screen.queryByText('auth.modal.account.title')).toBeNull();
    expect(screen.queryByText('eric@illinois.edu')).toBeNull();
    await act(async () => next.resolve(ANON));
    expect(screen.getByText('auth.modal.signin.headline')).toBeInTheDocument();
  });

  it('ignores a rejected initial auth read after close and cleans up its subscription', async () => {
    const initial = heldAuth(); const stop = vi.fn();
    mockGetAuthState.mockReturnValueOnce(initial.promise).mockResolvedValue(PERMANENT);
    mockOnAuthChange.mockReturnValue(stop);
    const view = render(<AuthModal />);
    modalState = { open: false, phase: 'auto' }; view.rerender(<AuthModal />);
    expect(stop).toHaveBeenCalledTimes(1);
    await act(async () => initial.reject(new Error('closed modal failure')));
    modalState = { open: true, phase: 'auto' }; view.rerender(<AuthModal />);
    expect(await screen.findByText('auth.modal.account.title')).toBeInTheDocument();
    expect(screen.queryByTestId('auth-state-error')).toBeNull();
  });

  it('does not send an email when the forced sign-in current-session check fails', async () => {
    modalState = { open: true, phase: 'signin' };
    mockGetAuthState.mockResolvedValueOnce(PERMANENT).mockRejectedValue(new Error('auth check failed'));
    render(<AuthModal />);
    await waitFor(() => expect(mockGetAuthState).toHaveBeenCalledTimes(1));
    const input = screen.getByLabelText('auth.modal.signin.emailLabel');
    fireEvent.change(input, { target: { value: 'eric@illinois.edu' } }); fireEvent.submit(input.closest('form')!);
    expect(await screen.findByText('auth.modal.signin.sendUnconfirmed')).toBeInTheDocument();
    expect(mockSignIn).not.toHaveBeenCalled(); expect(mockSignInExisting).not.toHaveBeenCalled();
    expect(screen.getByText('auth.modal.signin.submit')).not.toBeDisabled();
    expect(setPhaseMock).not.toHaveBeenCalledWith('sent');
  });
});
