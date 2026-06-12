'use client';

/*
 * "Change University" modal — design prototype (/labs/university only).
 *
 * Visual language mirrors AuthModal / SaveSearchDialog exactly:
 *   fixed inset-0 z-50 flex items-center justify-center p-4
 *   absolute inset-0 bg-gray-900/60 backdrop-blur-sm
 *   relative w-full bg-white rounded-2xl shadow-2xl animate-in
 * Mounted conditionally by the parent (same pattern as SaveSearchDialog)
 * so each open starts from fresh useState initializers.
 *
 * Variant A: every university selectable; honest coverage badge per card.
 * Variant B: only schools with campus data selectable; the rest render
 *            dimmed with a "Coming soon" chip + a vote/notify ghost button.
 */

import { Bell, Check, GraduationCap, MapPin, Search, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  NATIONAL_OPPORTUNITY_COUNT,
  UNIVERSITIES,
  type UniversityEntry,
} from './universities';

export type SwitcherVariant = 'A' | 'B';

interface UniversitySwitcherModalProps {
  variant: SwitcherVariant;
  initialSelectedId: string;
  onCancel: () => void;
  onConfirm: (id: string) => void;
  onVote: (entry: UniversityEntry) => void;
}

function CoverageChip({ entry, variant }: { entry: UniversityEntry; variant: SwitcherVariant }) {
  const { campusOpportunities, nationalOnly } = entry.dataCoverage;
  if (!nationalOnly && campusOpportunities >= 1000) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-emerald-50/80 text-emerald-600">
        <span className="w-1.5 h-1.5 rounded-full bg-current opacity-60" aria-hidden="true" />
        {campusOpportunities.toLocaleString()}+ 校内+全国机会
      </span>
    );
  }
  if (!nationalOnly) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-blue-50/80 text-blue-600">
        <span className="w-1.5 h-1.5 rounded-full bg-current opacity-60" aria-hidden="true" />
        {campusOpportunities} campus opportunities
      </span>
    );
  }
  if (variant === 'B') {
    return (
      <span className="inline-flex items-center px-2.5 py-1 rounded-lg text-[11px] font-medium bg-gray-100/80 text-gray-500">
        Coming soon
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2.5 py-1 rounded-lg text-[11px] font-medium bg-amber-50/80 text-amber-600">
      全国性机会 · 校内数据建设中
    </span>
  );
}

function CardBody({ entry, variant }: { entry: UniversityEntry; variant: SwitcherVariant }) {
  return (
    <>
      <p className="text-[14px] font-semibold text-gray-900 leading-snug pr-6">{entry.name}</p>
      <p className="text-[12px] text-gray-500 mt-0.5">{entry.nameZh}</p>
      <p className="flex items-center gap-1 text-[12px] text-gray-400 mt-1.5">
        <MapPin className="w-3 h-3" aria-hidden="true" />
        {entry.location}
      </p>
      <p className="flex items-center gap-1 text-[12px] text-gray-500 mt-1">
        <GraduationCap className="w-3 h-3 text-gray-400" aria-hidden="true" />
        {entry.catalog
          ? `${entry.catalog.colleges} colleges · ${entry.catalog.majors} majors`
          : '院系目录建设中 · catalog pending'}
      </p>
      <div className="mt-2.5">
        <CoverageChip entry={entry} variant={variant} />
      </div>
    </>
  );
}

export default function UniversitySwitcherModal({
  variant,
  initialSelectedId,
  onCancel,
  onConfirm,
  onVote,
}: UniversitySwitcherModalProps) {
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(initialSelectedId);
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
    if (!q) return UNIVERSITIES;
    return UNIVERSITIES.filter((u) =>
      [u.name, u.nameZh, u.shortTag, u.location].some((s) => s.toLowerCase().includes(q)),
    );
  }, [query]);

  const selected = UNIVERSITIES.find((u) => u.id === selectedId);

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
            切换学校 · Change University
          </h2>
          <button
            type="button"
            onClick={onCancel}
            className="p-2 -mr-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Close"
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
              placeholder="搜索学校… Search universities…"
              aria-label="Search universities"
              className="w-full pl-9 pr-3.5 py-2.5 border border-gray-200 rounded-xl text-[14px] placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {filtered.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-gray-200 px-6 py-12 text-center">
              <p className="text-sm font-medium text-gray-600">没有匹配的学校</p>
              <p className="mt-1 text-[13px] text-gray-400">No universities match &ldquo;{query.trim()}&rdquo;</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {filtered.map((entry) => {
                const isSelected = entry.id === selectedId;
                const selectable = variant === 'A' || !entry.dataCoverage.nationalOnly;

                if (!selectable) {
                  // Plain div, NOT aria-disabled: the nested vote button must
                  // stay reachable for assistive tech (and Playwright).
                  return (
                    <div
                      key={entry.id}
                      data-testid={`university-card-${entry.id}`}
                      className="relative text-left rounded-xl border border-gray-200 p-4 opacity-60"
                    >
                      <CardBody entry={entry} variant={variant} />
                      <button
                        type="button"
                        onClick={() => onVote(entry)}
                        className="mt-2.5 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 text-[12px] font-medium text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors"
                      >
                        <Bell className="w-3 h-3" aria-hidden="true" />
                        提醒我 / Vote
                      </button>
                    </div>
                  );
                }

                return (
                  <button
                    key={entry.id}
                    type="button"
                    onClick={() => setSelectedId(entry.id)}
                    aria-pressed={isSelected}
                    data-testid={`university-card-${entry.id}`}
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
                    <CardBody entry={entry} variant={variant} />
                  </button>
                );
              })}
            </div>
          )}

          {variant === 'A' && (
            <p className="mt-4 text-[11px] text-gray-400 leading-relaxed">
              所有学校都能看到约 {NATIONAL_OPPORTUNITY_COUNT.toLocaleString()} 条全国性机会（NSF REU、Simplify
              实习等）。Every school sees ~{NATIONAL_OPPORTUNITY_COUNT.toLocaleString()} national opportunities;
              campus-specific coverage is shown per card.
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-gray-100 bg-gray-50/50">
          <p className="text-[13px] text-gray-600 truncate">
            已选 Selected:{' '}
            <span className="font-medium text-gray-900">{selected ? selected.shortTag : '—'}</span>
          </p>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2 rounded-lg text-[13px] font-medium text-gray-600 hover:bg-gray-100 transition-colors"
            >
              取消 Cancel
            </button>
            <button
              type="button"
              onClick={() => onConfirm(selectedId)}
              disabled={!selected}
              className="px-4 py-2 rounded-lg text-[13px] font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              确认 Confirm
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
