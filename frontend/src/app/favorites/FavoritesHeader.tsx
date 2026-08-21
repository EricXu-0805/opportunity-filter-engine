'use client';

import { GitCompare, X } from 'lucide-react';
import EmailMeButton from '@/components/EmailMeButton';
import { sendFavoritesEmail } from '@/lib/api';
import { opportunityRecordKind } from '@/lib/match-utils';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import { opportunitySourceUrl, targetPosture } from '@/lib/target-truth';
import { getInteractionsFull } from '@/lib/supabase';
import { MAX_COMPARE, MIN_COMPARE, type Opp, type TFunc } from './types';

// Mirrors MAX_ITEMS_PER_EMAIL in backend/routes/email.py. Sending more is a
// 422 on the whole digest, so the producer slices — and the UI says so.
const MAX_EMAIL_ITEMS = 50;

export interface FavoritesHeaderProps {
  opportunities: Opp[];
  serverOpportunitiesCount: number;
  selectionMode: boolean;
  onEnterSelection: () => void;
  onCancelSelection: () => void;
  t: TFunc;
}

export function FavoritesHeader({
  opportunities,
  serverOpportunitiesCount,
  selectionMode,
  onEnterSelection,
  onCancelSelection,
  t,
}: FavoritesHeaderProps) {
  // Server-backed favorites the student could still choose between. Custom
  // imports are excluded for the same reason toggleSelect refuses them:
  // /compare resolves against the canonical table.
  const comparableCount = opportunities.filter(
    (o) => !o._customId && targetPosture(o) === 'actionable',
  ).length;

  // What the email will actually carry, computed with the same filter the
  // producer uses. The backend caps a digest at 50 items, so a longer
  // shortlist is truncated — and a digest that silently omits rows the
  // student saved reads as complete. Counted from the mailable rows rather
  // than the rendered list: custom imports are dropped before the slice, so
  // counting the screen would announce a truncation that never happens.
  const mailableCount = opportunities.filter((o) => !o._customId).length;
  const emailNotice = mailableCount > MAX_EMAIL_ITEMS
    ? t('email.favoritesTruncated', { shown: MAX_EMAIL_ITEMS, total: mailableCount })
    : undefined;

  return (
    <div className="mb-10 flex items-start justify-between gap-4 flex-wrap">
      <div>
        <h1 className="text-4xl font-bold text-gray-900 tracking-tight">{t('favorites.title')}</h1>
        <p className="mt-2 text-[15px] text-gray-400">
          {opportunities.length === 0 ? t('favorites.empty') : t('favorites.count', { count: opportunities.length })}
        </p>
        {selectionMode && (
          <p className="mt-1 text-[13px] text-indigo-600 font-medium">
            {t('favorites.selectionHint', { min: MIN_COMPARE, max: MAX_COMPARE })}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0 flex-wrap">
        {!selectionMode && opportunities.length > 0 && (
          <EmailMeButton
            label={t('email.sendFavorites')}
            title={t('email.subtitle')}
            notice={emailNotice}
            onSend={async (emailAddr) => {
              // W14: a failed status load must not silently export blank
              // notes/status columns as if none existed — the email is a
              // data export, so fail it loudly and let the user retry.
              const interactions = await getInteractionsFull();
              const items = opportunities
                .filter((o) => !o._customId)
                .slice(0, MAX_EMAIL_ITEMS)
                .map((o) => {
                  const rec = interactions.get(o.id);
                  // ROLLOUT BRIDGE — see EmailMatchItem. The new backend reads
                  // only the id (plus the user's own notes/status). But during
                  // the Vercel-first window an OLD backend renders straight
                  // from these legacy fields, so they have to be truth-safe on
                  // their own: a closed saved target degrades to `unknown`
                  // with no deadline, so the old renderer cannot print a due
                  // date or call it an opening. Faculty keeps its own kind —
                  // that label already says the opening is unconfirmed.
                  const rawKind = opportunityRecordKind(o);
                  const actionable = targetPosture(o) === 'actionable';
                  const bridgeKind = rawKind === 'faculty_contact'
                    ? 'faculty_contact'
                    : actionable && rawKind === 'listing'
                      ? 'listing'
                      : 'unknown';
                  return {
                    opportunity_id: o.id,
                    notes: rec?.notes || '',
                    status: rec?.type || '',
                    title: o.title,
                    // source_url first: never hand an old renderer an
                    // application URL to present as the source link.
                    url: opportunitySourceUrl(o) || '',
                    source: o.source || '',
                    deadline: bridgeKind === 'listing' ? o.deadline || null : null,
                    record_kind: bridgeKind as 'listing' | 'faculty_contact' | 'unknown',
                  };
                });
              return sendFavoritesEmail(emailAddr, items);
            }}
          />
        )}
        {/* Counted from what can actually be compared, not from how many rows
            are saved. Two closed favorites are two rows and zero choices, and
            offering Compare there invites a comparison of options the student
            no longer has. */}
        {RELEASE_SCOPE.compare && !selectionMode && comparableCount >= MIN_COMPARE && (
          <button
            type="button"
            onClick={onEnterSelection}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-600 text-white text-[13px] font-semibold hover:bg-indigo-700 transition-colors shadow-[0_2px_12px_rgba(79,70,229,0.25)]"
          >
            <GitCompare className="w-4 h-4" aria-hidden="true" />
            {t('favorites.compare')}
          </button>
        )}
        {selectionMode && (
          <button
            type="button"
            onClick={onCancelSelection}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-gray-300 text-gray-700 text-[13px] font-semibold hover:bg-gray-50 transition-colors"
          >
            <X className="w-4 h-4" aria-hidden="true" />
            {t('favorites.cancel')}
          </button>
        )}
      </div>
    </div>
  );
}
