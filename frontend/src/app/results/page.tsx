'use client';

import { useCallback, useEffect, useMemo, useReducer, useRef, useState, Suspense } from 'react';
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
import { captureOwnerToken } from '@/lib/identity-owner';

import type { ProfileData } from '@/lib/types';
import { downloadCSV } from '@/lib/csv-export';
import { matchesToCSV } from '@/lib/match-utils';
import { targetPosture } from '@/lib/target-truth';
import {
  ApiError,
  getMatchView,
  type MatchViewRequestState,
} from '@/lib/api';
import { isTrustedMatchViewPage } from '@/lib/match-cache';
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
import { homeSchoolOf } from '@/lib/discovery-scope';
import { bySlug } from '@/lib/schools';
import type { MatchResult } from '@/lib/types';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import {
  getAuthState,
  type InteractionType,
} from '@/lib/supabase';
import { useAuthModal } from '@/lib/auth-modal-context';
import { useT } from '@/i18n/client';

import { EmptyState } from './EmptyState';
import { favoriteExportView, favoriteRowsForTab } from './export-view';
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
  readSemanticRerankUrlPin,
  resolveSemanticRerank,
  useResultsUrlSync,
} from './use-results-url';
import { useHighlightSet } from './use-highlight-set';
import { useSavedSearchAck } from './use-saved-search-ack';
import { useResultsData } from './use-results-data';
import { useAcceptedProfileView, useCrossSchoolToggle } from './use-results-profile-view';
import { useResultsInteractions } from './use-results-interactions';
import { useResultsKeyboardNav } from './use-results-keyboard-nav';

const ColdEmailModal = dynamic(() => import('@/components/ColdEmailModal'), {
  ssr: false,
});

const PAGE_SIZE = 50;
const EMPTY_VIEW_COUNTS: Record<Tab, number> = {
  all: 0,
  high_priority: 0,
  good_match: 0,
  reach: 0,
  starred: 0,
};

function localIsoDate(now = new Date()): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

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
  // The document this page renders AND the snapshot a write from it carries,
  // as ONE value committed in one step (see use-results-profile-view).
  const {
    accepted: { profile, view },
    accept: acceptProfileView,
    clear: clearProfileView,
  } = useAcceptedProfileView();
  const hasStoredProfile = useHasLocalStorageKey(STORAGE_KEYS.PROFILE);

  const initialUrl = useMemo(() => readInitialFiltersFromUrl(searchParams), [searchParams]);
  const [activeTab, setActiveTab] = useState<Tab>(initialUrl.activeTab);
  const [searchQuery, setSearchQuery] = useState(initialUrl.searchQuery);
  const debouncedQuery = useDebounce(searchQuery, 250);
  const [filters, setFilters] = useState<Filters>(initialUrl.filters);
  const [sortBy, setSortBy] = useState<SortKey>(initialUrl.sortBy);
  // Derived, not pinned in state. Local ownership is established asynchronously,
  // so the stored preference is unreadable on the first render — a useState
  // initializer would freeze that "unreadable" into an off for the whole visit,
  // and the on-by-default would never reach anyone. These two hooks resettle
  // when ownership lands (and when the toggle below writes), so the value
  // follows.
  const [semanticUrlPin, setSemanticUrlPin] = useState<boolean | null>(() =>
    readSemanticRerankUrlPin(searchParams),
  );
  const semanticPrefExists = useHasLocalStorageKey(STORAGE_KEYS.SEMANTIC_RERANK);
  const semanticPrefValue = useLocalStorageJSON<string>(STORAGE_KEYS.SEMANTIC_RERANK);
  const semanticRerank = resolveSemanticRerank(
    semanticUrlPin,
    semanticPrefExists,
    semanticPrefValue,
  );
  // A browser that refuses storage answers `undefined` forever (Safari private
  // mode, a blocked third-party context), so waiting on it unconditionally
  // would spin a skeleton for the whole visit. Bound the wait and proceed with
  // whatever is known — resolveSemanticRerank reads an unknown preference as
  // off, so the student gets the deterministic list rather than a spinner.
  const [semanticSettleTimedOut, setSemanticSettleTimedOut] = useState(false);
  useEffect(() => {
    if (semanticPrefExists !== undefined) return;
    const timer = setTimeout(() => setSemanticSettleTimedOut(true), 1500);
    return () => clearTimeout(timer);
  }, [semanticPrefExists]);
  const semanticSettled = semanticUrlPin !== null
    || semanticPrefExists !== undefined
    || semanticSettleTimedOut;
  useResultsUrlSync({
    activeTab, debouncedQuery, filters, sortBy, semanticRerank, semanticSettled,
  });

  const highlightSet = useHighlightSet(searchParams);
  useSavedSearchAck(searchParams, highlightSet);

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
    openedAgainstResults: MatchResult[] | null;
  }>({
    open: false,
    opportunityId: '',
    opportunityTitle: '',
    opportunitySchool: null,
    openedAgainstResults: null,
  });

  // Close (never leave open) the recipient modal on a REAL identity switch —
  // it can trigger a write, and a U1-opened modal must not be left able to
  // present or confirm-send against U2's identity. Also resets pagination:
  // the private filter set (favorite_ids/dismissed_ids, below) is about to
  // change out from under whatever page the user was on.
  // The cross-school toggle is declared below (it needs the data hook's
  // setter), but the identity transition has to reach it. Held in a ref
  // rather than reordered: the transition can only fire after mount, so the
  // effect that fills this has always run by then.
  const clearCrossSchoolRef = useRef<() => void>(() => {});
  const handleIdentityChange = useCallback(() => {
    setEmailModal((m) => (m.open ? { ...m, open: false } : m));
    // SYNCHRONOUSLY, in the transition itself — not in a passive effect keyed
    // on identityGeneration, which runs after paint and would leave U1's
    // document on screen and its view actionable for a full render.
    clearProfileView();
    clearCrossSchoolRef.current();
    setPage(1);
  }, [clearProfileView]);
  const {
    favs,
    interactions,
    noteContactConfirmed,
    ownerReady,
    identityGeneration,
    ownerScopeKey,
    favoritesLoadError,
    retryFavoritesLoad,
    interactionsLoading,
    interactionsError,
    favSaveErrors,
    trackSaveErrors,
    pendingFavIds,
    pendingTrackIds,
    handleToggleFav: handleToggleFavRaw,
    handleTrackInteraction: handleTrackInteractionRaw,
    retryFavSave,
    retryTrackSave,
    retryInteractionsLoad,
  } = useResultsInteractions(handleIdentityChange);

  // Page-level wrappers: preserve the pre-extraction "jump back to page 1"
  // semantics on every favorite/status mutation attempt — the filtered list
  // (favorite_ids/dismissed_ids feed matchView below) can shrink out from
  // under a later page. Reset happens synchronously at click time, same as
  // before, not gated on whether the hook's own guards let the write proceed.
  const handleToggleFav = useCallback((oppId: string) => {
    setPage(1);
    return handleToggleFavRaw(oppId);
  }, [handleToggleFavRaw]);
  const handleTrackInteraction = useCallback((oppId: string, type: InteractionType) => {
    setPage(1);
    return handleTrackInteractionRaw(oppId, type);
  }, [handleTrackInteractionRaw]);

  useEffect(() => {
    // Re-accepted only when this page genuinely gets a new snapshot: its
    // stored profile changed, or the identity did.
    acceptProfileView();
  }, [rawStoredProfile, identityGeneration, acceptProfileView]);

  const homeSchool = homeSchoolOf(profile);
  const viewToday = useMemo(() => localIsoDate(), []);
  const favoriteIds = useMemo(() => [...favs].sort(), [favs]);
  const dismissedIds = useMemo(
    () => [...interactions.entries()]
      .filter(([, value]) => value === 'dismissed')
      .map(([id]) => id)
      .sort(),
    [interactions],
  );
  const matchView = useMemo<MatchViewRequestState>(() => ({
    tab: activeTab,
    search_query: debouncedQuery,
    paid: filters.paid,
    intl: filters.intl,
    source: filters.source,
    on_campus: filters.onCampus,
    deadline: filters.deadline,
    min_score: filters.minScore,
    scope: filters.scope,
    sort_by: sortBy,
    show_dismissed: showDismissed,
    favorite_ids: favoriteIds,
    dismissed_ids: dismissedIds,
    today: viewToday,
  }), [
    activeTab,
    debouncedQuery,
    filters,
    sortBy,
    showDismissed,
    favoriteIds,
    dismissedIds,
    viewToday,
  ]);
  const {
    data,
    setData,
    loading,
    error,
    showSlowHint,
    paginationReady,
    refining,
    refined,
    refineFailed,
  } = useResultsData(
    profile,
    semanticRerank,
    matchView,
    page,
    t,
    semanticSettled,
    // A dead cursor is dropped by the hook; returning to page 1 is the page's
    // own job, since it owns `page`.
    useCallback(() => setPage(1), []),
  );

  // Facets are derived from the complete canonical snapshot by the backend,
  // never guessed from the current 50-card page.
  const sourceOptions = useMemo<Array<[string, string]>>(() => [
    ['', t('results.filters.sourceAll')],
    ...(data?.source_facets ?? []).map(
      ({ source }) => [source, sourceLabel(source, t)] as [string, string],
    ),
  ], [data?.source_facets, t]);

  // Same rule as sourceOptions, applied to the one facet that was ignoring it.
  // The undated chip selects on `is_rolling`; every other value reads
  // `deadline`, which 786 of 789 records had already let expire — so on
  // 2026-08-14 the three day-windows returned zero rows each and "passed"
  // returned 786. Render each chip only when the server counted something it
  // would return.
  //
  // Its LABEL says "No deadline listed", not "Rolling — apply anytime", and
  // that is not cosmetic. `is_rolling` is a blanket collector default written
  // whenever a scrape found no date (campus_graph.py, simplify_internships.py
  // and ucb_campus.py all set the literal True): 6,690 non-faculty records
  // carry it and 58 have the scraped `deadline_note` evidence that
  // noDeadlineKind requires before any surface may say "rolling". Two testers
  // walking production picked the chip and were shown programs whose own
  // pages publish a deadline — Northwestern SynBREU, whose cohort was already
  // formed, and UIUC PRIMO. What the chip actually selects is records we
  // found no deadline for, and now that is what it says.
  const deadlineOptions = useMemo<Array<[string, string]>>(() => {
    const facets = data?.deadline_facets ?? {};
    const label = (value: string) =>
      t(`results.filters.deadline${value === 'passed' ? 'Passed' : value}`);
    const options: Array<[string, string]> = [
      ['', t('results.filters.deadlineAll')],
      ['rolling', t('results.filters.deadlineRolling')],
      ...(['7', '14', '30', 'passed'] as const)
        .filter((value) => (facets[value] ?? 0) > 0)
        .map((value) => [value, label(value)] as [string, string]),
    ];
    // A value can outlive its rows — shared URLs and saved presets both carry
    // one. Dropping it from the list would leave the select showing a filter
    // the person cannot see or clear, and an empty page with no explanation.
    if (filters.deadline && !options.some(([value]) => value === filters.deadline)) {
      options.push([filters.deadline, label(filters.deadline)]);
    }
    return options;
  }, [data?.deadline_facets, filters.deadline, t]);

  const homeSchoolEntry = bySlug(homeSchool);
  const hasCampusCoverage = homeSchoolEntry?.coverage.campusOpportunities !== 'pending';
  const scopeOptions = useMemo<Array<[string, string]>>(() => {
    if (!data?.scope_available) return [];
    return [
      ['', t('results.filters.scopeAll')],
      ...(hasCampusCoverage
        ? [['campus', t('results.filters.scopeMySchool')] as [string, string]]
        : []),
      ['open', t('results.filters.scopeOpen')],
    ];
  }, [data?.scope_available, t, hasCampusCoverage]);
  const scopeIndicator = t(
    homeSchoolEntry?.coverage.campusOpportunities === 'pending'
      ? 'results.scopeIndicatorPending'
      : 'results.scopeIndicator',
    { school: homeSchoolEntry?.shortName ?? homeSchool },
  );

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
    if (!RELEASE_SCOPE.matchAiRefine) return;
    // Release the arrival URL's pin: a student who followed a ?ai=0 share link
    // and then switched the toggle on means it for this visit.
    setSemanticUrlPin(null);
    writeLocalStorageJSON(STORAGE_KEYS.SEMANTIC_RERANK, next ? '1' : '0', captureOwnerToken());
    setData(null);
    setPage(1);
  }, [setData]);

  // Cross-school opt-in is a PROFILE field (the backend's scope filter reads
  // it), not a client-side facet: persist it like other profile edits
  // (localStorage + Supabase), then drop the data so useResultsData re-ranks
  // under the new hashProfile key. writeLocalStorageJSON dispatches the
  // synthetic storage event that updates this page's own profile snapshot.
  //
  // Displayed FROM the same tuple the click writes against, so the value on
  // screen and the value in the payload cannot disagree.
  const includeCrossSchool = profile?.include_cross_school ?? false;
  const onCrossSchoolApplied = useCallback(() => {
    setData(null);
    setPage(1);
  }, [setData]);
  const {
    busy: crossSchoolBusy,
    failed: crossSchoolFailed,
    toggle: toggleCrossSchool,
    retry: retryCrossSchool,
    clear: clearCrossSchoolFailure,
  } = useCrossSchoolToggle(view, onCrossSchoolApplied);
  useEffect(() => {
    clearCrossSchoolRef.current = clearCrossSchoolFailure;
  }, [clearCrossSchoolFailure]);

  const paginated = useMemo(() => data?.results ?? [], [data?.results]);
  const filteredTotal = data?.filtered_total ?? 0;
  const totalPages = Math.ceil(filteredTotal / PAGE_SIZE);
  const effectivePage = Math.min(Math.max(1, page), Math.max(1, totalPages));
  const counts: Record<Tab, number> = data?.view_counts
    ? { ...EMPTY_VIEW_COUNTS, ...data.view_counts }
    : EMPTY_VIEW_COUNTS;

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

  // Tab badges are complete-snapshot counts returned by /matches/view. They
  // remain exact even though this render holds only one bounded card page.

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

  const handleTabChange = useCallback((next: Tab) => {
    setPage(1);
    setActiveTab(next);
  }, []);
  const handleSearchQueryChange = useCallback((next: string) => {
    setPage(1);
    setSearchQuery(next);
  }, []);
  const handleFiltersChange = useCallback((next: Filters) => {
    setPage(1);
    setFilters(next);
  }, []);
  const handleSortChange = useCallback((next: SortKey) => {
    setPage(1);
    setSortBy(next);
  }, []);
  const handleShowDismissedChange = useCallback((next: boolean) => {
    setPage(1);
    setShowDismissed(next);
  }, []);

  const openEmailModal = useCallback(
    (opportunityId: string) => {
      const results = data?.results;
      if (!results) return;
      const match = results.find((m) => m.opportunity.id === opportunityId);
      // Re-checked here, not just on the card that offered the button. This
      // modal copies an id and then lives on its own — it is the one target
      // control on this page that is NOT inside the result's keyed subtree,
      // so nothing unmounts it when the row goes away.
      if (!match || targetPosture(match.opportunity) !== 'actionable') return;
      setEmailModal({
        open: true,
        opportunityId,
        opportunityTitle: match.opportunity.title ?? t('results.opportunityFallback'),
        opportunitySchool: match.opportunity.school ?? null,
        openedAgainstResults: results,
      });
    },
    [data, t],
  );

  const closeEmailModal = useCallback(() => {
    setEmailModal({
      open: false,
      opportunityId: '',
      opportunityTitle: '',
      opportunitySchool: null,
      openedAgainstResults: null,
    });
  }, []);

  // Re-resolved on every render against the CURRENT results, so a stale target
  // cannot exist rather than being cleaned up after the fact. A passive effect
  // would run after paint, leaving one frame in which a dialog for a target
  // that just closed is on screen with a working Generate button.
  //
  // Absence of results is not evidence of life either. `data` is null on
  // every refetch — the cache no longer paints, so that window is now the
  // normal state between a filter change and its answer — and standing on the
  // check made when the dialog opened means a Generate button backed by a
  // posture nobody has re-read. During a split deploy the backend answering
  // it may not even understand the current truth contract. So a null results
  // set withdraws the dialog exactly like a set that no longer contains the
  // target: it fails closed, and a live target has to be opened again
  // deliberately rather than resurfacing on its own.
  const emailTargetLive = useMemo(() => {
    if (!emailModal.open) return false;
    const results = data?.results;
    // A modal belongs to the exact results snapshot on which the student
    // opened it. Once that snapshot is withdrawn or replaced, the old modal
    // cannot revive when a later response happens to contain the same id;
    // the student must explicitly open it against the new evidence.
    if (!results || results !== emailModal.openedAgainstResults) return false;
    const match = results.find((m) => m.opportunity.id === emailModal.opportunityId);
    return !!match && targetPosture(match.opportunity) === 'actionable';
  }, [emailModal.open, emailModal.opportunityId, emailModal.openedAgainstResults, data]);

  const [helpOpen, setHelpOpen] = useState(false);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [digestAvailable, setDigestAvailable] = useState(false);
  const openHelp = useCallback(() => setHelpOpen(true), []);

  const { focusedIdx, setFocusedIdx } = useResultsKeyboardNav({
    paginated,
    emailModalOpen: emailModal.open && emailTargetLive,
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
    if (savePresets(upsertPreset(presets, preset), captureOwnerToken())) {
      setActivePresetId(preset.id);
    } else {
      window.alert(t('results.presets.saveError'));
    }
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
    setPage(1);
  }, []);

  const handleDeletePreset = useCallback((id: string) => {
    if (savePresets(removePreset(presets, id), captureOwnerToken())) {
      if (activePresetId === id) setActivePresetId(null);
    } else {
      window.alert(t('results.presets.deleteError'));
    }
  }, [presets, activePresetId, t]);

  const fetchCompleteView = useCallback(async (
    requestedView: MatchViewRequestState,
  ) => {
    if (!profile) return [];
    const rows: MatchResult[] = [];
    const ids = new Set<string>();
    const cursors = new Set<string>();
    let cursor: string | null = null;
    let resultSetId: string | undefined;
    let viewId: string | undefined;
    for (let pageIndex = 0; pageIndex < 100; pageIndex += 1) {
      const response = await getMatchView(profile, requestedView, {
        cursor,
        pageSize: 100,
      });
      // Every page, before its rows join the accumulator. The export is the
      // furthest a row travels from this session — a spreadsheet is read
      // months later with none of the page's context — and it used to check
      // only generation/duplicates, so a closed row or one with no truth could
      // still reach a Deadline or a URL column.
      if (!isTrustedMatchViewPage(response)) {
        throw new Error('untrusted match view page');
      }
      if (
        (resultSetId && response.result_set_id !== resultSetId)
        || (viewId && response.view_id !== viewId)
      ) {
        throw new Error('match view generation changed');
      }
      resultSetId = response.result_set_id;
      viewId = response.view_id;
      for (const result of response.results) {
        if (ids.has(result.opportunity_id)) {
          throw new Error('duplicate result in match view');
        }
        ids.add(result.opportunity_id);
        rows.push(result);
      }
      if (!response.has_more) {
        if (rows.length !== response.filtered_total) {
          throw new Error('incomplete match view');
        }
        return rows;
      }
      if (!response.next_cursor || cursors.has(response.next_cursor)) {
        throw new Error('invalid match view cursor');
      }
      cursors.add(response.next_cursor);
      cursor = response.next_cursor;
    }
    throw new Error('match view exceeded page safety limit');
  }, [profile]);

  const loadEmailMatches = useCallback(async () => {
    if (!profile) return [];
    const response = await getMatchView(profile, matchView, { pageSize: 50 });
    // This is a second, independent fetch — it does not pass through
    // useResultsData's validation — so it repeats the same three checks here.
    // Without them a page that the results view would refuse can still be
    // mailed, and during the Vercel-first window those rows reach an old
    // backend through the legacy bridge fields, which renders whatever it is
    // handed. All-or-nothing: never quietly mail a shorter digest than the one
    // the user asked for.
    if (!isTrustedMatchViewPage(response)) {
      throw new ApiError(
        502,
        'MATCH_CONTRACT_MISMATCH',
        'Match results need to be refreshed. Please retry.',
        true,
      );
    }
    return response.results;
  }, [profile, matchView]);

  const handleExport = useCallback(async () => {
    try {
      // Ask the server for the filtered favorites directly. Broad profiles can
      // span 50+ pages, while the canonical bucket carried by each favorite
      // lets us reconstruct starred ∩ active-tab exactly without scanning the
      // complete bucket (and colliding with the view rate limit).
      const rows = await fetchCompleteView(favoriteExportView(matchView));
      const exportRows = favoriteRowsForTab(rows, activeTab);
      if (exportRows.length === 0) return;
      downloadCSV(
        `opportunities-${new Date().toISOString().slice(0, 10)}.csv`,
        matchesToCSV(exportRows),
      );
    } catch {
      window.alert(t('results.loadFailed'));
    }
  }, [activeTab, matchView, fetchCompleteView, t]);

  const handleClearAll = useCallback(() => {
    setPage(1);
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

      {/*
        Favorite/status SAVE failures are per-opportunity now (favSaveErrors/
        trackSaveErrors — see use-results-interactions.ts) and render at the
        corresponding card via MatchList/MatchCard, not here — a single
        page-level slot used to let one id's error silently overwrite
        another's. LOAD failures (favorites, interactions) are still
        page-level: they aren't about any one card, they mean the whole
        list's saved state couldn't be confirmed at all.
      */}
      {(favoritesLoadError || interactionsError) && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-50 border border-red-200" role="alert">
          <p className="flex items-center gap-2 text-[13px] text-red-700">
            {interactionsError ? t('results.interactionsLoadError') : t('results.favoritesLoadError')}
            <button
              type="button"
              onClick={interactionsError ? retryInteractionsLoad : retryFavoritesLoad}
              className="font-semibold text-indigo-600 hover:text-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
            >
              {t('common.retry')}
            </button>
          </p>
        </div>
      )}

      <ResultsHeader
        loading={loading}
        showSlowHint={showSlowHint}
        refining={refining}
        refined={refined}
        refineFailed={refineFailed}
        data={data}
        filteredTotal={filteredTotal}
        counts={counts}
        favs={favs}
        activeTab={activeTab}
        semanticRerank={semanticRerank}
        onSemanticChange={toggleSemantic}
        onOpenHelp={openHelp}
        onExport={handleExport}
        loadEmailMatches={loadEmailMatches}
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
        <ResultsTabs activeTab={activeTab} onChange={handleTabChange} counts={counts} t={t} />
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
            onSearchQueryChange={handleSearchQueryChange}
            debouncedQuery={debouncedQuery}
            presets={presets}
            activePresetId={activePresetId}
            activeFilterCount={activeFilterCount}
            filteredCount={filteredTotal}
            onApplyPreset={handleApplyPreset}
            onDeletePreset={handleDeletePreset}
            onSavePreset={handleSavePreset}
            onSaveSearch={handleSaveSearchToAccount}
            t={t}
          />
          <FilterRail
            filters={filters}
            onFiltersChange={handleFiltersChange}
            sortBy={sortBy}
            onSortByChange={handleSortChange}
            showDismissed={showDismissed}
            onShowDismissedChange={handleShowDismissedChange}
            dismissedCount={dismissedCount}
            activeFilterCount={activeFilterCount}
            sourceOptions={sourceOptions}
            deadlineOptions={deadlineOptions}
            scopeOptions={scopeOptions}
            includeCrossSchool={includeCrossSchool}
            crossSchoolDisabled={!view || crossSchoolBusy}
            crossSchoolFailed={crossSchoolFailed}
            onCrossSchoolRetry={retryCrossSchool}
            onIncludeCrossSchoolChange={toggleCrossSchool}
            t={t}
          />
          {scopeOptions.length > 0 && (
            <p className="text-[12px] text-gray-500">{scopeIndicator}</p>
          )}
          {RELEASE_SCOPE.crossSchoolMatching && (
            <p className="text-[12px] text-gray-500">{t('results.filters.crossSchoolHint')}</p>
          )}
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
          {filteredTotal === 0 ? (
            <EmptyState
              hasFilters={activeFilterCount > 0 || !!debouncedQuery.trim()}
              deadlineFilterFoundNothing={
                !!filters.deadline
                && filters.deadline !== 'rolling'
                && !(data.results ?? []).some((m) => !!m.opportunity.deadline)
              }
              tab={activeTab}
              onClearFilters={handleClearAll}
              onShowRolling={() => setFilters({ ...filters, deadline: 'rolling' })}
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
              ownerReady={ownerReady}
              identityGeneration={identityGeneration}
              ownerScopeKey={ownerScopeKey}
              pendingFavIds={pendingFavIds}
              pendingTrackIds={pendingTrackIds}
              favSaveErrors={favSaveErrors}
              trackSaveErrors={trackSaveErrors}
              interactionsUnready={interactionsLoading || interactionsError}
              feedback={feedback}
              onDraftEmail={openEmailModal}
              onToggleFavorite={handleToggleFav}
              onTrackInteraction={handleTrackInteraction}
              onRetryFavSave={retryFavSave}
              onRetryTrackSave={retryTrackSave}
              onFeedback={handleFeedback}
              positionOffset={data.view_start ?? (effectivePage - 1) * PAGE_SIZE}
              page={effectivePage}
              totalPages={totalPages}
              paginationReady={paginationReady}
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

      {profile && emailTargetLive && (
        <ColdEmailModal
          isOpen={emailModal.open}
          onClose={closeEmailModal}
          profile={profile}
          opportunityId={emailModal.opportunityId}
          opportunityTitle={emailModal.opportunityTitle}
          opportunitySchool={emailModal.opportunitySchool}
          // The row as this page currently sees it, re-resolved every render.
          // Undefined while a refetch is in flight or the row has gone, which
          // fails the follow-up chips closed rather than letting them write a
          // reminder against a posture nobody has re-read.
          reminderTarget={data?.results?.find(
            (m) => m.opportunity.id === emailModal.opportunityId,
          )?.opportunity}
          onContactConfirmed={(record) => {
            if (record?.type) noteContactConfirmed(emailModal.opportunityId, record.type);
          }}
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
