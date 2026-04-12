'use client';

import { useState, useEffect, useMemo } from 'react';
import { Loader2, AlertCircle } from 'lucide-react';
import { getStats } from '@/lib/api';
import type { StatsResponse } from '@/lib/types';

function StatBlock({ value, label, accent }: { value: number; label: string; accent?: string }) {
  const color = accent || 'text-gray-900';
  return (
    <div className="text-center">
      <p className={`text-4xl font-bold tabular-nums tracking-tight ${color}`}>{value}</p>
      <p className="text-[11px] font-medium text-gray-400 mt-1 uppercase tracking-wider">{label}</p>
    </div>
  );
}

function BarRow({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-4">
      <span className="text-[13px] text-gray-500 w-36 truncate shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-black/[0.04] rounded-full overflow-hidden">
        <div
          className={`h-full ${color} rounded-full transition-all duration-700 ease-out`}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>
      <span className="text-[13px] font-semibold text-gray-400 tabular-nums w-8 text-right">{value}</span>
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function fetchStats() {
      try {
        const data = await getStats();
        if (!cancelled) setStats(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchStats();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
        <p className="text-[13px] text-gray-400">Loading...</p>
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
  const sourceEntries = Object.entries(stats.by_source).sort(([, a], [, b]) => b - a);
  const maxType = Math.max(...typeEntries.map(([, v]) => v), 1);
  const maxSource = Math.max(...sourceEntries.map(([, v]) => v), 1);

  const BAR_COLORS = ['bg-blue-400', 'bg-emerald-400', 'bg-amber-400', 'bg-indigo-400', 'bg-rose-400', 'bg-teal-400'];

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
      <div className="text-center mb-16">
        <h1 className="text-4xl font-bold text-gray-900 tracking-tight">Dashboard</h1>
        <p className="mt-2 text-[15px] text-gray-400">Live overview of all opportunities in our database.</p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-8 mb-16">
        <StatBlock value={stats.total} label="Total" />
        <StatBlock value={stats.active} label="Active" accent="text-emerald-600" />
        <StatBlock value={stats.paid_total} label="Paid" accent="text-blue-600" />
        <StatBlock value={stats.international_friendly_total} label="Intl Friendly" accent="text-indigo-600" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8">
          <h2 className="text-[15px] font-semibold text-gray-900 mb-6">By Type</h2>
          <div className="space-y-4">
            {typeEntries.map(([type, count], i) => (
              <BarRow key={type} label={type} value={count} max={maxType} color={BAR_COLORS[i % BAR_COLORS.length]} />
            ))}
          </div>
        </div>

        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8">
          <h2 className="text-[15px] font-semibold text-gray-900 mb-6">By Source</h2>
          <div className="space-y-4">
            {sourceEntries.map(([source, count], i) => (
              <BarRow key={source} label={source} value={count} max={maxSource} color={BAR_COLORS[i % BAR_COLORS.length]} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
