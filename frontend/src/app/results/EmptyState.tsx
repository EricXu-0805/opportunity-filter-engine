import { Star } from 'lucide-react';
import type { Tab, TFunc } from './types';

export function EmptyState({
  hasFilters,
  tab,
  onClearFilters,
  t,
}: {
  hasFilters: boolean;
  tab: Tab;
  onClearFilters: () => void;
  t: TFunc;
}) {
  if (hasFilters) {
    return (
      <div className="text-center py-16 space-y-3">
        <p className="text-gray-500 text-lg">{t('results.empty.withFilters')}</p>
        <p className="text-gray-400 text-sm">{t('results.empty.withFiltersHint')}</p>
        <button
          type="button"
          onClick={onClearFilters}
          className="mt-2 px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 rounded-xl hover:bg-blue-100 transition-colors"
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
