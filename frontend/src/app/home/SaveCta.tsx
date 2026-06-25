'use client';

/*
 * SaveCta — inline "Save my work" callout that lives at the bottom of
 * the home page, BELOW the SubmitRow / ProfileStrength block.
 *
 * R67 problem #1 fix: in R66 we renamed the header pill to "Save" to
 * avoid a hard "Sign in" CTA, but real users couldn't tell the product
 * had accounts at all. R67 reverses that: the header pill says "Sign in"
 * (explicit account entry), and the "Save my work" voice moves HERE —
 * tied to the action of saving the profile the user just filled out.
 *
 * Two surfaces, two voices:
 *   - header pill = "Sign in"     (account system entry)
 *   - this CTA    = "Save my work" (save-the-data context)
 *
 * Guest-only: hides itself when the user has a permanent (non-anon)
 * session. Dismissable via sessionStorage so it doesn't nag once the
 * user has explicitly closed it this session.
 */

import { Sparkles, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  getAuthState,
  onAuthChange,
  type AuthState,
} from '@/lib/supabase';
import { useAuthModal } from '@/lib/auth-modal-context';
import type { TFunc } from './types';

const DISMISS_KEY = 'ofe_home_save_cta_dismissed';

export function SaveCta({ t }: { t: TFunc }) {
  const { openModal } = useAuthModal();
  const [state, setState] = useState<AuthState | null>(null);
  const [dismissed, setDismissed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    try { return sessionStorage.getItem(DISMISS_KEY) === '1'; } catch { return false; }
  });

  useEffect(() => {
    let cancelled = false;
    getAuthState().then(s => { if (!cancelled) setState(s); });
    const unsub = onAuthChange(s => { if (!cancelled) setState(s); });
    return () => { cancelled = true; unsub(); };
  }, []);

  const isPermanent = Boolean(state?.user && !state.isAnonymous);
  if (isPermanent || dismissed) return null;

  const handleClick = () => openModal({ reason: 'home-save-cta' });
  const handleDismiss = () => {
    try { sessionStorage.setItem(DISMISS_KEY, '1'); } catch { /* private mode */ }
    setDismissed(true);
  };

  return (
    <section
      className="mt-10 max-w-2xl mx-auto"
      aria-label={t('home.saveCta.title')}
      data-testid="home-save-cta"
    >
      <div className="relative rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 to-white px-6 py-5 shadow-[0_1px_8px_rgba(79,70,229,0.08)]">
        <button
          type="button"
          onClick={handleDismiss}
          aria-label={t('home.saveCta.dismiss')}
          className="absolute top-3 right-3 p-1 rounded-md text-gray-400 hover:text-gray-600 hover:bg-white/60 transition-colors"
          data-testid="home-save-cta-dismiss"
        >
          <X className="w-3.5 h-3.5" aria-hidden="true" />
        </button>

        <div className="flex items-start gap-3 pr-6">
          <div className="w-9 h-9 rounded-xl bg-indigo-100 flex items-center justify-center shrink-0">
            <Sparkles className="w-4 h-4 text-indigo-600" aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-[14px] font-semibold text-gray-900">
              {t('home.saveCta.title')}
            </h3>
            <p className="text-[12.5px] text-gray-600 leading-relaxed mt-0.5">
              {t('home.saveCta.body')}
            </p>
            <button
              type="button"
              onClick={handleClick}
              data-testid="home-save-cta-button"
              className="mt-3 inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-[12.5px] font-medium text-white bg-indigo-600 hover:bg-indigo-700 transition-colors shadow-[0_1px_4px_rgba(79,70,229,0.25)]"
            >
              <Sparkles className="w-3 h-3" aria-hidden="true" />
              {t('home.saveCta.cta')}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
