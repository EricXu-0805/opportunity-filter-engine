'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { ArrowRight, GraduationCap } from 'lucide-react';
import { useT } from '@/i18n/client';
import EmptyState from './EmptyState';
import FellowshipCard from './FellowshipCard';
import FellowshipFilters from './FellowshipFilters';
import { useFellowshipsData } from './use-fellowships-data';
import {
  applyFellowshipFilters,
  DEFAULT_FELLOWSHIP_FILTERS,
  type FellowshipFiltersState,
} from './types';

const PAGE_SIZE = 30;

export default function FellowshipsPage() {
  const { t } = useT();
  const { loading, error, opportunities } = useFellowshipsData();
  const [filters, setFilters] = useState<FellowshipFiltersState>(DEFAULT_FELLOWSHIP_FILTERS);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const filtered = useMemo(
    () => applyFellowshipFilters(opportunities, filters),
    [opportunities, filters],
  );

  const visible = filtered.slice(0, visibleCount);
  const hasFilters = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FELLOWSHIP_FILTERS);

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-14 sm:py-20">
      <header className="mb-10">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 to-blue-500 text-white flex items-center justify-center">
            <GraduationCap className="w-5 h-5" aria-hidden="true" />
          </div>
          <div>
            <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 tracking-tight leading-[1.1]">
              {t('fellowships.title')}
            </h1>
          </div>
        </div>
        <p className="mt-3 text-base sm:text-lg text-gray-500 max-w-2xl">
          {t('fellowships.subtitle')}
        </p>
        <div className="mt-4">
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-700"
          >
            {t('fellowships.toMatcher')}
            <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </Link>
        </div>
      </header>

      <FellowshipFilters
        filters={filters}
        onChange={(next) => { setFilters(next); setVisibleCount(PAGE_SIZE); }}
        totalCount={opportunities.length}
        filteredCount={filtered.length}
      />

      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="rounded-2xl bg-white border border-gray-200 p-5 shadow-[0_1px_6px_rgba(0,0,0,0.04)] space-y-3"
            >
              <div className="skeleton h-5 w-3/4" />
              <div className="skeleton h-4 w-1/2" />
              <div className="flex gap-2">
                <div className="skeleton h-6 w-16 rounded-full" />
                <div className="skeleton h-6 w-20 rounded-full" />
              </div>
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {!loading && !error && (
        <>
          {filtered.length === 0 ? (
            <EmptyState
              hasFilters={hasFilters}
              onClearFilters={() => { setFilters(DEFAULT_FELLOWSHIP_FILTERS); setVisibleCount(PAGE_SIZE); }}
            />
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {visible.map((opp) => (
                  <FellowshipCard key={opp.id} opp={opp} />
                ))}
              </div>
              {visibleCount < filtered.length && (
                <div className="mt-8 flex justify-center">
                  <button
                    type="button"
                    onClick={() => setVisibleCount((n) => n + PAGE_SIZE)}
                    className="px-5 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
                  >
                    {t('fellowships.loadMore', { remaining: filtered.length - visibleCount })}
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
