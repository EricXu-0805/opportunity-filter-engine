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
} from 'lucide-react';
import MatchCard from '@/components/MatchCard';
import ColdEmailModal from '@/components/ColdEmailModal';
import { getMatches } from '@/lib/api';
import { getFavorites, toggleFavorite, getInteractions, trackInteraction, removeInteraction } from '@/lib/supabase';
import type { InteractionType } from '@/lib/supabase';
import type { ProfileData, MatchResult, MatchesResponse, SkillWithLevel } from '@/lib/types';

const SEARCH_ALIASES: Record<string, string[]> = {
  ml: ['machine learning'],
  ai: ['artificial intelligence'],
  nlp: ['natural language processing'],
  cv: ['computer vision'],
  dl: ['deep learning'],
  hci: ['human computer interaction', 'human-computer interaction'],
  rl: ['reinforcement learning'],
  ds: ['data science'],
  se: ['software engineering'],
  pl: ['programming languages'],
  os: ['operating systems'],
  db: ['database'],
  ece: ['electrical', 'computer engineering'],
  cs: ['computer science'],
  ee: ['electrical engineering'],
  me: ['mechanical engineering'],
  ce: ['civil engineering'],
  cheme: ['chemical engineering'],
  matsci: ['materials science'],
  neuro: ['neuroscience'],
  bioinfo: ['bioinformatics'],
};

function expandSearchAliases(query: string): string[] {
  const terms = [query];
  const aliases = SEARCH_ALIASES[query];
  if (aliases) terms.push(...aliases);
  for (const [abbr, expansions] of Object.entries(SEARCH_ALIASES)) {
    if (query.includes(abbr) && query !== abbr) {
      for (const exp of expansions) {
        terms.push(query.replace(abbr, exp));
      }
    }
  }
  return terms;
}

type Tab = 'all' | 'high_priority' | 'good_match' | 'reach' | 'starred';

interface Filters {
  paid: '' | 'yes' | 'no';
  intl: '' | 'yes' | 'no';
  source: '' | 'uiuc_sro' | 'nsf_reu' | 'manual' | 'uiuc_our_rss' | 'uiuc_faculty' | 'handshake';
  onCampus: '' | 'yes' | 'no';
}

const TABS: { key: Tab; label: string; icon: React.ElementType; color: string }[] = [
  { key: 'all', label: 'All', icon: Filter, color: 'text-gray-600' },
  { key: 'high_priority', label: 'High Priority', icon: Zap, color: 'text-emerald-600' },
  { key: 'good_match', label: 'Good Match', icon: Target, color: 'text-blue-600' },
  { key: 'reach', label: 'Reach', icon: TrendingUp, color: 'text-amber-600' },
  { key: 'starred', label: 'Starred', icon: Star, color: 'text-amber-500' },
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

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
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

  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
  });
  type SortKey = 'score' | 'deadline' | 'newest';
  const [sortBy, setSortBy] = useState<SortKey>(
    (searchParams.get('sort') as SortKey) || 'score',
  );
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

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

  // Sync filters to URL (non-blocking)
  useEffect(() => {
    const params = new URLSearchParams();
    if (activeTab !== 'all') params.set('tab', activeTab);
    if (debouncedQuery) params.set('q', debouncedQuery);
    if (filters.paid) params.set('paid', filters.paid);
    if (filters.intl) params.set('intl', filters.intl);
    if (filters.source) params.set('source', filters.source);
    if (filters.onCampus) params.set('loc', filters.onCampus);
    if (sortBy !== 'score') params.set('sort', sortBy);
    const qs = params.toString();
    const newUrl = qs ? `/results?${qs}` : '/results';
    window.history.replaceState(null, '', newUrl);
  }, [activeTab, debouncedQuery, filters]);

  const handleToggleFav = useCallback(async (oppId: string) => {
    const wasFaved = favs.has(oppId);
    const nowFaved = await toggleFavorite(oppId, wasFaved);
    setFavs(prev => {
      const next = new Set(prev);
      nowFaved ? next.add(oppId) : next.delete(oppId);
      return next;
    });
  }, [favs]);

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
      setProfile(parsed as ProfileData);

      const cached = sessionStorage.getItem('ofe_match_results');
      if (cached) {
        try {
          const cachedData = JSON.parse(cached) as MatchesResponse;
          setData(cachedData);
          setLoading(false);
        } catch {
          // corrupt cache — will re-fetch
        }
      }
    } catch {
      router.replace('/');
    }
  }, [router]);

  useEffect(() => {
    if (!profile || data) return;
    let cancelled = false;

    async function fetchMatches() {
      setLoading(true);
      setError(null);
      try {
        const result = await getMatches(profile!);
        if (!cancelled) {
          setData(result);
          try { sessionStorage.setItem('ofe_match_results', JSON.stringify(result)); } catch { /* quota */ }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load matches');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchMatches();
    return () => { cancelled = true; };
  }, [profile, data]);

  // Keyboard: Escape closes email modal
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && emailModal.open) {
        setEmailModal({ open: false, opportunityId: '', opportunityTitle: '' });
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [emailModal.open]);

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

    if (debouncedQuery.trim()) {
      const q = debouncedQuery.toLowerCase();
      const expanded = expandSearchAliases(q);
      results = results.filter((m) => {
        const title = m.opportunity.title.toLowerCase();
        const org = m.opportunity.organization?.toLowerCase() ?? '';
        const kws = m.opportunity.keywords ?? [];
        return expanded.some((term) =>
          title.includes(term) ||
          org.includes(term) ||
          kws.some((k) => k.toLowerCase().includes(term))
        );
      });
    }

    if (sortBy === 'deadline') {
      results.sort((a, b) => {
        const da = a.opportunity.deadline || '9999';
        const db = b.opportunity.deadline || '9999';
        return da.localeCompare(db);
      });
    } else if (sortBy === 'newest') {
      results.sort((a, b) => {
        const pa = (a.opportunity as unknown as { posted_date?: string }).posted_date || '';
        const pb = (b.opportunity as unknown as { posted_date?: string }).posted_date || '';
        return pb.localeCompare(pa);
      });
    }

    return results;
  }, [data, activeTab, debouncedQuery, filters, favs, sortBy]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page],
  );

  useEffect(() => { setPage(1); }, [activeTab, debouncedQuery, filters, sortBy]);

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
        opportunityTitle: match?.opportunity.title ?? 'Opportunity',
      });
    },
    [data],
  );

  const activeFilterCount = Object.values(filters).filter(Boolean).length;

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <button
        type="button"
        onClick={() => router.push('/')}
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 mb-8 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Profile
      </button>

      <div className="mb-10">
        <h1 className="text-4xl font-bold text-gray-900 tracking-tight">
          Your Matches
        </h1>
        <p className="mt-2 text-[15px] text-gray-400">
          {loading
            ? 'Analyzing your profile...'
            : data
              ? `${counts.all} opportunities ranked for you`
              : 'Loading...'}
        </p>
      </div>

      {!loading && data && (
        <div className="grid grid-cols-4 gap-3 mb-10">
          <SummaryCard label="Total" count={counts.all} />
          <SummaryCard label="High Priority" count={counts.high_priority} accent="emerald" />
          <SummaryCard label="Good Match" count={counts.good_match} accent="blue" />
          <SummaryCard label="Reach" count={counts.reach} accent="amber" />
        </div>
      )}

      {!loading && data && (
        <div className="inline-flex items-center bg-black/[0.04] rounded-full p-1 mb-10">
          {TABS.map(({ key, label, icon: Icon, color }) => (
            <button
              key={key}
              type="button"
              onClick={() => setActiveTab(key)}
              className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-[13px] font-medium whitespace-nowrap transition-all duration-300
                ${
                  activeTab === key
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
            >
              <Icon className={`w-3.5 h-3.5 ${activeTab === key ? color : ''}`} />
              {label}
              <span className="text-[11px] font-semibold tabular-nums text-gray-400">
                {counts[key]}
              </span>
            </button>
          ))}
        </div>
      )}

      {!loading && data && (
        <div className="space-y-3 mb-8">
          <div className="relative">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by title, school, or research area..."
              className="w-full pl-11 pr-10 py-3 bg-white rounded-xl border-0 shadow-[0_1px_4px_rgba(0,0,0,0.04)] text-[14px] text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all duration-300"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full hover:bg-gray-100 transition-colors"
              >
                <X className="w-3.5 h-3.5 text-gray-400" />
              </button>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <FilterSelect
              value={filters.paid}
              onChange={(v) => setFilters((f) => ({ ...f, paid: v as Filters['paid'] }))}
              options={[['', 'Paid / Unpaid'], ['yes', 'Paid only'], ['no', 'Unpaid']]}
            />
            <FilterSelect
              value={filters.intl}
              onChange={(v) => setFilters((f) => ({ ...f, intl: v as Filters['intl'] }))}
              options={[['', 'International status'], ['yes', 'Intl friendly only'], ['no', 'Show all (incl. US-only)']]}
            />
            <FilterSelect
              value={filters.source}
              onChange={(v) => setFilters((f) => ({ ...f, source: v as Filters['source'] }))}
              options={[['', 'All sources'], ['uiuc_sro', 'UIUC SRO'], ['nsf_reu', 'NSF REU'], ['uiuc_faculty', 'Faculty Research'], ['handshake', 'Handshake'], ['manual', 'UIUC Labs'], ['uiuc_our_rss', 'OUR RSS']]}
            />
            <FilterSelect
              value={filters.onCampus}
              onChange={(v) => setFilters((f) => ({ ...f, onCampus: v as Filters['onCampus'] }))}
              options={[['', 'Any location'], ['yes', 'On campus'], ['no', 'Off campus / Remote']]}
            />
            <FilterSelect
              value={sortBy}
              onChange={(v) => setSortBy(v as SortKey)}
              options={[['score', 'Sort: Best match'], ['deadline', 'Sort: Deadline soonest'], ['newest', 'Sort: Recently posted']]}
            />
            {activeFilterCount > 0 && (
              <button
                type="button"
                onClick={() => setFilters({ paid: '', intl: '', source: '', onCampus: '' })}
                className="px-3 py-1.5 text-[12px] font-medium text-red-500 hover:text-red-700 transition-colors"
              >
                Clear {activeFilterCount} filter{activeFilterCount > 1 ? 's' : ''}
              </button>
            )}
          </div>
          {(debouncedQuery.trim() || activeFilterCount > 0) && (
            <p className="text-[13px] text-gray-400 mt-2">
              {filtered.length === 0
                ? 'No results'
                : `${filtered.length} result${filtered.length > 1 ? 's' : ''}`}
              {debouncedQuery.trim() && (
                <span> for <span className="font-medium text-gray-600">&ldquo;{debouncedQuery}&rdquo;</span>
                  {SEARCH_ALIASES[debouncedQuery.toLowerCase()] && (
                    <span className="text-gray-300"> (also matching: {SEARCH_ALIASES[debouncedQuery.toLowerCase()]?.join(', ')})</span>
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
            Retry
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
                setFilters({ paid: '', intl: '', source: '', onCampus: '' });
                setSearchQuery('');
              }}
            />
          ) : (
            <>
              {paginated.map((match: MatchResult) => (
                <MemoizedMatchCard
                  key={match.opportunity.id}
                  match={match}
                  profile={profile}
                  onDraftEmail={openEmailModal}
                  isFavorited={favs.has(match.opportunity.id)}
                  onToggleFavorite={handleToggleFav}
                  interaction={interactions.get(match.opportunity.id)}
                  onTrackInteraction={(oppId, type) => {
                    const current = interactions.get(oppId);
                    if (current === type) {
                      removeInteraction(oppId).catch(() => {});
                      setInteractions((prev) => { const n = new Map(prev); n.delete(oppId); return n; });
                    } else {
                      trackInteraction(oppId, type).catch(() => {});
                      setInteractions((prev) => new Map(prev).set(oppId, type));
                    }
                  }}
                />
              ))}

              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 pt-4">
                  <button
                    type="button"
                    disabled={page <= 1}
                    onClick={() => { setPage(p => p - 1); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
                    className="px-4 py-2 text-sm font-medium border border-gray-200 rounded-xl hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    Previous
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
                    Next
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
    </div>
  );
}

const MemoizedMatchCard = memo(MatchCard, (prev, next) => {
  return (
    prev.match.opportunity.id === next.match.opportunity.id &&
    prev.match.final_score === next.match.final_score &&
    prev.isFavorited === next.isFavorited &&
    prev.interaction === next.interaction &&
    prev.profile === next.profile
  );
});
MemoizedMatchCard.displayName = 'MemoizedMatchCard';

function EmptyState({
  hasFilters,
  tab,
  onClearFilters,
}: {
  hasFilters: boolean;
  tab: Tab;
  onClearFilters: () => void;
}) {
  if (hasFilters) {
    return (
      <div className="text-center py-16 space-y-3">
        <p className="text-gray-500 text-lg">No matches with these filters.</p>
        <p className="text-gray-400 text-sm">Try broadening your search or removing some filters.</p>
        <button
          type="button"
          onClick={onClearFilters}
          className="mt-2 px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 rounded-xl hover:bg-blue-100 transition-colors"
        >
          Clear all filters
        </button>
      </div>
    );
  }

  if (tab === 'starred') {
    return (
      <div className="text-center py-16 space-y-2">
        <Star className="w-8 h-8 text-gray-300 mx-auto" />
        <p className="text-gray-500 text-lg">No starred opportunities yet.</p>
        <p className="text-gray-400 text-sm">Click the star icon on any match to save it here.</p>
      </div>
    );
  }

  return (
    <div className="text-center py-16">
      <p className="text-gray-400 text-lg">No matches in this category.</p>
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
