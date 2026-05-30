/*
 * SaveFavoritesAnchor only renders when ALL three are true:
 *   - user is anonymous (or no session)
 *   - favoriteCount >= 3
 *   - localStorage dismiss flag not set
 *
 * Tests cover the boundary conditions on each axis. We don't test the
 * exact copy — that's i18n's job, and the dictionary already has the
 * strings.
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
    t: (key: string, vars?: Record<string, string | number>) => {
      if (vars?.count !== undefined) return `${key}:${vars.count}`;
      return key;
    },
  }),
}));

import SaveFavoritesAnchor from './SaveFavoritesAnchor';

const ANON: unknown = {
  session: { user: { id: 'anon', is_anonymous: true } },
  user: { id: 'anon', is_anonymous: true },
  isAnonymous: true,
  email: null,
};

const PERMANENT: unknown = {
  session: { user: { id: 'perm', is_anonymous: false, email: 'e@i.edu' } },
  user: { id: 'perm', is_anonymous: false },
  isAnonymous: false,
  email: 'e@i.edu',
};

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('SaveFavoritesAnchor — visibility', () => {
  it('hides when fewer than 3 favorites, even for anon', async () => {
    mockGetAuthState.mockResolvedValue(ANON);
    const { container } = render(<SaveFavoritesAnchor favoriteCount={2} />);
    // Give the auth resolver microtask a chance to run before we assert
    await new Promise(r => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="save-favorites-anchor"]')).toBeNull();
  });

  it('hides for permanent users even at 5 favorites', async () => {
    mockGetAuthState.mockResolvedValue(PERMANENT);
    const { container } = render(<SaveFavoritesAnchor favoriteCount={5} />);
    await new Promise(r => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="save-favorites-anchor"]')).toBeNull();
  });

  it('renders for anon at exactly 3 favorites', async () => {
    mockGetAuthState.mockResolvedValue(ANON);
    render(<SaveFavoritesAnchor favoriteCount={3} />);
    await waitFor(() => {
      expect(screen.getByTestId('save-favorites-anchor')).toBeInTheDocument();
    });
  });

  it('hides when dismiss flag is already in localStorage', async () => {
    localStorage.setItem('ofe_anchor_3fav_dismissed', '1');
    mockGetAuthState.mockResolvedValue(ANON);
    const { container } = render(<SaveFavoritesAnchor favoriteCount={5} />);
    await new Promise(r => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="save-favorites-anchor"]')).toBeNull();
  });
});

describe('SaveFavoritesAnchor — interactions', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue(ANON);
  });

  it('opens the modal with the anchor reason on CTA click', async () => {
    render(<SaveFavoritesAnchor favoriteCount={3} />);
    await waitFor(() => screen.getByTestId('save-favorites-anchor'));
    // CTA + dismiss share the same container; click the cta by its label key
    const cta = screen.getByText('auth.anchor.favorites3.cta');
    cta.click();
    expect(mockOpenModal).toHaveBeenCalledWith({ reason: 'save-favorites-anchor' });
  });

  it('persists the dismiss flag and hides itself on dismiss click', async () => {
    const { container } = render(<SaveFavoritesAnchor favoriteCount={3} />);
    await waitFor(() => screen.getByTestId('save-favorites-anchor'));
    const dismiss = screen.getByText('auth.anchor.favorites3.dismiss');
    dismiss.click();
    await waitFor(() => {
      expect(container.querySelector('[data-testid="save-favorites-anchor"]')).toBeNull();
    });
    expect(localStorage.getItem('ofe_anchor_3fav_dismissed')).toBe('1');
  });
});
