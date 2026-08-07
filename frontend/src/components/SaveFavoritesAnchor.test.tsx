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
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, writeUserScopedRaw } from '@/lib/identity-owner';
import { STORAGE_KEYS } from '@/lib/storage-keys';

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

beforeEach(async () => {
  localStorage.clear();
  // The anchor only ever shows for an anonymous SESSION, which still has a
  // real uid (just flagged isAnonymous) — establish that readiness the same
  // way ensureAnonSession does in production, so the gated dismiss read/
  // write actually has an owner to resolve against.
  advanceOwnerEpoch('anon-test-uid');
  await syncLocalIdentityOwner('anon-test-uid');
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
    writeUserScopedRaw(STORAGE_KEYS.ANCHOR_3FAV_DISMISSED, '1', captureOwnerToken());
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

  it('a dismiss write attempted while the identity is mid-transition (blocked, not yet synced) does NOT optimistically hide the anchor', async () => {
    render(<SaveFavoritesAnchor favoriteCount={3} />);
    await waitFor(() => screen.getByTestId('save-favorites-anchor'));

    // A real transition — but the choke point that would prove local
    // ownership (syncLocalIdentityOwner) hasn't run yet, so isLocalOwnerReady
    // is false for the new uid at the exact moment the click's own
    // captureOwnerToken() resolves. writeUserScopedRaw's gate must reject
    // this write, since click-to-write here is fully synchronous — there is
    // no async gap for a token to go stale relative to itself, only whether
    // the CURRENT owner is actually ready right now.
    advanceOwnerEpoch('anon-test-uid-2');

    const dismiss = screen.getByText('auth.anchor.favorites3.dismiss');
    dismiss.click();
    // A tick for any pending re-render to settle — this asserts the
    // ABSENCE of a change, so there is no positive condition to await.
    await new Promise((r) => setTimeout(r, 0));

    expect(screen.getByTestId('save-favorites-anchor')).toBeInTheDocument();
    expect(localStorage.getItem('ofe_anchor_3fav_dismissed')).toBeNull();
  });
});
