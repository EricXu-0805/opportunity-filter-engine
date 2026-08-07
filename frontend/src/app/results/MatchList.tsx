'use client';

import { Fragment, memo } from 'react';
import MatchCard from '@/components/MatchCard';
import { ConciergeCta } from './ConciergeCta';
import type { MatchResult, ProfileData } from '@/lib/types';
import type { InteractionType } from '@/lib/supabase';
import type { MatchVerdict, MatchFeedbackContext } from '@/lib/match-feedback';
import type { TFunc } from './types';

const MemoizedMatchCard = memo(MatchCard, (prev, next) => {
  return (
    prev.match.opportunity.id === next.match.opportunity.id &&
    prev.match.final_score === next.match.final_score &&
    prev.isFavorited === next.isFavorited &&
    prev.interaction === next.interaction &&
    prev.favoritePending === next.favoritePending &&
    prev.trackPending === next.trackPending &&
    prev.favSaveError === next.favSaveError &&
    prev.trackSaveError === next.trackSaveError &&
    prev.ownerReady === next.ownerReady &&
    prev.ownerScopeKey === next.ownerScopeKey &&
    prev.isNew === next.isNew &&
    prev.profile === next.profile &&
    prev.feedbackVerdict === next.feedbackVerdict &&
    prev.position === next.position &&
    prev.onDraftEmail === next.onDraftEmail &&
    prev.onToggleFavorite === next.onToggleFavorite &&
    prev.onTrackInteraction === next.onTrackInteraction &&
    prev.onRetryFavSave === next.onRetryFavSave &&
    prev.onRetryTrackSave === next.onRetryTrackSave &&
    prev.onFeedback === next.onFeedback
  );
});
MemoizedMatchCard.displayName = 'MemoizedMatchCard';

export interface MatchListProps {
  matches: MatchResult[];
  profile: ProfileData | null;
  highlightSet: Set<string>;
  focusedIdx: number;
  favs: Set<string>;
  interactions: Map<string, InteractionType>;
  /** False until the shared owner primitive is primed for this list — see
   *  ownerReady in use-results-interactions.ts. Disables every favorite
   *  star until then, AND (per card) the Tailor CTA — see MatchCard. */
  ownerReady: boolean;
  /** Bumps ONLY on a REAL identity transition — see identityGeneration in
   *  use-results-interactions.ts. Folded into each card's React key below
   *  so a real identity change force-destroys every card's local UI state
   *  (an open Tailor modal, its draft, an in-flight request) immediately;
   *  a benign same-uid rerender leaves the SAME key, so nothing remounts. */
  identityGeneration: number;
  /** The exact current resolved uid, or null — see ownerScopeKey in
   *  use-results-interactions.ts. Passed through to each card so
   *  owner-scoped local persistence (Tailor drafts) never has to guess it. */
  ownerScopeKey: string | null;
  /** Opportunity ids with a favorite/track write currently in flight —
   *  disables just that card's own control, not the whole list. */
  pendingFavIds: Set<string>;
  pendingTrackIds: Set<string>;
  /** Opportunity ids whose LATEST favorite/status write attempt failed —
   *  per-id (see use-results-interactions.ts), rendered at the owning card
   *  only; a different id's error/retry is completely independent. */
  favSaveErrors: Set<string>;
  trackSaveErrors: Set<string>;
  /** True while the bulk interaction read is loading or has failed — see
   *  interactionsLoading/interactionsError in use-results-interactions.ts.
   *  Disables every status control until a confirmed read lands. */
  interactionsUnready: boolean;
  feedback: Map<string, MatchVerdict>;
  onDraftEmail: (opportunityId: string) => void;
  onToggleFavorite: (opportunityId: string) => void;
  onTrackInteraction: (opportunityId: string, type: InteractionType) => void;
  onRetryFavSave: (opportunityId: string) => void;
  onRetryTrackSave: (opportunityId: string) => void;
  onFeedback: (opportunityId: string, verdict: MatchVerdict | null, context: MatchFeedbackContext) => void;
  // 1-based rank of matches[0] minus one within the full filtered list, so
  // each card can report its absolute list position with feedback votes.
  positionOffset: number;
  page: number;
  totalPages: number;
  paginationReady: boolean;
  onPageChange: (next: number) => void;
  t: TFunc;
}

export function MatchList({
  matches,
  profile,
  highlightSet,
  focusedIdx,
  favs,
  interactions,
  ownerReady,
  identityGeneration,
  ownerScopeKey,
  pendingFavIds,
  pendingTrackIds,
  favSaveErrors,
  trackSaveErrors,
  interactionsUnready,
  feedback,
  onDraftEmail,
  onToggleFavorite,
  onTrackInteraction,
  onRetryFavSave,
  onRetryTrackSave,
  onFeedback,
  positionOffset,
  page,
  totalPages,
  paginationReady,
  onPageChange,
  t,
}: MatchListProps) {
  return (
    <>
      {/*
        R69-C: lg:grid-cols-2 at the lg (1024px) breakpoint reclaims the
        ~50% of horizontal whitespace the single-column layout left on
        the right side of >= 1440px viewports. Mobile + tablet keep the
        single-column stack, so this is a desktop-only density bump.
        items-start prevents grid auto-stretch from forcing both cells
        in a row to the height of the expanded one — collapsed cards
        stay compact even when their sibling is expanded.

        Keyboard nav caveat: j/k cycles through `paginated` in document
        order, so on a 2-col grid the visual progression goes
        left→right→down rather than purely down. Acceptable trade for
        the density win; revisit in a future round if keyboard power
        users object.
      */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6 items-start">
        {matches.map((match: MatchResult, idx: number) => {
          const isNew = highlightSet.has(match.opportunity.id);
          const ringClass = focusedIdx === idx
            ? 'ring-2 ring-indigo-500/40 rounded-2xl'
            : isNew
            ? 'ring-2 ring-amber-400/70 rounded-2xl'
            : '';
          return (
            // Keyed by identityGeneration + opportunity id (not opportunity
            // id alone): a REAL identity change bumps identityGeneration,
            // forcing React to tear down and rebuild this ENTIRE subtree —
            // MatchCard's own local state (tailorOpen) and everything
            // TailorModal owns internally (draft, in-flight request, AI
            // result) are destroyed with it, not just visually hidden. A
            // same-uid rerender (ownerReady flipping on a retry, a data
            // reload, etc.) keeps the SAME key, so nothing remounts and
            // in-progress work survives untouched.
            <Fragment key={`${identityGeneration}:${match.opportunity.id}`}>
              <div
                id={`match-card-${match.opportunity.id}`}
                className={`transition-all ${ringClass}`}
              >
                <MemoizedMatchCard
                  match={match}
                  profile={profile}
                  onDraftEmail={onDraftEmail}
                  isFavorited={favs.has(match.opportunity.id)}
                  onToggleFavorite={onToggleFavorite}
                  favoritePending={!ownerReady || pendingFavIds.has(match.opportunity.id)}
                  favSaveError={favSaveErrors.has(match.opportunity.id)}
                  onRetryFavSave={onRetryFavSave}
                  interaction={interactions.get(match.opportunity.id)}
                  onTrackInteraction={onTrackInteraction}
                  trackPending={!ownerReady || interactionsUnready || pendingTrackIds.has(match.opportunity.id)}
                  trackSaveError={trackSaveErrors.has(match.opportunity.id)}
                  onRetryTrackSave={onRetryTrackSave}
                  ownerReady={ownerReady}
                  ownerScopeKey={ownerScopeKey}
                  isNew={isNew}
                  feedbackVerdict={feedback.get(match.opportunity.id) ?? null}
                  onFeedback={onFeedback}
                  position={positionOffset + idx + 1}
                />
              </div>
              {page === 1 && idx === Math.min(3, matches.length - 1) && (
                <div className="lg:col-span-2">
                  <ConciergeCta t={t} />
                </div>
              )}
            </Fragment>
          );
        })}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-4">
          <button
            type="button"
            disabled={!paginationReady || page <= 1}
            onClick={() => { onPageChange(page - 1); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
            className="px-4 py-2 text-sm font-medium border border-gray-200 rounded-xl hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {t('results.pagination.previous')}
          </button>
          <span className="text-sm text-gray-500 tabular-nums px-3">
            {page} / {totalPages}
          </span>
          <button
            type="button"
            disabled={!paginationReady || page >= totalPages}
            onClick={() => { onPageChange(page + 1); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
            className="px-4 py-2 text-sm font-medium border border-gray-200 rounded-xl hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {t('results.pagination.next')}
          </button>
        </div>
      )}
    </>
  );
}
