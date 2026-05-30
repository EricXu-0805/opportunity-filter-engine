'use client';

import { BookmarkPlus, Cloud, Search, X } from 'lucide-react';
import type { FilterPreset } from '@/lib/filter-presets';
import { PresetPill } from './PresetPill';
import { SEARCH_ALIASES_FOR_HINT, type TFunc } from './types';

export interface ResultsSearchProps {
  searchQuery: string;
  onSearchQueryChange: (next: string) => void;
  debouncedQuery: string;
  presets: FilterPreset[];
  activePresetId: string | null;
  activeFilterCount: number;
  filteredCount: number;
  onApplyPreset: (preset: FilterPreset) => void;
  onDeletePreset: (id: string) => void;
  onSavePreset: () => void;
  onSaveSearch: () => void;
  t: TFunc;
}

export function ResultsSearch({
  searchQuery,
  onSearchQueryChange,
  debouncedQuery,
  presets,
  activePresetId,
  activeFilterCount,
  filteredCount,
  onApplyPreset,
  onDeletePreset,
  onSavePreset,
  onSaveSearch,
  t,
}: ResultsSearchProps) {
  const hasActiveFilters = activeFilterCount > 0 || !!debouncedQuery.trim();
  return (
    <>
      <div className="relative">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          id="results-search-input"
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchQueryChange(e.target.value)}
          placeholder={t('results.search.placeholder')}
          className="w-full pl-11 pr-24 py-3 bg-white rounded-xl border-0 shadow-[0_1px_4px_rgba(0,0,0,0.04)] text-[14px] text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all duration-300"
        />
        <kbd className="absolute right-10 top-1/2 -translate-y-1/2 hidden sm:inline-flex items-center justify-center h-5 px-1.5 text-[10px] font-mono text-gray-400 bg-gray-100 border border-gray-200 rounded">
          /
        </kbd>
        {searchQuery && (
          <button
            type="button"
            onClick={() => onSearchQueryChange('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full hover:bg-gray-100 transition-colors"
            aria-label={t('results.clearSearchAria')}
          >
            <X className="w-3.5 h-3.5 text-gray-400" />
          </button>
        )}
      </div>
      {(presets.length > 0 || hasActiveFilters) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {presets.map(p => (
            <PresetPill
              key={p.id}
              preset={p}
              active={p.id === activePresetId}
              onApply={onApplyPreset}
              onDelete={onDeletePreset}
              t={t}
            />
          ))}
          {hasActiveFilters && (
            <>
              <button
                type="button"
                onClick={onSavePreset}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 transition-colors"
                title={t('results.savePresetTitle')}
              >
                <BookmarkPlus className="w-3 h-3" />
                {t('results.savePresetButton')}
              </button>
              <button
                type="button"
                onClick={onSaveSearch}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 transition-colors"
                title={t('results.saveSearchTitle')}
              >
                <Cloud className="w-3 h-3" />
                {t('results.saveSearchButton')}
              </button>
            </>
          )}
        </div>
      )}
      {hasActiveFilters && (
        <p className="text-[13px] text-gray-400 mt-2">
          {filteredCount === 0
            ? t('results.search.noResults')
            : t('results.search.resultsFound', { count: filteredCount })}
          {debouncedQuery.trim() && (
            <span> {t('results.resultsForPrefix')} <span className="font-medium text-gray-600">&ldquo;{debouncedQuery}&rdquo;</span>
              {SEARCH_ALIASES_FOR_HINT[debouncedQuery.toLowerCase()] && (
                <span className="text-gray-300"> ({t('results.alsoMatching', { terms: SEARCH_ALIASES_FOR_HINT[debouncedQuery.toLowerCase()]?.join(', ') ?? '' })})</span>
              )}
            </span>
          )}
        </p>
      )}
    </>
  );
}
