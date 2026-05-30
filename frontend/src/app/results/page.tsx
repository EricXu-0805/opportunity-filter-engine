'use client';

import { useCallback, useEffect, useMemo, useState, Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter, useSearchParams } from 'next/navigation';
import { AlertCircle, ArrowLeft } from 'lucide-react';

import StorageStatusBanner from '@/components/StorageStatusBanner';
import { KeyboardHelpDialog } from '@/components/KeyboardHelpDialog';
import { useDebounce } from '@/lib/use-debounce';
import { useLoadingNarrative } from '@/lib/use-loading-narrative';
import { useHasLocalStorageKey, useLocalStorageJSON } from '@/lib/use-local-storage-json';
import { downloadCSV } from '@/lib/csv-export';
import { matchesToCSV } from '@/lib/match-utils';
import {
  parsePresetsArray,
  removePreset,
  savePresets,
  upsertPreset,
  type FilterPreset,
} from '@/lib/filter-presets';
import { saveSearch } from '@/lib/saved-searches';
import {
  getFavorites,
  getInteractions,
  removeInteraction,
  toggleFavorite,
  trackInteraction,
  type InteractionType,
} from '@/lib/supabase';
import { useT } from '@/i18n/client';

import { EmptyState } from './EmptyState';
import { FilterRail } from './FilterRail';
import { MatchList } from './MatchList';
import { ResultsHeader } from './ResultsHeader';
import { ResultsSearch } from './ResultsSearch';
import { ResultsTabs } from './ResultsTabs';
import { SkeletonCard } from './SkeletonCard';
import { SummaryCard } from './SummaryCard';
import {
  DEFAULT_FILTERS,
  migrateProfile,
  type Filters,
  type LegacyProfileShape,
  type SortKey,
  type Tab,
} from './types';
import {
  readInitialFiltersFromUrl,
  readInitialSemanticRerank,
  useResultsUrlSync,
} from './use-results-url';
import { useHighlightSet } from './use-highlight-set';
import { useSavedSearchAck } from './use-saved-search-ack';
import { useResultsData } from './use-results-data';
import { useResultsFilters } from './use-results-filters';
import { useResultsKeyboardNav } from './use-results-keyboard-nav';

const ColdEmailModal = dynamic(() => import('@/components/ColdEmailModal'), {
  ssr: false,
});

const PAGE_SIZE = 20;

export default function ResultsPage() {
  return (
    <Suspense fallback={<ResultsLoading />}>
      <ResultsContent />
    </Suspense>
  );
}

function ResultsLoading() {
  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <div className="mb-10">
        <div className="skeleton h-10 w-64 mb-3" />
        <div className="skeleton h-5 w-48" />
      </div>
      <div className="space-y-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    </div>
  );
}

function ResultsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useT();

  const rawStoredProfile = useLocalStorageJSON<LegacyProfileShape>('ofe_profile');
  const profile = useMemo(() => migrateProfile(rawStoredProfile), [rawStoredProfile]);
  const hasStoredProfile = useHasLocalStorageKey('ofe_profile');

  const initialUrl = useMemo(() => readInitialFiltersFromUrl(searchParams), [searchParams]);
  const [activeTab, setActiveTab] = useState<Tab>(initialUrl.activeTab);
  const [searchQuery, setSearchQuery] = useState(initialUrl.searchQuery);
  const debouncedQuery = useDebounce(searchQuery, 250);
  const [filters, setFilters] = useState<Filters>(initialUrl.filters);
  const [sortBy, setSortBy] = useState<SortKey>(initialUrl.sortBy);
  const [semanticRerank, setSemanticRerank] = useState<boolean>(() =>
    readInitialSemanticRerank(searchParams),
  );
  useResultsUrlSync({ activeTab, debouncedQuery, filters, sortBy, semanticRerank });

  const highlightSet = useHighlightSet(searchParams);
  useSavedSearchAck(searchParams, highlightSet);

  const { data, setData, loading, error, showSlowHint } = useResultsData(
    profile,
    semanticRerank,
    t,
  );

  const [showDismissed, setShowDismissed] = useState(false);
  const [page, setPage] = useState(1);

  const presets = useLocalStorageJSON<unknown, FilterPreset[]>(
    'ofe_filter_presets',
    parsePresetsArray,
  );
  const [activePresetId, setActivePresetId] = useState<string | null>(null);

  const [emailModal, setEmailModal] = useState<{
    open: boolean;
    opportunityId: string;
    opportunityTitle: string;
  }>({ open: false, opportunityId: '', opportunityTitle: '' });

  const [favs, setFavs] = useState<Set<string>>(new Set());
  const [interactions, setInteractions] = useState<Map<string, InteractionType>>(new Map());
  useEffect(() => {
    let cancelled = false;
    getFavorites()
      .then((d) => { if (!cancelled) setFavs(d); })
      .catch(() => {});
    getInteractions()
      .then((d) => { if (!cancelled) setInteractions(d); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const handleToggleFav = useCallback(async (oppId: string) => {
    setFavs(prev => {
      const next = new Set(prev);
      if (next.has(oppId)) next.delete(oppId);
      else next.add(oppId);
      return next;
    });
    try {
      const wasFaved = favs.has(oppId);
      await toggleFavorite(oppId, wasFaved);
    } catch {
      setFavs(prev => {
        const next = new Set(prev);
        if (next.has(oppId)) next.delete(oppId);
        else next.add(oppId);
        return next;
      });
    }
  }, [favs]);

  const handleTrackInteraction = useCallback((oppId: string, type: InteractionType) => {
    setInteractions(prev => {
      const current = prev.get(oppId);
      const next = new Map(prev);
      if (current === type) {
        next.delete(oppId);
        removeInteraction(oppId).catch(() => {});
      } else {
        next.set(oppId, type);
        trackInteraction(oppId, type).catch(() => {});
      }
      return next;
    });
  }, []);

  useEffect(() => {
    if (hasStoredProfile === false) router.replace('/');
  }, [hasStoredProfile, router]);

  const toggleSemantic = useCallback((next: boolean) => {
    setSemanticRerank(next);
    try { localStorage.setItem('ofe_semantic_rerank', next ? '1' : '0'); } catch { /* quota */ }
    setData(null);
    setPage(1);
  }, [setData]);

  const { filtered, paginated, totalPages } = useResultsFilters({
    data,
    activeTab,
    debouncedQuery,
    filters,
    favs,
    sortBy,
    interactions,
    showDismissed,
    page,
    pageSize: PAGE_SIZE,
  });

  // eslint-disable-next-line react-hooks/set-state-in-effect -- reset pagination to page 1 when filter inputs change; key-remount would lose focus on the search box mid-typing, which is worse than the cascading render
  useEffect(() => { setPage(1); }, [activeTab, debouncedQuery, filters, sortBy]);

  const dismissedCount = useMemo(
    () => Array.from(interactions.values()).filter(v => v === 'dismissed').length,
    [interactions],
  );

  const counts = useMemo(() => {
    if (!data) return { all: 0, high_priority: 0, good_match: 0, reach: 0, starred: 0 } as Record<Tab, number>;
    const withoutLowFit = data.total - data.low_fit;
    return {
      all: withoutLowFit,
      high_priority: data.high_priority,
      good_match: data.good_match,
      reach: data.reach,
      starred: favs.size,
    } as Record<Tab, number>;
  }, [data, favs]);

  const loadingPhase = useLoadingNarrative({
    loading,
    semanticRerank,
    opportunityCount: data?.total ?? 0,
    t,
  });

  const activeFilterCount =
    (filters.paid ? 1 : 0) +
    (filters.intl ? 1 : 0) +
    (filters.source ? 1 : 0) +
    (filters.onCampus ? 1 : 0) +
    (filters.deadline ? 1 : 0) +
    (filters.minScore > 0 ? 1 : 0);

  const openEmailModal = useCallback(
    (opportunityId: string) => {
      const match = data?.results.find((m) => m.opportunity.id === opportunityId);
      setEmailModal({
        open: true,
        opportunityId,
        opportunityTitle: match?.opportunity.title ?? t('results.opportunityFallback'),
      });
    },
    [data, t],
  );

  const closeEmailModal = useCallback(() => {
    setEmailModal({ open: false, opportunityId: '', opportunityTitle: '' });
  }, []);

  const [helpOpen, setHelpOpen] = useState(false);
  const openHelp = useCallback(() => setHelpOpen(true), []);

  const { focusedIdx, setFocusedIdx } = useResultsKeyboardNav({
    paginated,
    emailModalOpen: emailModal.open,
    onCloseEmailModal: closeEmailModal,
    onToggleFavorite: handleToggleFav,
    onOpenHelp: openHelp,
  });

  // Reset keyboard-nav focus when filters change so j/k starts from the top
  // of the newly-filtered list. key-remount would lose the search box focus
  // mid-typing, so we accept the cascading render here.
  useEffect(() => { setFocusedIdx(-1); }, [activeTab, debouncedQuery, filters, sortBy, page, setFocusedIdx]);

  const handleSavePreset = useCallback(() => {
    const name = window.prompt(t('results.presets.namePrompt'), '')?.trim();
    if (!name) return;
    const preset: FilterPreset = {
      id: `p_${Date.now().toString(36)}`,
      name: name.slice(0, 50),
      filters: { ...filters },
      sortBy,
      tab: activeTab,
    };
    savePresets(upsertPreset(presets, preset));
    setActivePresetId(preset.id);
  }, [filters, sortBy, activeTab, presets, t]);

  const handleSaveSearchToAccount = useCallback(async () => {
    const name = window.prompt(t('results.saveSearchPrompt'), '')?.trim();
    if (!name) return;
    const saved = await saveSearch({
      name,
      query: debouncedQuery,
      filters: { ...filters },
      sort_by: sortBy,
      tab: activeTab,
    });
    if (!saved) {
      window.alert(t('results.saveSearchError'));
    }
  }, [filters, sortBy, activeTab, debouncedQuery, t]);

  const handleApplyPreset = useCallback((preset: FilterPreset) => {
    setFilters(preset.filters as typeof DEFAULT_FILTERS);
    setSortBy(preset.sortBy);
    setActiveTab(preset.tab as Tab);
    setActivePresetId(preset.id);
  }, []);

  const handleDeletePreset = useCallback((id: string) => {
    savePresets(removePreset(presets, id));
    if (activePresetId === id) setActivePresetId(null);
  }, [presets, activePresetId]);

  const handleExport = useCallback(() => {
    const rows = activeTab === 'starred'
      ? filtered
      : filtered.filter(m => favs.has(m.opportunity.id));
    if (rows.length === 0) return;
    downloadCSV(`opportunities-${new Date().toISOString().slice(0, 10)}.csv`, matchesToCSV(rows));
  }, [filtered, favs, activeTab]);

  const handleClearAll = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
    setSearchQuery('');
  }, []);

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <button
        type="button"
        onClick={() => router.push('/')}
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 mb-8 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        {t('results.backToProfile')}
      </button>

      <StorageStatusBanner />

      <ResultsHeader
        loading={loading}
        showSlowHint={showSlowHint}
        data={data}
        filtered={filtered}
        counts={counts}
        favs={favs}
        activeTab={activeTab}
        semanticRerank={semanticRerank}
        onSemanticChange={toggleSemantic}
        onOpenHelp={openHelp}
        onExport={handleExport}
        loadingMessage={loadingPhase.message}
        t={t}
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8 sm:mb-10">
        {!loading && data ? (
          <>
            <SummaryCard label={t('results.summary.total')} count={counts.all} />
            <SummaryCard label={t('results.summary.highPriority')} count={counts.high_priority} accent="emerald" />
            <SummaryCard label={t('results.summary.goodMatch')} count={counts.good_match} accent="blue" />
            <SummaryCard label={t('results.summary.reach')} count={counts.reach} accent="amber" />
          </>
        ) : (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="bg-white rounded-2xl shadow-[0_1px_6px_rgba(0,0,0,0.04)] px-5 py-5">
              <div className="skeleton h-9 w-14 mb-2" />
              <div className="skeleton h-3 w-20" />
            </div>
          ))
        )}
      </div>

      {(loading || !data) && (
        <div className="mb-8 sm:mb-10 h-[44px]" aria-hidden="true" />
      )}

      {!loading && data && (
        <ResultsTabs activeTab={activeTab} onChange={setActiveTab} counts={counts} t={t} />
      )}

      {(loading || !data) && (
        <div className="space-y-3 mb-8">
          <div className="skeleton h-11 rounded-xl" />
          <div className="flex flex-wrap gap-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="skeleton h-7 w-28 rounded-lg" />
            ))}
          </div>
        </div>
      )}

      {!loading && data && (
        <div className="space-y-3 mb-8">
          <ResultsSearch
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            debouncedQuery={debouncedQuery}
            presets={presets}
            activePresetId={activePresetId}
            activeFilterCount={activeFilterCount}
            filteredCount={filtered.length}
            onApplyPreset={handleApplyPreset}
            onDeletePreset={handleDeletePreset}
            onSavePreset={handleSavePreset}
            onSaveSearch={handleSaveSearchToAccount}
            t={t}
          />
          <FilterRail
            filters={filters}
            onFiltersChange={setFilters}
            sortBy={sortBy}
            onSortByChange={setSortBy}
            showDismissed={showDismissed}
            onShowDismissedChange={setShowDismissed}
            dismissedCount={dismissedCount}
            activeFilterCount={activeFilterCount}
            t={t}
          />
        </div>
      )}

      {loading && (
        <div className="space-y-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {error && (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
          <AlertCircle className="w-10 h-10 text-red-500" />
          <p className="text-gray-700 font-medium">{error}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="text-sm text-blue-600 underline hover:text-blue-700"
          >
            {t('common.retry')}
          </button>
        </div>
      )}

      {!loading && !error && data && (
        <div className="space-y-6">
          {filtered.length === 0 ? (
            <EmptyState
              hasFilters={activeFilterCount > 0 || !!debouncedQuery.trim()}
              tab={activeTab}
              onClearFilters={handleClearAll}
              t={t}
            />
          ) : (
            <MatchList
              matches={paginated}
              profile={profile}
              highlightSet={highlightSet}
              focusedIdx={focusedIdx}
              favs={favs}
              interactions={interactions}
              onDraftEmail={openEmailModal}
              onToggleFavorite={handleToggleFav}
              onTrackInteraction={handleTrackInteraction}
              page={page}
              totalPages={totalPages}
              onPageChange={setPage}
              t={t}
            />
          )}
        </div>
      )}

      {loading && (
        <div
          className="fixed top-12 left-0 right-0 z-40"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={loadingPhase.percent}
          aria-label={loadingPhase.message || t('common.loading')}
        >
          <div className="h-[2px] bg-black/[0.03]">
            <div
              className="h-full bg-blue-500 rounded-r-full transition-[width] duration-700 ease-out"
              style={{ width: `${loadingPhase.percent}%` }}
            />
          </div>
        </div>
      )}

      {profile && (
        <ColdEmailModal
          isOpen={emailModal.open}
          onClose={closeEmailModal}
          profile={profile}
          opportunityId={emailModal.opportunityId}
          opportunityTitle={emailModal.opportunityTitle}
        />
      )}

      {helpOpen && <KeyboardHelpDialog onClose={() => setHelpOpen(false)} t={t} />}
    </div>
  );
}
