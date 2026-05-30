'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Phased "what the AI is doing" narrative for the /results page wait.
 *
 * AcadeLink's results-transition feels alive because it walks the user
 * through what is actually happening behind the scenes ("reading your
 * profile", "scanning N opportunities", "re-ranking with AI"). Our
 * previous loading state showed one static "Analyzing..." string and a
 * 60%-fixed progress bar that never moved, which read as a frozen page.
 *
 * The narrative is purely cosmetic — it does NOT reflect real progress
 * from the backend (which returns a single response, not a stream). The
 * percentages are tuned so the bar grows monotonically, holds at ~95%
 * until the response arrives, then jumps to 100% on `loading=false`.
 *
 * Phases differ by mode:
 *   - Plain (no AI rerank): 4 phases over ~4s.
 *   - AI rerank: 5 phases over ~6s, with an explicit re-ranking step.
 *
 * If the response arrives mid-phase, the hook stops advancing and
 * leaves the last message visible until the loader unmounts.
 *
 * Cross-file contract:
 *   - `app/results/page.tsx` (or `use-results-data.ts` post-R30) reads
 *     `phase.message` for the subtitle and `phase.percent` for the
 *     top progress bar. The CSS class on the bar uses `transition-all`
 *     so width changes animate naturally between phase steps.
 *   - i18n keys: `results.loadingPhases.{readingProfile,scanning,
 *     scoring,reranking,polishing}`.
 */

export type LoadingPhaseKey =
  | 'readingProfile'
  | 'scanning'
  | 'scoring'
  | 'reranking'
  | 'polishing';

export interface LoadingPhase {
  key: LoadingPhaseKey;
  /** Resolved i18n string for the current phase (already with placeholders filled). */
  message: string;
  /** Cosmetic progress 0-100. Holds at the last phase's value until loading ends. */
  percent: number;
  /** Phase index (0-based). -1 when not loading. */
  phaseIndex: number;
}

interface PhaseStep {
  key: LoadingPhaseKey;
  /** ms after loading started before advancing to this phase. */
  delayMs: number;
  /** Target progress percent at this phase. */
  percent: number;
}

const PHASES_PLAIN: PhaseStep[] = [
  { key: 'readingProfile', delayMs: 0,    percent: 15 },
  { key: 'scanning',       delayMs: 900,  percent: 50 },
  { key: 'scoring',        delayMs: 2200, percent: 80 },
  { key: 'polishing',      delayMs: 3800, percent: 95 },
];

const PHASES_AI: PhaseStep[] = [
  { key: 'readingProfile', delayMs: 0,    percent: 12 },
  { key: 'scanning',       delayMs: 900,  percent: 38 },
  { key: 'scoring',        delayMs: 2200, percent: 60 },
  { key: 'reranking',      delayMs: 3600, percent: 85 },
  { key: 'polishing',      delayMs: 5200, percent: 95 },
];

const PHASE_DONE: LoadingPhase = {
  key: 'polishing',
  message: '',
  percent: 100,
  phaseIndex: -1,
};

type Replier = (path: string, vars?: Record<string, string | number>) => string;

interface UseLoadingNarrativeArgs {
  loading: boolean;
  semanticRerank: boolean;
  /** Total opportunities scanned, used in the "scanning N..." string. */
  opportunityCount: number;
  /** i18n resolver (t function from useT()). */
  t: Replier;
}

export function useLoadingNarrative({
  loading,
  semanticRerank,
  opportunityCount,
  t,
}: UseLoadingNarrativeArgs): LoadingPhase {
  const [phaseIndex, setPhaseIndex] = useState(0);
  const startedAtRef = useRef<number | null>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  /* eslint-disable react-hooks/set-state-in-effect --
     The loading→narrative pipeline is a time-driven state machine.
     When `loading` flips true we MUST reset phaseIndex to 0 (sync,
     pre-paint) so the user sees "Reading your profile..." on the
     same render that the skeleton appears — not one paint later.
     React.dev's recommended key-remount alternative would force the
     whole tree to remount, which breaks the existing in-flight
     fetch + the saved focus state on the search input. */
  useEffect(() => {
    if (!loading) {
      startedAtRef.current = null;
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
      return;
    }

    // a11y: hold at phase 0 when the user prefers reduced motion. Avoids
    // a stream of state updates / progress-bar tweens that would defeat
    // the purpose of the OS-level preference.
    const reduced =
      typeof window !== 'undefined'
      && window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    setPhaseIndex(0);
    startedAtRef.current = Date.now();
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];

    if (reduced) return;

    const phases = semanticRerank ? PHASES_AI : PHASES_PLAIN;
    for (let i = 1; i < phases.length; i++) {
      const target = i;
      const timer = setTimeout(() => {
        setPhaseIndex(target);
      }, phases[i].delayMs);
      timersRef.current.push(timer);
    }

    return () => {
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
    };
  }, [loading, semanticRerank]);
  /* eslint-enable react-hooks/set-state-in-effect */

  if (!loading) return PHASE_DONE;

  const phases = semanticRerank ? PHASES_AI : PHASES_PLAIN;
  const safeIndex = Math.min(phaseIndex, phases.length - 1);
  const step = phases[safeIndex];

  const message = step.key === 'scanning' && opportunityCount > 0
    ? t('results.loadingPhases.scanning', { count: opportunityCount })
    : t(`results.loadingPhases.${step.key}`);

  return {
    key: step.key,
    message,
    percent: step.percent,
    phaseIndex: safeIndex,
  };
}
