import { Star } from 'lucide-react';
import type { Tab, TFunc } from './types';

export function EmptyState({
  hasFilters,
  deadlineFilterFoundNothing,
  tab,
  onClearFilters,
  onShowRolling,
  t,
}: {
  hasFilters: boolean;
  /** A deadline filter is active and not one match carries a deadline at all. */
  deadlineFilterFoundNothing?: boolean;
  tab: Tab;
  onClearFilters: () => void;
  onShowRolling?: () => void;
  t: TFunc;
}) {
  // Explain the missing deadline evidence without converting an undated
  // faculty contact into a supposedly open/rolling position. The optional
  // action does NOT select records "marked rolling" — it selects
  // `is_rolling: true`, which campus_graph, simplify_internships and
  // ucb_campus all write whenever a scrape found no date. It returns 6,690
  // live records and only 58 of them carry the scraped `deadline_note` that
  // noDeadlineKind requires before any surface may say "rolling", so it is
  // labelled for what it selects. Same rule the chip already follows.
  if (deadlineFilterFoundNothing) {
    return (
      <div className="text-center py-16 space-y-3">
        <p className="text-gray-500 text-lg">{t('results.empty.noDeadlines')}</p>
        <p className="text-gray-400 text-sm">{t('results.empty.noDeadlinesHint')}</p>
        <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
          {onShowRolling && (
            <button
              type="button"
              onClick={onShowRolling}
              className="px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-xl hover:bg-indigo-100 transition-colors"
            >
              {t('results.empty.showRolling')}
            </button>
          )}
          <button
            type="button"
            onClick={onClearFilters}
            className="px-4 py-2 text-sm font-medium text-gray-500 hover:text-gray-700 transition-colors"
          >
            {t('results.empty.clearAll')}
          </button>
        </div>
      </div>
    );
  }

  if (hasFilters) {
    return (
      <div className="text-center py-16 space-y-3">
        <p className="text-gray-500 text-lg">{t('results.empty.withFilters')}</p>
        <p className="text-gray-400 text-sm">{t('results.empty.withFiltersHint')}</p>
        <button
          type="button"
          onClick={onClearFilters}
          className="mt-2 px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-xl hover:bg-indigo-100 transition-colors"
        >
          {t('results.empty.clearAll')}
        </button>
      </div>
    );
  }

  if (tab === 'starred') {
    return (
      <div className="text-center py-16 space-y-2">
        <Star className="w-8 h-8 text-gray-300 mx-auto" />
        <p className="text-gray-500 text-lg">{t('results.empty.starred')}</p>
        <p className="text-gray-400 text-sm">{t('results.empty.starredHint')}</p>
      </div>
    );
  }

  return (
    <div className="text-center py-16">
      <p className="text-gray-400 text-lg">{t('results.empty.category')}</p>
    </div>
  );
}
