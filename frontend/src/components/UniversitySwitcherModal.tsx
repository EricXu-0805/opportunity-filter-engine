'use client';

/*
 * "Change University" modal — production port of the Variant A prototype
 * (design/university-switcher branch, decision in PR #187).
 *
 * Visual language mirrors AuthModal / SaveSearchDialog:
 *   fixed inset-0 z-50 flex items-center justify-center p-4
 *   absolute inset-0 bg-gray-900/60 backdrop-blur-sm
 *   relative w-full bg-white rounded-2xl shadow-2xl animate-in
 * Mounted conditionally by the parent (same pattern as SaveSearchDialog)
 * so each open starts from fresh useState initializers.
 */

import { Check, GraduationCap, MapPin, Search, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useT } from '@/i18n/client';
import { COLLEGES, COLLEGE_MAJORS } from '@/lib/colleges';
import { SCHOOLS, type School } from '@/lib/schools';

interface UniversitySwitcherModalProps {
  initialSelectedSlug: string;
  onCancel: () => void;
  onConfirm: (slug: string) => void;
}

const UIUC_MAJOR_COUNT = Object.values(COLLEGE_MAJORS).reduce((sum, m) => sum + m.length, 0);

function CoverageChip({ school, t }: { school: School; t: ReturnType<typeof useT>['t'] }) {
  const { campusOpportunities, note } = school.coverage;
  if (campusOpportunities === 'pending') {
    return (
      <span className="inline-flex items-center px-2.5 py-1 rounded-lg text-[11px] font-medium bg-amber-50/80 text-amber-600">
        {t(note)}
      </span>
    );
  }
  const cls = campusOpportunities >= 1000
    ? 'bg-emerald-50/80 text-emerald-600'
    : 'bg-blue-50/80 text-blue-600';
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium ${cls}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-60" aria-hidden="true" />
      {t(note, { count: campusOpportunities.toLocaleString() })}
    </span>
  );
}

export default function UniversitySwitcherModal({
  initialSelectedSlug,
  onCancel,
  onConfirm,
}: UniversitySwitcherModalProps) {
  const { t, locale } = useT();
  const [query, setQuery] = useState('');
  const [selectedSlug, setSelectedSlug] = useState(initialSelectedSlug);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    searchRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); onCancel(); }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return SCHOOLS;
    return SCHOOLS.filter((u) =>
      [u.name, u.nameZh, u.shortName, u.location].some((s) => s.toLowerCase().includes(q)),
    );
  }, [query]);

  const selected = SCHOOLS.find((u) => u.slug === selectedSlug);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="university-switcher-title"
    >
      <div className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm" onClick={onCancel} aria-hidden="true" />
      <div className="relative w-full max-w-2xl max-h-[85vh] flex flex-col bg-white rounded-2xl shadow-2xl overflow-hidden animate-in">

        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 id="university-switcher-title" className="text-[15px] font-semibold text-gray-900">
            {t('universitySwitcher.title')}
          </h2>
          <button
            type="button"
            onClick={onCancel}
            className="p-2 -mr-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label={t('universitySwitcher.closeAria')}
          >
            <X className="w-4 h-4 text-gray-400" aria-hidden="true" />
          </button>
        </div>

        <div className="px-6 pt-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" aria-hidden="true" />
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('universitySwitcher.searchPlaceholder')}
              aria-label={t('universitySwitcher.searchAria')}
              className="w-full pl-9 pr-3.5 py-2.5 border border-gray-200 rounded-xl text-[14px] placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {filtered.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-gray-200 px-6 py-12 text-center">
              <p className="text-sm font-medium text-gray-600">
                {t('universitySwitcher.noMatch', { query: query.trim() })}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {filtered.map((entry) => {
                const isSelected = entry.slug === selectedSlug;
                const primaryName = locale === 'zh' ? entry.nameZh : entry.name;
                const secondaryName = locale === 'zh' ? entry.name : entry.nameZh;
                return (
                  <button
                    key={entry.slug}
                    type="button"
                    onClick={() => setSelectedSlug(entry.slug)}
                    aria-pressed={isSelected}
                    data-testid={`university-card-${entry.slug}`}
                    className={`relative text-left rounded-xl border p-4 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                      isSelected
                        ? 'border-blue-500 ring-2 ring-blue-500/30 bg-blue-50/30'
                        : 'border-gray-200 hover:border-gray-300 hover:shadow-sm'
                    }`}
                  >
                    {isSelected && (
                      <span className="absolute top-3 right-3 w-5 h-5 rounded-full bg-blue-600 flex items-center justify-center">
                        <Check className="w-3 h-3 text-white" aria-hidden="true" />
                      </span>
                    )}
                    <p className="text-[14px] font-semibold text-gray-900 leading-snug pr-6">{primaryName}</p>
                    <p className="text-[12px] text-gray-500 mt-0.5">{secondaryName}</p>
                    <p className="flex items-center gap-1 text-[12px] text-gray-400 mt-1.5">
                      <MapPin className="w-3 h-3" aria-hidden="true" />
                      {entry.location}
                    </p>
                    <p className="flex items-center gap-1 text-[12px] text-gray-500 mt-1">
                      <GraduationCap className="w-3 h-3 text-gray-400" aria-hidden="true" />
                      {entry.slug === 'uiuc'
                        ? t('universitySwitcher.catalogSummary', {
                            colleges: COLLEGES.length,
                            majors: UIUC_MAJOR_COUNT,
                          })
                        : t('universitySwitcher.catalogPending')}
                    </p>
                    <div className="mt-2.5">
                      <CoverageChip school={entry} t={t} />
                    </div>
                  </button>
                );
              })}
            </div>
          )}

          <p className="mt-4 text-[11px] text-gray-400 leading-relaxed">
            {t('universitySwitcher.footerNote')}
          </p>
        </div>

        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-gray-100 bg-gray-50/50">
          <p className="text-[13px] text-gray-600 truncate">
            {t('universitySwitcher.selectedLabel')}{' '}
            <span className="font-medium text-gray-900">{selected ? selected.shortName : '—'}</span>
          </p>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2 rounded-lg text-[13px] font-medium text-gray-600 hover:bg-gray-100 transition-colors"
            >
              {t('common.cancel')}
            </button>
            <button
              type="button"
              onClick={() => onConfirm(selectedSlug)}
              disabled={!selected}
              className="px-4 py-2 rounded-lg text-[13px] font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {t('universitySwitcher.confirm')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
