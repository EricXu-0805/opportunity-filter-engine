/*
 * GuestBanner is sessionStorage-gated: it only renders right after a
 * deliberate sign-out. Tests cover the gate plus the dismiss path.
 *
 * sessionStorage in jsdom is real (not mocked) and reset by
 * test-setup.ts between tests, so we can write/read it directly.
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
    t: (key: string) => key,
  }),
}));

import GuestBanner from './GuestBanner';

const ANON: unknown = {
  session: null,
  user: null,
  isAnonymous: false,
  email: null,
};

const PERMANENT: unknown = {
  session: { user: { id: 'p', is_anonymous: false, email: 'e@i.edu' } },
  user: { id: 'p', is_anonymous: false },
  isAnonymous: false,
  email: 'e@i.edu',
};

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('GuestBanner — visibility gating', () => {
  it('hides when the just-signed-out flag is absent (first-visit anon)', async () => {
    mockGetAuthState.mockResolvedValue(ANON);
    const { container } = render(<GuestBanner />);
    await new Promise(r => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="guest-banner"]')).toBeNull();
  });

  it('shows when just-signed-out + still anon + not dismissed', async () => {
    sessionStorage.setItem('ofe_just_signed_out', '1');
    mockGetAuthState.mockResolvedValue(ANON);
    render(<GuestBanner />);
    await waitFor(() => {
      expect(screen.getByTestId('guest-banner')).toBeInTheDocument();
    });
  });

  it('hides when the user has signed back in (permanent session)', async () => {
    sessionStorage.setItem('ofe_just_signed_out', '1');
    mockGetAuthState.mockResolvedValue(PERMANENT);
    const { container } = render(<GuestBanner />);
    await new Promise(r => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="guest-banner"]')).toBeNull();
  });

  it('hides when the dismiss flag is already set in sessionStorage', async () => {
    sessionStorage.setItem('ofe_just_signed_out', '1');
    sessionStorage.setItem('ofe_guest_banner_dismissed', '1');
    mockGetAuthState.mockResolvedValue(ANON);
    const { container } = render(<GuestBanner />);
    await new Promise(r => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="guest-banner"]')).toBeNull();
  });
});

describe('GuestBanner — interactions', () => {
  beforeEach(() => {
    sessionStorage.setItem('ofe_just_signed_out', '1');
    mockGetAuthState.mockResolvedValue(ANON);
  });

  it('opens the auth modal with the banner reason on Sign-back-in click', async () => {
    render(<GuestBanner />);
    await waitFor(() => screen.getByTestId('guest-banner'));
    const cta = screen.getByText('auth.guestBanner.cta');
    cta.click();
    expect(mockOpenModal).toHaveBeenCalledWith({ reason: 'guest-banner' });
  });

  it('persists the dismiss flag and hides itself on dismiss click', async () => {
    const { container } = render(<GuestBanner />);
    await waitFor(() => screen.getByTestId('guest-banner'));
    const dismissBtn = screen.getByLabelText('common.dismiss');
    dismissBtn.click();
    await waitFor(() => {
      expect(container.querySelector('[data-testid="guest-banner"]')).toBeNull();
    });
    expect(sessionStorage.getItem('ofe_guest_banner_dismissed')).toBe('1');
  });
});
