'use client';

import { useState, useEffect, useMemo, useCallback, useRef, memo, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  ArrowLeft,
  Filter,
  Zap,
  Target,
  TrendingUp,
  AlertCircle,
  Search,
  Star,
  X,
  Download,
  EyeOff,
  Bookmark,
  BookmarkPlus,
  Trash2,
  Sparkles,
} from 'lucide-react';
import dynamic from 'next/dynamic';
import MatchCard from '@/components/MatchCard';
import StorageStatusBanner from '@/components/StorageStatusBanner';
import EmailMeButton from '@/components/EmailMeButton';
import { KeyboardHelpDialog } from '@/components/KeyboardHelpDialog';
import { useDebounce } from '@/lib/use-debounce';
import { downloadCSV } from '@/lib/csv-export';

const ColdEmailModal = dynamic(() => import('@/components/ColdEmailModal'), {
  ssr: false,
});
import { getMatches, sendMatchesEmail } from '@/lib/api';
import { getFavorites, toggleFavorite, getInteractions, trackInteraction, removeInteraction } from '@/lib/supabase';
import type { InteractionType } from '@/lib/supabase';
import type { ProfileData, MatchResult, MatchesResponse } from '@/lib/types';
import {
  daysUntil,
  expandSearchAliases,
  matchesToCSV,
  hashProfile as hashProfileUtil,
} from '@/lib/match-utils';
import {
  loadPresets,
  savePresets,
  upsertPreset,
  removePreset,
} from '@/lib/filter-presets';
import type { FilterPreset } from '@/lib/filter-presets';
import { useT } from '@/i18n/client';

const SEARCH_ALIASES_FOR_HINT: Record<string, string[]> = {
  ml: ['machine learning'], ai: ['artificial intelligence'], nlp: ['natural language processing'],
  cv: ['computer vision'], dl: ['deep learning'], rl: ['reinforcement learning'],
  ds: ['data science'], se: ['software engineering'], db: ['database'],
  hci: ['human computer interaction'], cs: ['computer science'], ece: ['electrical'],
};

type Tab = 'all' | 'high_priority' | 'good_match' | 'reach' | 'starred';

interface Filters {
  paid: '' | 'yes' | 'no';
  intl: '' | 'yes' | 'no';
  source: '' | 'uiuc_sro' | 'nsf_reu' | 'manual' | 'uiuc_our_rss' | 'uiuc_faculty' | 'handshake';
  onCampus: '' | 'yes' | 'no';
  deadline: '' | '7' | '14' | '30' | 'passed';
  minScore: number;
}

const DEFAULT_FILTERS: Filters = {
  paid: '',
  intl: '',
  source: '',
  onCampus: '',
  deadline: '',
  minScore: 0,
};

const TABS: { key: Tab; labelKey: string; icon: React.ElementType; color: string }[] = [
  { key: 'all', labelKey: 'results.tabs.all', icon: Filter, color: 'text-gray-600' },
  { key: 'high_priority', labelKey: 'results.tabs.highPriority', icon: Zap, color: 'text-emerald-600' },
  { key: 'good_match', labelKey: 'results.tabs.goodMatch', icon: Target, color: 'text-blue-600' },
  { key: 'reach', labelKey: 'results.tabs.reach', icon: TrendingUp, color: 'text-amber-600' },
  { key: 'starred', labelKey: 'results.tabs.starred', icon: Star, color: 'text-amber-500' },
];

function SkeletonCard() {
  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm space-y-4">
      <div className="flex items-start justify-between">
        <div className="space-y-2 flex-1">
          <div className="skeleton h-5 w-3/4" />
          <div className="skeleton h-4 w-1/2" />
        </div>
        <div className="skeleton h-6 w-24 rounded-full" />
      </div>
      <div className="flex gap-2">
        <div className="skeleton h-6 w-20 rounded-full" />
        <div className="skeleton h-6 w-16 rounded-full" />
        <div className="skeleton h-6 w-16 rounded-full" />
      </div>
      <div className="skeleton h-2 w-full" />
    </div>
  );
}

const hashProfile = hashProfileUtil;



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

  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showSlowHint, setShowSlowHint] = useState(false);

  const [activeTab, setActiveTab] = useState<Tab>(
    (searchParams.get('tab') as Tab) || 'all',
  );
  const [searchQuery, setSearchQuery] = useState(searchParams.get('q') || '');
  const debouncedQuery = useDebounce(searchQuery, 250);

  const [filters, setFilters] = useState<Filters>({
    paid: (searchParams.get('paid') || '') as Filters['paid'],
    intl: (searchParams.get('intl') || '') as Filters['intl'],
    source: (searchParams.get('source') || '') as Filters['source'],
    onCampus: (searchParams.get('loc') || '') as Filters['onCampus'],
    deadline: (searchParams.get('dl') || '') as Filters['deadline'],
    minScore: Number(searchParams.get('min') || 0),
  });
  type SortKey = 'score' | 'deadline' | 'newest';
  const [sortBy, setSortBy] = useState<SortKey>(
    (searchParams.get('sort') as SortKey) || 'score',
  );
  const [showDismissed, setShowDismissed] = useState(false);
  const [semanticRerank, setSemanticRerank] = useState<boolean>(() => {
    const p = searchParams.get('ai');
    if (p === '1') return true;
    if (p === '0') return false;
    if (typeof window === 'undefined') return true;
    const stored = localStorage.getItem('ofe_semantic_rerank');
    if (stored === '0') return false;
    if (stored === '1') return true;
    return true;
  });
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  const [presets, setPresets] = useState<FilterPreset[]>([]);
  const [activePresetId, setActivePresetId] = useState<string | null>(null);
  useEffect(() => { setPresets(loadPresets()); }, []);

  const [emailModal, setEmailModal] = useState<{
    open: boolean;
    opportunityId: string;
    opportunityTitle: string;
  }>({ open: false, opportunityId: '', opportunityTitle: '' });

  const [favs, setFavs] = useState<Set<string>>(new Set());
  const [interactions, setInteractions] = useState<Map<string, InteractionType>>(new Map());
  useEffect(() => {
    getFavorites().then(setFavs).catch(() => {});
    getInteractions().then(setInteractions).catch(() => {});
  }, []);

  useEffect(() => {
    const params = new URLSearchParams();
    if (activeTab !== 'all') params.set('tab', activeTab);
    if (debouncedQuery) params.set('q', debouncedQuery);
    if (filters.paid) params.set('paid', filters.paid);
    if (filters.intl) params.set('intl', filters.intl);
    if (filters.source) params.set('source', filters.source);
    if (filters.onCampus) params.set('loc', filters.onCampus);
    if (filters.deadline) params.set('dl', filters.deadline);
    if (filters.minScore > 0) params.set('min', String(filters.minScore));
    if (sortBy !== 'score') params.set('sort', sortBy);
    if (!semanticRerank) params.set('ai', '0');
    const qs = params.toString();
    const newUrl = qs ? `/results?${qs}` : '/results';
    window.history.replaceState(null, '', newUrl);
  }, [activeTab, debouncedQuery, filters, sortBy, semanticRerank]);

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
    const raw = localStorage.getItem('ofe_profile');
    if (!raw) {
      router.replace('/');
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed.skills) && parsed.skills.length > 0 && typeof parsed.skills[0] === 'string') {
        parsed.skills = (parsed.skills as string[]).map((name: string) => ({ name, level: 'beginner' as const }));
      }
      const loadedProfile = parsed as ProfileData;
      setProfile(loadedProfile);

      const cachedRaw = sessionStorage.getItem('ofe_match_results');
      if (cachedRaw) {
        try {
          const cached = JSON.parse(cachedRaw) as {
            hash: string;
            semantic?: boolean;
            data: MatchesResponse;
          };
          const hashOk = cached.hash === hashProfile(loadedProfile);
          const semanticOk = (cached.semantic ?? false) === semanticRerank;
          if (hashOk && semanticOk) {
            setData(cached.data);
            setLoading(false);
          } else {
            sessionStorage.removeItem('ofe_match_results');
          }
        } catch {
          sessionStorage.removeItem('ofe_match_results');
        }
      }
    } catch {
      router.replace('/');
    }
    // semanticRerank is intentionally read but not in deps: this effect
    // should only run on mount to load profile + any matching cache, not
    // refire every time the toggle flips.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  useEffect(() => {
    if (!loading) {
      setShowSlowHint(false);
      return;
    }
    const timer = setTimeout(() => setShowSlowHint(true), 8000);
    return () => clearTimeout(timer);
  }, [loading]);

  useEffect(() => {
    if (!profile || data) return;
    let cancelled = false;

    async function fetchMatches() {
      setLoading(true);
      setError(null);
      try {
        const result = await getMatches(profile!, { semantic: semanticRerank });
        if (!cancelled) {
          setData(result);
          try {
            sessionStorage.setItem(
              'ofe_match_results',
              JSON.stringify({
                hash: hashProfile(profile!),
                semantic: semanticRerank,
                data: result,
              }),
            );
          } catch { /* quota */ }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : t('results.loadFailed'));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchMatches();
    return () => { cancelled = true; };
  }, [profile, data, semanticRerank, t]);

  const toggleSemantic = useCallback((next: boolean) => {
    setSemanticRerank(next);
    try { localStorage.setItem('ofe_semantic_rerank', next ? '1' : '0'); } catch { /* quota */ }
    setData(null);
    setPage(1);
  }, []);

  const [focusedIdx, setFocusedIdx] = useState(-1);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => { setFocusedIdx(-1); }, [activeTab, debouncedQuery, filters, sortBy, page]);

  const filtered = useMemo(() => {
    if (!data?.results) return [];
    let results: MatchResult[];

    if (activeTab === 'starred') {
      results = data.results.filter((m) => favs.has(m.opportunity.id));
    } else if (activeTab === 'all') {
      results = data.results.filter((m) => m.bucket !== 'low_fit');
    } else {
      results = data.results.filter((m) => m.bucket === activeTab);
    }

    if (!showDismissed) {
      results = results.filter((m) => interactions.get(m.opportunity.id) !== 'dismissed');
    }

    if (filters.paid) {
      results = results.filter((m) =>
        filters.paid === 'yes'
          ? m.opportunity.paid === 'yes' || m.opportunity.paid === 'stipend'
          : m.opportunity.paid === 'no' || m.opportunity.paid === 'unknown',
      );
    }
    if (filters.intl) {
      results = results.filter((m) =>
        filters.intl === 'yes'
          ? m.opportunity.eligibility.international_friendly === 'yes'
          : true,
      );
    }
    if (filters.source) {
      results = results.filter((m) => m.opportunity.source === filters.source);
    }
    if (filters.onCampus) {
      results = results.filter((m) =>
        filters.onCampus === 'yes' ? m.opportunity.on_campus : !m.opportunity.on_campus,
      );
    }
    if (filters.deadline) {
      results = results.filter((m) => {
        const d = daysUntil(m.opportunity.deadline);
        if (filters.deadline === 'passed') return d !== null && d < 0;
        if (d === null || d < 0) return false;
        return d <= Number(filters.deadline);
      });
    }
    if (filters.minScore > 0) {
      results = results.filter((m) => m.final_score >= filters.minScore);
    }

    if (debouncedQuery.trim()) {
      const q = debouncedQuery.toLowerCase();
      const expanded = expandSearchAliases(q);
      results = results.filter((m) => {
        const title = m.opportunity.title.toLowerCase();
        const org = m.opportunity.organization?.toLowerCase() ?? '';
        const kws = m.opportunity.keywords ?? [];
        const desc = (m.opportunity.description_clean ?? m.opportunity.description_raw ?? '').toLowerCase();
        const dept = m.opportunity.department?.toLowerCase() ?? '';
        const reasons = m.reasons_fit.join(' ').toLowerCase();
        return expanded.some((term) =>
          title.includes(term) ||
          org.includes(term) ||
          dept.includes(term) ||
          kws.some((k) => k.toLowerCase().includes(term)) ||
          desc.includes(term) ||
          reasons.includes(term)
        );
      });
    }

    if (sortBy === 'deadline') {
      results = [...results].sort((a, b) => {
        const da = a.opportunity.deadline || '9999';
        const db = b.opportunity.deadline || '9999';
        return da.localeCompare(db);
      });
    } else if (sortBy === 'newest') {
      results = [...results].sort((a, b) => {
        const pa = a.opportunity.posted_date || '';
        const pb = b.opportunity.posted_date || '';
        return pb.localeCompare(pa);
      });
    }

    return results;
  }, [data, activeTab, debouncedQuery, filters, favs, sortBy, interactions, showDismissed]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page],
  );

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

  const activeFilterCount =
    (filters.paid ? 1 : 0) +
    (filters.intl ? 1 : 0) +
    (filters.source ? 1 : 0) +
    (filters.onCampus ? 1 : 0) +
    (filters.deadline ? 1 : 0) +
    (filters.minScore > 0 ? 1 : 0);

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
    const next = upsertPreset(presets, preset);
    setPresets(next);
    savePresets(next);
    setActivePresetId(preset.id);
  }, [filters, sortBy, activeTab, presets, t]);

  const handleApplyPreset = useCallback((preset: FilterPreset) => {
    setFilters(preset.filters as typeof DEFAULT_FILTERS);
    setSortBy(preset.sortBy);
    setActiveTab(preset.tab as Tab);
    setActivePresetId(preset.id);
  }, []);

  const handleDeletePreset = useCallback((id: string) => {
    const next = removePreset(presets, id);
    setPresets(next);
    savePresets(next);
    if (activePresetId === id) setActivePresetId(null);
  }, [presets, activePresetId]);

  const handleExport = useCallback(() => {
    const rows = activeTab === 'starred'
      ? filtered
      : filtered.filter(m => favs.has(m.opportunity.id));
    if (rows.length === 0) return;
    downloadCSV(`opportunities-${new Date().toISOString().slice(0, 10)}.csv`, matchesToCSV(rows));
  }, [filtered, favs, activeTab]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && emailModal.open) {
        setEmailModal({ open: false, opportunityId: '', opportunityTitle: '' });
        return;
      }
      const target = e.target as HTMLElement;
      const isTyping = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA' || target?.isContentEditable;
      if (isTyping) return;

      if (e.key === '/') {
        e.preventDefault();
        document.getElementById('results-search-input')?.focus();
        return;
      }

      if (paginated.length === 0) return;

      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault();
        setFocusedIdx(i => {
          const next = Math.min(paginated.length - 1, i < 0 ? 0 : i + 1);
          document.getElementById(`match-card-${paginated[next]?.opportunity.id}`)
            ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
          return next;
        });
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault();
        setFocusedIdx(i => {
          const next = Math.max(0, i <= 0 ? 0 : i - 1);
          document.getElementById(`match-card-${paginated[next]?.opportunity.id}`)
            ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
          return next;
        });
      } else if (e.key === 's' && focusedIdx >= 0) {
        e.preventDefault();
        const match = paginated[focusedIdx];
        if (match) handleToggleFav(match.opportunity.id);
      } else if (e.key === 'Enter' && focusedIdx >= 0) {
        e.preventDefault();
        const match = paginated[focusedIdx];
        const url = match?.opportunity.application?.application_url || match?.opportunity.url;
        if (url) window.open(url, '_blank', 'noopener,noreferrer');
      } else if (e.key === '?' && e.shiftKey) {
        e.preventDefault();
        setHelpOpen(true);
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [emailModal.open, paginated, focusedIdx, handleToggleFav]);

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

      <div className="mb-8 sm:mb-10 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl sm:text-4xl font-bold text-gray-900 tracking-tight">
            {t('results.title')}
          </h1>
          <p className="mt-1.5 sm:mt-2 text-[13px] sm:text-[15px] text-gray-400">
            {loading
              ? semanticRerank
                ? t('results.analyzingAi')
                : t('results.analyzing')
              : data
                ? (
                  <>
                    {t('results.rankedFor', { count: counts.all })}
                    {semanticRerank && (
                      <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-violet-50 text-violet-700 align-middle">
                        <Sparkles className="w-2.5 h-2.5" aria-hidden="true" />
                        {t('results.aiBadge')}
                      </span>
                    )}
                  </>
                )
                : t('common.loading')}
          </p>
          {loading && showSlowHint && (
            <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2.5 py-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" aria-hidden="true" />
              {t('results.slowHint')}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <SemanticToggle value={semanticRerank} onChange={toggleSemantic} disabled={loading} t={t} />
          {!loading && data && (
            <button
              type="button"
              onClick={() => setHelpOpen(true)}
              className="hidden md:inline-flex items-center justify-center h-6 px-2 text-[10px] font-mono text-gray-400 bg-gray-100 border border-gray-200 rounded hover:bg-gray-200 hover:text-gray-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 transition-colors"
              aria-label={t('results.keyboardHelp.open_aria_show')}
              title={t('results.keyboardHelp.open_title')}
            >
              ?
            </button>
          )}
          {!loading && data && filtered.length > 0 && (
            <EmailMeButton
              label={t('email.sendMatches')}
              title={t('email.subtitle')}
              onSend={async (emailAddr) => {
                const top = filtered.slice(0, 50);
                const items = top.map((m) => ({
                  title: m.opportunity.title,
                  url: m.opportunity.url || m.opportunity.source_url || '',
                  score: m.final_score,
                  source: m.opportunity.source || '',
                  deadline: m.opportunity.deadline || null,
                  organization: m.opportunity.organization || '',
                }));
                const hint = t('email.subjectMatches', { count: items.length });
                return sendMatchesEmail(emailAddr, items, hint);
              }}
            />
          )}
          {!loading && data && favs.size > 0 && (
            <button
              type="button"
              onClick={handleExport}
              className="inline-flex items-center gap-2 px-3 py-2 text-[12px] font-medium text-gray-600 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
              title={activeTab === 'starred' ? t('results.exportFilteredTitle') : t('results.exportStarredTitle')}
            >
              <Download className="w-3.5 h-3.5" />
              {activeTab === 'starred'
                ? t('results.exportLabelFiltered')
                : t('results.exportLabelStarred', { count: favs.size })}
            </button>
          )}
        </div>
      </div>

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
        <div className="overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0 mb-8 sm:mb-10 no-scrollbar">
          <div className="inline-flex items-center bg-black/[0.04] rounded-full p-1" role="tablist" aria-label={t('results.matchCategoryAria')}>
            {TABS.map(({ key, labelKey, icon: Icon, color }) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={activeTab === key}
                onClick={() => setActiveTab(key)}
                className={`inline-flex items-center gap-1.5 px-3 sm:px-4 py-2 rounded-full text-[12px] sm:text-[13px] font-medium whitespace-nowrap transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
                  ${
                    activeTab === key
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'
                  }`}
              >
                <Icon className={`w-3.5 h-3.5 ${activeTab === key ? color : ''}`} aria-hidden="true" />
                {t(labelKey)}
                <span className="text-[11px] font-semibold tabular-nums text-gray-400" aria-label={t('results.countResultsAria', { count: counts[key] })}>
                  {counts[key]}
                </span>
              </button>
            ))}
          </div>
        </div>
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
          <div className="relative">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              id="results-search-input"
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('results.search.placeholder')}
              className="w-full pl-11 pr-24 py-3 bg-white rounded-xl border-0 shadow-[0_1px_4px_rgba(0,0,0,0.04)] text-[14px] text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all duration-300"
            />
            <kbd className="absolute right-10 top-1/2 -translate-y-1/2 hidden sm:inline-flex items-center justify-center h-5 px-1.5 text-[10px] font-mono text-gray-400 bg-gray-100 border border-gray-200 rounded">
              /
            </kbd>
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full hover:bg-gray-100 transition-colors"
                aria-label={t('results.clearSearchAria')}
              >
                <X className="w-3.5 h-3.5 text-gray-400" />
              </button>
            )}
          </div>
          {(presets.length > 0 || activeFilterCount > 0 || !!debouncedQuery.trim()) && (
            <div className="flex flex-wrap items-center gap-1.5">
              {presets.map(p => (
                <PresetPill
                  key={p.id}
                  preset={p}
                  active={p.id === activePresetId}
                  onApply={handleApplyPreset}
                  onDelete={handleDeletePreset}
                  t={t}
                />
              ))}
              {(activeFilterCount > 0 || !!debouncedQuery.trim()) && (
                <button
                  type="button"
                  onClick={handleSavePreset}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 transition-colors"
                  title={t('results.savePresetTitle')}
                >
                  <BookmarkPlus className="w-3 h-3" />
                  {t('results.savePresetButton')}
                </button>
              )}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 -mx-4 px-4 sm:mx-0 sm:px-0">
            <FilterSelect
              value={filters.paid}
              onChange={(v) => setFilters((f) => ({ ...f, paid: v as Filters['paid'] }))}
              options={[['', t('results.filters.paidAll')], ['yes', t('results.filters.paidYes')], ['no', t('results.filters.paidNo')]]}
            />
            <FilterSelect
              value={filters.intl}
              onChange={(v) => setFilters((f) => ({ ...f, intl: v as Filters['intl'] }))}
              options={[['', t('results.filters.intlAll')], ['yes', t('results.filters.intlYes')], ['no', t('results.filters.intlNo')]]}
            />
            <FilterSelect
              value={filters.source}
              onChange={(v) => setFilters((f) => ({ ...f, source: v as Filters['source'] }))}
              options={[['', t('results.filters.sourceAll')], ['uiuc_sro', t('results.filters.sourceUiucSro')], ['nsf_reu', t('results.filters.sourceNsfReu')], ['uiuc_faculty', t('results.filters.sourceUiucFaculty')], ['handshake', t('results.filters.sourceHandshake')], ['manual', t('results.filters.sourceManual')], ['uiuc_our_rss', t('results.filters.sourceOurRss')]]}
            />
            <FilterSelect
              value={filters.onCampus}
              onChange={(v) => setFilters((f) => ({ ...f, onCampus: v as Filters['onCampus'] }))}
              options={[['', t('results.filters.locAll')], ['yes', t('results.filters.locYes')], ['no', t('results.filters.locNo')]]}
            />
            <FilterSelect
              value={filters.deadline}
              onChange={(v) => setFilters((f) => ({ ...f, deadline: v as Filters['deadline'] }))}
              options={[['', t('results.filters.deadlineAll')], ['7', t('results.filters.deadline7')], ['14', t('results.filters.deadline14')], ['30', t('results.filters.deadline30')], ['passed', t('results.filters.deadlinePassed')]]}
            />
            <FilterSelect
              value={sortBy}
              onChange={(v) => setSortBy(v as SortKey)}
              options={[['score', t('results.filters.sortScore')], ['deadline', t('results.filters.sortDeadline')], ['newest', t('results.filters.sortNewest')]]}
            />
            <MinScoreFilter
              value={filters.minScore}
              onChange={(v) => setFilters((f) => ({ ...f, minScore: v }))}
              t={t}
            />
            {dismissedCount > 0 && (
              <button
                type="button"
                onClick={() => setShowDismissed(s => !s)}
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
                onClick={() => setFilters(DEFAULT_FILTERS)}
                className="px-3 py-1.5 text-[12px] font-medium text-red-500 hover:text-red-700 transition-colors"
              >
                {activeFilterCount > 1
                  ? t('results.clearNFilters', { count: activeFilterCount })
                  : t('results.clearNFilter', { count: activeFilterCount })}
              </button>
            )}
          </div>
          {(debouncedQuery.trim() || activeFilterCount > 0) && (
            <p className="text-[13px] text-gray-400 mt-2">
              {filtered.length === 0
                ? t('results.search.noResults')
                : t('results.search.resultsFound', { count: filtered.length })}
              {debouncedQuery.trim() && (
                <span> {t('results.resultsForPrefix')} <span className="font-medium text-gray-600">&ldquo;{debouncedQuery}&rdquo;</span>
                  {SEARCH_ALIASES_FOR_HINT[debouncedQuery.toLowerCase()] && (
                    <span className="text-gray-300"> ({t('results.alsoMatching', { terms: SEARCH_ALIASES_FOR_HINT[debouncedQuery.toLowerCase()]?.join(', ') ?? '' })})</span>
                  )}
                </span>
              )}
            </p>
          )}
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
              onClearFilters={() => {
                setFilters(DEFAULT_FILTERS);
                setSearchQuery('');
              }}
              t={t}
            />
          ) : (
            <>
              {paginated.map((match: MatchResult, idx: number) => (
                <div
                  key={match.opportunity.id}
                  id={`match-card-${match.opportunity.id}`}
                  className={`transition-all ${focusedIdx === idx ? 'ring-2 ring-blue-500/40 rounded-2xl' : ''}`}
                >
                  <MemoizedMatchCard
                    match={match}
                    profile={profile}
                    onDraftEmail={openEmailModal}
                    isFavorited={favs.has(match.opportunity.id)}
                    onToggleFavorite={handleToggleFav}
                    interaction={interactions.get(match.opportunity.id)}
                    onTrackInteraction={handleTrackInteraction}
                  />
                </div>
              ))}

              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 pt-4">
                  <button
                    type="button"
                    disabled={page <= 1}
                    onClick={() => { setPage(p => p - 1); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
                    className="px-4 py-2 text-sm font-medium border border-gray-200 rounded-xl hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    {t('results.pagination.previous')}
                  </button>
                  <span className="text-sm text-gray-500 tabular-nums px-3">
                    {page} / {totalPages}
                  </span>
                  <button
                    type="button"
                    disabled={page >= totalPages}
                    onClick={() => { setPage(p => p + 1); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
                    className="px-4 py-2 text-sm font-medium border border-gray-200 rounded-xl hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    {t('results.pagination.next')}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {loading && (
        <div className="fixed top-12 left-0 right-0 z-40">
          <div className="h-[2px] bg-black/[0.03]">
            <div className="h-full bg-blue-500 rounded-r-full animate-pulse" style={{ width: '60%' }} />
          </div>
        </div>
      )}

      {profile && (
        <ColdEmailModal
          isOpen={emailModal.open}
          onClose={() =>
            setEmailModal({ open: false, opportunityId: '', opportunityTitle: '' })
          }
          profile={profile}
          opportunityId={emailModal.opportunityId}
          opportunityTitle={emailModal.opportunityTitle}
        />
      )}

      {helpOpen && <KeyboardHelpDialog onClose={() => setHelpOpen(false)} t={t} />}
    </div>
  );
}

const MemoizedMatchCard = memo(MatchCard, (prev, next) => {
  return (
    prev.match.opportunity.id === next.match.opportunity.id &&
    prev.match.final_score === next.match.final_score &&
    prev.isFavorited === next.isFavorited &&
    prev.interaction === next.interaction &&
    prev.profile === next.profile &&
    prev.onDraftEmail === next.onDraftEmail &&
    prev.onToggleFavorite === next.onToggleFavorite &&
    prev.onTrackInteraction === next.onTrackInteraction
  );
});
MemoizedMatchCard.displayName = 'MemoizedMatchCard';

function EmptyState({
  hasFilters,
  tab,
  onClearFilters,
  t,
}: {
  hasFilters: boolean;
  tab: Tab;
  onClearFilters: () => void;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  if (hasFilters) {
    return (
      <div className="text-center py-16 space-y-3">
        <p className="text-gray-500 text-lg">{t('results.empty.withFilters')}</p>
        <p className="text-gray-400 text-sm">{t('results.empty.withFiltersHint')}</p>
        <button
          type="button"
          onClick={onClearFilters}
          className="mt-2 px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 rounded-xl hover:bg-blue-100 transition-colors"
        >
          {t('results.empty.clearAll')}
        </button>
      </div>
    );
  }

  if (tab === 'starred') {
    return (
      <div className="text-center py-16 space-y-2">
        <Star className="w-8 h-8 text-gray-300 mx-auto" />
        <p className="text-gray-500 text-lg">{t('results.empty.starred')}</p>
        <p className="text-gray-400 text-sm">{t('results.empty.starredHint')}</p>
      </div>
    );
  }

  return (
    <div className="text-center py-16">
      <p className="text-gray-400 text-lg">{t('results.empty.category')}</p>
    </div>
  );
}

function FilterSelect({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`px-3 py-1.5 rounded-lg text-[12px] font-medium border transition-colors cursor-pointer outline-none ${
        value
          ? 'bg-blue-50 border-blue-200 text-blue-700'
          : 'bg-white border-gray-200 text-gray-500 hover:border-gray-300'
      }`}
    >
      {options.map(([val, label]) => (
        <option key={val} value={val}>{label}</option>
      ))}
    </select>
  );
}

function MinScoreFilter({
  value,
  onChange,
  t,
}: {
  value: number;
  onChange: (v: number) => void;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  const [open, setOpen] = useState(false);
  const active = value > 0;
  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={`px-3 py-1.5 rounded-lg text-[12px] font-medium border transition-colors cursor-pointer outline-none ${
          active
            ? 'bg-blue-50 border-blue-200 text-blue-700'
            : 'bg-white border-gray-200 text-gray-500 hover:border-gray-300'
        }`}
      >
        {active ? t('results.minScore.buttonActive', { value }) : t('results.minScore.button')}
      </button>
      {open && (
        <div className="absolute z-20 mt-2 right-0 bg-white rounded-xl shadow-lg border border-gray-200 p-4 w-64">
          <div className="flex items-center justify-between text-[11px] text-gray-500 mb-2">
            <span>{t('results.minScore.label')}</span>
            <span className="font-semibold tabular-nums text-gray-700">{value}</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={value}
            onChange={(e) => onChange(Number(e.target.value))}
            className="w-full accent-blue-600"
          />
          <div className="flex justify-between mt-3">
            <button
              type="button"
              onClick={() => onChange(0)}
              className="text-[11px] text-gray-500 hover:text-gray-700"
            >
              {t('results.minScore.reset')}
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-[11px] font-medium text-blue-600 hover:text-blue-700"
            >
              {t('results.minScore.done')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SemanticToggle({
  value,
  onChange,
  disabled,
  t,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={t('results.semantic.aria')}
      disabled={disabled}
      onClick={() => onChange(!value)}
      title={value ? t('results.semantic.titleOn') : t('results.semantic.titleOff')}
      className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-[12px] font-medium border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed ${
        value
          ? 'bg-gradient-to-r from-blue-600 to-violet-600 text-white border-transparent shadow-sm'
          : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300'
      }`}
    >
      <Sparkles className={`w-3.5 h-3.5 ${value ? 'text-white' : 'text-gray-400'}`} aria-hidden="true" />
      <span className="hidden sm:inline">{t('results.semantic.label')}</span>
      <span className={`text-[10px] font-semibold tracking-wider uppercase ${value ? 'opacity-90' : 'opacity-60'}`}>
        {value ? t('results.semantic.on') : t('results.semantic.off')}
      </span>
    </button>
  );
}

function PresetPill({
  preset,
  active,
  onApply,
  onDelete,
  t,
}: {
  preset: FilterPreset;
  active: boolean;
  onApply: (p: FilterPreset) => void;
  onDelete: (id: string) => void;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full text-[11px] font-medium border transition-colors ${
      active
        ? 'bg-blue-600 border-blue-600 text-white'
        : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'
    }`}>
      <button
        type="button"
        onClick={() => onApply(preset)}
        className="inline-flex items-center gap-1 pl-2.5 pr-1.5 py-1"
        aria-label={t('results.presets.applyLabel', { name: preset.name })}
      >
        <Bookmark className={`w-2.5 h-2.5 ${active ? 'fill-white' : ''}`} aria-hidden="true" />
        {preset.name}
      </button>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          if (window.confirm(t('results.presets.deleteConfirm', { name: preset.name }))) onDelete(preset.id);
        }}
        className={`pr-2 py-1 ${active ? 'text-white/70 hover:text-white' : 'text-gray-300 hover:text-red-500'}`}
        aria-label={t('results.presets.deleteLabel', { name: preset.name })}
      >
        <Trash2 className="w-2.5 h-2.5" />
      </button>
    </span>
  );
}

function SummaryCard({
  label,
  count,
  accent,
}: {
  label: string;
  count: number;
  accent?: 'emerald' | 'blue' | 'amber';
}) {
  const textColor = accent
    ? { emerald: 'text-emerald-600', blue: 'text-blue-600', amber: 'text-amber-600' }[accent]
    : 'text-gray-900';

  return (
    <div className="bg-white rounded-2xl shadow-[0_1px_6px_rgba(0,0,0,0.04)] px-5 py-5">
      <p className={`text-3xl font-bold tabular-nums tracking-tight ${textColor}`}>{count}</p>
      <p className="text-[11px] font-medium text-gray-400 mt-1 uppercase tracking-wider">{label}</p>
    </div>
  );
}
