'use client';

import { useEffect, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { Sparkles, X } from 'lucide-react';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { captureOwnerToken, onLocalOwnerStateChange, readUserScopedRaw, writeUserScopedRaw } from '@/lib/identity-owner';
import { track, trackOnce } from '@/lib/analytics';
import type { TFunc } from './types';

const DISMISS_EVENT = 'ofe:concierge-cta-dismissed';

function subscribeDismissal(onChange: () => void) {
  window.addEventListener(DISMISS_EVENT, onChange);
  // A real identity transition must also trigger a re-read: the previous
  // owner's dismiss decision is not this one's, and readiness itself may
  // flip readUserScopedRaw's answer even with no storage bytes changing.
  const unsubOwner = onLocalOwnerStateChange(onChange);
  return () => { window.removeEventListener(DISMISS_EVENT, onChange); unsubOwner(); };
}

/**
 * The concierge willingness-to-pay funnel entry, placed inside the results
 * feed where the buying moment happens (the intent CTA previously lived only
 * on /account, leaving the funnel dark). Links to the account Plan card,
 * which is the waitlist capture with payments off and the order flow with
 * payments on. Dismissal persists per browser.
 */
export function ConciergeCta({ t }: { t: TFunc }) {
  // External-store read (not state-in-effect): server snapshot says dismissed,
  // so SSR renders nothing and the card appears on the client without a
  // hydration mismatch.
  const dismissed = useSyncExternalStore(
    subscribeDismissal,
    () => readUserScopedRaw(STORAGE_KEYS.RESULTS_CTA_DISMISSED) === '1',
    () => true,
  );

  useEffect(() => {
    if (!dismissed) trackOnce('concierge_cta_view');
  }, [dismissed]);

  if (dismissed) return null;

  return (
    <div
      data-testid="concierge-cta"
      className="relative rounded-2xl border border-indigo-200 bg-gradient-to-r from-indigo-50 to-violet-50 px-5 py-4 sm:px-6 sm:py-5"
    >
      <button
        type="button"
        aria-label={t('results.conciergeCta.dismiss')}
        data-testid="concierge-cta-dismiss"
        onClick={() => {
          // Dispatched unconditionally: a failed write (stale/blocked owner)
          // means the re-read below resolves to the SAME "not dismissed"
          // truth the write itself was gated against — there is no window
          // where dispatching could show a dismissal that never landed.
          writeUserScopedRaw(STORAGE_KEYS.RESULTS_CTA_DISMISSED, '1', captureOwnerToken());
          window.dispatchEvent(new Event(DISMISS_EVENT));
        }}
        className="absolute top-3 right-3 p-1 text-indigo-300 hover:text-indigo-500 transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-6">
        <div className="flex-1 min-w-0">
          <p className="text-[15px] font-semibold text-gray-900 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-indigo-600 shrink-0" aria-hidden="true" />
            {t('results.conciergeCta.title')}
          </p>
          <p className="mt-1 text-[13px] leading-relaxed text-gray-600">
            {t('results.conciergeCta.desc')}
          </p>
        </div>
        <Link
          href="/account"
          onClick={() => void track('intent_clicked', { source: 'results' })}
          className="shrink-0 inline-flex items-center justify-center px-5 py-2.5 rounded-full bg-indigo-600 text-white text-[13.5px] font-semibold hover:bg-indigo-700 transition-colors"
        >
          {t('results.conciergeCta.button')}
        </Link>
      </div>
    </div>
  );
}
