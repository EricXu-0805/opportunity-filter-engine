'use client';

import { useState, useEffect, useMemo } from 'react';
import {
  Loader2,
  AlertCircle,
  Send,
  MessageSquare,
  XCircle,
  Users,
  Star,
  BarChart3,
  ArrowRight,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { getStats } from '@/lib/api';
import { getOpportunitiesByIds } from '@/lib/api';
import { getFavorites, getInteractions } from '@/lib/supabase';
import type { InteractionType } from '@/lib/supabase';
import type { StatsResponse } from '@/lib/types';

const STATUS_CONFIG: Record<InteractionType, { label: string; icon: React.ElementType; color: string; bg: string }> = {
  applied: { label: 'Applied', icon: Send, color: 'text-blue-600', bg: 'bg-blue-50' },
  replied: { label: 'Replied', icon: MessageSquare, color: 'text-emerald-600', bg: 'bg-emerald-50' },
  rejected: { label: 'Rejected', icon: XCircle, color: 'text-red-500', bg: 'bg-red-50' },
  interviewing: { label: 'Interviewing', icon: Users, color: 'text-violet-600', bg: 'bg-violet-50' },
};

interface TrackedOpp {
  id: string;
  title: string;
  organization?: string;
  opportunity_type?: string;
  status: InteractionType;
}

export default function DashboardPage() {
  const router = useRouter();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [tracked, setTracked] = useState<TrackedOpp[]>([]);
  const [favCount, setFavCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [statsData, interactions, favSet] = await Promise.all([
          getStats(),
          getInteractions(),
          getFavorites(),
        ]);
        if (cancelled) return;
        setStats(statsData);
        setFavCount(favSet.size);

        if (interactions.size > 0) {
          const ids = Array.from(interactions.keys());
          const opps = await getOpportunitiesByIds(ids);
          if (cancelled) return;
          setTracked(
            opps.map((o) => ({
              id: o.id as string,
              title: o.title as string,
              organization: o.organization as string | undefined,
              opportunity_type: o.opportunity_type as string | undefined,
              status: interactions.get(o.id as string)!,
            })),
          );
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { applied: 0, replied: 0, rejected: 0, interviewing: 0 };
    for (const t of tracked) counts[t.status] = (counts[t.status] || 0) + 1;
    return counts;
  }, [tracked]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
        <p className="text-[13px] text-gray-400">Loading dashboard...</p>
      </div>
    );
  }

  if (error || !stats) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <AlertCircle className="w-8 h-8 text-red-400" />
        <p className="text-gray-600 font-medium">{error || 'No data'}</p>
        <button type="button" onClick={() => window.location.reload()} className="text-[13px] text-blue-600 hover:underline">
          Retry
        </button>
      </div>
    );
  }

  const typeEntries = Object.entries(stats.by_type).sort(([, a], [, b]) => b - a);
  const maxType = Math.max(...typeEntries.map(([, v]) => v), 1);

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
      <div className="mb-12">
        <h1 className="text-4xl font-bold text-gray-900 tracking-tight">Dashboard</h1>
        <p className="mt-2 text-[15px] text-gray-400">Your activity and opportunity database overview.</p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-12">
        <StatCard value={statusCounts.applied} label="Applied" color="text-blue-600" />
        <StatCard value={statusCounts.replied} label="Replied" color="text-emerald-600" />
        <StatCard value={statusCounts.interviewing} label="Interviewing" color="text-violet-600" />
        <StatCard value={favCount} label="Saved" color="text-amber-500" />
      </div>

      {tracked.length > 0 && (
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] mb-12 overflow-hidden">
          <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-100">
            <BarChart3 className="w-4 h-4 text-gray-400" />
            <h2 className="text-[15px] font-semibold text-gray-900">Application Tracker</h2>
            <span className="text-[12px] text-gray-400 ml-auto">{tracked.length} tracked</span>
          </div>
          <div className="divide-y divide-gray-50">
            {tracked.map((t) => {
              const cfg = STATUS_CONFIG[t.status];
              const Icon = cfg.icon;
              return (
                <div key={t.id} className="flex items-center gap-4 px-6 py-3.5 hover:bg-gray-50/50 transition-colors">
                  <div className={`w-8 h-8 rounded-lg ${cfg.bg} flex items-center justify-center shrink-0`}>
                    <Icon className={`w-4 h-4 ${cfg.color}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[14px] font-medium text-gray-900 truncate">{t.title}</p>
                    <p className="text-[12px] text-gray-400 truncate">
                      {t.organization}{t.opportunity_type ? ` · ${t.opportunity_type}` : ''}
                    </p>
                  </div>
                  <span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold ${cfg.bg} ${cfg.color}`}>
                    {cfg.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {tracked.length === 0 && (
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 mb-12 text-center">
          <BarChart3 className="w-8 h-8 text-gray-200 mx-auto mb-3" />
          <p className="text-[15px] text-gray-500 mb-1">No applications tracked yet.</p>
          <p className="text-[13px] text-gray-400 mb-4">Mark opportunities as Applied, Replied, or Interviewing from the results page.</p>
          <button
            type="button"
            onClick={() => router.push('/')}
            className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-blue-600 bg-blue-50 rounded-xl hover:bg-blue-100 transition-colors"
          >
            Find Matches <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-10">
        <StatCard value={stats.total} label="Total Opps" />
        <StatCard value={stats.active} label="Active" color="text-emerald-600" />
        <StatCard value={stats.paid_total} label="Paid" color="text-blue-600" />
        <StatCard value={stats.international_friendly_total} label="Intl Friendly" color="text-indigo-600" />
      </div>

      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8">
        <h2 className="text-[15px] font-semibold text-gray-900 mb-6">By Type</h2>
        <div className="space-y-3">
          {typeEntries.map(([type, count]) => {
            const pct = (count / maxType) * 100;
            return (
              <div key={type} className="flex items-center gap-4">
                <span className="text-[13px] text-gray-500 w-36 truncate shrink-0">{type}</span>
                <div className="flex-1 h-2 bg-black/[0.04] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-400 rounded-full transition-all duration-700"
                    style={{ width: `${Math.max(pct, 2)}%` }}
                  />
                </div>
                <span className="text-[13px] font-semibold text-gray-400 tabular-nums w-8 text-right">{count}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function StatCard({ value, label, color }: { value: number; label: string; color?: string }) {
  return (
    <div className="bg-white rounded-2xl shadow-[0_1px_6px_rgba(0,0,0,0.04)] px-5 py-5">
      <p className={`text-3xl font-bold tabular-nums tracking-tight ${color || 'text-gray-900'}`}>{value}</p>
      <p className="text-[11px] font-medium text-gray-400 mt-1 uppercase tracking-wider">{label}</p>
    </div>
  );
}
