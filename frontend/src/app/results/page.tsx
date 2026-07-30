'use client';

import { useCallback, useEffect, useMemo, useRef, useState, Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter, useSearchParams } from 'next/navigation';
import { AlertCircle, ArrowLeft } from 'lucide-react';

import StorageStatusBanner from '@/components/StorageStatusBanner';
import { KeyboardHelpDialog } from '@/components/KeyboardHelpDialog';
import { useDebounce } from '@/lib/use-debounce';
import { useLoadingNarrative } from '@/lib/use-loading-narrative';
import {
  useHasLocalStorageKey,
  useLocalStorageJSON,
  writeLocalStorageJSON,
} from '@/lib/use-local-storage-json';
import { downloadCSV } from '@/lib/csv-export';
import { matchesToCSV } from '@/lib/match-utils';
import {
  parsePresetsArray,
  removePreset,
  savePresets,
  upsertPreset,
  type FilterPreset,
} from '@/lib/filter-presets';
import {
  listSavedSearchDigests,
  saveSearch,
  setSavedSearchDigest,
  type SavedSearchDigest,
} from '@/lib/saved-searches';
import {
  getMatchFeedback,
  setMatchFeedback,
  type MatchFeedbackContext,
  type MatchVerdict,
} from '@/lib/match-feedback';
import { mergeHydratedFeedback } from './feedback-hydration';
import { hasScopeData, homeSchoolOf } from '@/lib/discovery-scope';
import { bySlug } from '@/lib/schools';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import {
  getAuthState,
  getFavorites,
  getInteractions,
  removeInteraction,
  saveProfile,
  toggleFavorite,
  trackInteraction,
  type InteractionType,
} from '@/lib/supabase';
import { useAuthModal } from '@/lib/auth-modal-context';
import { useT } from '@/i18n/client';

import { EmptyState } from './EmptyState';
import { FilterRail } from './FilterRail';
import { MatchList } from './MatchList';
import { ResultsHeader } from './ResultsHeader';
import { ResultsSearch } from './ResultsSearch';
import { ResultsTabs } from './ResultsTabs';
import { ProfileCompletenessHint } from './ProfileCompletenessHint';
import { SaveSearchDialog } from './SaveSearchDialog';
import { SkeletonCard } from './SkeletonCard';
import {
  DEFAULT_FILTERS,
  migrateProfile,
  sourceLabel,
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
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6 items-start">
        {Array.from({ length: 6 }).map((_, i) => (
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
  // R66: openAuthModal is renamed locally to avoid shadowing the email
  // modal's own "open" state names elsewhere in this large component.
  const { openModal: openAuthModal } = useAuthModal();

  const rawStoredProfile = useLocalStorageJSON<LegacyProfileShape>(STORAGE_KEYS.PROFILE);
  const profile = useMemo(() => migrateProfile(rawStoredProfile), [rawStoredProfile]);
  const hasStoredProfile = useHasLocalStorageKey(STORAGE_KEYS.PROFILE);

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

  // Source-filter chips derived from the sources actually present (by count),
  // so every real source — incl. simplify_internships — is filterable.
  const sourceOptions = useMemo<Array<[string, string]>>(() => {
    const counts = new Map<string, number>();
    for (const m of data?.results ?? []) {
      const s = m.opportunity.source;
      if (s) counts.set(s, (counts.get(s) ?? 0) + 1);
    }
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([s]) => s);
    return [
      ['', t('results.filters.sourceAll')],
      ...sorted.map((s) => [s, sourceLabel(s, t)] as [string, string]),
    ];
  }, [data, t]);

  const homeSchool = homeSchoolOf(profile);
  const homeSchoolEntry = bySlug(homeSchool);
  // Discovery-scope facet (PR #187), data-derived like sourceOptions:
  // empty (hidden) when no result carries school/audience metadata. The
  // "My school" option is suppressed for schools with no campus coverage
  // yet (campusOpportunities: 'pending') — offering it would only ever
  // return zero results with the facet still shown.
  const hasCampusCoverage = homeSchoolEntry?.coverage.campusOpportunities !== 'pending';
  const scopeOptions = useMemo<Array<[string, string]>>(() => {
    if (!(data?.results ?? []).some((m) => hasScopeData(m.opportunity))) return [];
    return [
      ['', t('results.filters.scopeAll')],
      ...(hasCampusCoverage
        ? [['campus', t('results.filters.scopeMySchool')] as [string, string]]
        : []),
      ['open', t('results.filters.scopeOpen')],
    ];
  }, [data, t, hasCampusCoverage]);
  const scopeIndicator = t(
    homeSchoolEntry?.coverage.campusOpportunities === 'pending'
      ? 'results.scopeIndicatorPending'
      : 'results.scopeIndicator',
    { school: homeSchoolEntry?.shortName ?? homeSchool },
  );

  const [showDismissed, setShowDismissed] = useState(false);
  const [page, setPage] = useState(1);

  const presets = useLocalStorageJSON<unknown, FilterPreset[]>(
    STORAGE_KEYS.FILTER_PRESETS,
    parsePresetsArray,
  );
  const [activePresetId, setActivePresetId] = useState<string | null>(null);

  const [emailModal, setEmailModal] = useState<{
    open: boolean;
    opportunityId: string;
    opportunityTitle: string;
    opportunitySchool: string | null;
  }>({ open: false, opportunityId: '', opportunityTitle: '', opportunitySchool: null });

  const [favs, setFavs] = useState<Set<string>>(new Set());
  // Mirror favs into a ref so handleToggleFav can read the current set without
  // depending on `favs` — a [favs] dep made the callback unstable and defeated
  // MatchCard's memoization, re-rendering all visible cards on every toggle.
  const favsRef = useRef(favs);
  useEffect(() => { favsRef.current = favs; }, [favs]);
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
    const wasFaved = favsRef.current.has(oppId);
    const flip = (s: Set<string>) => {
      const next = new Set(s);
      if (next.has(oppId)) next.delete(oppId);
      else next.add(oppId);
      return next;
    };
    setFavs(flip);
    try {
      await toggleFavorite(oppId, wasFaved);
    } catch {
      setFavs(flip); // revert the optimistic toggle on failure
    }
  }, []);

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

  // Match-accuracy thumbs (Phase 9.6). Optimistic like favorites; the card
  // passes bucket + final_score along so the persisted row stays
  // interpretable after the scorer's weights change.
  const [feedback, setFeedback] = useState<Map<string, MatchVerdict>>(new Map());
  // Per-id mutation counters: a hydration response that raced a user's click
  // (fetch started before the click, resolved after) must not clobber the
  // newer verdict — mergeHydratedFeedback only applies ids whose version is
  // unchanged since the request was issued.
  const feedbackMutationVersions = useRef<Map<string, number>>(new Map());
  const handleFeedback = useCallback((
    oppId: string,
    verdict: MatchVerdict | null,
    context: MatchFeedbackContext,
  ) => {
    feedbackMutationVersions.current.set(
      oppId, (feedbackMutationVersions.current.get(oppId) ?? 0) + 1,
    );
    setFeedback(prev => {
      const next = new Map(prev);
      if (verdict) next.set(oppId, verdict);
      else next.delete(oppId);
      return next;
    });
    setMatchFeedback(oppId, verdict, context).catch(() => {});
  }, []);

  useEffect(() => {
    if (hasStoredProfile === false) router.replace('/');
  }, [hasStoredProfile, router]);

  const toggleSemantic = useCallback((next: boolean) => {
    setSemanticRerank(next);
    try { localStorage.setItem(STORAGE_KEYS.SEMANTIC_RERANK, next ? '1' : '0'); } catch { /* quota */ }
    setData(null);
    setPage(1);
  }, [setData]);

  // Cross-school opt-in is a PROFILE field (the backend's scope filter reads
  // it), not a client-side facet: persist it like other profile edits
  // (localStorage + Supabase), then drop the data so useResultsData re-ranks
  // under the new hashProfile key. writeLocalStorageJSON dispatches the
  // synthetic storage event that updates this page's own profile snapshot.
  const includeCrossSchool = profile?.include_cross_school ?? false;
  const toggleCrossSchool = useCallback((next: boolean) => {
    if (!rawStoredProfile) return;
    const updated = { ...rawStoredProfile, include_cross_school: next };
    writeLocalStorageJSON(STORAGE_KEYS.PROFILE, updated);
    saveProfile(updated as unknown as Record<string, unknown>).catch(() => {});
    setData(null);
    setPage(1);
  }, [rawStoredProfile, setData]);

  const { filtered, paginated, totalPages, effectivePage, counts } = useResultsFilters({
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
    homeSchool,
  });

  // eslint-disable-next-line react-hooks/set-state-in-effect -- reset pagination to page 1 when filter inputs change; key-remount would lose focus on the search box mid-typing, which is worse than the cascading render
  useEffect(() => { setPage(1); }, [activeTab, debouncedQuery, filters, sortBy, showDismissed]);

  // Hydrate saved verdicts for the cards currently on screen. Fetching per
  // visible page (instead of all 600+ result ids at once) keeps the
  // PostgREST `in=(...)` URL bounded; feedbackFetchedRef dedupes so paging
  // back and forth doesn't refetch ids we've already asked about.
  const feedbackFetchedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const ids = paginated
      .map(m => m.opportunity.id)
      .filter(id => !feedbackFetchedRef.current.has(id));
    if (ids.length === 0) return;
    const requestedVersions = new Map(
      ids.map(id => [id, feedbackMutationVersions.current.get(id) ?? 0]),
    );
    ids.forEach(id => feedbackFetchedRef.current.add(id));
    let cancelled = false;
    getMatchFeedback(ids)
      .then((d) => {
        if (cancelled || d.size === 0) return;
        setFeedback(prev => mergeHydratedFeedback(
          prev, d, requestedVersions, feedbackMutationVersions.current,
        ));
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [paginated]);

  const dismissedCount = useMemo(
    () => Array.from(interactions.values()).filter(v => v === 'dismissed').length,
    [interactions],
  );

  // `counts` now comes from useResultsFilters so each tab badge reflects the
  // active field filters (source/scope/search/…) and matches the list under
  // that tab — see the hook for the rationale. (Previously these were the
  // global server-side bucket counts, which disagreed with a filtered list,
  // e.g. "high_priority 25" above an empty list when a source filter excluded
  // all 25.)

  const loadingPhase = useLoadingNarrative({
    loading,
    semanticRerank,
    opportunityCount: data?.total ?? 0,
    t,
  });

  const activeFilterCount =
    (filters.paid ? 1 : 0) +
    // intl='no' is the labeled "Show all" option — it filters nothing, so it
    // must not light the "Filters · N" badge over an unchanged list.
    (filters.intl === 'yes' ? 1 : 0) +
    (filters.source ? 1 : 0) +
    (filters.onCampus ? 1 : 0) +
    (filters.deadline ? 1 : 0) +
    (filters.minScore > 0 ? 1 : 0) +
    (filters.scope ? 1 : 0);

  const openEmailModal = useCallback(
    (opportunityId: string) => {
      const match = data?.results.find((m) => m.opportunity.id === opportunityId);
      setEmailModal({
        open: true,
        opportunityId,
        opportunityTitle: match?.opportunity.title ?? t('results.opportunityFallback'),
        opportunitySchool: match?.opportunity.school ?? null,
      });
    },
    [data, t],
  );

  const closeEmailModal = useCallback(() => {
    setEmailModal({ open: false, opportunityId: '', opportunityTitle: '', opportunitySchool: null });
  }, []);

  const [helpOpen, setHelpOpen] = useState(false);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [digestAvailable, setDigestAvailable] = useState(false);
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
    // R66: the "Save to account" button used to silently save under
    // the anonymous UUID, which is what made the CTA "lie" — it
    // claimed to save to an account that didn't exist. Now we gate
    // the actual save behind real account state: anon users get the
    // sign-in modal, permanent users proceed straight to the save.
    const authState = await getAuthState();
    if (!authState.user || authState.isAnonymous) {
      openAuthModal({ reason: 'save-search' });
      return;
    }
    // Probe whether migration 013's digest columns exist — null hides the
    // digest opt-in inside the dialog (graceful pre-migration degradation).
    const digests = await listSavedSearchDigests();
    setDigestAvailable(digests !== null);
    setSaveDialogOpen(true);
  }, [openAuthModal]);

  const closeSaveDialog = useCallback(() => setSaveDialogOpen(false), []);

  const handleSaveSearchSubmit = useCallback(async (
    input: { name: string; digest: SavedSearchDigest | null },
  ) => {
    setSaveDialogOpen(false);
    const saved = await saveSearch({
      name: input.name,
      query: debouncedQuery,
      filters: { ...filters },
      sort_by: sortBy,
      tab: activeTab,
    });
    if (!saved) {
      window.alert(t('results.saveSearchError'));
      return;
    }
    if (input.digest?.optIn) {
      // Digest persistence is additive — a failure here must not unwind
      // the already-successful save, so it only logs via the helper.
      await setSavedSearchDigest(saved.id, input.digest);
    }
  }, [filters, sortBy, activeTab, debouncedQuery, t]);

  const handleApplyPreset = useCallback((preset: FilterPreset) => {
    // Merge over defaults: presets saved before newer filter keys (e.g.
    // scope) existed must not leave those keys undefined in state.
    setFilters({ ...DEFAULT_FILTERS, ...preset.filters });
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

  // R69-A: cold-visit pre-check. The router.replace('/') effect above
  // is reactive — between the first render and the effect firing, the
  // skeleton row + loading narrative ("Reading your profile...") paints
  // for ~1 frame, which feels like a glitch to a user who never had a
  // profile. Returning null here suppresses that flash; the effect still
  // performs the actual navigation. hasStoredProfile is undefined while
  // localStorage probes; we only skip rendering once it's been confirmed
  // absent (=== false), so users with profiles never hit this branch.
  if (hasStoredProfile === false) return null;

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

      {/*
        R69-A: the 4-cell summary grid (Total / High Priority / Good Match /
        Reach) was removed here — those numbers already render twice elsewhere
        on this page (in the header subtitle "{count} opportunities ranked
        for you" and in the tab row "All 608 / High Priority 39 / Good Match
        298 / Reach 271"). Triple-printing the same figure consumed ~250px of
        mobile real estate above the fold for zero new information.
      */}

      {!loading && data && (
        <ResultsTabs activeTab={activeTab} onChange={setActiveTab} counts={counts} t={t} />
      )}

      {!loading && data && profile && (
        <ProfileCompletenessHint profile={profile} onEdit={() => router.push('/')} t={t} />
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
            sourceOptions={sourceOptions}
            scopeOptions={scopeOptions}
            includeCrossSchool={includeCrossSchool}
            onIncludeCrossSchoolChange={toggleCrossSchool}
            t={t}
          />
          {scopeOptions.length > 0 && (
            <p className="text-[12px] text-gray-500">{scopeIndicator}</p>
          )}
          <p className="text-[12px] text-gray-500">{t('results.filters.crossSchoolHint')}</p>
        </div>
      )}

      {loading && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6 items-start">
          {Array.from({ length: 6 }).map((_, i) => (
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
            className="text-sm text-indigo-600 underline hover:text-indigo-700"
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
              feedback={feedback}
              onDraftEmail={openEmailModal}
              onToggleFavorite={handleToggleFav}
              onTrackInteraction={handleTrackInteraction}
              onFeedback={handleFeedback}
              positionOffset={(effectivePage - 1) * PAGE_SIZE}
              page={effectivePage}
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
              className="h-full bg-indigo-500 rounded-r-full transition-[width] duration-700 ease-out"
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
          opportunitySchool={emailModal.opportunitySchool}
        />
      )}

      {helpOpen && <KeyboardHelpDialog onClose={() => setHelpOpen(false)} t={t} />}

      {saveDialogOpen && (
        <SaveSearchDialog
          digestAvailable={digestAvailable}
          onCancel={closeSaveDialog}
          onSave={handleSaveSearchSubmit}
          t={t}
        />
      )}

    </div>
  );
}
