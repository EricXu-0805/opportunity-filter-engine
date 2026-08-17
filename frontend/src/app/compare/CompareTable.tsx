'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { readUserScopedRaw } from '@/lib/identity-owner';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import type { Opportunity, ProfileData } from '@/lib/types';
import { useHasLocalStorageKey, useLocalStorageJSON } from '@/lib/use-local-storage-json';
import { useT } from '@/i18n/client';
import { getMatchExplanation, type MatchExplanationResponse } from '@/lib/api';
import { cachedMatcherVersion } from '@/lib/match-cache';
import { hashProfile } from '@/lib/match-utils';
import {
  computeDecisionFactors,
  sortByCanonicalScore,
  type CanonicalMatchSummary,
  type CompareRow,
} from './scores';
import BucketCards from './BucketCards';
import DifferencesSection from './DifferencesSection';
import RadarChart from './RadarChart';

// AI-mode explain calls are paid completions; local deterministic summaries
// share the same bounded memoization shape. Cache per (opportunity,
// profile-hash, effective requested mode) in sessionStorage so revisits and
// re-renders within the hour render instantly;
// a profile edit changes the hash and misses. The contact-trust version in the
// prefix deliberately strands older entries whose explanation/reason strings
// may contain an address copied from corpus text.
//
// Not owner-epoch scoped, and NOT in USER_SCOPED_PREFIXES — deliberately:
// the key is content-addressed (opportunity id + full profile hash + AI
// toggle), not identity-addressed. A collision requires two identities
// sharing the EXACT SAME profile content for the SAME opportunity, and in
// that case the LLM explanation these inputs deterministically produce is
// itself identical regardless of who asks — there is no information a
// second identity could read here that their own request wouldn't have
// produced anyway. Cross-account isolation is not a relevant property of
// a pure function's memoized output; per-tab sessionStorage already bounds
// the sharing window to the SAME open tab.
// v2 strands ai0 entries written before fail-close, when the backend still
// called the provider and returned method=llm even for llm=false.
const EXPLAIN_CACHE_PREFIX = 'ofe_explain_faculty_truth_ai_close_v2_';
const EXPLAIN_TTL_MS = 60 * 60 * 1000;

function readExplainCache(key: string): MatchExplanationResponse | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const c = JSON.parse(raw) as { savedAt: number; data: MatchExplanationResponse };
    if (!c || typeof c.savedAt !== 'number' || !c.data) return null;
    if (Date.now() - c.savedAt >= EXPLAIN_TTL_MS) return null;
    // Never mix matcher generations across surfaces: when the /results cache
    // was written by a different matcher version, a cached explain from the
    // old generation must miss and re-fetch, not render beside new numbers.
    const listVersion = cachedMatcherVersion();
    if (listVersion && c.data.matcher_version && c.data.matcher_version !== listVersion) {
      return null;
    }
    return c.data;
  } catch {
    return null;
  }
}

function writeExplainCache(key: string, data: MatchExplanationResponse): void {
  try {
    sessionStorage.setItem(key, JSON.stringify({ savedAt: Date.now(), data }));
  } catch {
    // quota / private mode — skip; the next visit simply re-fetches.
  }
}

// The same explicit AI-refine opt-in /results honors. Missing, unreadable, or
// legacy state is deterministic; Compare must never turn AI on by default.
// Gated on RELEASE_SCOPE.matchAiRefine first, exactly like
// use-results-url.ts's readInitialSemanticRerank: a stale persisted '1'
// must never force llm:true while the feature itself is dormant.
function readAiTogglePreference(): boolean {
  if (!RELEASE_SCOPE.matchAiRefine) return false;
  return readUserScopedRaw(STORAGE_KEYS.SEMANTIC_RERANK) === '1';
}

function toCanonicalSummary(resp: MatchExplanationResponse): CanonicalMatchSummary | null {
  if (
    typeof resp.final_score !== 'number'
    || !Number.isFinite(resp.final_score)
    || resp.final_score < 0
    || resp.final_score > 100
    || typeof resp.bucket !== 'string'
  ) {
    return null;
  }
  return {
    final_score: resp.final_score,
    bucket: resp.bucket,
    reasons_fit: Array.isArray(resp.reasons_fit) ? resp.reasons_fit : [],
    reasons_gap: Array.isArray(resp.reasons_gap) ? resp.reasons_gap : [],
    explanation: typeof resp.explanation === 'string' ? resp.explanation : '',
    method: resp.method === 'llm' ? 'llm' : 'local',
  };
}

export default function CompareTable({ opps }: { opps: Opportunity[] }) {
  const { t } = useT();
  // Tri-state: useLocalStorageJSON alone returns null both while hydrating
  // and when no profile exists, which used to leave visitors without a
  // profile stuck on a permanent loading card.
  const hasProfile = useHasLocalStorageKey(STORAGE_KEYS.PROFILE);
  const profile = useLocalStorageJSON<ProfileData>(STORAGE_KEYS.PROFILE);
  const [matches, setMatches] = useState<Map<string, CanonicalMatchSummary | 'error'>>(new Map());

  useEffect(() => {
    if (!profile) return;
    const profileHash = hashProfile(profile);
    const ids = opps.map((o) => o.id);
    let cancelled = false;
    const setOne = (id: string, value: CanonicalMatchSummary | 'error') => {
      if (cancelled) return;
      setMatches((prev) => {
        const next = new Map(prev);
        next.set(id, value);
        return next;
      });
    };
    const llm = readAiTogglePreference();
    (async () => {
      await Promise.all(
        ids.map(async (id) => {
          const cacheKey = `${EXPLAIN_CACHE_PREFIX}${id}_${profileHash}_${llm ? 'ai1' : 'ai0'}`;
          const cached = readExplainCache(cacheKey);
          if (cached) {
            setOne(id, toCanonicalSummary(cached) ?? 'error');
            return;
          }
          try {
            const resp = await getMatchExplanation(profile, id, { llm });
            const summary = toCanonicalSummary(resp);
            if (summary) writeExplainCache(cacheKey, resp);
            setOne(id, summary ?? 'error');
          } catch {
            // The row stays explicitly unavailable. A local factor estimate is
            // never promoted into a replacement match score.
            setOne(id, 'error');
          }
        }),
      );
    })();
    return () => { cancelled = true; };
  }, [opps, profile]);

  const ranked = useMemo(() => {
    if (!profile) return null;
    if (!opps.every((opp) => matches.has(opp.id))) return null;
    const rows: CompareRow[] = opps.map((opp, inputIndex) => {
      const state = matches.get(opp.id);
      const failed = state === 'error' || state === undefined;
      return {
        opp,
        inputIndex,
        factors: computeDecisionFactors(profile, opp),
        status: failed ? 'error' : 'ready',
        match: failed ? null : state,
      };
    });
    return sortByCanonicalScore(rows);
  }, [matches, opps, profile]);

  if (hasProfile === undefined) {
    return (
      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center">
        <p className="text-sm text-gray-500">{t('compare.loadingProfile')}</p>
      </div>
    );
  }

  if (!profile) {
    return (
      <div>
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center mb-8">
          <p className="text-sm text-gray-500 mb-4">{t('compare.noProfile')}</p>
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 text-white text-[13px] font-medium hover:bg-indigo-700 transition-colors"
          >
            {t('compare.createProfile')}
          </Link>
        </div>
        <DifferencesSection rows={opps.map((opp) => ({ opp }))} profile={null} />
      </div>
    );
  }

  if (!ranked) {
    return (
      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center">
        <p className="text-sm text-gray-500">{t('compare.analyzing')}</p>
      </div>
    );
  }

  return (
    <div>
      <BucketCards rows={ranked} />
      <DifferencesSection rows={ranked} profile={profile} />
      <RadarChart rows={ranked} />
    </div>
  );
}
