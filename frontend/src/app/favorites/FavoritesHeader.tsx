'use client';

import { GitCompare, X } from 'lucide-react';
import EmailMeButton from '@/components/EmailMeButton';
import { sendFavoritesEmail } from '@/lib/api';
import { getInteractionsFull } from '@/lib/supabase';
import { MAX_COMPARE, MIN_COMPARE, type Opp, type TFunc } from './types';

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
            onSend={async (emailAddr) => {
              const interactions = await getInteractionsFull().catch(() => new Map());
              const items = opportunities
                .filter((o) => !o._customId)
                .slice(0, 50)
                .map((o) => {
                  const rec = interactions.get(o.id);
                  return {
                    title: o.title,
                    url: o.url || '',
                    source: o.source || '',
                    deadline: o.deadline || null,
                    notes: rec?.notes || '',
                    status: rec?.type || '',
                  };
                });
              return sendFavoritesEmail(emailAddr, items);
            }}
          />
        )}
        {!selectionMode && serverOpportunitiesCount >= MIN_COMPARE && (
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
