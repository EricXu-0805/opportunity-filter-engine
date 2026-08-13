'use client';

import { useT } from '@/i18n/client';
import {
  DEFAULT_FELLOWSHIP_FILTERS,
  type DeadlineFilter,
  type FellowshipFiltersState,
  type IntlFilter,
  type PaidFilter,
  type ProgramTypeFilter,
} from './types';

interface FellowshipFiltersProps {
  filters: FellowshipFiltersState;
  onChange: (next: FellowshipFiltersState) => void;
  totalCount: number;
  filteredCount: number;
  /**
   * Whether any loaded record could satisfy the "upcoming" pill.
   *
   * It requires `deadline_is_estimate === false` — a confirmed future date, not
   * a guess. Only nsf_reu ever writes that field and no NSF shard is in the
   * published corpus, so the pill matched 0 of 1,406 records: a control whose
   * every click returned an empty page. Rendering it on the evidence instead of
   * unconditionally means it comes back by itself when real deadlines land.
   */
  hasConfirmedDeadlines: boolean;
}

export default function FellowshipFilters({
  filters,
  onChange,
  totalCount,
  filteredCount,
  hasConfirmedDeadlines,
}: FellowshipFiltersProps) {
  const { t } = useT();
  const isClean = JSON.stringify(filters) === JSON.stringify(DEFAULT_FELLOWSHIP_FILTERS);

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-5 mb-8 shadow-[0_1px_6px_rgba(0,0,0,0.04)]">
      <div className="flex items-center justify-between mb-4 gap-3">
        <p className="text-[13px] text-gray-500">
          {t('fellowships.countLabel', { filtered: filteredCount, total: totalCount })}
        </p>
        {!isClean && (
          <button
            type="button"
            onClick={() => onChange(DEFAULT_FELLOWSHIP_FILTERS)}
            className="text-[12px] font-medium text-indigo-600 hover:text-indigo-700"
          >
            {t('fellowships.clearFilters')}
          </button>
        )}
      </div>

      <FilterGroup label={t('fellowships.type')}>
        {(['', 'fellowship', 'summer_program'] as ProgramTypeFilter[]).map((type) => (
          <FilterPill
            key={type || 'any'}
            active={filters.type === type}
            onClick={() => onChange({ ...filters, type })}
            label={t(`fellowships.types.${type || 'any'}`)}
          />
        ))}
      </FilterGroup>

      <FilterGroup label={t('fellowships.intl')}>
        {(['', 'yes', 'no'] as IntlFilter[]).map((international) => (
          <FilterPill
            key={international || 'any'}
            active={filters.international === international}
            onClick={() => onChange({ ...filters, international })}
            label={t(`fellowships.intlOptions.${international || 'any'}`)}
          />
        ))}
      </FilterGroup>

      <FilterGroup label={t('fellowships.paid')}>
        {(['', 'paid', 'unpaid'] as PaidFilter[]).map((paid) => (
          <FilterPill
            key={paid || 'any'}
            active={filters.paid === paid}
            onClick={() => onChange({ ...filters, paid })}
            label={t(`fellowships.paidOptions.${paid || 'any'}`)}
          />
        ))}
      </FilterGroup>

      <FilterGroup label={t('fellowships.deadline')} last>
        {((hasConfirmedDeadlines
          ? ['', 'upcoming', 'rolling']
          : ['', 'rolling']) as DeadlineFilter[]).map((deadline) => (
          <FilterPill
            key={deadline || 'any'}
            active={filters.deadline === deadline}
            onClick={() => onChange({ ...filters, deadline })}
            label={t(`fellowships.deadlineOptions.${deadline || 'any'}`)}
          />
        ))}
      </FilterGroup>
    </div>
  );
}

function FilterGroup({
  label,
  last = false,
  children,
}: {
  label: string;
  last?: boolean;
  children: React.ReactNode;
}) {
  return (
    <fieldset className={last ? undefined : 'mb-4'}>
      <legend className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-2">
        {label}
      </legend>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </fieldset>
  );
}

function FilterPill({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`px-3 py-1.5 rounded-full text-[12px] font-medium transition-colors ${
        active
          ? 'bg-indigo-600 text-white'
          : 'bg-black/[0.04] text-gray-600 hover:bg-black/[0.08]'
      }`}
    >
      {label}
    </button>
  );
}
