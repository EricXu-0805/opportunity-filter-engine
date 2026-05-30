'use client';

import { BellRing, Cloud, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { savedSearchToUrl, type SavedSearch } from '@/lib/saved-searches';
import {
  formatSavedSearchTimestamp,
  summarizeSavedSearchFilters,
  type TFunc,
} from './types';

export interface SavedSearchesSectionProps {
  savedSearches: SavedSearch[];
  onApplyOptimisticClear: (id: string) => void;
  onRemove: (search: SavedSearch) => void;
  t: TFunc;
}

export function SavedSearchesSection({
  savedSearches,
  onApplyOptimisticClear,
  onRemove,
  t,
}: SavedSearchesSectionProps) {
  return (
    <section className="mb-8" aria-labelledby="saved-searches-heading">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <h2 id="saved-searches-heading" className="text-[15px] font-semibold text-gray-900 inline-flex items-center gap-2">
            <Cloud className="w-4 h-4 text-indigo-500" aria-hidden="true" />
            {t('favorites.savedSearches.sectionTitle')}
          </h2>
          {savedSearches.length > 0 && (
            <p className="text-[12px] text-gray-400 mt-0.5">
              {t('favorites.savedSearches.sectionHint')}
            </p>
          )}
        </div>
        {savedSearches.length > 0 && (
          <span className="text-[11px] text-gray-400 tabular-nums">
            {t('favorites.savedSearches.itemCount', { count: savedSearches.length })}
          </span>
        )}
      </div>
      {savedSearches.length === 0 ? (
        <div className="text-center py-6 px-4 rounded-xl bg-gray-50/80 border border-dashed border-gray-200">
          <p className="text-[13px] text-gray-500">
            {t('favorites.savedSearches.emptyHint')}
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {savedSearches.map((search) => {
            const summary = summarizeSavedSearchFilters(search, t);
            const timestampLabel = formatSavedSearchTimestamp(search.last_run_at, t);
            const newCount = search.new_match_ids?.length ?? 0;
            const hasNew = newCount > 0;
            return (
              <li
                key={search.id}
                className="group bg-white rounded-xl shadow-[0_1px_6px_rgba(0,0,0,0.04)] hover:shadow-[0_2px_12px_rgba(0,0,0,0.06)] transition-shadow flex items-center"
              >
                <Link
                  href={savedSearchToUrl(
                    search,
                    hasNew
                      ? { highlight: search.new_match_ids, savedSearchId: search.id }
                      : undefined,
                  )}
                  onClick={hasNew ? () => onApplyOptimisticClear(search.id) : undefined}
                  aria-label={t('favorites.savedSearches.applyAria', { name: search.name })}
                  className="flex-1 min-w-0 px-4 py-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded-l-xl"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-[14px] font-medium text-gray-900 truncate">
                      {search.name}
                    </span>
                    {hasNew && (
                      <span
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-100/80 text-amber-700 text-[11px] font-semibold shrink-0"
                        aria-label={t('favorites.savedSearches.newMatchesAria', { count: newCount })}
                      >
                        <BellRing className="w-3 h-3" aria-hidden="true" />
                        {t('favorites.savedSearches.newBadge', { count: newCount })}
                      </span>
                    )}
                  </div>
                  <p className="text-[12px] text-gray-500 truncate mt-0.5">{summary}</p>
                  <p className="text-[11px] text-gray-400 truncate mt-0.5 tabular-nums">{timestampLabel}</p>
                </Link>
                <button
                  type="button"
                  onClick={() => onRemove(search)}
                  aria-label={t('favorites.savedSearches.deleteAria', { name: search.name })}
                  className="p-3 mr-1 rounded-lg text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
                >
                  <Trash2 className="w-4 h-4" aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
