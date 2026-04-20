'use client';

import { Suspense, useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, AlertTriangle, Database, RefreshCw } from 'lucide-react';
import { useT } from '@/i18n/client';

interface SourceRow {
  source: string;
  total: number;
  empty_majors?: number;
  empty_keywords?: number;
  empty_description?: number;
  short_description?: number;
  missing_deadline?: number;
  rolling_deadline?: number;
  missing_skills?: number;
  past_deadline?: number;
  stale_verify?: number;
  flagged_inactive?: number;
}

interface WorstField {
  id: string;
  title: string;
  source: string;
  missing_count: number;
  url: string;
}

interface AdminResponse {
  total: number;
  global: Record<string, number>;
  sources: SourceRow[];
  worst_fields: WorstField[];
  generated_at: string;
}

interface HistoryEntry {
  t: string;
  total: number;
  empty_majors?: number;
  empty_keywords?: number;
  missing_deadline?: number;
  rolling_deadline?: number;
  flagged_inactive?: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

export default function AdminPage() {
  return (
    <Suspense fallback={null}>
      <AdminInner />
    </Suspense>
  );
}

function AdminInner() {
  const { t } = useT();
  const searchParams = useSearchParams();
  const queryToken = searchParams.get('token');
  const [token, setToken] = useState<string>(queryToken ?? '');
  const [data, setData] = useState<AdminResponse | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (tok: string) => {
    if (!tok) return;
    setLoading(true);
    setError(null);
    try {
      const [mainRes, histRes] = await Promise.all([
        fetch(`${API_BASE}/admin/data-quality?token=${encodeURIComponent(tok)}`),
        fetch(`${API_BASE}/admin/data-quality/history?token=${encodeURIComponent(tok)}&limit=30`),
      ]);
      if (mainRes.status === 401) {
        setError('Invalid admin token');
        setData(null);
      } else if (mainRes.status === 503) {
        setError('Admin endpoints disabled — ADMIN_TOKEN not set on backend');
        setData(null);
      } else if (!mainRes.ok) {
        setError(`API ${mainRes.status}`);
        setData(null);
      } else {
        setData(await mainRes.json() as AdminResponse);
        if (histRes.ok) {
          const h = await histRes.json() as { history: HistoryEntry[] };
          setHistory(h.history ?? []);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (queryToken) {
      setToken(queryToken);
      fetchData(queryToken);
    }
  }, [queryToken, fetchData]);

  return (
    <div className="min-h-screen bg-gradient-to-b from-white to-gray-50">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          {t('admin.back')}
        </Link>

        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 tracking-tight flex items-center gap-3">
              <Database className="w-7 h-7 text-blue-600" />
              {t('admin.title')}
            </h1>
            <p className="mt-2 text-[14px] text-gray-500">
              {t('admin.subtitle')}
            </p>
          </div>
          {data && (
            <button
              type="button"
              onClick={() => fetchData(token)}
              disabled={loading}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-gray-200 bg-white text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              {t('admin.refresh')}
            </button>
          )}
        </div>

        {!data && !error && !loading && (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <p className="text-[14px] text-gray-600 mb-3">{t('admin.unauthorizedHint')}</p>
            <form
              onSubmit={(e) => { e.preventDefault(); fetchData(token); }}
              className="flex gap-2"
            >
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Admin token"
                className="flex-1 px-3.5 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none"
                autoFocus
              />
              <button
                type="submit"
                disabled={!token || loading}
                className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? '...' : 'Load'}
              </button>
            </form>
          </div>
        )}

        {loading && !data && (
          <p className="text-sm text-gray-500">{t('admin.loading')}</p>
        )}

        {error && (
          <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
            <AlertTriangle className="w-4 h-4 text-red-600 mt-0.5 shrink-0" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {data && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
              <StatCard label={t('admin.totalRecords')} value={data.total} color="blue" />
              <StatCard
                label={t('admin.emptyMajors')}
                value={data.global.empty_majors || 0}
                color={(data.global.empty_majors || 0) > 50 ? 'amber' : 'green'}
                pct={data.total ? ((data.global.empty_majors || 0) / data.total * 100) : 0}
              />
              <StatCard
                label={t('admin.emptyKeywords')}
                value={data.global.empty_keywords || 0}
                color={(data.global.empty_keywords || 0) > 50 ? 'amber' : 'green'}
                pct={data.total ? ((data.global.empty_keywords || 0) / data.total * 100) : 0}
              />
              <StatCard
                label={t('admin.rollingDeadline')}
                value={data.global.rolling_deadline || 0}
                color="green"
                pct={data.total ? ((data.global.rolling_deadline || 0) / data.total * 100) : 0}
                hint="legitimate"
              />
              <StatCard
                label={t('admin.missingDeadline')}
                value={data.global.missing_deadline || 0}
                color={(data.global.missing_deadline || 0) > 100 ? 'amber' : 'gray'}
                pct={data.total ? ((data.global.missing_deadline || 0) / data.total * 100) : 0}
              />
              <StatCard label={t('admin.pastDeadline')} value={data.global.past_deadline || 0} color="gray" />
              <StatCard label={t('admin.flaggedInactive')} value={data.global.flagged_inactive || 0} color="gray" />
              <StatCard label={t('admin.shortDescription')} value={data.global.short_description || 0} color="gray" />
            </div>

            {history.length > 1 && (
              <section className="mb-10">
                <h2 className="text-[15px] font-semibold text-gray-900 mb-3">{t('admin.trendTitle')}</h2>
                <TrendChart history={history} />
              </section>
            )}

            {history.length <= 1 && (
              <p className="mb-8 text-[12px] text-gray-400 italic">{t('admin.trendEmpty')}</p>
            )}

            <section className="mb-10">
              <h2 className="text-[15px] font-semibold text-gray-900 mb-3">
                {t('admin.bySource')}
              </h2>
              <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden overflow-x-auto">
                <table className="w-full text-sm min-w-[700px]">
                  <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
                    <tr>
                      <th className="px-4 py-2.5 text-left">Source</th>
                      <th className="px-4 py-2.5 text-right">Total</th>
                      <th className="px-4 py-2.5 text-right">Empty majors</th>
                      <th className="px-4 py-2.5 text-right">Empty kw</th>
                      <th className="px-4 py-2.5 text-right">Rolling</th>
                      <th className="px-4 py-2.5 text-right">Missing deadline</th>
                      <th className="px-4 py-2.5 text-right">Past</th>
                      <th className="px-4 py-2.5 text-right">Inactive</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {data.sources.map((row) => (
                      <tr key={row.source} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-900">{row.source}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-600">{row.total}</td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          <Cell v={row.empty_majors || 0} total={row.total} />
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          <Cell v={row.empty_keywords || 0} total={row.total} />
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-emerald-600">
                          {row.rolling_deadline || 0}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          <Cell v={row.missing_deadline || 0} total={row.total} mute />
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-500">
                          {row.past_deadline || 0}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-500">
                          {row.flagged_inactive || 0}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section>
              <h2 className="text-[15px] font-semibold text-gray-900 mb-3">
                {t('admin.worstFields')}
              </h2>
              <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
                    <tr>
                      <th className="px-4 py-2.5 text-left">Title</th>
                      <th className="px-4 py-2.5 text-left">Source</th>
                      <th className="px-4 py-2.5 text-right">Missing</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {data.worst_fields.map((row) => (
                      <tr key={row.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-gray-900 truncate max-w-md">
                          {row.url ? (
                            <a href={row.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                              {row.title || row.id}
                            </a>
                          ) : (row.title || row.id)}
                        </td>
                        <td className="px-4 py-3 text-gray-500">{row.source}</td>
                        <td className="px-4 py-3 text-right tabular-nums font-semibold text-amber-600">
                          {row.missing_count}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <p className="mt-8 text-[11px] text-gray-400 text-right">
              Generated {new Date(data.generated_at).toLocaleString()}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label, value, color, pct, hint,
}: {
  label: string; value: number; color: 'blue' | 'amber' | 'green' | 'gray';
  pct?: number; hint?: string;
}) {
  const colors = {
    blue: 'text-blue-700 bg-blue-50',
    amber: 'text-amber-700 bg-amber-50',
    green: 'text-emerald-700 bg-emerald-50',
    gray: 'text-gray-700 bg-gray-50',
  }[color];
  return (
    <div className={`rounded-2xl p-4 ${colors}`}>
      <p className="text-[11px] font-semibold uppercase tracking-wider opacity-70">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">{value.toLocaleString()}</p>
      {pct !== undefined && pct > 0 && (
        <p className="text-[11px] opacity-70">{pct.toFixed(1)}%</p>
      )}
      {hint && (
        <p className="text-[10px] opacity-60 mt-0.5 italic">{hint}</p>
      )}
    </div>
  );
}

function Cell({ v, total, mute }: { v: number; total: number; mute?: boolean }) {
  if (v === 0) return <span className="text-gray-300">0</span>;
  const pct = total ? (v / total * 100) : 0;
  const cls = mute ? 'text-gray-500' : pct > 30 ? 'text-amber-700 font-semibold' : 'text-gray-700';
  return <span className={cls}>{v} <span className="text-[10px] opacity-60">({pct.toFixed(0)}%)</span></span>;
}

function TrendChart({ history }: { history: HistoryEntry[] }) {
  if (history.length < 2) return null;

  const series = [
    { key: 'empty_majors' as const, label: 'Empty majors', color: '#f59e0b' },
    { key: 'empty_keywords' as const, label: 'Empty keywords', color: '#8b5cf6' },
    { key: 'missing_deadline' as const, label: 'Missing deadline', color: '#6b7280' },
    { key: 'flagged_inactive' as const, label: 'Flagged inactive', color: '#94a3b8' },
  ];

  const W = 720;
  const H = 160;
  const PAD = 24;

  const xMax = history.length - 1;
  const yValues = series.flatMap(s => history.map(h => h[s.key] ?? 0));
  const yMax = Math.max(1, ...yValues);

  const x = (i: number) => PAD + (i / Math.max(1, xMax)) * (W - 2 * PAD);
  const y = (v: number) => H - PAD - (v / yMax) * (H - 2 * PAD);

  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#e5e7eb" />
        {series.map(s => {
          const points = history
            .map((h, i) => `${x(i)},${y(h[s.key] ?? 0)}`)
            .join(' ');
          return (
            <g key={s.key}>
              <polyline fill="none" stroke={s.color} strokeWidth={2} points={points} />
              {history.map((h, i) => (
                <circle
                  key={i}
                  cx={x(i)}
                  cy={y(h[s.key] ?? 0)}
                  r={2.5}
                  fill={s.color}
                />
              ))}
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap gap-3 mt-3 text-[11px] text-gray-600">
        {series.map(s => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
