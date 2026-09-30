'use client';

import { useT } from '@/i18n/client';
import { RELEASE_SCOPE } from '@/lib/release-scope';

const STEPS = [
  'profile',
  'matches',
  ...(RELEASE_SCOPE.compare ? ['compare' as const] : []),
  ...(RELEASE_SCOPE.askAi ? ['act' as const] : []),
  'email',
  'tracker',
] as const;

/**
 * How JoinALab works, one step per card. The screenshots that illustrated the
 * steps were captured on 2026-07-06, before the release scope closed: they
 * showed the retired Fellowships and Roadmap nav, a closed AI-match toggle, a
 * real faculty email and an outdated résumé-storage claim. They were removed
 * rather than shown; recapture them from the release build with a synthetic
 * record before adding images back.
 */
export function WalkthroughSection() {
  const { t } = useT();
  return (
    <section aria-labelledby="walkthrough-heading" className="mt-20">
      <div className="text-center mb-10">
        <h2 id="walkthrough-heading" className="text-2xl sm:text-3xl font-bold text-gray-900 tracking-tight">
          {t('home.walkthrough.title')}
        </h2>
        <p className="mt-2 text-[15px] text-gray-500">{t('home.walkthrough.subtitle')}</p>
      </div>

      <ol className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {STEPS.map((key, i) => (
          <li key={key} className="rounded-2xl border border-gray-200 bg-white px-4 py-4">
            <div className="flex items-center gap-3">
              <span
                aria-hidden="true"
                className="shrink-0 w-7 h-7 rounded-full bg-indigo-600 text-white text-[13px] font-semibold inline-flex items-center justify-center"
              >
                {i + 1}
              </span>
              <h3 className="text-[15px] font-semibold text-gray-800">
                {t(`home.walkthrough.steps.${key}.title`)}
              </h3>
            </div>
            <p className="mt-2 text-[13px] leading-relaxed text-gray-500">
              {t(`home.walkthrough.steps.${key}.caption`)}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
