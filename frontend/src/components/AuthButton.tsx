'use client';

/*
 * Header auth state pill.
 *
 *   anonymous session (or none) → "Sign in" link to /auth/sign-in
 *   permanent user signed in    → short email label linking to /auth/sign-in
 *                                 (which renders the sign-out panel)
 *
 * Why a Link, not a button:
 *   - The actual sign-in flow lives on /auth/sign-in to keep the header
 *     thin and to give magic-link copy / outcome state real estate.
 *   - Future Flow B (cross-device merge) UI also belongs on that page.
 */

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { getAuthState, onAuthChange, type AuthState } from '@/lib/supabase';
import { useT } from '@/i18n/client';

interface AuthButtonProps {
  variant?: 'desktop' | 'mobile';
  onNavigate?: () => void;
  /**
   * Only meaningful on the mobile variant. The header keeps the panel
   * focusable only when it's open — mirrors the NAV_ITEMS behavior so
   * the tabindex test stays green and the link doesn't trap focus when
   * the panel is collapsed.
   */
  tabIndex?: number;
}

export default function AuthButton({
  variant = 'desktop',
  onNavigate,
  tabIndex,
}: AuthButtonProps) {
  const { t } = useT();
  const [state, setState] = useState<AuthState | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAuthState().then(s => { if (!cancelled) setState(s); });
    const unsub = onAuthChange(s => setState(s));
    return () => { cancelled = true; unsub(); };
  }, []);

  const isPermanent = Boolean(state?.user && !state.isAnonymous);
  const label = isPermanent
    ? shortEmail(state?.email || '')
    : t('auth.button.signIn');
  const ariaLabel = isPermanent
    ? t('auth.button.accountAria', { email: state?.email || '' })
    : t('auth.button.signInAria');

  if (variant === 'mobile') {
    return (
      <Link
        href="/auth/sign-in"
        onClick={onNavigate}
        aria-label={ariaLabel}
        data-testid="auth-button-mobile"
        tabIndex={tabIndex}
        className="px-3.5 py-2 rounded-xl text-[14px] font-medium text-gray-600 hover:text-gray-900 hover:bg-black/[0.04] transition-colors"
      >
        {label}
      </Link>
    );
  }

  return (
    <Link
      href="/auth/sign-in"
      aria-label={ariaLabel}
      data-testid="auth-button"
      className="px-3 py-1.5 rounded-full text-[12px] font-medium text-gray-600 hover:text-gray-900 hover:bg-black/[0.04] transition-colors shrink-0"
    >
      {label}
    </Link>
  );
}

/**
 * Compact a long email so it fits in the header pill. We keep the
 * local-part if it's short, otherwise truncate after the first dot or
 * 12 chars and append "...". The domain is always dropped for display.
 */
function shortEmail(email: string): string {
  if (!email) return '';
  const at = email.indexOf('@');
  const local = at > 0 ? email.slice(0, at) : email;
  if (local.length <= 12) return local;
  const dot = local.indexOf('.');
  if (dot > 0 && dot <= 12) return `${local.slice(0, dot)}…`;
  return `${local.slice(0, 11)}…`;
}
