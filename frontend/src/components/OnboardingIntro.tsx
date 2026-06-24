'use client';

import { useCallback, useEffect, useState } from 'react';
import { UserRound, Sparkles, Send, X } from 'lucide-react';
import { useT } from '@/i18n/client';
import { track } from '@/lib/analytics';
import { STORAGE_KEYS } from '@/lib/storage-keys';

const STEP_ICONS = [UserRound, Sparkles, Send] as const;

// First-visit-only product intro. The three steps stream in one after another
// (existing `.animate-in` fade-slide), then "Try it" dismisses into the engine
// (the homepage profile form). Shown once — gated on localStorage so it never
// re-nags. Server renders nothing; the client upgrades after mount to avoid a
// hydration mismatch (localStorage is window-only).
export default function OnboardingIntro() {
  const { t } = useT();
  const [show, setShow] = useState(false);
  const [revealed, setRevealed] = useState(0);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- first-visit gate reads localStorage (window-only), so the decision must run after mount to avoid an SSR/hydration mismatch
      if (localStorage.getItem(STORAGE_KEYS.ONBOARDING_SEEN) !== '1') setShow(true);
    } catch { /* storage unavailable */ }
  }, []);

  useEffect(() => {
    if (!show || revealed >= STEP_ICONS.length) return;
    const id = setTimeout(() => setRevealed((n) => n + 1), revealed === 0 ? 200 : 500);
    return () => clearTimeout(id);
  }, [show, revealed]);

  const dismiss = useCallback((completed: boolean) => {
    try { localStorage.setItem(STORAGE_KEYS.ONBOARDING_SEEN, '1'); } catch { /* ignore */ }
    if (completed) track('onboarding_completed');
    setShow(false);
  }, []);

  useEffect(() => {
    if (!show) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') dismiss(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [show, dismiss]);

  if (!show) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('onboarding.title')}
      data-testid="onboarding-intro"
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
    >
      <div
        className="absolute inset-0 bg-gray-900/70 backdrop-blur-sm"
        onClick={() => dismiss(false)}
        aria-hidden="true"
      />
      <div className="relative w-full max-w-lg bg-white rounded-3xl shadow-2xl overflow-hidden animate-in">
        <button
          type="button"
          onClick={() => dismiss(false)}
          aria-label={t('onboarding.close')}
          className="absolute top-4 right-4 p-1.5 text-gray-400 hover:text-gray-700 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="px-7 pt-9 pb-7">
          <p className="text-[22px] font-bold tracking-tight text-gray-900">
            JoinA<span className="text-blue-600">Lab</span>
          </p>
          <h2 className="mt-2 text-[15px] text-gray-500">{t('onboarding.subtitle')}</h2>

          <div className="mt-6 space-y-3 min-h-[180px]">
            {[0, 1, 2].map((i) => {
              if (i >= revealed) return null;
              const Icon = STEP_ICONS[i];
              return (
                <div key={i} className="flex items-start gap-3 animate-in" data-testid={`onboarding-step-${i}`}>
                  <div className="shrink-0 w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center">
                    <Icon className="w-4 h-4" strokeWidth={2} aria-hidden="true" />
                  </div>
                  <div>
                    <p className="text-[14px] font-semibold text-gray-900">{t(`onboarding.step${i + 1}Title`)}</p>
                    <p className="text-[13px] text-gray-500 leading-snug">{t(`onboarding.step${i + 1}Body`)}</p>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-6 flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => dismiss(false)}
              className="text-[13px] font-medium text-gray-400 hover:text-gray-700 transition-colors"
            >
              {t('onboarding.skip')}
            </button>
            <button
              type="button"
              onClick={() => dismiss(true)}
              data-testid="onboarding-cta"
              className="inline-flex items-center gap-1.5 rounded-full bg-gray-900 text-white text-[14px] font-semibold px-6 py-2.5 hover:bg-gray-800 transition-colors"
            >
              {t('onboarding.cta')}
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
