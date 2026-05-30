'use client';

import {
  COLLEGE_KEYS,
  DEFAULT_FELLOWSHIP_FILTERS,
  FELLOWSHIP_YEARS,
  type CollegeKey,
  type FellowshipFiltersState,
  type FellowshipYear,
  type IntlFilter,
} from './types';
import { useT } from '@/i18n/client';

interface FellowshipFiltersProps {
  filters: FellowshipFiltersState;
  onChange: (next: FellowshipFiltersState) => void;
  totalCount: number;
  filteredCount: number;
}

export default function FellowshipFilters({
  filters,
  onChange,
  totalCount,
  filteredCount,
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
            className="text-[12px] font-medium text-blue-600 hover:text-blue-700"
          >
            {t('fellowships.clearFilters')}
          </button>
        )}
      </div>

      <fieldset className="mb-4">
        <legend className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-2">
          {t('fellowships.year')}
        </legend>
        <div className="flex flex-wrap gap-1.5">
          <FilterPill
            active={filters.year === ''}
            onClick={() => onChange({ ...filters, year: '' })}
            label={t('fellowships.years.any')}
          />
          {FELLOWSHIP_YEARS.map((y) => (
            <FilterPill
              key={y}
              active={filters.year === y}
              onClick={() => onChange({ ...filters, year: y as FellowshipYear })}
              label={t(`fellowships.years.${y}`)}
            />
          ))}
        </div>
      </fieldset>

      <fieldset className="mb-4">
        <legend className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-2">
          {t('fellowships.intl')}
        </legend>
        <div className="flex flex-wrap gap-1.5">
          <FilterPill
            active={filters.international === ''}
            onClick={() => onChange({ ...filters, international: '' })}
            label={t('fellowships.intlOptions.any')}
          />
          <FilterPill
            active={filters.international === 'yes'}
            onClick={() => onChange({ ...filters, international: 'yes' as IntlFilter })}
            label={t('fellowships.intlOptions.yes')}
          />
          <FilterPill
            active={filters.international === 'no'}
            onClick={() => onChange({ ...filters, international: 'no' as IntlFilter })}
            label={t('fellowships.intlOptions.no')}
          />
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-2">
          {t('fellowships.college')}
        </legend>
        <div className="flex flex-wrap gap-1.5">
          {COLLEGE_KEYS.map((c) => (
            <FilterPill
              key={c}
              active={filters.college === c}
              onClick={() => onChange({ ...filters, college: c as CollegeKey })}
              label={t(`fellowships.colleges.${c}`)}
            />
          ))}
        </div>
      </fieldset>
    </div>
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
          ? 'bg-blue-600 text-white'
          : 'bg-black/[0.04] text-gray-600 hover:bg-black/[0.08]'
      }`}
    >
      {label}
    </button>
  );
}
