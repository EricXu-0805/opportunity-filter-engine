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
const mockSignOut = vi.fn();
const mockGetAuthState = vi.fn();
const mockOnAuthChange = vi.fn((_cb: (s: unknown) => void) => () => {});

vi.mock('@/lib/supabase', () => ({
  getAuthState: () => mockGetAuthState(),
  onAuthChange: (cb: (s: unknown) => void) => mockOnAuthChange(cb),
  signInOrLinkEmail: (email: string, redirect: string) => mockSignIn(email, redirect),
  signOutOfAccount: () => mockSignOut(),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
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
      expect(screen.getByText('auth.modal.signin.title')).toBeInTheDocument();
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
    await waitFor(() => screen.getByText('auth.modal.signin.title'));
    expect(screen.getByText('auth.modal.signin.trust')).toBeInTheDocument();
  });

  it('transitions to the sent phase on successful submit', async () => {
    mockSignIn.mockResolvedValue({ ok: true, mode: 'link-anon', message: 'check inbox' });
    render(<AuthModal />);
    await waitFor(() => screen.getByText('auth.modal.signin.title'));
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
    await waitFor(() => screen.getByText('auth.modal.signin.title'));
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
