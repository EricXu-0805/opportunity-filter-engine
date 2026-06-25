'use client';

import { memo } from 'react';
import MatchCard from '@/components/MatchCard';
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
    prev.isNew === next.isNew &&
    prev.profile === next.profile &&
    prev.feedbackVerdict === next.feedbackVerdict &&
    prev.onDraftEmail === next.onDraftEmail &&
    prev.onToggleFavorite === next.onToggleFavorite &&
    prev.onTrackInteraction === next.onTrackInteraction &&
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
  feedback: Map<string, MatchVerdict>;
  onDraftEmail: (opportunityId: string) => void;
  onToggleFavorite: (opportunityId: string) => void;
  onTrackInteraction: (opportunityId: string, type: InteractionType) => void;
  onFeedback: (opportunityId: string, verdict: MatchVerdict | null, context: MatchFeedbackContext) => void;
  page: number;
  totalPages: number;
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
  feedback,
  onDraftEmail,
  onToggleFavorite,
  onTrackInteraction,
  onFeedback,
  page,
  totalPages,
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
            <div
              key={match.opportunity.id}
              id={`match-card-${match.opportunity.id}`}
              className={`transition-all ${ringClass}`}
            >
              <MemoizedMatchCard
                match={match}
                profile={profile}
                onDraftEmail={onDraftEmail}
                isFavorited={favs.has(match.opportunity.id)}
                onToggleFavorite={onToggleFavorite}
                interaction={interactions.get(match.opportunity.id)}
                onTrackInteraction={onTrackInteraction}
                isNew={isNew}
                feedbackVerdict={feedback.get(match.opportunity.id) ?? null}
                onFeedback={onFeedback}
              />
            </div>
          );
        })}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-4">
          <button
            type="button"
            disabled={page <= 1}
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
            disabled={page >= totalPages}
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
