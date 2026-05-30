'use client';

/*
 * Cross-tree opener for the AuthModal.
 *
 * Why a Context instead of a global event bus or per-component prop drill:
 *   - The modal is opened from at least 4 surfaces (Header AccountMenu,
 *     ResultsSearch "Save to account" button, SaveFavoritesAnchor,
 *     GuestBanner) plus deep links via /auth/sign-in. Threading callbacks
 *     through every parent would balloon prop counts.
 *   - useAuthModal() colocates the open/close API with the components
 *     that need it, which keeps the modal's open semantics testable.
 *
 * The provider also owns the modal's mount point — exactly one <AuthModal />
 * lives at the root, sharing state across every consumer. This avoids the
 * "two modals on top of each other" bug that happens when each consumer
 * renders its own.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

export type AuthModalPhase = 'auto' | 'signin' | 'sent' | 'account' | 'signout-confirm';

/**
 * Why we record `reason`: future PRs will want to know which anchor
 * was the highest-converting (header CTA vs save-search vs 3-fav
 * anchor). Surface-level analytics is a one-line add later if we log
 * this string. Kept narrow on purpose.
 */
export type AuthModalReason =
  | 'header'
  | 'save-search'
  | 'save-favorites-anchor'
  | 'guest-banner'
  | 'deep-link';

interface OpenOptions {
  reason?: AuthModalReason;
  /** Force a specific phase. Default: `auto` — picks based on session. */
  phase?: AuthModalPhase;
}

interface AuthModalContextValue {
  open: boolean;
  phase: AuthModalPhase;
  reason: AuthModalReason | null;
  /** Open the modal. Default phase is `auto`. */
  openModal: (opts?: OpenOptions) => void;
  closeModal: () => void;
  setPhase: (phase: AuthModalPhase) => void;
}

const AuthModalContext = createContext<AuthModalContextValue | null>(null);

/**
 * Inert fallback returned when there's no provider in the tree. This
 * exists so unit tests that render auth-aware components in isolation
 * (e.g. Header.test.tsx renders <Header />, which contains AccountMenu)
 * don't need to wrap every render in <AuthModalProvider> just to mount.
 * In production the provider is mounted at the layout root, so the
 * fallback only ever fires in tests.
 */
const INERT: AuthModalContextValue = {
  open: false,
  phase: 'auto',
  reason: null,
  openModal: () => {},
  closeModal: () => {},
  setPhase: () => {},
};

export function useAuthModal(): AuthModalContextValue {
  return useContext(AuthModalContext) ?? INERT;
}

interface AuthModalProviderProps {
  children: ReactNode;
}

export function AuthModalProvider({ children }: AuthModalProviderProps) {
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<AuthModalPhase>('auto');
  const [reason, setReason] = useState<AuthModalReason | null>(null);

  const openModal = useCallback((opts?: OpenOptions) => {
    setPhase(opts?.phase ?? 'auto');
    setReason(opts?.reason ?? null);
    setOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    setOpen(false);
    // Reset reason on close so the next open starts fresh. We
    // intentionally do NOT reset phase: the modal animates out and
    // we'd flash through 'auto' before it unmounts — leaving the last
    // phase lets the exit animation finish with the correct content.
    setReason(null);
  }, []);

  // ESC to close. Lives in the provider so we only attach one listener
  // app-wide instead of one per consumer.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener('keydown', onKey); };
  }, [open]);

  const value = useMemo<AuthModalContextValue>(() => ({
    open,
    phase,
    reason,
    openModal,
    closeModal,
    setPhase,
  }), [open, phase, reason, openModal, closeModal]);

  return (
    <AuthModalContext.Provider value={value}>
      {children}
    </AuthModalContext.Provider>
  );
}
