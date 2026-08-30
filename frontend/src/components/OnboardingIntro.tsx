'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Star, Check, Sparkles, Calendar, Target, Send, MapPin } from 'lucide-react';
import { useT } from '@/i18n/client';
import { track } from '@/lib/analytics';
import { isOwnerTokenValid, onLocalOwnerStateChange } from '@/lib/identity-owner';
import {
  hydrateProfile,
  makeProfileViewSnapshot,
  type ProfileViewSnapshot,
} from '@/lib/profile-sync';
import type { ProfileData } from '@/lib/types';
import { persistHomeSchool } from '@/lib/school-confirmation';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { SCHOOLS } from '@/lib/schools';

type T = (key: string, vars?: Record<string, string | number>) => string;
type SlideKey =
  | 'welcome' | 'generate' | 'favorites' | 'compare'
  | 'tracker' | 'dashboard' | 'roadmap' | 'school';

const SLIDES: SlideKey[] = [
  'welcome',
  'generate',
  'favorites',
  ...(RELEASE_SCOPE.compare ? ['compare' as const] : []),
  'tracker',
  'dashboard',
  ...(RELEASE_SCOPE.roadmap ? ['roadmap' as const] : []),
  'school',
];

// Feature slides that carry a "where to find it" location chip (welcome/school don't).
const LOCATIONS: Partial<Record<SlideKey, string>> = {
  generate: 'generateLoc',
  favorites: 'favoritesLoc',
  compare: 'compareLoc',
  tracker: 'trackerLoc',
  dashboard: 'dashboardLoc',
  roadmap: 'roadmapLoc',
};

// ---- per-feature mini visuals — each "assembles" on view (staggered .ob-* anims) ----

function WelcomeVisual({ t }: { t: T }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3.5 py-2">
      <div className="ob-pop w-[72px] h-[72px] rounded-[20px] bg-gradient-to-br from-indigo-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-indigo-500/30">
        <Sparkles className="w-9 h-9 text-white" strokeWidth={2.2} aria-hidden="true" />
      </div>
      <p className="ob-rise text-[24px] font-bold tracking-tight text-gray-900" style={{ animationDelay: '0.12s' }}>
        JoinA<span className="text-indigo-600">Lab</span>
      </p>
      <p className="ob-rise text-[13px] text-gray-500" style={{ animationDelay: '0.22s' }}>
        {t('onboarding.welcomeTitle')}
      </p>
    </div>
  );
}

function ResultsVisual({ t }: { t: T }) {
  const rows = [
    { title: t('onboarding.exResearch'), pct: 94, tier: t('onboarding.tierHigh'), bar: 'bg-emerald-500', dot: 'bg-emerald-500', badge: 'bg-emerald-50 text-emerald-700' },
    { title: t('onboarding.exInternship'), pct: 88, tier: t('onboarding.tierGood'), bar: 'bg-indigo-500', dot: 'bg-indigo-500', badge: 'bg-indigo-50 text-indigo-700' },
    ...(RELEASE_SCOPE.fellowships
      ? [{ title: t('onboarding.exFellowship'), pct: 71, tier: t('onboarding.tierReach'), bar: 'bg-amber-500', dot: 'bg-amber-500', badge: 'bg-amber-50 text-amber-700' }]
      : []),
  ];
  return (
    <div className="w-full max-w-[360px] mx-auto space-y-2.5">
      {rows.map((r, idx) => (
        <div
          key={r.title}
          className="ob-rise rounded-xl border border-gray-100 bg-white px-3.5 py-2.5 shadow-sm"
          style={{ animationDelay: `${idx * 0.1}s` }}
        >
          <div className="flex items-center gap-2.5">
            <span className={`shrink-0 w-2 h-2 rounded-full ${r.dot}`} />
            <span className="flex-1 min-w-0 truncate text-[13px] font-medium text-gray-800">{r.title}</span>
            <span className="text-[13px] font-bold text-gray-900 tabular-nums">{r.pct}%</span>
          </div>
          <div className="mt-2 flex items-center gap-2.5">
            <span className="h-1.5 flex-1 rounded-full bg-gray-100 overflow-hidden">
              <span
                className={`block h-full rounded-full ob-bar ${r.bar}`}
                style={{ width: `${r.pct}%`, animationDelay: `${idx * 0.1 + 0.15}s` }}
              />
            </span>
            <span className={`shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded ${r.badge}`}>{r.tier}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function FavoritesVisual({ t }: { t: T }) {
  const cards = [t('onboarding.exResearch'), t('onboarding.exInternship')];
  return (
    <div className="grid grid-cols-2 gap-3 w-full max-w-[340px] mx-auto">
      {cards.map((title, k) => (
        <div
          key={title}
          className="ob-rise rounded-xl border border-gray-100 bg-white p-3.5 shadow-sm"
          style={{ animationDelay: `${k * 0.12}s` }}
        >
          <div className="flex items-start justify-between gap-2">
            <span className="text-[12.5px] font-medium text-gray-800 leading-snug">{title}</span>
            <Star
              className="ob-pop shrink-0 w-4 h-4 fill-amber-400 text-amber-400"
              style={{ animationDelay: `${k * 0.12 + 0.22}s` }}
              aria-hidden="true"
            />
          </div>
          <div className="mt-3 h-1.5 w-full rounded bg-gray-100" />
          <div className="mt-1.5 h-1.5 w-2/3 rounded bg-gray-100" />
        </div>
      ))}
    </div>
  );
}

function RadarVisual({ t }: { t: T }) {
  const cx = 100, cy = 86, r = 58;
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
    <svg viewBox="0 0 200 182" className="w-full max-w-[300px] mx-auto" role="img" aria-label={t('onboarding.compareTitle')}>
      {[0.34, 0.67, 1].map((s) => (
        <polygon key={s} points={ring(s)} fill="none" stroke="#e5e7eb" strokeWidth={1} />
      ))}
      {Array.from({ length: 6 }).map((_, idx) => {
        const [x, y] = pt(idx, 100);
        return <line key={idx} x1={cx} y1={cy} x2={x} y2={y} stroke="#e5e7eb" strokeWidth={1} />;
      })}
      <g className="ob-grow">
        <polygon points={poly(b)} fill="rgba(245,158,11,0.16)" stroke="#f59e0b" strokeWidth={1.5} />
        <polygon points={poly(a)} fill="rgba(79,70,229,0.18)" stroke="#4f46e5" strokeWidth={1.5} />
      </g>
      {labels.map((lab, idx) => {
        const [x, y] = pt(idx, 138);
        return (
          <text key={lab} x={x} y={y} fontSize={9} fill="#6b7280" textAnchor="middle" dominantBaseline="middle">
            {lab}
          </text>
        );
      })}
    </svg>
  );
}

function TrackerVisual({ t }: { t: T }) {
  const stages = [
    { l: t('onboarding.statApplied'), c: 'bg-indigo-50 text-indigo-700' },
    { l: t('onboarding.statReplied'), c: 'bg-emerald-50 text-emerald-700' },
    { l: t('onboarding.statInterview'), c: 'bg-violet-50 text-violet-700' },
  ];
  return (
    <div className="flex items-center justify-center gap-2 flex-wrap py-3">
      {stages.map((s, idx) => (
        <span key={s.l} className="flex items-center gap-2">
          <span
            className={`ob-pop text-[13px] font-medium px-3 py-1.5 rounded-full ${s.c}`}
            style={{ animationDelay: `${idx * 0.2}s` }}
          >
            {s.l}
          </span>
          {idx < stages.length - 1 && (
            <ArrowRight
              className="ob-pop w-4 h-4 text-gray-300"
              style={{ animationDelay: `${idx * 0.2 + 0.1}s` }}
              aria-hidden="true"
            />
          )}
        </span>
      ))}
    </div>
  );
}

function DashboardVisual({ t }: { t: T }) {
  const tiles = [
    { n: '128', Icon: Target, c: 'text-indigo-600 bg-indigo-50' },
    { n: '12', Icon: Star, c: 'text-amber-600 bg-amber-50' },
    { n: '4', Icon: Send, c: 'text-emerald-600 bg-emerald-50' },
  ];
  return (
    <div className="w-full max-w-[340px] mx-auto space-y-3">
      <div className="grid grid-cols-3 gap-3">
        {tiles.map((tile, idx) => (
          <div
            key={tile.n}
            className="ob-pop rounded-xl border border-gray-100 bg-white p-3 shadow-sm"
            style={{ animationDelay: `${idx * 0.1}s` }}
          >
            <span className={`inline-flex w-7 h-7 rounded-lg items-center justify-center ${tile.c}`}>
              <tile.Icon className="w-4 h-4" aria-hidden="true" />
            </span>
            <p className="mt-2 text-[20px] font-bold text-gray-900 leading-none tabular-nums">{tile.n}</p>
          </div>
        ))}
      </div>
      <div className="ob-rise flex items-center gap-2 rounded-xl border border-gray-100 bg-white px-3.5 py-2.5 shadow-sm" style={{ animationDelay: '0.32s' }}>
        <Calendar className="w-4 h-4 text-rose-500 shrink-0" aria-hidden="true" />
        <span className="text-[12px] text-gray-600">{t('onboarding.dimDeadline')}</span>
        <span className="ml-auto text-[12px] font-semibold text-rose-600 animate-pulse">5d</span>
      </div>
    </div>
  );
}

function RoadmapVisual({ t }: { t: T }) {
  const items = [
    { label: t('onboarding.roadmapEx1'), tag: t('onboarding.roadmapHave'), done: true },
    { label: t('onboarding.roadmapEx2'), tag: t('onboarding.roadmapHave'), done: true },
    { label: t('onboarding.roadmapEx3'), tag: t('onboarding.roadmapGap'), done: false },
    { label: t('onboarding.roadmapEx4'), tag: t('onboarding.roadmapGap'), done: false },
  ];
  return (
    <div className="w-full max-w-[300px] mx-auto space-y-2.5">
      {items.map((it, k) => (
        <div
          key={it.label}
          className="ob-rise flex items-center gap-3"
          style={{ animationDelay: `${k * 0.1}s` }}
        >
          <span className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${it.done ? 'bg-emerald-500 text-white' : 'border-2 border-gray-200 bg-white'}`}>
            {it.done
              ? <Check className="ob-pop w-3.5 h-3.5" strokeWidth={3} style={{ animationDelay: `${k * 0.1 + 0.18}s` }} aria-hidden="true" />
              : <span className="w-1.5 h-1.5 rounded-full bg-gray-300" />}
          </span>
          <span className="flex-1 text-[13px] font-medium text-gray-800">{it.label}</span>
          <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${it.done ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'}`}>
            {it.tag}
          </span>
        </div>
      ))}
    </div>
  );
}

function SlideVisual({ slide, t }: { slide: SlideKey; t: T }) {
  switch (slide) {
    case 'generate': return <ResultsVisual t={t} />;
    case 'favorites': return <FavoritesVisual t={t} />;
    case 'compare': return <RadarVisual t={t} />;
    case 'tracker': return <TrackerVisual t={t} />;
    case 'dashboard': return <DashboardVisual t={t} />;
    case 'roadmap': return <RoadmapVisual t={t} />;
    default: return <WelcomeVisual t={t} />;
  }
}

// Final-step school gate: a selectable list of every supported campus, default
// UIUC, with a live-data / coming-soon badge. Scrolls; the choice is held in the
// parent so paging back and forth preserves it.
function SchoolPicker({ t, locale, selected, onSelect }: {
  t: T; locale: string; selected: string; onSelect: (slug: string) => void;
}) {
  return (
    <div className="max-h-[220px] overflow-y-auto -mx-0.5 px-0.5 space-y-1.5" data-testid="onboarding-school-list">
      {SCHOOLS.map((s) => {
        const isSel = s.slug === selected;
        const live = s.coverage.campusOpportunities !== 'pending';
        return (
          <button
            key={s.slug}
            type="button"
            onClick={() => onSelect(s.slug)}
            aria-pressed={isSel}
            data-testid={`onboarding-school-${s.slug}`}
            className={`w-full flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors ${
              isSel ? 'border-indigo-500 bg-indigo-50/60 ring-1 ring-indigo-500' : 'border-gray-200 bg-white hover:bg-gray-50'
            }`}
          >
            <span className="shrink-0 w-2.5 h-2.5 rounded-full" style={{ backgroundColor: s.color }} aria-hidden="true" />
            <span className="flex-1 min-w-0">
              <span className="block text-[13.5px] font-semibold text-gray-900 truncate">
                {locale === 'zh' ? s.nameZh : s.shortName}
              </span>
              <span className="block text-[11px] text-gray-400 truncate">{s.location}</span>
            </span>
            <span className={`shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
              live ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'
            }`}>
              {t(live ? 'onboarding.schoolLiveBadge' : 'onboarding.schoolSoonBadge')}
            </span>
            {isSel
              ? <Check className="shrink-0 w-4 h-4 text-indigo-600" aria-hidden="true" />
              : <span className="shrink-0 w-4 h-4" aria-hidden="true" />}
          </button>
        );
      })}
    </div>
  );
}

// First-visit product tour. Feature slides each pair an animated "demo" of a real
// feature with a one-line explanation and a "where to find it" chip; the final
// slide is a school gate (default UIUC, changeable later in the profile). Skipping
// the tour — or pressing Esc / clicking the backdrop — jumps straight to that gate
// rather than dismissing, so a campus is always chosen before the app is used.
// A hydration that fails because ownership is not confirmed yet resolves on its
// own within a tick or two; these bound how long the tour keeps asking.
const ACCEPT_RETRIES = 4;
const ACCEPT_RETRY_MS = 400;

// Shown once, gated on localStorage; server renders nothing, client upgrades after
// mount to avoid a hydration mismatch.
export default function OnboardingIntro() {
  const { t, locale } = useT();

  const [show, setShow] = useState(false);
  // The view this tour will confirm against, accepted ONCE from a real
  // hydration. Not fabricated: "the tour has not been seen on this browser"
  // does not mean there is no row — storage gets cleared, and people sign in
  // on a second device. Declaring an unknown baseline here would let a
  // one-field write claim it was made against nothing while a real row sits
  // in the cloud.
  const [view, setView] = useState<ProfileViewSnapshot | null>(null);
  // Which acceptance is current. An identity switch mid-tour starts a new
  // one, and the previous hydration's answer must not land on top of it.
  const acceptSeqRef = useRef(0);
  const [i, setI] = useState(0);
  // Nav direction drives the slide-in transition: +1 = forward (enter from the
  // right), -1 = back (enter from the left).
  const [dir, setDir] = useState<1 | -1>(1);
  const [schoolSlug, setSchoolSlug] = useState('uiuc');
  const [finishing, setFinishing] = useState(false);
  const finishInFlightRef = useRef(false);
  // The tour stays open when the campus could not be saved — see finish().
  const [finishError, setFinishError] = useState(false);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- first-visit gate reads localStorage (window-only), so the decision must run after mount to avoid an SSR/hydration mismatch
      if (localStorage.getItem(STORAGE_KEYS.ONBOARDING_SEEN) !== '1') setShow(true);
    } catch { /* storage unavailable */ }
  }, []);

  useEffect(() => {
    if (!show) return;
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const accept = (attempt = 0) => {
      acceptSeqRef.current += 1;
      const seq = acceptSeqRef.current;
      // Drop a baseline that is no longer valid for whoever owns the browser
      // now — but only that one. Clearing unconditionally on every attempt
      // (which is what this did) means each retry throws away a baseline that
      // had already landed, and the confirm gate flickers shut behind a read
      // that has not even resolved yet.
      setView((v) => (v && isOwnerTokenValid(v.token, v.token.uid) ? v : null));
      hydrateProfile().then((h) => {
        if (cancelled) return;
        // Deliberately NOT gated on `seq` still being current. A read belongs
        // to the identity in effect now if its own token is still valid, and
        // that is what isOwnerTokenValid checks: an identity switch bumps the
        // owner epoch, which the token then fails. `seq`, by contrast, also
        // advances on a SAME-identity readiness transition, and every load
        // fires two of those — so the counter check threw away the one read
        // that had succeeded ("hydrate ok seq 1 cur 3 ... valid true"),
        // leaving `view` null and the last step's CTA disabled forever on a
        // tour that cannot be dismissed. Every first-time visitor was stuck.
        if (!isOwnerTokenValid(h.token, h.token.uid)) return;
        setView(makeProfileViewSnapshot({
          baseProfile: h.baseProfile,
          renderedProfile: h.profile ?? ({} as ProfileData),
          revision: h.revision,
          token: h.token,
          identityGeneration: h.token.epoch,
          source: 'hydration',
        }));
      }).catch(() => {
        if (cancelled || seq !== acceptSeqRef.current) return;
        // A read that FAILED is not "there is no row". Fail closed: the tour
        // stays open and unconfirmable rather than writing against a baseline
        // it could not establish.
        // A failure is not evidence that an ALREADY-accepted baseline is
        // wrong, and dropping one costs the student the only read that landed.
        // Only an invalid one goes.
        setView((v) => (v && isOwnerTokenValid(v.token, v.token.uid) ? v : null));
        // Do not fail closed FOREVER. The read that fails here is usually
        // "ownership not confirmed yet", which resolves on its own moments
        // later — and the owner-state notification that would have retried it
        // may already have fired. Without this the tour's own retry depends on
        // an event that has been and gone.
        if (attempt < ACCEPT_RETRIES) {
          retry = setTimeout(() => accept(attempt + 1), ACCEPT_RETRY_MS * (attempt + 1));
        }
      });
    };
    accept();
    const off = onLocalOwnerStateChange(() => accept());
    return () => {
      cancelled = true;
      if (retry !== undefined) clearTimeout(retry);
      off();
    };
  }, [show]);

  const gotoSchoolGate = useCallback(() => { setDir(1); setI(SLIDES.length - 1); }, []);

  useEffect(() => {
    if (!show) return;
    // Esc never dismisses; it routes to the school gate (no-op once already there),
    // so the campus choice can't be bypassed.
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') gotoSchoolGate(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [show, gotoSchoolGate]);

  if (!show) return null;

  const slide = SLIDES[i];
  const isLast = i === SLIDES.length - 1;
  const locKey = LOCATIONS[slide];

  // Strictly ordered, and every step gated on the one before it:
  //   persist the campus (a single-key CAS patch) -> write the confirmation
  //   receipt -> broadcast -> track -> mark the tour seen -> close.
  // persistHomeSchool owns the first three (the receipt has to be written
  // before its own broadcast wakes the confirm gate). If the campus did not
  // land, NOTHING after it runs: a tour that closes on a failed save leaves
  // the user matched against a school they were never actually saved as, with
  // the gate suppressed by an ONBOARDING_SEEN flag they can't undo.
  const finish = async () => {
    // The ref, not the state: two clicks in the same tick both read the old
    // `finishing` and both run — two CAS writes, two receipts, two analytics
    // events for one decision.
    if (finishInFlightRef.current) return;
    // The exact object accepted above, never a fresh capture. Capturing a
    // token here would hand a choice made under one identity a currently-
    // valid token belonging to another, and every preflight downstream would
    // pass it.
    const accepted = view;
    if (!accepted) { setFinishError(true); return; }
    finishInFlightRef.current = true;
    setFinishing(true);
    try {
      const result = await persistHomeSchool(schoolSlug, accepted, { confirm: true });
      if (!result.ok) {
        setFinishError(true);
        return;
      }
      track('onboarding_completed', { school: schoolSlug });
      try { localStorage.setItem(STORAGE_KEYS.ONBOARDING_SEEN, '1'); } catch { /* ignore */ }
      setShow(false);
    } finally {
      finishInFlightRef.current = false;
      setFinishing(false);
    }
  };
  const next = () => {
    if (isLast) { void finish(); return; }
    setDir(1);
    setI((n) => n + 1);
  };
  const back = () => { setDir(-1); setI((n) => Math.max(0, n - 1)); };

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
        onClick={gotoSchoolGate}
        aria-hidden="true"
      />
      <div className="relative w-full max-w-2xl bg-white rounded-3xl shadow-2xl overflow-hidden">
        {/* top bar: step counter + Skip (Skip is hidden on the final gate slide) */}
        <div className="flex items-center justify-between px-5 sm:px-7 pt-4">
          <span className="text-[12px] font-medium text-gray-400 tabular-nums">
            {i + 1} / {SLIDES.length}
          </span>
          {!isLast && (
            <button
              type="button"
              onClick={gotoSchoolGate}
              data-testid="onboarding-skip"
              className="text-[13px] font-medium text-gray-400 hover:text-gray-700 transition-colors"
            >
              {t('onboarding.skipTour')}
            </button>
          )}
        </div>

        <div className="px-5 sm:px-7 pt-3 pb-5">
          {/* the stage re-keys on slide change so the .ob-* demo animations replay;
              the direction class glides the whole step in from the correct side */}
          <div key={i} className={dir === 1 ? 'ob-slide-next' : 'ob-slide-prev'}>
            {isLast ? (
              <div>
                <div className="flex items-center gap-2.5">
                  <span className="ob-pop inline-flex w-7 h-7 rounded-full bg-emerald-500 items-center justify-center shrink-0">
                    <Check className="w-4 h-4 text-white" strokeWidth={3} aria-hidden="true" />
                  </span>
                  <span className="text-[13px] font-semibold text-emerald-600">{t('onboarding.readyTitle')}</span>
                </div>
                <h2 className="mt-3 text-[20px] sm:text-[22px] font-bold tracking-tight text-gray-900">
                  {t('onboarding.schoolTitle')}
                </h2>
                <p className="mt-2 text-[14px] leading-relaxed text-gray-500">
                  {t('onboarding.schoolBody')}
                </p>
                <div className="mt-4">
                  <SchoolPicker t={t} locale={locale} selected={schoolSlug} onSelect={setSchoolSlug} />
                </div>
              </div>
            ) : (
              <>
                <div className="rounded-2xl bg-gradient-to-br from-slate-50 to-indigo-50/50 ring-1 ring-black/[0.04] px-4 sm:px-6 py-6 min-h-[208px] sm:min-h-[224px] flex flex-col justify-center">
                  <SlideVisual slide={slide} t={t} />
                </div>

                {locKey && (
                  <div className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-indigo-50 text-indigo-700 px-3 py-1 text-[12px] font-medium">
                    <MapPin className="w-3.5 h-3.5" aria-hidden="true" />
                    <span>{t(`onboarding.${locKey}`)}</span>
                  </div>
                )}

                <h2 className="mt-3 text-[20px] sm:text-[22px] font-bold tracking-tight text-gray-900">
                  {t(`onboarding.${slide}Title`)}
                </h2>
                <p className="mt-2 text-[14.5px] leading-relaxed text-gray-500 min-h-[44px]">
                  {t(`onboarding.${slide}Body`)}
                </p>
              </>
            )}
          </div>

          {/* progress dots */}
          <div className="mt-5 flex items-center justify-center gap-1.5" aria-hidden="true">
            {SLIDES.map((s, idx) => (
              <span
                key={s}
                className={`h-1.5 rounded-full transition-all ${idx === i ? 'w-5 bg-gray-900' : 'w-1.5 bg-gray-200'}`}
              />
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 px-5 sm:px-7 py-4 border-t border-black/[0.05]">
          {i === 0 ? (
            <span />
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

          <div className="flex items-center gap-3">
            {finishError && (
              <span data-testid="onboarding-error" role="alert" className="text-[12px] text-amber-600">
                {t('onboarding.finishFailed')}
              </span>
            )}
            <button
              type="button"
              onClick={next}
              // Only while a save is in flight. It used to also require an
              // accepted baseline, which turned "we could not read your row"
              // into a grey button with no explanation, on the one step of a
              // tour that cannot be dismissed. finish() still refuses to write
              // without that baseline — it just says so now, and the student
              // can try again.
              disabled={finishing}
              data-testid="onboarding-primary"
              className="inline-flex items-center gap-1.5 rounded-full bg-gray-900 text-white text-[14px] font-semibold px-6 py-2.5 hover:bg-gray-800 disabled:opacity-50 transition-colors"
            >
              {isLast ? t(finishing ? 'common.saving' : 'onboarding.cta') : t('onboarding.next')}
              <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
