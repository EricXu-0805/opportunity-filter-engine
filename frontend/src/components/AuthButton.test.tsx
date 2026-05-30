/*
 * AuthButton renders three states (anon / no-session → "Sign in",
 * permanent → email pill) and routes to /auth/sign-in. Tests cover
 * the label switch, accessibility props, and the tabIndex forwarding
 * that keeps the Header mobile-panel-tabindex tests green.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

const mockGetAuthState = vi.fn();
// Signature mirrors the real onAuthChange: takes a callback, returns
// an unsubscribe function. We never invoke the callback in these tests
// (initial state comes from getAuthState), but the unsubscribe MUST be
// returned so the component's useEffect cleanup doesn't crash on
// unmount.
const mockOnAuthChange = vi.fn((_cb: (s: unknown) => void) => () => {});

vi.mock('@/lib/supabase', () => ({
  getAuthState: () => mockGetAuthState(),
  onAuthChange: (cb: (s: unknown) => void) => mockOnAuthChange(cb),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string>) => {
      // Minimal fake: return the key, optionally append the email var
      // so the email-pill test can assert the email actually rendered.
      if (vars?.email) return `${key}:${vars.email}`;
      return key;
    },
  }),
}));

import AuthButton from './AuthButton';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('AuthButton — anon user', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'a', is_anonymous: true, email: null } },
      user: { id: 'a', is_anonymous: true },
      isAnonymous: true,
      email: null,
    });
  });

  it('shows the sign-in label', async () => {
    render(<AuthButton />);
    await waitFor(() => {
      expect(screen.getByTestId('auth-button')).toHaveTextContent('auth.button.signIn');
    });
  });

  it('links to /auth/sign-in', async () => {
    render(<AuthButton />);
    await waitFor(() => {
      const link = screen.getByTestId('auth-button');
      expect(link.getAttribute('href')).toBe('/auth/sign-in');
    });
  });

  it('uses the sign-in aria label, not the account one', async () => {
    render(<AuthButton />);
    await waitFor(() => {
      expect(screen.getByTestId('auth-button')).toHaveAttribute(
        'aria-label',
        'auth.button.signInAria',
      );
    });
  });
});

describe('AuthButton — permanent user', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'p', is_anonymous: false, email: 'eric@illinois.edu' } },
      user: { id: 'p', is_anonymous: false },
      isAnonymous: false,
      email: 'eric@illinois.edu',
    });
  });

  it('shows a shortened local-part instead of the sign-in label', async () => {
    render(<AuthButton />);
    await waitFor(() => {
      const link = screen.getByTestId('auth-button');
      // "eric" fits under 12 chars, so it renders un-truncated.
      expect(link).toHaveTextContent('eric');
      expect(link).not.toHaveTextContent('@illinois.edu');
    });
  });

  it('uses the account aria label with the full email', async () => {
    render(<AuthButton />);
    await waitFor(() => {
      const link = screen.getByTestId('auth-button');
      expect(link).toHaveAttribute('aria-label', 'auth.button.accountAria:eric@illinois.edu');
    });
  });

  it('truncates long local-parts after a dot or 11 chars', async () => {
    mockGetAuthState.mockResolvedValue({
      session: null,
      user: null,
      isAnonymous: false,
      email: 'super.long.address@example.com',
    });
    // Force the permanent path by also providing a user
    mockGetAuthState.mockResolvedValue({
      session: { user: { id: 'p', email: 'super.long.address@example.com' } },
      user: { id: 'p', is_anonymous: false },
      isAnonymous: false,
      email: 'super.long.address@example.com',
    });
    render(<AuthButton />);
    await waitFor(() => {
      const link = screen.getByTestId('auth-button');
      // "super" comes before the first dot — should render as "super…"
      expect(link.textContent).toContain('super');
      expect(link.textContent).toContain('…');
      expect(link.textContent?.length ?? 0).toBeLessThanOrEqual(13);
    });
  });
});

describe('AuthButton — mobile variant', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue({
      session: null,
      user: null,
      isAnonymous: false,
      email: null,
    });
  });

  it('uses the mobile testid', async () => {
    render(<AuthButton variant="mobile" />);
    await waitFor(() => {
      expect(screen.getByTestId('auth-button-mobile')).toBeInTheDocument();
    });
  });

  it('forwards tabIndex so the header panel can lock it out when closed', async () => {
    render(<AuthButton variant="mobile" tabIndex={-1} />);
    await waitFor(() => {
      const link = screen.getByTestId('auth-button-mobile');
      expect(link.getAttribute('tabindex')).toBe('-1');
    });
  });

  it('fires onNavigate when clicked (for header panel auto-close)', async () => {
    const onNavigate = vi.fn();
    render(<AuthButton variant="mobile" onNavigate={onNavigate} tabIndex={0} />);
    await waitFor(() => {
      expect(screen.getByTestId('auth-button-mobile')).toBeInTheDocument();
    });
    screen.getByTestId('auth-button-mobile').click();
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });
});
