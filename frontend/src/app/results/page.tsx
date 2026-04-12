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
} from 'lucide-react';
import MatchCard from '@/components/MatchCard';
import ColdEmailModal from '@/components/ColdEmailModal';
import { getMatches } from '@/lib/api';
import type { ProfileData, MatchResult, MatchesResponse, MatchBucket } from '@/lib/types';

type Tab = 'all' | 'high_priority' | 'good_match' | 'reach';

const TABS: { key: Tab; label: string; icon: React.ElementType; color: string }[] = [
  { key: 'all', label: 'All', icon: Filter, color: 'text-gray-600' },
  { key: 'high_priority', label: 'High Priority', icon: Zap, color: 'text-emerald-600' },
  { key: 'good_match', label: 'Good Match', icon: Target, color: 'text-blue-600' },
  { key: 'reach', label: 'Reach', icon: TrendingUp, color: 'text-amber-600' },
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
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  // Cold email modal state
  const [emailModal, setEmailModal] = useState<{
    open: boolean;
    opportunityId: string;
    opportunityTitle: string;
  }>({ open: false, opportunityId: '', opportunityTitle: '' });

  // Load profile from localStorage
  useEffect(() => {
    const raw = localStorage.getItem('ofe_profile');
    if (!raw) {
      router.replace('/');
      return;
    }
    try {
      const parsed = JSON.parse(raw) as ProfileData;
      setProfile(parsed);
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
    if (activeTab === 'all') return data.results.filter((m) => m.bucket !== 'low_fit');
    return data.results.filter((m) => m.bucket === activeTab);
  }, [data, activeTab]);

  // Paginate
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page],
  );

  // Reset page when tab changes
  useEffect(() => { setPage(1); }, [activeTab]);

  // Bucket counts — use the pre-computed counts from the API response
  const counts = useMemo(() => {
    if (!data) return { all: 0, high_priority: 0, good_match: 0, reach: 0 };
    const withoutLowFit = data.total - data.low_fit;
    return {
      all: withoutLowFit,
      high_priority: data.high_priority,
      good_match: data.good_match,
      reach: data.reach,
    };
  }, [data]);

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

      {/* Page header */}
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight">
          Your Matches
        </h1>
        <p className="mt-2 text-gray-500">
          {loading
            ? 'Analyzing your profile against available opportunities...'
            : data
              ? `Found ${data.total} opportunities ranked for you`
              : 'Loading...'}
        </p>
      </div>

      {/* Summary bar */}
      {!loading && data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
          <SummaryCard
            label="Total"
            count={counts.all}
            color="bg-gray-50 text-gray-900"
            borderColor="border-gray-200"
          />
          <SummaryCard
            label="High Priority"
            count={counts.high_priority}
            color="bg-emerald-50 text-emerald-700"
            borderColor="border-emerald-200"
          />
          <SummaryCard
            label="Good Match"
            count={counts.good_match}
            color="bg-blue-50 text-blue-700"
            borderColor="border-blue-200"
          />
          <SummaryCard
            label="Reach"
            count={counts.reach}
            color="bg-amber-50 text-amber-700"
            borderColor="border-amber-200"
          />
        </div>
      )}

      {/* Tabs */}
      {!loading && data && (
        <div className="flex items-center gap-1 mb-8 overflow-x-auto pb-1">
          {TABS.map(({ key, label, icon: Icon, color }) => (
            <button
              key={key}
              type="button"
              onClick={() => setActiveTab(key)}
              className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium whitespace-nowrap transition-all
                ${
                  activeTab === key
                    ? 'bg-white border border-gray-200 shadow-sm text-gray-900'
                    : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
                }`}
            >
              <Icon className={`w-4 h-4 ${activeTab === key ? color : ''}`} />
              {label}
              <span
                className={`ml-1 text-xs font-bold tabular-nums ${
                  activeTab === key ? 'text-gray-500' : 'text-gray-400'
                }`}
              >
                {counts[key]}
              </span>
            </button>
          ))}
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
        <div className="fixed top-16 left-0 right-0 z-40">
          <div className="h-1 bg-blue-100">
            <div className="h-full bg-gradient-to-r from-blue-600 to-blue-400 rounded-r-full animate-pulse" style={{ width: '60%' }} />
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

// ── Summary Card mini-component ──────────────────────────────────────
function SummaryCard({
  label,
  count,
  color,
  borderColor,
}: {
  label: string;
  count: number;
  color: string;
  borderColor: string;
}) {
  return (
    <div
      className={`rounded-2xl border ${borderColor} ${color} px-5 py-4`}
    >
      <p className="text-2xl font-extrabold tabular-nums">{count}</p>
      <p className="text-xs font-medium mt-1 opacity-70">{label}</p>
    </div>
  );
}
