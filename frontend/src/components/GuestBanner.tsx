'use client';

/*
 * GuestBanner — shown after a deliberate sign-out.
 *
 * Why we don't show this for first-visit anonymous users:
 *   - A first-visit user has never agreed to "save my work"; nagging
 *     them on first load is exactly the cold-gate anti-pattern.
 *   - Only after a sign-out do we have evidence the user wants
 *     persistence (they had it, they removed it) — that's when the
 *     "your data is safe, sign back in" reassurance is meaningful.
 *
 * Trigger: sessionStorage flag `ofe_just_signed_out` set by AuthModal's
 * confirmSignOut handler. Cleared on dismiss. Banner survives across
 * page navigations within the same session but disappears on tab
 * close — by design. Users who close the tab and reopen aren't in
 * "just signed out" emotional state any more.
 */

import { X } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  getAuthState,
  onAuthChange,
  type AuthState,
} from '@/lib/supabase';
import { useAuthModal } from '@/lib/auth-modal-context';
import { useT } from '@/i18n/client';

const FLAG_KEY = 'ofe_just_signed_out';
const DISMISS_KEY = 'ofe_guest_banner_dismissed';

function readSession(key: string): string | null {
  if (typeof window === 'undefined') return null;
  try { return sessionStorage.getItem(key); } catch { return null; }
}

function writeSession(key: string, value: string | null) {
  if (typeof window === 'undefined') return;
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch { /* private mode */ }
}

export default function GuestBanner() {
  const { t } = useT();
  const { openModal } = useAuthModal();
  // Initial reads from sessionStorage are lazy so we never setState in
  // an effect: the banner derives `shown` from these + auth state.
  const [authState, setAuthState] = useState<AuthState | null>(null);
  const [justSignedOut] = useState(() => readSession(FLAG_KEY) === '1');
  const [dismissed, setDismissed] = useState(() => readSession(DISMISS_KEY) === '1');

  useEffect(() => {
    let cancelled = false;
    getAuthState().then(s => { if (!cancelled) setAuthState(s); });
    const unsub = onAuthChange(s => { if (!cancelled) setAuthState(s); });
    return () => { cancelled = true; unsub(); };
  }, []);

  // Side-effect-only: when the user signs back in, clear the flag so a
  // future sign-out triggers fresh state. We DON'T setState here —
  // `shown` derives `isAnon` from authState directly below, so React
  // will naturally re-render the banner away.
  useEffect(() => {
    if (authState?.user && !authState.isAnonymous) {
      writeSession(FLAG_KEY, null);
      writeSession(DISMISS_KEY, null);
    }
  }, [authState]);

  const isAnon = authState !== null && (!authState.user || authState.isAnonymous);
  const shown = isAnon && justSignedOut && !dismissed;
  if (!shown) return null;

  const dismiss = () => {
    writeSession(DISMISS_KEY, '1');
    setDismissed(true);
  };

  return (
    <div
      role="status"
      data-testid="guest-banner"
      className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-3"
    >
      <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
        <div className="flex-1 text-[13px] leading-relaxed">
          <p className="font-semibold text-amber-900">{t('auth.guestBanner.title')}</p>
          <p className="text-amber-800 mt-0.5">{t('auth.guestBanner.body')}</p>
        </div>
        <button
          type="button"
          onClick={() => openModal({ reason: 'guest-banner' })}
          className="shrink-0 px-3 py-1 rounded-full text-[12px] font-medium text-amber-900 bg-amber-100 hover:bg-amber-200 transition-colors"
        >
          {t('auth.guestBanner.cta')}
        </button>
        <button
          type="button"
          onClick={dismiss}
          aria-label={t('common.dismiss')}
          className="shrink-0 p-1 rounded-lg hover:bg-amber-100 transition-colors"
        >
          <X className="w-4 h-4 text-amber-700" />
        </button>
      </div>
    </div>
  );
}
