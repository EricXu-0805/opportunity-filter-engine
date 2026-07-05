'use client';

import { useState } from 'react';
import Image from 'next/image';
import type { TFunc } from './types';

const STEPS = [
  { key: 'profile', image: '/walkthrough/step-profile.webp' },
  { key: 'matches', image: '/walkthrough/step-matches.webp' },
  { key: 'act', image: '/walkthrough/step-act.webp' },
] as const;

/**
 * Product walkthrough on the landing page — real screenshots of the three-step
 * funnel (profile → ranked matches → act on one). Assets are 1440px WebP
 * captures regenerated via frontend/walk-capture instructions whenever the UI
 * meaningfully changes; keep them under ~100KB each.
 */
export function WalkthroughSection({ t }: { t: TFunc }) {
  const [active, setActive] = useState(0);
  const step = STEPS[active];

  return (
    <section aria-labelledby="walkthrough-heading" className="mt-20">
      <div className="text-center mb-10">
        <h2 id="walkthrough-heading" className="text-2xl sm:text-3xl font-bold text-gray-900 tracking-tight">
          {t('home.walkthrough.title')}
        </h2>
        <p className="mt-2 text-[15px] text-gray-500">{t('home.walkthrough.subtitle')}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className="lg:col-span-4 flex flex-col gap-3" role="tablist" aria-label={t('home.walkthrough.title')}>
          {STEPS.map((s, i) => (
            <button
              key={s.key}
              type="button"
              role="tab"
              aria-selected={i === active}
              onClick={() => setActive(i)}
              className={`text-left rounded-2xl border px-5 py-4 transition-all duration-200 ${
                i === active
                  ? 'border-indigo-300 bg-indigo-50/60 shadow-sm'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <div className="flex items-center gap-3">
                <span
                  className={`shrink-0 w-7 h-7 rounded-full text-[13px] font-semibold inline-flex items-center justify-center ${
                    i === active ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-500'
                  }`}
                >
                  {i + 1}
                </span>
                <span className={`text-[15px] font-semibold ${i === active ? 'text-indigo-700' : 'text-gray-800'}`}>
                  {t(`home.walkthrough.steps.${s.key}.title`)}
                </span>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-gray-500">
                {t(`home.walkthrough.steps.${s.key}.caption`)}
              </p>
            </button>
          ))}
        </div>

        <div className="lg:col-span-8">
          <div className="rounded-2xl border border-gray-200 bg-white p-2 shadow-[0_8px_30px_rgba(15,23,42,0.06)] overflow-hidden">
            <Image
              key={step.key}
              src={step.image}
              alt={t(`home.walkthrough.steps.${step.key}.title`)}
              width={1440}
              height={900}
              loading="lazy"
              className="w-full h-auto rounded-xl border border-gray-100"
            />
          </div>
        </div>
      </div>
    </section>
  );
}
