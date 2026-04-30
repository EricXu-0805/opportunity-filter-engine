'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Database,
  Lock,
  RefreshCw,
  X,
  Zap,
} from 'lucide-react';
import { useT } from '@/i18n/client';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';
const SESSION_KEY = 'ofe_admin_token';

type FieldKey = 'empty_majors' | 'empty_keywords' | 'empty_description' | 'missing_deadline' | 'missing_skills';

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
  missing_fields?: FieldKey[];
  url: string;
}

interface AdminResponse {
  total: number;
  global: Record<string, number>;
  sources: SourceRow[];
  worst_fields: WorstField[];
  generated_at: string;
  data_updated_at?: string | null;
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

interface CollectorRow {
  source: string;
  status: string;
  fetched?: number;
  new?: number;
  updated?: number;
  error?: string;
  deep?: boolean;
}

interface CollectorStatus {
  sources: CollectorRow[];
  last_run_at?: string | null;
  duration_seconds?: number;
  total_in_file?: number;
}

interface HealthAlert {
  level: 'alert' | 'warn';
  kind: string;
  message: string;
  metric?: string;
  current?: number;
  baseline?: number;
  delta?: number;
  pct_jump?: number;
}

interface HealthResponse {
  ok: boolean;
  alerts: HealthAlert[];
  checked_at: string;
}

async function adminFetch<T>(path: string, token: string, init?: RequestInit): Promise<{ data?: T; status: number; error?: string }> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.headers || {}),
        'X-Admin-Token': token,
      },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      return { status: res.status, error: text || `HTTP ${res.status}` };
    }
    return { status: res.status, data: (await res.json()) as T };
  } catch (e) {
    return { status: 0, error: e instanceof Error ? e.message : String(e) };
  }
}

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

  const [token, setToken] = useState<string>('');
  const [tokenInput, setTokenInput] = useState<string>('');
  const [data, setData] = useState<AdminResponse | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [collectorStatus, setCollectorStatus] = useState<CollectorStatus | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeFieldFilter, setActiveFieldFilter] = useState<FieldKey | null>(null);
  const [triggerStatus, setTriggerStatus] = useState<{ kind: 'idle' | 'busy' | 'ok' | 'err'; message?: string }>({ kind: 'idle' });

  const fetchAll = useCallback(async (tok: string) => {
    if (!tok) return;
    setLoading(true);
    setError(null);
    try {
      const [main, hist, healthR, collector] = await Promise.all([
        adminFetch<AdminResponse>(`/admin/data-quality`, tok),
        adminFetch<{ history: HistoryEntry[] }>(`/admin/data-quality/history?limit=30`, tok),
        adminFetch<HealthResponse>(`/admin/health-check`, tok),
        adminFetch<CollectorStatus>(`/admin/collector-status`, tok),
      ]);
      if (main.status === 401) {
        setError('Invalid admin token');
        sessionStorage.removeItem(SESSION_KEY);
        setToken('');
        setData(null);
        return;
      }
      if (main.status === 503) {
        setError('Admin endpoints disabled — ADMIN_TOKEN not set on backend');
        setData(null);
        return;
      }
      if (main.error) {
        setError(main.error);
        setData(null);
        return;
      }
      setData(main.data ?? null);
      setHistory(hist.data?.history ?? []);
      setHealth(healthR.data ?? null);
      setCollectorStatus(collector.data ?? null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const queryToken = searchParams.get('token');
    let resolved: string | null = null;
    if (queryToken) {
      resolved = queryToken;
      try { sessionStorage.setItem(SESSION_KEY, queryToken); } catch { /* private mode */ }
      const url = new URL(window.location.href);
      url.searchParams.delete('token');
      window.history.replaceState(null, '', url.pathname + (url.search ? url.search : ''));
    } else {
      try { resolved = sessionStorage.getItem(SESSION_KEY); } catch { resolved = null; }
    }
    if (resolved) {
      setToken(resolved);
      setTokenInput(resolved);
      fetchAll(resolved);
    }
  }, [searchParams, fetchAll]);

  const handleSubmitToken = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (!tokenInput) return;
    try { sessionStorage.setItem(SESSION_KEY, tokenInput); } catch { /* private mode */ }
    setToken(tokenInput);
    fetchAll(tokenInput);
  }, [tokenInput, fetchAll]);

  const handleLock = useCallback(() => {
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* private mode */ }
    setToken('');
    setTokenInput('');
    setData(null);
    setHistory([]);
    setCollectorStatus(null);
    setHealth(null);
    setError(null);
  }, []);

  const handleTriggerRefresh = useCallback(async (mode: 'quick' | 'deep') => {
    if (!token) return;
    setTriggerStatus({ kind: 'busy' });
    const res = await adminFetch<{ ok: boolean }>(`/admin/trigger-refresh?mode=${mode}`, token, { method: 'POST' });
    if (res.status === 503) {
      setTriggerStatus({ kind: 'err', message: t('admin.triggerRefreshDisabled') });
      return;
    }
    if (res.error) {
      setTriggerStatus({ kind: 'err', message: res.error });
      return;
    }
    setTriggerStatus({ kind: 'ok', message: t('admin.triggerRefreshOk') });
  }, [token, t]);

  const previousSnapshot = useMemo(() => history.length >= 2 ? history[history.length - 2] : null, [history]);
  const filteredWorstFields = useMemo(() => {
    if (!data) return [];
    if (!activeFieldFilter) return data.worst_fields;
    return data.worst_fields.filter(w => w.missing_fields?.includes(activeFieldFilter));
  }, [data, activeFieldFilter]);

  if (!token) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-white to-gray-50">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
          <Link href="/" className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 mb-6">
            <ArrowLeft className="w-4 h-4" />
            {t('admin.back')}
          </Link>
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-gray-900 tracking-tight flex items-center gap-3">
              <Database className="w-7 h-7 text-blue-600" />
              {t('admin.title')}
            </h1>
            <p className="mt-2 text-[14px] text-gray-500">{t('admin.subtitle')}</p>
          </div>
          {error && (
            <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
              <AlertTriangle className="w-4 h-4 text-red-600 mt-0.5 shrink-0" />
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <p className="text-[14px] text-gray-600 mb-4">{t('admin.unauthorizedHint')}</p>
            <form onSubmit={handleSubmitToken} className="flex gap-2">
              <input
                type="password"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="Admin token"
                className="flex-1 px-3.5 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none"
                autoFocus
                autoComplete="off"
              />
              <button type="submit" disabled={!tokenInput || loading} className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
                {loading ? '...' : 'Load'}
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-white to-gray-50">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <Link href="/" className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 mb-6">
          <ArrowLeft className="w-4 h-4" />
          {t('admin.back')}
        </Link>

        <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 tracking-tight flex items-center gap-3">
              <Database className="w-7 h-7 text-blue-600" />
              {t('admin.title')}
            </h1>
            <p className="mt-2 text-[14px] text-gray-500">{t('admin.subtitle')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {data && (
              <button type="button" onClick={() => fetchAll(token)} disabled={loading} className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-gray-200 bg-white text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                {t('admin.refresh')}
              </button>
            )}
            <button type="button" onClick={handleLock} className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-gray-200 bg-white text-sm font-medium text-gray-600 hover:bg-gray-50">
              <Lock className="w-3.5 h-3.5" />
              {t('admin.lock')}
            </button>
          </div>
        </div>

        {data?.data_updated_at && <FreshnessBanner iso={data.data_updated_at} t={t} />}

        {health && health.alerts.length > 0 && <AlertList health={health} t={t} />}

        {error && (
          <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
            <AlertTriangle className="w-4 h-4 text-red-600 mt-0.5 shrink-0" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {loading && !data && (
          <p className="text-sm text-gray-500">{t('admin.loading')}</p>
        )}

        {data && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
              <StatCard label={t('admin.totalRecords')} value={data.total} color="blue" />
              <StatCard label={t('admin.emptyMajors')} value={data.global.empty_majors || 0} color={(data.global.empty_majors || 0) > 50 ? 'amber' : 'green'} pct={data.total ? ((data.global.empty_majors || 0) / data.total * 100) : 0} delta={diff('empty_majors', data, previousSnapshot)} active={activeFieldFilter === 'empty_majors'} onClick={() => setActiveFieldFilter(activeFieldFilter === 'empty_majors' ? null : 'empty_majors')} />
              <StatCard label={t('admin.emptyKeywords')} value={data.global.empty_keywords || 0} color={(data.global.empty_keywords || 0) > 50 ? 'amber' : 'green'} pct={data.total ? ((data.global.empty_keywords || 0) / data.total * 100) : 0} delta={diff('empty_keywords', data, previousSnapshot)} active={activeFieldFilter === 'empty_keywords'} onClick={() => setActiveFieldFilter(activeFieldFilter === 'empty_keywords' ? null : 'empty_keywords')} />
              <StatCard label={t('admin.rollingDeadline')} value={data.global.rolling_deadline || 0} color="green" pct={data.total ? ((data.global.rolling_deadline || 0) / data.total * 100) : 0} hint="legitimate" />
              <StatCard label={t('admin.missingDeadline')} value={data.global.missing_deadline || 0} color={(data.global.missing_deadline || 0) > 100 ? 'amber' : 'gray'} pct={data.total ? ((data.global.missing_deadline || 0) / data.total * 100) : 0} delta={diff('missing_deadline', data, previousSnapshot)} active={activeFieldFilter === 'missing_deadline'} onClick={() => setActiveFieldFilter(activeFieldFilter === 'missing_deadline' ? null : 'missing_deadline')} />
              <StatCard label={t('admin.pastDeadline')} value={data.global.past_deadline || 0} color="gray" />
              <StatCard label={t('admin.flaggedInactive')} value={data.global.flagged_inactive || 0} color="gray" delta={diff('flagged_inactive', data, previousSnapshot)} />
              <StatCard label={t('admin.shortDescription')} value={data.global.short_description || 0} color="gray" />
            </div>

            {history.length > 1 ? (
              <section className="mb-10">
                <h2 className="text-[15px] font-semibold text-gray-900 mb-3">{t('admin.trendTitle')}</h2>
                <TrendChart history={history} />
              </section>
            ) : (
              <p className="mb-8 text-[12px] text-gray-400 italic">{t('admin.trendEmpty')}</p>
            )}

            <SourceTable rows={data.sources} t={t} />

            <WorstFieldsSection
              rows={filteredWorstFields}
              activeFilter={activeFieldFilter}
              onClearFilter={() => setActiveFieldFilter(null)}
              t={t}
            />

            <CollectorStatusSection status={collectorStatus} t={t} />

            <RefreshTriggerSection
              status={triggerStatus}
              onTrigger={handleTriggerRefresh}
              t={t}
            />

            <p className="mt-8 text-[11px] text-gray-400 text-right">
              Generated {new Date(data.generated_at).toLocaleString()}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function diff(key: string, current: AdminResponse, previous: HistoryEntry | null): number | null {
  if (!previous) return null;
  const cur = current.global[key] ?? 0;
  const prev = (previous as unknown as Record<string, unknown>)[key];
  if (typeof prev !== 'number') return null;
  return cur - prev;
}

function FreshnessBanner({ iso, t }: { iso: string; t: ReturnType<typeof useT>['t'] }) {
  const ageHours = (Date.now() - new Date(iso).getTime()) / (1000 * 60 * 60);
  const stale = ageHours >= 96;
  const warn = !stale && ageHours >= 72;
  const bg = stale ? 'bg-red-50 border-red-200 text-red-800' : warn ? 'bg-amber-50 border-amber-200 text-amber-800' : 'bg-emerald-50 border-emerald-200 text-emerald-800';
  return (
    <div className={`flex items-center gap-3 ${bg} border rounded-xl px-4 py-3 mb-6 text-sm`}>
      <CheckCircle2 className="w-4 h-4 shrink-0" />
      <span className="font-medium">{t('admin.freshness.label')}</span>
      <span>{humanAge(ageHours, t)}</span>
      {stale && <span className="ml-auto text-[12px]">⚠ {t('admin.freshness.stale')}</span>}
    </div>
  );
}

function humanAge(hours: number, t: ReturnType<typeof useT>['t']): string {
  if (hours < 1 / 60) return t('admin.freshness.justNow');
  if (hours < 1) return t('admin.freshness.minutesAgo', { n: Math.round(hours * 60) });
  if (hours < 48) return t('admin.freshness.hoursAgo', { n: Math.round(hours) });
  return t('admin.freshness.daysAgo', { n: Math.round(hours / 24) });
}

function AlertList({ health, t }: { health: HealthResponse; t: ReturnType<typeof useT>['t'] }) {
  return (
    <section className="mb-6 bg-amber-50 border border-amber-200 rounded-2xl p-4">
      <h2 className="flex items-center gap-2 text-[14px] font-semibold text-amber-900 mb-2">
        <AlertTriangle className="w-4 h-4" />
        {t('admin.healthAlertsTitle')}
      </h2>
      <ul className="space-y-1.5 text-[13px] text-amber-900">
        {health.alerts.map((a, i) => (
          <li key={i} className="flex items-start gap-2">
            <span className={`mt-0.5 shrink-0 inline-flex items-center justify-center px-1.5 py-0.5 text-[10px] font-bold rounded ${a.level === 'alert' ? 'bg-red-200 text-red-900' : 'bg-amber-200 text-amber-900'}`}>
              {a.level.toUpperCase()}
            </span>
            <span>{a.message}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function StatCard({
  label, value, color, pct, hint, delta, active, onClick,
}: {
  label: string;
  value: number;
  color: 'blue' | 'amber' | 'green' | 'gray';
  pct?: number;
  hint?: string;
  delta?: number | null;
  active?: boolean;
  onClick?: () => void;
}) {
  const colors = {
    blue: 'text-blue-700 bg-blue-50',
    amber: 'text-amber-700 bg-amber-50',
    green: 'text-emerald-700 bg-emerald-50',
    gray: 'text-gray-700 bg-gray-50',
  }[color];
  const className = `rounded-2xl p-4 transition-all ${colors} ${active ? 'ring-2 ring-blue-500 shadow-sm' : ''} ${onClick ? 'cursor-pointer hover:scale-[1.02]' : ''}`;
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag type={onClick ? 'button' : undefined} onClick={onClick} className={`${className} text-left w-full`}>
      <p className="text-[11px] font-semibold uppercase tracking-wider opacity-70">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">{value.toLocaleString()}</p>
      {pct !== undefined && pct > 0 && (
        <p className="text-[11px] opacity-70">{pct.toFixed(1)}%</p>
      )}
      {hint && (
        <p className="text-[10px] opacity-60 mt-0.5 italic">{hint}</p>
      )}
      {typeof delta === 'number' && delta !== 0 && (
        <p className={`text-[10px] mt-1 font-medium ${delta > 0 ? 'text-red-600' : 'text-emerald-600'}`}>
          {delta > 0 ? `▲ +${delta}` : `▼ ${delta}`}
        </p>
      )}
    </Tag>
  );
}

function Cell({ v, total, mute }: { v: number; total: number; mute?: boolean }) {
  if (v === 0) return <span className="text-gray-300">0</span>;
  const pct = total ? (v / total * 100) : 0;
  const cls = mute ? 'text-gray-500' : pct > 30 ? 'text-amber-700 font-semibold' : 'text-gray-700';
  return <span className={cls}>{v} <span className="text-[10px] opacity-60">({pct.toFixed(0)}%)</span></span>;
}

function SourceTable({ rows, t }: { rows: SourceRow[]; t: ReturnType<typeof useT>['t'] }) {
  const cols = t('admin.bySourceCols') as unknown as Record<string, string>;
  return (
    <section className="mb-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3">{t('admin.bySource')}</h2>
      <div className="hidden sm:block bg-white rounded-2xl border border-gray-100 overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-4 py-2.5 text-left">{cols.source}</th>
              <th className="px-4 py-2.5 text-right">{cols.total}</th>
              <th className="px-4 py-2.5 text-right">{cols.emptyMajors}</th>
              <th className="px-4 py-2.5 text-right">{cols.emptyKeywords}</th>
              <th className="px-4 py-2.5 text-right">{cols.rolling}</th>
              <th className="px-4 py-2.5 text-right">{cols.missingDeadline}</th>
              <th className="px-4 py-2.5 text-right">{cols.past}</th>
              <th className="px-4 py-2.5 text-right">{cols.inactive}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((row) => (
              <tr key={row.source} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium text-gray-900">{row.source}</td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-600">{row.total}</td>
                <td className="px-4 py-3 text-right tabular-nums"><Cell v={row.empty_majors || 0} total={row.total} /></td>
                <td className="px-4 py-3 text-right tabular-nums"><Cell v={row.empty_keywords || 0} total={row.total} /></td>
                <td className="px-4 py-3 text-right tabular-nums text-emerald-600">{row.rolling_deadline || 0}</td>
                <td className="px-4 py-3 text-right tabular-nums"><Cell v={row.missing_deadline || 0} total={row.total} mute /></td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-500">{row.past_deadline || 0}</td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-500">{row.flagged_inactive || 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="sm:hidden grid gap-3">
        {rows.map(row => (
          <div key={row.source} className="bg-white rounded-2xl border border-gray-100 p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="font-semibold text-gray-900">{row.source}</p>
              <p className="text-[12px] tabular-nums text-gray-500">{cols.total}: <span className="font-medium text-gray-700">{row.total}</span></p>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
              <dt className="text-gray-500">{cols.emptyMajors}</dt>
              <dd className="text-right tabular-nums"><Cell v={row.empty_majors || 0} total={row.total} /></dd>
              <dt className="text-gray-500">{cols.emptyKeywords}</dt>
              <dd className="text-right tabular-nums"><Cell v={row.empty_keywords || 0} total={row.total} /></dd>
              <dt className="text-gray-500">{cols.rolling}</dt>
              <dd className="text-right tabular-nums text-emerald-600">{row.rolling_deadline || 0}</dd>
              <dt className="text-gray-500">{cols.missingDeadline}</dt>
              <dd className="text-right tabular-nums"><Cell v={row.missing_deadline || 0} total={row.total} mute /></dd>
              <dt className="text-gray-500">{cols.past}</dt>
              <dd className="text-right tabular-nums text-gray-500">{row.past_deadline || 0}</dd>
              <dt className="text-gray-500">{cols.inactive}</dt>
              <dd className="text-right tabular-nums text-gray-500">{row.flagged_inactive || 0}</dd>
            </dl>
          </div>
        ))}
      </div>
    </section>
  );
}

function WorstFieldsSection({
  rows, activeFilter, onClearFilter, t,
}: {
  rows: WorstField[];
  activeFilter: FieldKey | null;
  onClearFilter: () => void;
  t: ReturnType<typeof useT>['t'];
}) {
  const cols = t('admin.worstFieldsCols') as unknown as Record<string, string>;
  return (
    <section>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-[15px] font-semibold text-gray-900">{t('admin.worstFields')}</h2>
        {activeFilter && (
          <button type="button" onClick={onClearFilter} className="inline-flex items-center gap-1.5 text-[12px] text-blue-600 hover:text-blue-800">
            <X className="w-3 h-3" />
            {t('admin.filterActive', { field: activeFilter })} · {t('admin.clearFilter')}
          </button>
        )}
      </div>
      <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[600px]">
          <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-4 py-2.5 text-left">{cols.title}</th>
              <th className="px-4 py-2.5 text-left hidden md:table-cell">{cols.fields}</th>
              <th className="px-4 py-2.5 text-left">{cols.source}</th>
              <th className="px-4 py-2.5 text-right">{cols.missing}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-[13px] text-gray-400 italic">
                  No matching records.
                </td>
              </tr>
            ) : rows.map((row) => (
              <tr key={row.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-900 truncate max-w-md">
                  {row.url ? (
                    <a href={row.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                      {row.title || row.id}
                    </a>
                  ) : (row.title || row.id)}
                </td>
                <td className="px-4 py-3 hidden md:table-cell">
                  <div className="flex flex-wrap gap-1">
                    {(row.missing_fields || []).map(f => (
                      <span key={f} className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-800">
                        {f.replace('_', ' ')}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 text-gray-500">{row.source}</td>
                <td className="px-4 py-3 text-right tabular-nums font-semibold text-amber-600">{row.missing_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CollectorStatusSection({ status, t }: { status: CollectorStatus | null; t: ReturnType<typeof useT>['t'] }) {
  const cols = t('admin.collectorStatusCols') as unknown as Record<string, string>;
  return (
    <section className="mt-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3">{t('admin.collectorStatusTitle')}</h2>
      {!status || !status.last_run_at || status.sources.length === 0 ? (
        <p className="text-[13px] text-gray-400 italic">{t('admin.collectorStatusEmpty')}</p>
      ) : (
        <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-4 py-2.5 text-left">{cols.source}</th>
                <th className="px-4 py-2.5 text-left">{cols.status}</th>
                <th className="px-4 py-2.5 text-right">{cols.fetched}</th>
                <th className="px-4 py-2.5 text-right">{cols.new}</th>
                <th className="px-4 py-2.5 text-right">{cols.updated}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {status.sources.map(s => (
                <tr key={s.source} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {s.source}
                    {s.deep && <span className="ml-2 text-[10px] text-blue-600 font-medium">DEEP</span>}
                  </td>
                  <td className="px-4 py-3">
                    {s.status === 'ok' ? (
                      <span className="inline-flex items-center gap-1 text-emerald-700 text-[12px] font-medium">
                        <CheckCircle2 className="w-3 h-3" /> ok
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-red-700 text-[12px] font-medium" title={s.error || ''}>
                        <AlertTriangle className="w-3 h-3" /> {s.status}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-gray-600">{s.fetched ?? '—'}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-emerald-700">{s.new ?? '—'}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-gray-500">{s.updated ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {status?.last_run_at && (
        <p className="mt-2 text-[11px] text-gray-400">
          Last run: {new Date(status.last_run_at).toLocaleString()}
          {status.duration_seconds && ` · ${status.duration_seconds.toFixed(0)}s`}
          {typeof status.total_in_file === 'number' && ` · ${status.total_in_file.toLocaleString()} records`}
        </p>
      )}
    </section>
  );
}

function RefreshTriggerSection({
  status, onTrigger, t,
}: {
  status: { kind: 'idle' | 'busy' | 'ok' | 'err'; message?: string };
  onTrigger: (mode: 'quick' | 'deep') => void;
  t: ReturnType<typeof useT>['t'];
}) {
  return (
    <section className="mt-10 bg-white rounded-2xl border border-gray-100 p-5">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3 flex items-center gap-2">
        <Zap className="w-4 h-4 text-blue-600" />
        {t('admin.triggerRefresh')}
      </h2>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => onTrigger('quick')} disabled={status.kind === 'busy'} className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${status.kind === 'busy' ? 'animate-spin' : ''}`} />
          {t('admin.triggerRefreshQuick')}
        </button>
        <button type="button" onClick={() => onTrigger('deep')} disabled={status.kind === 'busy'} className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-gray-700 text-white text-sm font-medium hover:bg-gray-800 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${status.kind === 'busy' ? 'animate-spin' : ''}`} />
          {t('admin.triggerRefreshDeep')}
        </button>
      </div>
      {status.message && (
        <p className={`mt-3 text-[12px] ${status.kind === 'err' ? 'text-red-700' : 'text-emerald-700'}`}>
          {status.message}
        </p>
      )}
    </section>
  );
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
  const H = 180;
  const PAD = 30;

  const xMax = history.length - 1;
  const yValues = series.flatMap(s => history.map(h => h[s.key] ?? 0));
  const yMax = Math.max(1, ...yValues);

  const x = (i: number) => PAD + (i / Math.max(1, xMax)) * (W - 2 * PAD);
  const y = (v: number) => H - PAD - (v / yMax) * (H - 2 * PAD);

  const yTicks = [0, Math.round(yMax / 2), yMax];

  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
        {yTicks.map(tv => (
          <g key={tv}>
            <line x1={PAD} y1={y(tv)} x2={W - PAD} y2={y(tv)} stroke="#f3f4f6" strokeDasharray="2 2" />
            <text x={PAD - 6} y={y(tv) + 3} fontSize="10" fill="#9ca3af" textAnchor="end" className="tabular-nums">{tv}</text>
          </g>
        ))}
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#e5e7eb" />
        {series.map(s => {
          const points = history.map((h, i) => `${x(i)},${y(h[s.key] ?? 0)}`).join(' ');
          return (
            <g key={s.key}>
              <polyline fill="none" stroke={s.color} strokeWidth={2} points={points} />
              {history.map((h, i) => {
                const v = h[s.key] ?? 0;
                const dateLabel = (() => { try { return new Date(h.t).toLocaleDateString(); } catch { return h.t; } })();
                return (
                  <circle key={i} cx={x(i)} cy={y(v)} r={3} fill={s.color}>
                    <title>{`${s.label}: ${v} (${dateLabel})`}</title>
                  </circle>
                );
              })}
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
