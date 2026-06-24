'use client';

import { useCallback, useEffect, useState } from 'react';
import { X, ArrowLeft, ArrowRight, Star, Check, Sparkles, Calendar, Target, Send } from 'lucide-react';
import { useT } from '@/i18n/client';
import { track } from '@/lib/analytics';
import { STORAGE_KEYS } from '@/lib/storage-keys';

type T = (key: string, vars?: Record<string, string | number>) => string;
type SlideKey =
  | 'welcome' | 'generate' | 'favorites' | 'compare'
  | 'tracker' | 'dashboard' | 'roadmap' | 'ready';

const SLIDES: SlideKey[] = [
  'welcome', 'generate', 'favorites', 'compare', 'tracker', 'dashboard', 'roadmap', 'ready',
];

// ---- per-feature mini visuals (illustrative, language-neutral where possible) ----

function WelcomeVisual() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-2">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-600 to-blue-500 flex items-center justify-center shadow-lg">
        <Sparkles className="w-7 h-7 text-white" strokeWidth={2.2} aria-hidden="true" />
      </div>
      <p className="text-[20px] font-bold tracking-tight text-gray-900">
        JoinA<span className="text-blue-600">Lab</span>
      </p>
    </div>
  );
}

function ResultsVisual({ t }: { t: T }) {
  const rows = [
    { pct: '94%', tier: t('onboarding.tierHigh'), dot: 'bg-emerald-500', badge: 'bg-emerald-50 text-emerald-700' },
    { pct: '88%', tier: t('onboarding.tierGood'), dot: 'bg-blue-500', badge: 'bg-blue-50 text-blue-700' },
    { pct: '71%', tier: t('onboarding.tierReach'), dot: 'bg-amber-500', badge: 'bg-amber-50 text-amber-700' },
  ];
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.pct} className="flex items-center gap-3 rounded-xl border border-gray-100 bg-white px-3 py-2.5 shadow-sm">
          <span className={`shrink-0 w-2 h-2 rounded-full ${r.dot}`} />
          <div className="flex-1 min-w-0">
            <div className="h-2.5 w-3/4 rounded bg-gray-200 mb-1.5" />
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${r.badge}`}>{r.tier}</span>
          </div>
          <span className="text-[13px] font-bold text-gray-900">{r.pct}</span>
        </div>
      ))}
    </div>
  );
}

function FavoritesVisual() {
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {[0, 1].map((k) => (
        <div key={k} className="rounded-xl border border-gray-100 bg-white p-3 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="h-2 w-12 rounded bg-gray-200" />
            <Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" aria-hidden="true" />
          </div>
          <div className="mt-2.5 h-2 w-full rounded bg-gray-100" />
          <div className="mt-1.5 h-2 w-2/3 rounded bg-gray-100" />
        </div>
      ))}
    </div>
  );
}

function RadarVisual({ t }: { t: T }) {
  const cx = 100, cy = 86, r = 54;
  const labels = [
    t('onboarding.dimSkill'), t('onboarding.dimEligibility'), t('onboarding.dimEffort'),
    t('onboarding.dimPay'), t('onboarding.dimDeadline'), t('onboarding.dimIntl'),
  ];
  const a = [92, 88, 60, 100, 78, 100];
  const b = [68, 64, 92, 50, 96, 100];
  const pt = (idx: number, val: number): [number, number] => {
    const ang = -Math.PI / 2 + idx * (Math.PI * 2 / 6);
    return [cx + Math.cos(ang) * r * (val / 100), cy + Math.sin(ang) * r * (val / 100)];
  };
  const poly = (vals: number[]) => vals.map((v, idx) => pt(idx, v).join(',')).join(' ');
  const ring = (scale: number) => Array.from({ length: 6 }, (_, idx) => pt(idx, scale * 100).join(',')).join(' ');
  return (
    <svg viewBox="0 0 200 178" className="w-full max-w-[260px] mx-auto" role="img" aria-label={t('onboarding.compareTitle')}>
      {[0.34, 0.67, 1].map((s) => (
        <polygon key={s} points={ring(s)} fill="none" stroke="#e5e7eb" strokeWidth={1} />
      ))}
      {Array.from({ length: 6 }).map((_, idx) => {
        const [x, y] = pt(idx, 100);
        return <line key={idx} x1={cx} y1={cy} x2={x} y2={y} stroke="#e5e7eb" strokeWidth={1} />;
      })}
      <polygon points={poly(b)} fill="rgba(245,158,11,0.16)" stroke="#f59e0b" strokeWidth={1.5} />
      <polygon points={poly(a)} fill="rgba(37,99,235,0.18)" stroke="#2563eb" strokeWidth={1.5} />
      {labels.map((lab, idx) => {
        const [x, y] = pt(idx, 134);
        return (
          <text key={lab} x={x} y={y} fontSize={8.5} fill="#6b7280" textAnchor="middle" dominantBaseline="middle">
            {lab}
          </text>
        );
      })}
    </svg>
  );
}

function TrackerVisual({ t }: { t: T }) {
  const stages = [
    { l: t('onboarding.statApplied'), c: 'bg-blue-50 text-blue-700' },
    { l: t('onboarding.statReplied'), c: 'bg-emerald-50 text-emerald-700' },
    { l: t('onboarding.statInterview'), c: 'bg-violet-50 text-violet-700' },
  ];
  return (
    <div className="flex items-center justify-center gap-1.5 flex-wrap py-3">
      {stages.map((s, idx) => (
        <span key={s.l} className="flex items-center gap-1.5">
          <span className={`text-[12px] font-medium px-2.5 py-1 rounded-full ${s.c}`}>{s.l}</span>
          {idx < stages.length - 1 && <ArrowRight className="w-3.5 h-3.5 text-gray-300" aria-hidden="true" />}
        </span>
      ))}
    </div>
  );
}

function DashboardVisual() {
  const tiles = [
    { n: '128', Icon: Target, c: 'text-blue-600 bg-blue-50' },
    { n: '12', Icon: Star, c: 'text-amber-600 bg-amber-50' },
    { n: '4', Icon: Send, c: 'text-emerald-600 bg-emerald-50' },
  ];
  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-3 gap-2.5">
        {tiles.map((tile) => (
          <div key={tile.n} className="rounded-xl border border-gray-100 bg-white p-3 shadow-sm">
            <span className={`inline-flex w-6 h-6 rounded-lg items-center justify-center ${tile.c}`}>
              <tile.Icon className="w-3.5 h-3.5" aria-hidden="true" />
            </span>
            <p className="mt-2 text-[18px] font-bold text-gray-900 leading-none">{tile.n}</p>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 rounded-xl border border-gray-100 bg-white px-3 py-2 shadow-sm">
        <Calendar className="w-3.5 h-3.5 text-rose-500" aria-hidden="true" />
        <div className="h-2 w-1/2 rounded bg-gray-200" />
        <span className="ml-auto text-[11px] font-semibold text-rose-600">5d</span>
      </div>
    </div>
  );
}

function RoadmapVisual() {
  const steps = [true, true, false, false];
  return (
    <div className="space-y-2 py-1">
      {steps.map((done, k) => (
        <div key={k} className="flex items-center gap-2.5">
          <span className={`shrink-0 w-5 h-5 rounded-full flex items-center justify-center ${done ? 'bg-emerald-500 text-white' : 'border-2 border-gray-200'}`}>
            {done && <Check className="w-3 h-3" strokeWidth={3} aria-hidden="true" />}
          </span>
          <div className={`h-2.5 rounded ${done ? 'bg-gray-200 w-2/3' : 'bg-gray-100 w-3/4'}`} />
        </div>
      ))}
    </div>
  );
}

function ReadyVisual() {
  return (
    <div className="flex items-center justify-center py-4">
      <div className="w-16 h-16 rounded-full bg-emerald-500 flex items-center justify-center shadow-lg">
        <Check className="w-8 h-8 text-white" strokeWidth={2.5} aria-hidden="true" />
      </div>
    </div>
  );
}

function SlideVisual({ slide, t }: { slide: SlideKey; t: T }) {
  switch (slide) {
    case 'generate': return <ResultsVisual t={t} />;
    case 'favorites': return <FavoritesVisual />;
    case 'compare': return <RadarVisual t={t} />;
    case 'tracker': return <TrackerVisual t={t} />;
    case 'dashboard': return <DashboardVisual />;
    case 'roadmap': return <RoadmapVisual />;
    case 'ready': return <ReadyVisual />;
    default: return <WelcomeVisual />;
  }
}

// First-visit product tour. Eight switchable slides — each pairs a mini visual
// of a real feature with a one-line explanation — that the user pages through
// (Back / Next, progress dots) and finishes with "Try it" into the engine.
// Shown once, gated on localStorage. Server renders nothing; client upgrades
// after mount to avoid a hydration mismatch.
export default function OnboardingIntro() {
  const { t } = useT();
  const [show, setShow] = useState(false);
  const [i, setI] = useState(0);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- first-visit gate reads localStorage (window-only), so the decision must run after mount to avoid an SSR/hydration mismatch
      if (localStorage.getItem(STORAGE_KEYS.ONBOARDING_SEEN) !== '1') setShow(true);
    } catch { /* storage unavailable */ }
  }, []);

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

  const slide = SLIDES[i];
  const isLast = i === SLIDES.length - 1;
  const next = () => (isLast ? dismiss(true) : setI((n) => n + 1));
  const back = () => setI((n) => Math.max(0, n - 1));

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('onboarding.welcomeTitle')}
      data-testid="onboarding-intro"
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
    >
      <div
        className="absolute inset-0 bg-gray-900/70 backdrop-blur-sm"
        onClick={() => dismiss(false)}
        aria-hidden="true"
      />
      <div className="relative w-full max-w-md bg-white rounded-3xl shadow-2xl overflow-hidden">
        <button
          type="button"
          onClick={() => dismiss(false)}
          aria-label={t('onboarding.close')}
          className="absolute top-3.5 right-3.5 z-10 p-1.5 text-gray-400 hover:text-gray-700 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="px-6 pt-8 pb-5">
          {/* visual + copy re-key on slide change so .animate-in replays (the
              "streaming" page-to-page feel) */}
          <div key={i} className="animate-in">
            <div className="min-h-[176px] flex flex-col justify-center">
              <SlideVisual slide={slide} t={t} />
            </div>
            <h2 className="mt-4 text-[18px] font-bold tracking-tight text-gray-900">
              {t(`onboarding.${slide}Title`)}
            </h2>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-gray-500 min-h-[60px]">
              {t(`onboarding.${slide}Body`)}
            </p>
          </div>

          {/* progress dots */}
          <div className="mt-4 flex items-center justify-center gap-1.5" aria-hidden="true">
            {SLIDES.map((s, idx) => (
              <span
                key={s}
                className={`h-1.5 rounded-full transition-all ${idx === i ? 'w-5 bg-gray-900' : 'w-1.5 bg-gray-200'}`}
              />
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-black/[0.05]">
          {i === 0 ? (
            <button
              type="button"
              onClick={() => dismiss(false)}
              data-testid="onboarding-skip"
              className="text-[13px] font-medium text-gray-400 hover:text-gray-700 transition-colors"
            >
              {t('onboarding.skip')}
            </button>
          ) : (
            <button
              type="button"
              onClick={back}
              data-testid="onboarding-back"
              className="inline-flex items-center gap-1 text-[13px] font-medium text-gray-500 hover:text-gray-900 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" aria-hidden="true" />
              {t('onboarding.back')}
            </button>
          )}

          <button
            type="button"
            onClick={next}
            data-testid="onboarding-primary"
            className="inline-flex items-center gap-1.5 rounded-full bg-gray-900 text-white text-[14px] font-semibold px-6 py-2.5 hover:bg-gray-800 transition-colors"
          >
            {isLast ? t('onboarding.cta') : t('onboarding.next')}
            <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}
