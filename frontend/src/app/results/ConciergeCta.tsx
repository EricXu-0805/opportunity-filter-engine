'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Sparkles, X } from 'lucide-react';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { track, trackOnce } from '@/lib/analytics';
import type { TFunc } from './types';

/**
 * The concierge willingness-to-pay funnel entry, placed inside the results
 * feed where the buying moment happens (the intent CTA previously lived only
 * on /account, leaving the funnel dark). Links to the account Plan card,
 * which is the waitlist capture with payments off and the order flow with
 * payments on. Dismissal persists per browser.
 */
export function ConciergeCta({ t }: { t: TFunc }) {
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    const seen = localStorage.getItem(STORAGE_KEYS.RESULTS_CTA_DISMISSED) === '1';
    setDismissed(seen);
    if (!seen) trackOnce('concierge_cta_view');
  }, []);

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
          localStorage.setItem(STORAGE_KEYS.RESULTS_CTA_DISMISSED, '1');
          setDismissed(true);
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
