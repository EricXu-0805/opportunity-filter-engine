'use client';

import { Lightbulb } from 'lucide-react';
import type { InteractionType } from '@/lib/supabase';
import type { ReminderSuggestion } from '@/lib/status-suggestions';
import { INTERACTION_OPTIONS, INTERACTION_PILL } from './types';
import type { TFunc } from './types';

export function InteractionPills({
  interaction,
  suggestion,
  onTrack,
  onUseSuggestion,
  onDismissSuggestion,
  t,
}: {
  interaction: InteractionType | undefined;
  suggestion: ReminderSuggestion | null;
  onTrack: (type: InteractionType) => void;
  onUseSuggestion: () => void;
  onDismissSuggestion: () => void;
  t: TFunc;
}) {
  return (
    <div className="border-t border-gray-100 px-5 sm:px-8 py-4 bg-gray-50/50 space-y-2">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t('detail.trackAriaLabel')}>
        <span className="text-[12px] text-gray-500 mr-1">{t('detail.track')}</span>
        {INTERACTION_OPTIONS.map((type) => {
          const active = interaction === type;
          return (
            <button
              key={type}
              type="button"
              aria-pressed={active}
              onClick={() => onTrack(type)}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                active ? INTERACTION_PILL[type] : 'bg-white border-gray-200 text-gray-400 hover:border-gray-300'
              }`}
            >
              {t(`detail.interactions.${type}`)}
            </button>
          );
        })}
      </div>
      {suggestion && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-2 px-3 py-2 text-[12px] bg-amber-50 border border-amber-200 rounded-lg animate-in"
        >
          <Lightbulb className="w-3.5 h-3.5 text-amber-600 shrink-0" aria-hidden="true" />
          <span className="text-amber-900">
            {t(
              suggestion.reason === 'follow_up_after_reply'
                ? 'detail.tracker.suggestions.followUpAfterReply'
                : 'detail.tracker.suggestions.thankYouAfterInterview',
              { date: suggestion.date },
            )}
          </span>
          <div className="ml-auto flex gap-1.5">
            <button
              type="button"
              onClick={onUseSuggestion}
              className="px-2.5 py-0.5 text-[11px] font-medium text-white bg-amber-600 hover:bg-amber-700 rounded-md transition-colors"
            >
              {t('detail.tracker.suggestions.useButton', { date: suggestion.date })}
            </button>
            <button
              type="button"
              onClick={onDismissSuggestion}
              className="px-2.5 py-0.5 text-[11px] font-medium text-amber-700 hover:text-amber-900 transition-colors"
            >
              {t('detail.tracker.suggestions.dismissButton')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
