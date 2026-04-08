'use client';

import { useState, useEffect, useMemo } from 'react';
import {
  BarChart3,
  Database,
  DollarSign,
  Globe,
  Activity,
  Loader2,
  AlertCircle,
  ExternalLink,
} from 'lucide-react';
import Card from '@/components/Card';
import { getStats } from '@/lib/api';
import type { StatsResponse } from '@/lib/types';

function MetricCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: number;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <Card padding="p-6">
      <div className="flex items-center justify-between mb-4">
        <div className={`w-10 h-10 rounded-xl ${color} flex items-center justify-center`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
      <p className="text-3xl font-extrabold text-gray-900 tabular-nums">{value}</p>
      <p className="text-sm text-gray-500 mt-1">{label}</p>
    </Card>
  );
}

function BarChartRow({
  label,
  value,
  max,
  color,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-4">
      <span className="text-sm text-gray-600 w-40 truncate shrink-0">{label}</span>
      <div className="flex-1 h-7 bg-gray-100 rounded-lg overflow-hidden relative">
        <div
          className={`h-full ${color} rounded-lg transition-all duration-500 ease-out`}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
        <span className="absolute inset-y-0 right-2 flex items-center text-xs font-bold text-gray-500 tabular-nums">
          {value}
        </span>
      </div>
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
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load dashboard');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchStats();
    return () => {
      cancelled = true;
    };
  }, []);

  // Derive sources list from by_source keys
  const sourcesList = useMemo(() => {
    if (!stats) return [];
    return Object.keys(stats.by_source);
  }, [stats]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
        <p className="text-sm text-gray-500">Loading dashboard data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
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
    );
  }

  if (!stats) return null;

  const typeEntries = Object.entries(stats.by_type).sort(([, a], [, b]) => b - a);
  const sourceEntries = Object.entries(stats.by_source).sort(([, a], [, b]) => b - a);
  const maxType = Math.max(...typeEntries.map(([, v]) => v), 1);
  const maxSource = Math.max(...sourceEntries.map(([, v]) => v), 1);

  const TYPE_COLORS = [
    'bg-blue-500',
    'bg-emerald-500',
    'bg-amber-500',
    'bg-indigo-500',
    'bg-rose-500',
    'bg-teal-500',
    'bg-orange-500',
    'bg-purple-500',
  ];
  const SOURCE_COLORS = [
    'bg-gradient-to-r from-blue-500 to-blue-400',
    'bg-gradient-to-r from-emerald-500 to-emerald-400',
    'bg-gradient-to-r from-amber-500 to-amber-400',
    'bg-gradient-to-r from-indigo-500 to-indigo-400',
    'bg-gradient-to-r from-rose-500 to-rose-400',
    'bg-gradient-to-r from-teal-500 to-teal-400',
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      {/* Header */}
      <div className="mb-10">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 text-blue-700 text-xs font-semibold mb-4">
          <Activity className="w-3.5 h-3.5" />
          Live Data
        </div>
        <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight">
          Opportunity Dashboard
        </h1>
        <p className="mt-2 text-gray-500">
          Overview of all research and internship opportunities in our database.
        </p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
        <MetricCard
          label="Total Opportunities"
          value={stats.total}
          icon={Database}
          color="bg-blue-50 text-blue-600"
        />
        <MetricCard
          label="Active"
          value={stats.active}
          icon={Activity}
          color="bg-emerald-50 text-emerald-600"
        />
        <MetricCard
          label="Paid Positions"
          value={stats.paid_total}
          icon={DollarSign}
          color="bg-amber-50 text-amber-600"
        />
        <MetricCard
          label="Intl Friendly"
          value={stats.international_friendly_total}
          icon={Globe}
          color="bg-indigo-50 text-indigo-600"
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-10">
        {/* By Type */}
        <Card>
          <div className="flex items-center gap-3 mb-6">
            <BarChart3 className="w-5 h-5 text-blue-600" />
            <h2 className="text-lg font-bold text-gray-900">By Type</h2>
          </div>
          <div className="space-y-3">
            {typeEntries.map(([type, count], i) => (
              <BarChartRow
                key={type}
                label={type}
                value={count}
                max={maxType}
                color={TYPE_COLORS[i % TYPE_COLORS.length]}
              />
            ))}
          </div>
        </Card>

        {/* By Source */}
        <Card>
          <div className="flex items-center gap-3 mb-6">
            <BarChart3 className="w-5 h-5 text-emerald-600" />
            <h2 className="text-lg font-bold text-gray-900">By Source</h2>
          </div>
          <div className="space-y-3">
            {sourceEntries.map(([source, count], i) => (
              <BarChartRow
                key={source}
                label={source}
                value={count}
                max={maxSource}
                color={SOURCE_COLORS[i % SOURCE_COLORS.length]}
              />
            ))}
          </div>
        </Card>
      </div>

      {/* Sources list */}
      {sourcesList.length > 0 && (
        <Card>
          <div className="flex items-center gap-3 mb-6">
            <ExternalLink className="w-5 h-5 text-gray-500" />
            <h2 className="text-lg font-bold text-gray-900">Data Sources</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {sourcesList.map((source) => (
              <span
                key={source}
                className="inline-flex items-center px-3 py-1.5 rounded-lg bg-gray-50 text-sm text-gray-600 border border-gray-200"
              >
                {source}
              </span>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
