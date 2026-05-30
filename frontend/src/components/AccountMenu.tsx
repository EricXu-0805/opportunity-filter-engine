'use client';

/*
 * AccountMenu — header auth pill that REPLACES AuthButton.
 *
 * Guest state:  small "Save" pill (+ Sparkles icon on desktop) → opens
 *               AuthModal in the signin phase.
 * Saved state:  avatar circle (first letter of email) + email prefix
 *               → opens AuthModal in the account phase.
 *
 * Why a button that opens a modal instead of a Link to /auth/sign-in:
 *   - Per R66 plan, sign-in is an action, not a destination. Opening a
 *     modal preserves the user's scroll position and current page.
 *   - Removes a navigation round-trip (the cause of "no real feedback").
 *
 * Mobile variant: same component, but uses a smaller pill that fits
 * the header's mobile panel layout (which lives outside <nav> so it
 * doesn't break the existing tabindex tests).
 */

import { Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  getAuthState,
  onAuthChange,
  type AuthState,
} from '@/lib/supabase';
import { useAuthModal } from '@/lib/auth-modal-context';
import { useT } from '@/i18n/client';

interface AccountMenuProps {
  variant?: 'desktop' | 'mobile';
  /** Caller-supplied side-effect to fire on click (used by mobile panel
   *  to close the nav drawer before opening the modal). */
  onActivate?: () => void;
  /** Mobile-only: forwards through to the link/button so the header
   *  panel's keyboard-trap tests stay green. */
  tabIndex?: number;
}

export default function AccountMenu({
  variant = 'desktop',
  onActivate,
  tabIndex,
}: AccountMenuProps) {
  const { t } = useT();
  const { openModal } = useAuthModal();
  const [state, setState] = useState<AuthState | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAuthState().then(s => { if (!cancelled) setState(s); });
    const unsub = onAuthChange(s => { if (!cancelled) setState(s); });
    return () => { cancelled = true; unsub(); };
  }, []);

  const isPermanent = Boolean(state?.user && !state.isAnonymous);
  const email = state?.email ?? '';

  const handleClick = () => {
    onActivate?.();
    openModal({ reason: 'header' });
  };

  // ====== guest variant ======
  if (!isPermanent) {
    const label = t('auth.menu.guestLabel');
    const aria = t('auth.menu.guestAria');
    if (variant === 'mobile') {
      return (
        <button
          type="button"
          onClick={handleClick}
          tabIndex={tabIndex}
          aria-label={aria}
          data-testid="account-menu-mobile"
          className="px-3.5 py-2 rounded-xl text-[14px] font-medium text-gray-600 hover:text-gray-900 hover:bg-black/[0.04] transition-colors text-left"
        >
          {label}
        </button>
      );
    }
    return (
      <button
        type="button"
        onClick={handleClick}
        aria-label={aria}
        data-testid="account-menu"
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 transition-colors shrink-0"
      >
        <Sparkles className="w-3 h-3" aria-hidden="true" />
        {label}
      </button>
    );
  }

  // ====== permanent variant ======
  const prefix = shortEmail(email);
  const aria = t('auth.menu.signedInAria', { email });
  if (variant === 'mobile') {
    return (
      <button
        type="button"
        onClick={handleClick}
        tabIndex={tabIndex}
        aria-label={aria}
        data-testid="account-menu-mobile"
        className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-[14px] font-medium text-gray-600 hover:text-gray-900 hover:bg-black/[0.04] transition-colors text-left"
      >
        <span className="w-6 h-6 rounded-full bg-blue-100 text-blue-700 text-[11px] font-semibold uppercase flex items-center justify-center">
          {firstLetter(email)}
        </span>
        <span className="truncate">{prefix}</span>
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label={aria}
      data-testid="account-menu"
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-[12px] font-medium text-gray-700 hover:bg-black/[0.04] transition-colors shrink-0"
    >
      <span className="w-5 h-5 rounded-full bg-blue-100 text-blue-700 text-[10px] font-semibold uppercase flex items-center justify-center">
        {firstLetter(email)}
      </span>
      <span className="truncate max-w-[10ch]">{prefix}</span>
    </button>
  );
}

function firstLetter(email: string): string {
  const t = email.trim();
  return t ? t[0].toUpperCase() : '?';
}

function shortEmail(email: string): string {
  if (!email) return '';
  const at = email.indexOf('@');
  const local = at > 0 ? email.slice(0, at) : email;
  if (local.length <= 12) return local;
  const dot = local.indexOf('.');
  if (dot > 0 && dot <= 12) return `${local.slice(0, dot)}…`;
  return `${local.slice(0, 11)}…`;
}
