'use client';

import { useState } from 'react';
import { ChevronDown, EyeOff, SlidersHorizontal } from 'lucide-react';
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

/**
 * R69-B: on viewports below the `sm` breakpoint the chip stack collapses
 * behind a single "Filters · N active" toggle button. Desktop layout
 * (>= 640px) is unchanged — the chips render in their current flex-wrap
 * row. The mobile collapse cuts roughly 200px of above-the-fold chrome on
 * a 375x812 viewport, which is what was pushing the first match card
 * below the fold pre-R69.
 */
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
  const [mobileExpanded, setMobileExpanded] = useState(false);
  const clearLabel = activeFilterCount > 1
    ? t('results.clearNFilters', { count: activeFilterCount })
    : t('results.clearNFilter', { count: activeFilterCount });

  return (
    <div>
      {/* Mobile toggle row — visible only below sm. The Clear button
          sits next to the toggle so users can wipe filters without
          having to expand first (the count badge tells them why
          they'd want to). */}
      <div className="flex sm:hidden items-center gap-2 -mx-4 px-4 mb-2">
        <button
          type="button"
          onClick={() => setMobileExpanded((v) => !v)}
          aria-expanded={mobileExpanded}
          aria-controls="filter-rail-chips"
          aria-label={
            mobileExpanded
              ? t('results.filtersMobileCollapseAria')
              : t('results.filtersMobileExpandAria')
          }
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium bg-white border border-gray-200 text-gray-700 hover:border-gray-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 transition-colors"
        >
          <SlidersHorizontal className="w-3.5 h-3.5" aria-hidden="true" />
          <span>{t('results.filtersMobileToggle')}</span>
          {activeFilterCount > 0 && (
            <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-semibold bg-blue-100 text-blue-700">
              {activeFilterCount}
            </span>
          )}
          <ChevronDown
            className={`w-3.5 h-3.5 transition-transform duration-200 ${mobileExpanded ? 'rotate-180' : ''}`}
            aria-hidden="true"
          />
        </button>
        {activeFilterCount > 0 && (
          <button
            type="button"
            onClick={() => onFiltersChange(DEFAULT_FILTERS)}
            className="px-3 py-1.5 text-[12px] font-medium text-red-500 hover:text-red-700 transition-colors"
          >
            {clearLabel}
          </button>
        )}
      </div>

      {/* Chips row — always visible on desktop (sm:flex). On mobile,
          visibility tracks mobileExpanded. We pick `flex` vs `hidden`
          here rather than relying on `sm:flex` alone so the chips
          actually render when a mobile user taps the toggle. */}
      <div
        id="filter-rail-chips"
        className={`${mobileExpanded ? 'flex' : 'hidden'} sm:flex flex-wrap items-center gap-2 -mx-4 px-4 sm:mx-0 sm:px-0`}
      >
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
        {/* Desktop Clear — hidden on mobile because the mobile toggle row
            already has its own Clear button next to the toggle. */}
        {activeFilterCount > 0 && (
          <button
            type="button"
            onClick={() => onFiltersChange(DEFAULT_FILTERS)}
            className="hidden sm:inline-flex px-3 py-1.5 text-[12px] font-medium text-red-500 hover:text-red-700 transition-colors"
          >
            {clearLabel}
          </button>
        )}
      </div>
    </div>
  );
}
