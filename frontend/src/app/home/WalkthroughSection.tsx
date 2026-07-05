'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import Image from 'next/image';
import type { TFunc } from './types';

const STEPS = [
  { key: 'profile', image: '/walkthrough/step-profile.webp' },
  { key: 'matches', image: '/walkthrough/step-matches.webp' },
  { key: 'compare', image: '/walkthrough/step-compare.webp' },
  { key: 'act', image: '/walkthrough/step-act.webp' },
  { key: 'email', image: '/walkthrough/step-email.webp' },
  { key: 'tracker', image: '/walkthrough/step-tracker.webp' },
] as const;

const STEP_MS = 5000;

function subscribeReducedMotion(onChange: () => void) {
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
  mq.addEventListener('change', onChange);
  return () => mq.removeEventListener('change', onChange);
}

/**
 * Product walkthrough on the landing page — an auto-advancing tour of the six
 * core features, captured as real 1440px WebP screenshots (regenerate with a
 * seeded profile + local backend whenever the UI meaningfully changes; keep
 * each under ~100KB). Autoplay pauses on hover, stops for good once the user
 * picks a step, and never runs under prefers-reduced-motion or off-screen.
 */
export function WalkthroughSection({ t }: { t: TFunc }) {
  const [active, setActive] = useState(0);
  const [manual, setManual] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [inView, setInView] = useState(false);
  const sectionRef = useRef<HTMLElement | null>(null);

  // External-store read (not state-in-effect): SSR snapshot says reduced, so
  // the server render has no animation and hydration can't mismatch.
  const reducedMotion = useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    () => true,
  );

  useEffect(() => {
    const el = sectionRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const obs = new IntersectionObserver(
      ([entry]) => setInView(entry.isIntersecting),
      { threshold: 0.25 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const playing = inView && !manual && !hovered && !reducedMotion;

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setActive((a) => (a + 1) % STEPS.length), STEP_MS);
    return () => clearInterval(id);
  }, [playing]);

  return (
    <section ref={sectionRef} aria-labelledby="walkthrough-heading" className="mt-20">
      <style>{'@keyframes ofe-walk-fill { from { width: 0% } to { width: 100% } }'}</style>
      <div className="text-center mb-10">
        <h2 id="walkthrough-heading" className="text-2xl sm:text-3xl font-bold text-gray-900 tracking-tight">
          {t('home.walkthrough.title')}
        </h2>
        <p className="mt-2 text-[15px] text-gray-500">{t('home.walkthrough.subtitle')}</p>
      </div>

      <div
        className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <div className="lg:col-span-4 flex flex-col gap-2.5" role="tablist" aria-label={t('home.walkthrough.title')}>
          {STEPS.map((s, i) => (
            <button
              key={s.key}
              type="button"
              role="tab"
              aria-selected={i === active}
              onClick={() => { setActive(i); setManual(true); }}
              className={`relative text-left rounded-2xl border px-4 py-3 transition-all duration-200 ${
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
              <p
                className={`text-[13px] leading-relaxed text-gray-500 overflow-hidden transition-all duration-300 ${
                  i === active ? 'mt-2 max-h-24 opacity-100' : 'mt-0 max-h-0 opacity-0'
                }`}
              >
                {t(`home.walkthrough.steps.${s.key}.caption`)}
              </p>
              {playing && i === active && (
                <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden rounded-b-2xl">
                  <span
                    key={active}
                    className="block h-full bg-indigo-500/70"
                    style={{ animation: `ofe-walk-fill ${STEP_MS}ms linear forwards` }}
                  />
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="lg:col-span-8">
          <div className="rounded-2xl border border-gray-200 bg-white p-2 shadow-[0_8px_30px_rgba(15,23,42,0.06)] overflow-hidden">
            <div className="relative w-full aspect-[16/10] rounded-xl border border-gray-100 overflow-hidden">
              {STEPS.map((s, i) => (
                <Image
                  key={s.key}
                  src={s.image}
                  alt={t(`home.walkthrough.steps.${s.key}.title`)}
                  fill
                  sizes="(min-width: 1024px) 60vw, 100vw"
                  loading={i === 0 ? 'eager' : 'lazy'}
                  className={`object-cover transition-opacity duration-500 ${
                    i === active ? 'opacity-100' : 'opacity-0'
                  }`}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
