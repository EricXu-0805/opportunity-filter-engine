'use client';

import { EyeOff } from 'lucide-react';
import { FilterSelect } from './FilterSelect';
import { MinScoreFilter } from './MinScoreFilter';
import { DEFAULT_FILTERS, type Filters, type SortKey, type TFunc } from './types';

export interface FilterRailProps {
  filters: Filters;
  onFiltersChange: (next: Filters) => void;
  sortBy: SortKey;
  onSortByChange: (next: SortKey) => void;
  showDismissed: boolean;
  onShowDismissedChange: (next: boolean) => void;
  dismissedCount: number;
  activeFilterCount: number;
  t: TFunc;
}

export function FilterRail({
  filters,
  onFiltersChange,
  sortBy,
  onSortByChange,
  showDismissed,
  onShowDismissedChange,
  dismissedCount,
  activeFilterCount,
  t,
}: FilterRailProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 -mx-4 px-4 sm:mx-0 sm:px-0">
      <FilterSelect
        value={filters.paid}
        onChange={(v) => onFiltersChange({ ...filters, paid: v as Filters['paid'] })}
        options={[['', t('results.filters.paidAll')], ['yes', t('results.filters.paidYes')], ['no', t('results.filters.paidNo')]]}
      />
      <FilterSelect
        value={filters.intl}
        onChange={(v) => onFiltersChange({ ...filters, intl: v as Filters['intl'] })}
        options={[['', t('results.filters.intlAll')], ['yes', t('results.filters.intlYes')], ['no', t('results.filters.intlNo')]]}
      />
      <FilterSelect
        value={filters.source}
        onChange={(v) => onFiltersChange({ ...filters, source: v as Filters['source'] })}
        options={[['', t('results.filters.sourceAll')], ['uiuc_sro', t('results.filters.sourceUiucSro')], ['nsf_reu', t('results.filters.sourceNsfReu')], ['uiuc_faculty', t('results.filters.sourceUiucFaculty')], ['handshake', t('results.filters.sourceHandshake')], ['manual', t('results.filters.sourceManual')], ['uiuc_our_rss', t('results.filters.sourceOurRss')]]}
      />
      <FilterSelect
        value={filters.onCampus}
        onChange={(v) => onFiltersChange({ ...filters, onCampus: v as Filters['onCampus'] })}
        options={[['', t('results.filters.locAll')], ['yes', t('results.filters.locYes')], ['no', t('results.filters.locNo')]]}
      />
      <FilterSelect
        value={filters.deadline}
        onChange={(v) => onFiltersChange({ ...filters, deadline: v as Filters['deadline'] })}
        options={[['', t('results.filters.deadlineAll')], ['7', t('results.filters.deadline7')], ['14', t('results.filters.deadline14')], ['30', t('results.filters.deadline30')], ['passed', t('results.filters.deadlinePassed')]]}
      />
      <FilterSelect
        value={sortBy}
        onChange={(v) => onSortByChange(v as SortKey)}
        options={[['score', t('results.filters.sortScore')], ['deadline', t('results.filters.sortDeadline')], ['newest', t('results.filters.sortNewest')]]}
      />
      <MinScoreFilter
        value={filters.minScore}
        onChange={(v) => onFiltersChange({ ...filters, minScore: v })}
        t={t}
      />
      {dismissedCount > 0 && (
        <button
          type="button"
          onClick={() => onShowDismissedChange(!showDismissed)}
          className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] font-medium border transition-colors ${
            showDismissed
              ? 'bg-gray-100 border-gray-300 text-gray-700'
              : 'bg-white border-gray-200 text-gray-400 hover:border-gray-300'
          }`}
          title={showDismissed ? t('results.hideDismissedTitle') : t('results.showDismissedTitle')}
        >
          <EyeOff className="w-3 h-3" />
          {showDismissed
            ? t('results.hideDismissedLabel', { count: dismissedCount })
            : t('results.showDismissedLabel', { count: dismissedCount })}
        </button>
      )}
      {activeFilterCount > 0 && (
        <button
          type="button"
          onClick={() => onFiltersChange(DEFAULT_FILTERS)}
          className="px-3 py-1.5 text-[12px] font-medium text-red-500 hover:text-red-700 transition-colors"
        >
          {activeFilterCount > 1
            ? t('results.clearNFilters', { count: activeFilterCount })
            : t('results.clearNFilter', { count: activeFilterCount })}
        </button>
      )}
    </div>
  );
}
