/*
 * AccountMenu renders one of two pill variants based on auth state and
 * opens the AuthModal on click. These tests verify the visual state
 * machine without exercising the modal itself — that lives in
 * AuthModal.test.tsx.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

const mockOpenModal = vi.fn();
const mockGetAuthState = vi.fn();
const mockOnAuthChange = vi.fn((_cb: (s: unknown) => void) => () => {});

vi.mock('@/lib/supabase', () => ({
  getAuthState: () => mockGetAuthState(),
  onAuthChange: (cb: (s: unknown) => void) => mockOnAuthChange(cb),
}));

vi.mock('@/lib/auth-modal-context', () => ({
  useAuthModal: () => ({
    open: false,
    phase: 'auto',
    reason: null,
    openModal: mockOpenModal,
    closeModal: vi.fn(),
    setPhase: vi.fn(),
  }),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string>) => {
      if (vars?.email) return `${key}:${vars.email}`;
      return key;
    },
  }),
}));

import AccountMenu from './AccountMenu';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('AccountMenu — guest variant', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'anon', is_anonymous: true } },
      user: { id: 'anon', is_anonymous: true },
      isAnonymous: true,
      email: null,
    });
  });

  it('renders the guest "Save" label, not an email', async () => {
    render(<AccountMenu />);
    await waitFor(() => {
      expect(screen.getByTestId('account-menu')).toHaveTextContent('auth.menu.guestLabel');
    });
  });

  it('uses the guest aria label', async () => {
    render(<AccountMenu />);
    await waitFor(() => {
      expect(screen.getByTestId('account-menu')).toHaveAttribute(
        'aria-label',
        'auth.menu.guestAria',
      );
    });
  });

  it('opens the auth modal on click', async () => {
    render(<AccountMenu />);
    await waitFor(() => screen.getByTestId('account-menu'));
    screen.getByTestId('account-menu').click();
    expect(mockOpenModal).toHaveBeenCalledTimes(1);
    expect(mockOpenModal).toHaveBeenCalledWith({ reason: 'header' });
  });
});

describe('AccountMenu — permanent (signed-in) variant', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'perm', is_anonymous: false, email: 'eric@illinois.edu' } },
      user: { id: 'perm', is_anonymous: false },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });
  });

  it('shows a shortened email prefix, not the sign-in label', async () => {
    render(<AccountMenu />);
    await waitFor(() => {
      const button = screen.getByTestId('account-menu');
      expect(button).toHaveTextContent('eric');
      expect(button).not.toHaveTextContent('@illinois.edu');
      expect(button).not.toHaveTextContent('auth.menu.guestLabel');
    });
  });

  it('uses the signed-in aria label with the full email', async () => {
    render(<AccountMenu />);
    await waitFor(() => {
      expect(screen.getByTestId('account-menu')).toHaveAttribute(
        'aria-label',
        'auth.menu.signedInAria:eric@illinois.edu',
      );
    });
  });

  it('opens an inline account dropdown on click — not an involuntary modal (Option C)', async () => {
    render(<AccountMenu />);
    await waitFor(() => screen.getByTestId('account-menu'));
    screen.getByTestId('account-menu').click();
    // Dropdown surfaces the full email + a sign-out action; the auth
    // modal is NOT opened just because a valid session was clicked.
    expect(await screen.findByText('eric@illinois.edu')).toBeInTheDocument();
    expect(screen.getByText('auth.modal.account.signOut')).toBeInTheDocument();
    expect(mockOpenModal).not.toHaveBeenCalled();
  });

  it('Sign out opens the signout-confirm dialog, preserving the data-loss warning', async () => {
    render(<AccountMenu />);
    await waitFor(() => screen.getByTestId('account-menu'));
    screen.getByTestId('account-menu').click();
    (await screen.findByText('auth.modal.account.signOut')).click();
    expect(mockOpenModal).toHaveBeenCalledWith({ reason: 'header', phase: 'signout-confirm' });
  });
});

describe('AccountMenu — mobile variant', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue({
      session: null,
      user: null,
      isAnonymous: false,
      email: null,
    });
  });

  it('uses the mobile-specific testid', async () => {
    render(<AccountMenu variant="mobile" />);
    await waitFor(() => {
      expect(screen.getByTestId('account-menu-mobile')).toBeInTheDocument();
    });
  });

  it('forwards tabIndex so the header panel can lock focus when collapsed', async () => {
    render(<AccountMenu variant="mobile" tabIndex={-1} />);
    await waitFor(() => {
      expect(screen.getByTestId('account-menu-mobile').getAttribute('tabindex')).toBe('-1');
    });
  });

  it('fires onActivate before opening the modal (so the panel can close)', async () => {
    const onActivate = vi.fn();
    render(<AccountMenu variant="mobile" onActivate={onActivate} tabIndex={0} />);
    await waitFor(() => screen.getByTestId('account-menu-mobile'));
    screen.getByTestId('account-menu-mobile').click();
    expect(onActivate).toHaveBeenCalledTimes(1);
    expect(mockOpenModal).toHaveBeenCalledTimes(1);
  });
});
