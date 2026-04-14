'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowLeft,
  Filter,
  Zap,
  Target,
  TrendingUp,
  AlertCircle,
  Search,
  Star,
} from 'lucide-react';
import MatchCard from '@/components/MatchCard';
import ColdEmailModal from '@/components/ColdEmailModal';
import { getMatches } from '@/lib/api';
import { getFavorites, toggleFavorite, getInteractions, trackInteraction, removeInteraction } from '@/lib/supabase';
import type { InteractionType } from '@/lib/supabase';
import type { ProfileData, MatchResult, MatchesResponse, MatchBucket, SkillWithLevel } from '@/lib/types';

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

export default function ResultsPage() {
  const router = useRouter();

  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [filters, setFilters] = useState<Filters>({ paid: '', intl: '', source: '', onCampus: '' });
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

  const handleToggleFav = useCallback(async (oppId: string) => {
    const wasFaved = favs.has(oppId);
    const nowFaved = await toggleFavorite(oppId, wasFaved);
    setFavs(prev => {
      const next = new Set(prev);
      nowFaved ? next.add(oppId) : next.delete(oppId);
      return next;
    });
  }, [favs]);

  // Load profile from localStorage
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
    } catch {
      router.replace('/');
    }
  }, [router]);

  // Fetch matches
  useEffect(() => {
    if (!profile) return;
    let cancelled = false;

    async function fetchMatches() {
      setLoading(true);
      setError(null);
      try {
        const result = await getMatches(profile!);
        if (!cancelled) setData(result);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load matches');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchMatches();
    return () => {
      cancelled = true;
    };
  }, [profile]);

  // Filter by tab (hide low_fit from "all")
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
          : m.opportunity.eligibility.international_friendly !== 'no',
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

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      results = results.filter((m) =>
        m.opportunity.title.toLowerCase().includes(q) ||
        m.opportunity.organization?.toLowerCase().includes(q) ||
        m.opportunity.keywords?.some((k) => k.toLowerCase().includes(q))
      );
    }
    return results;
  }, [data, activeTab, searchQuery, filters, favs]);

  // Paginate
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page],
  );

  // Reset page when tab changes
  useEffect(() => { setPage(1); }, [activeTab, searchQuery, filters]);

  // Bucket counts — use the pre-computed counts from the API response
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

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      {/* Back link */}
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
              <span
                className={`text-[11px] font-semibold tabular-nums ${
                  activeTab === key ? 'text-gray-400' : 'text-gray-400'
                }`}
              >
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
              className="w-full pl-11 pr-4 py-3 bg-white rounded-xl border-0 shadow-[0_1px_4px_rgba(0,0,0,0.04)] text-[14px] text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all duration-300"
            />
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
              options={[['', 'International status'], ['yes', 'Intl friendly'], ['no', 'Incl. US-only']]}
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
            {Object.values(filters).some(Boolean) && (
              <button
                type="button"
                onClick={() => setFilters({ paid: '', intl: '', source: '', onCampus: '' })}
                className="px-3 py-1.5 text-[12px] font-medium text-red-500 hover:text-red-700 transition-colors"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="space-y-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {/* Error state */}
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

      {/* Results */}
      {!loading && !error && data && (
        <div className="space-y-6">
          {filtered.length === 0 ? (
            <div className="text-center py-16">
              <p className="text-gray-400 text-lg">
                No matches in this category.
              </p>
            </div>
          ) : (
            <>
              {paginated.map((match: MatchResult) => (
                <MatchCard
                  key={match.opportunity.id}
                  match={match}
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

      {/* Loading bar at top while fetching */}
      {loading && (
        <div className="fixed top-12 left-0 right-0 z-40">
          <div className="h-[2px] bg-black/[0.03]">
            <div className="h-full bg-blue-500 rounded-r-full animate-pulse" style={{ width: '60%' }} />
          </div>
        </div>
      )}

      {/* Cold Email Modal */}
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
