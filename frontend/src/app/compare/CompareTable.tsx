'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { resolveSemanticRerank } from '@/app/results/use-results-url';
import type { Opportunity, ProfileData } from '@/lib/types';
import { targetPosture } from '@/lib/target-truth';
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
import BucketCards, { ReferenceOnlyCard } from './BucketCards';
import DifferencesSection from './DifferencesSection';
import RadarChart from './RadarChart';

const MIN_COMPARE = 2;

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
// v3 strands every entry written before target truth gated this surface. Those
// entries were keyed only by (id, profile, mode), so a closed target's cached
// score and explanation are still sitting in an open tab's sessionStorage —
// and reading one back would put a number and a paragraph of reasoning on a
// card that must show neither.
const EXPLAIN_CACHE_PREFIX = 'ofe_explain_target_truth_v3_';
const EXPLAIN_TTL_MS = 60 * 60 * 1000;

function readExplainCache(key: string): MatchExplanationResponse | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const c = JSON.parse(raw) as { savedAt: number; data: MatchExplanationResponse };
    if (!c || typeof c.savedAt !== 'number' || !c.data) return null;
    if (Date.now() - c.savedAt >= EXPLAIN_TTL_MS) return null;
    // The generation check lives in `toCanonicalSummary`, which every path —
    // live response, cache read, cache write — now runs. Duplicating a weaker
    // version of it here is how the two drifted: this one skipped the check
    // whenever `matcher_version` was absent, so a verdict from an unknown
    // generation was served as current.
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

function removeExplainCache(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Private mode can refuse writes; the entry is ignored either way.
  }
}

/**
 * A scored answer is only usable if it is an answer about the target asked
 * for, and one the server counts as a match.
 *
 * `excluded` covers the 200 that says `in_results: false` — a real score for a
 * record the /matches universe does not contain (another school's campus-only
 * posting, a citizenship restriction, below threshold). Rendering it as a
 * comparison row would rank something the student cannot act on against two
 * things they can.
 *
 * A mismatched echoed id is `null`: whatever that response describes, it is
 * not this card, and caching it under this card's key would make the error
 * permanent for the session.
 */
function toCanonicalSummary(
  resp: MatchExplanationResponse,
  requestedId: string,
): CanonicalMatchSummary | 'excluded' | null {
  // Present and equal, not "absent is fine". A response that does not name its
  // target cannot be attributed to this card, and an older backend that omits
  // the echo is one this surface will not render scores from — silently
  // trusting the request's own id is how a mismatch becomes invisible.
  if (resp.opportunity_id !== requestedId) return null;
  // Generation first, before any conclusion is drawn from the body — including
  // the exclusion. "Not in your results" is itself a verdict about a universe
  // some specific matcher computed; accepting it from an unknown or stale
  // generation sidelines a target on the say-so of a scorer that is no longer
  // the one ranking anything.
  if (typeof resp.matcher_version !== 'string' || resp.matcher_version === '') return null;
  const listVersion = cachedMatcherVersion();
  if (listVersion && resp.matcher_version !== listVersion) return null;
  // Explicit true. `undefined` is an older backend that never answered the
  // question "is this in your results", and treating silence as yes is what
  // puts a cross-school or below-threshold record into a ranked comparison.
  if (resp.in_results === false) return 'excluded';
  if (resp.in_results !== true) return null;
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
    matcher_version: resp.matcher_version,
  };
}

/** Targets that were asked for but cannot be compared, kept readable. */
function ReferenceOnlySection(
  { entries }: { entries: { opp: Opportunity; statusOverride?: string }[] },
) {
  const { t } = useT();
  if (entries.length === 0) return null;
  return (
    <section className="mt-8">
      <h2 className="text-[13px] font-semibold text-gray-700 mb-3">
        {t('compare.referenceOnlyTitle')}
      </h2>
      <p className="text-[12px] text-gray-500 mb-3">{t('compare.referenceOnlyBody')}</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {entries.map(({ opp, statusOverride }) => (
          <ReferenceOnlyCard key={opp.id} opp={opp} statusOverride={statusOverride} />
        ))}
      </div>
    </section>
  );
}

export default function CompareTable({ opps }: { opps: Opportunity[] }) {
  const { t } = useT();
  // Split before anything reads these records. /compare is reachable by URL —
  // ?ids= is typed, bookmarked, and shared — so the selection guard on
  // /favorites is not a gate this page sits behind. Everything downstream
  // (explain calls, the AI cache, ranking, differences, the radar) sees only
  // the comparable half; the rest never becomes a row at all.
  const { comparable, reference } = useMemo(() => ({
    comparable: opps.filter((opp) => targetPosture(opp) === 'actionable'),
    reference: opps.filter((opp) => targetPosture(opp) !== 'actionable'),
  }), [opps]);
  // Tri-state: useLocalStorageJSON alone returns null both while hydrating
  // and when no profile exists, which used to leave visitors without a
  // profile stuck on a permanent loading card.
  const hasProfile = useHasLocalStorageKey(STORAGE_KEYS.PROFILE);
  const profile = useLocalStorageJSON<ProfileData>(STORAGE_KEYS.PROFILE);
  // The same preference /results resolves, through the same function and the
  // same tri-state hooks. Compare reads the SAME snapshot /results serves, so
  // resolving it differently here would make the table contradict the list it
  // was opened from. No URL pin: /compare carries no ?ai=.
  const semanticPrefExists = useHasLocalStorageKey(STORAGE_KEYS.SEMANTIC_RERANK);
  const semanticPrefValue = useLocalStorageJSON<string>(STORAGE_KEYS.SEMANTIC_RERANK);
  const llm = resolveSemanticRerank(null, semanticPrefExists, semanticPrefValue);
  // The full identity of the request these verdicts answer — not just the id.
  // A score is a statement about (this profile, this AI mode, this target); a
  // Map keyed by id alone kept showing the old profile's numbers after an edit
  // until the new ones happened to arrive, and an in-flight response from the
  // previous identity could land afterwards and overwrite them.
  const profileHash = profile ? hashProfile(profile) : '';
  const requestIdentity = `${profileHash}|${llm ? 'ai1' : 'ai0'}|${
    comparable.map((o) => o.id).join(',')
  }`;
  const [verdicts, setVerdicts] = useState<{
    identity: string;
    byId: Map<string, CanonicalMatchSummary | 'error' | 'excluded'>;
  }>({ identity: '', byId: new Map() });

  useEffect(() => {
    if (!profile) return;
    const ids = comparable.map((o) => o.id);
    let cancelled = false;
    const setOne = (id: string, value: CanonicalMatchSummary | 'error' | 'excluded') => {
      if (cancelled) return;
      setVerdicts((prev) => {
        // React may defer a queued functional update until after cleanup. The
        // outer check covers invocation time; this one covers execution time.
        if (cancelled) return prev;
        // `ranked` hides a superseded identity during render. The first answer
        // for the new request adopts that identity and starts a fresh map;
        // later answers extend only that map. Effect cleanup marks late
        // responses from the old request as cancelled before they get here.
        const next = prev.identity === requestIdentity
          ? new Map(prev.byId)
          : new Map<string, CanonicalMatchSummary | 'error' | 'excluded'>();
        next.set(id, value);
        return { identity: requestIdentity, byId: next };
      });
    };
    const keyFor = (id: string) => (
      `${EXPLAIN_CACHE_PREFIX}${id}_${profileHash}_${llm ? 'ai1' : 'ai0'}`
    );

    // Read every cached verdict first, so the generations can be compared
    // against each other before any of them is used. Checked one at a time,
    // two individually-valid entries from different matcher generations both
    // "hit", and the table renders their incomparable numbers side by side.
    const cachedSummaries = new Map<string, CanonicalMatchSummary>();
    for (const id of ids) {
      const cached = readExplainCache(keyFor(id));
      if (!cached) continue;
      const summary = toCanonicalSummary(cached, id);
      // Only a complete, ready verdict counts as a hit. Anything else — a
      // wrong echo, a missing flag, a stale generation, a stored exclusion —
      // is dropped and re-fetched. Serving `error` from a poisoned entry
      // instead would strand the user on "unavailable" for the full hour of
      // the TTL, with no request ever made that could fix it.
      if (summary && summary !== 'excluded') cachedSummaries.set(id, summary);
      else removeExplainCache(keyFor(id));
    }
    const cachedGenerations = new Set(
      Array.from(cachedSummaries.values()).map((s) => s.matcher_version),
    );
    if (cachedGenerations.size > 1) {
      // Cached from two generations, with no page-level version to arbitrate.
      // Discard them all and ask again: the live answers come from whatever
      // generation is current, so one round converges instead of leaving the
      // student stuck behind a cache that can never agree with itself.
      for (const id of cachedSummaries.keys()) removeExplainCache(keyFor(id));
      cachedSummaries.clear();
    }

    (async () => {
      // Cache hits must not disguise a synchronous state update in the effect
      // body. Yield once; cleanup can then cancel a superseded request before
      // any cached or live answer is adopted.
      await Promise.resolve();
      if (cancelled) return;
      await Promise.all(
        ids.map(async (id) => {
          const cacheKey = keyFor(id);
          const hit = cachedSummaries.get(id);
          if (hit) {
            setOne(id, hit);
            return;
          }
          try {
            const resp = await getMatchExplanation(profile, id, { llm });
            const summary = toCanonicalSummary(resp, id);
            // Only a usable verdict is cached. An excluded result and a
            // mismatched echo are both answers we will not render, and
            // caching either would make the session repeat them without
            // ever asking again.
            if (summary && summary !== 'excluded') writeExplainCache(cacheKey, resp);
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
  }, [comparable, profile, profileHash, llm, requestIdentity]);

  const ranked = useMemo(() => {
    if (!profile) return null;
    // Answers from a superseded request are not a partial result set.
    if (verdicts.identity !== requestIdentity) return null;
    if (!comparable.every((opp) => verdicts.byId.has(opp.id))) return null;
    // One generation for the whole table, not per row. Each verdict is a
    // separate response, and a page-level version is not always available to
    // check against — so the rows are checked against each other. Two
    // generations mean two scoring functions, and putting their numbers in one
    // ranked list is a comparison of things that were never comparable.
    const versions = new Set(
      Array.from(verdicts.byId.values())
        .filter((state): state is CanonicalMatchSummary => (
          state !== 'error' && state !== 'excluded'
        ))
        .map((summary) => summary.matcher_version),
    );
    const mixedGenerations = versions.size > 1;

    const rows: CompareRow[] = comparable.map((opp, inputIndex) => {
      const state = verdicts.byId.get(opp.id);
      const scored = state !== undefined && state !== 'error' && state !== 'excluded';
      const usable = scored && !mixedGenerations;
      return {
        opp,
        inputIndex,
        factors: computeDecisionFactors(profile, opp),
        status: state === 'excluded' ? 'excluded' : usable ? 'ready' : 'error',
        match: usable ? state : null,
        matcherVersion: scored ? state.matcher_version : undefined,
      };
    });
    return sortByCanonicalScore(rows);
  }, [verdicts, requestIdentity, comparable, profile]);

  if (hasProfile === undefined) {
    return (
      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center">
        <p className="text-sm text-gray-500">{t('compare.loadingProfile')}</p>
      </div>
    );
  }

  // Second partition, after the answers come back. Target truth removed the
  // records that are not live; this removes the ones the server scored as
  // outside these results. Sorting them to the bottom is not enough — every
  // consumer below reads the row list, and Differences and the radar do not
  // look at `status` at all, so an excluded row would contribute its pay,
  // deadline, eligibility and factor spokes to a comparison it is not part of.
  const usable = ranked?.filter((row) => row.status !== 'excluded') ?? null;
  const excludedEntries = (ranked ?? [])
    .filter((row) => row.status === 'excluded')
    .map((row) => ({ opp: row.opp, statusOverride: t('compare.status.notInResults') }));

  // Rendered under every branch below, profile or no profile: what a
  // non-actionable target is allowed to show does not depend on whether the
  // visitor has a profile.
  const referenceSection = (
    <ReferenceOnlySection
      entries={[...reference.map((opp) => ({ opp })), ...excludedEntries]}
    />
  );

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
        {/* Differences compares only the comparable half. Feeding it a closed
            record would put that record's pay, deadline and eligibility into
            a table of "how these differ" — facts about an option that is not
            on offer. */}
        <DifferencesSection rows={comparable.map((opp) => ({ opp }))} profile={null} />
        {referenceSection}
      </div>
    );
  }

  if (comparable.length < MIN_COMPARE) {
    // One live target is not a comparison. Saying so beats rendering a
    // single-card "comparison" that quietly answers a question the student
    // did not ask.
    return (
      <div>
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center">
          <p className="text-sm text-gray-500">{t('compare.notEnoughComparable')}</p>
        </div>
        {referenceSection}
      </div>
    );
  }

  if (!ranked || !usable) {
    return (
      <div>
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center">
          <p className="text-sm text-gray-500">{t('compare.analyzing')}</p>
        </div>
        {referenceSection}
      </div>
    );
  }

  if (usable.length < MIN_COMPARE) {
    // One real target plus one the server put outside these results is not a
    // comparison, and presenting it as one answers a question nobody asked.
    return (
      <div>
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center">
          <p className="text-sm text-gray-500">{t('compare.notEnoughComparable')}</p>
        </div>
        {referenceSection}
      </div>
    );
  }

  return (
    <div>
      <BucketCards rows={usable} />
      <DifferencesSection rows={usable} profile={profile} />
      <RadarChart rows={usable} />
      {referenceSection}
    </div>
  );
}
