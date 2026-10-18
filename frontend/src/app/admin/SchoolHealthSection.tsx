'use client';

import { Fragment, useState } from 'react';
import { ChevronDown, ChevronRight, GraduationCap } from 'lucide-react';
import { enumLabel, isoAge } from './admin-utils';
import type { SchoolHealthRow, SchoolHealthWorkflow, SourceHealthRow, TFunc } from './types';

const STATE_ORDER: Record<string, number> = {
  fully_stale: 0,
  partially_degraded: 1,
  fully_fresh: 2,
};

const STATE_STYLES: Record<string, string> = {
  fully_stale: 'bg-red-50 text-red-700',
  partially_degraded: 'bg-amber-50 text-amber-700',
  fully_fresh: 'bg-emerald-50 text-emerald-700',
};

const FRESHNESS_ORDER: Record<string, number> = { unknown: 0, stale: 0, warn: 1, fresh: 2 };

const FRESHNESS_STYLES: Record<string, string> = {
  fresh: 'text-emerald-700',
  warn: 'text-amber-700',
  stale: 'text-red-700',
  unknown: 'text-red-700',
};

/** One fixed zone, so every operator reads the same time for the same record. */
export function formatUtc(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

function Stamp({ iso, empty, t }: { iso: string | null | undefined; empty: string; t: TFunc }) {
  const text = formatUtc(iso);
  if (!text) return <span className="text-gray-400">{empty}</span>;
  return (
    <span className="whitespace-nowrap">
      {text}
      <span className="block text-[11px] text-gray-400">{isoAge(iso, t)}</span>
    </span>
  );
}

function signed(n: number): string {
  return `${n > 0 ? '+' : ''}${n.toLocaleString('en-US')}`;
}

export function SchoolHealthSection({ health, t }: { health: SchoolHealthWorkflow; t: TFunc }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const { data, error } = health;
  if (!data && !error) return null;
  const col = (name: string) => t(`admin.schoolHealth.cols.${name}`);
  // Worst first: with a hundred schools, a dead one must not sit below the fold.
  const schools = [...(data?.schools ?? [])].sort(
    (a, b) => (STATE_ORDER[a.state] ?? -1) - (STATE_ORDER[b.state] ?? -1)
      || a.school.localeCompare(b.school),
  );
  const toggle = (school: string) => {
    const open = !expanded[school];
    setExpanded((s) => ({ ...s, [school]: open }));
    if (open) health.onOpen(school);
    else health.onClose(school);
  };
  const report = data?.report;

  return (
    <section className="mt-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-1 flex items-center gap-2">
        <GraduationCap className="w-4 h-4 text-indigo-600" />
        {t('admin.schoolHealth.title')}
      </h2>
      <p className="text-[12px] text-gray-500 mb-3">{t('admin.schoolHealth.note')}</p>
      {error && (
        <p role="alert" className="text-[13px] text-red-700 mb-2">
          {t('admin.schoolHealth.loadFailed', { error })}
        </p>
      )}
      {!data ? null : !data.available ? (
        <p className="text-[13px] text-gray-400 italic">{t('admin.schoolHealth.unavailable')}</p>
      ) : (
        <>
          {report && (
            <p className="text-[12px] font-medium text-gray-500 mb-2">
              {t('admin.schoolHealth.summary', {
                schools: report.school_count,
                fresh: report.fully_fresh_school_count,
                degraded: report.partially_degraded_school_count,
                stale: report.fully_stale_school_count,
                days: report.stale_days,
              })}
            </p>
          )}
          <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
                <tr>
                  <th className="px-4 py-2.5 text-left">{col('school')}</th>
                  <th className="px-4 py-2.5 text-left">{col('state')}</th>
                  <th className="px-4 py-2.5 text-left">{col('oldestSuccess')}</th>
                  <th className="px-4 py-2.5 text-left">{col('newestSuccess')}</th>
                  <th className="px-4 py-2.5 text-left">{col('failedStale')}</th>
                  <th className="px-4 py-2.5 text-right">{col('coverage')}</th>
                  <th className="px-4 py-2.5 text-left">{col('lastPublish')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {schools.map((s) => (
                  <Fragment key={s.school}>
                    <SchoolRow row={s} open={!!expanded[s.school]} onToggle={() => toggle(s.school)} t={t} />
                    {expanded[s.school] && (
                      <tr>
                        <td colSpan={7} className="px-4 py-3 bg-gray-50">
                          <SourceDrillDown
                            rows={health.shards[s.school]}
                            loading={!!health.shardLoading[s.school]}
                            error={health.shardErrors[s.school] ?? null}
                            t={t}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function SchoolRow({
  row, open, onToggle, t,
}: { row: SchoolHealthRow; open: boolean; onToggle: () => void; t: TFunc }) {
  const never = t('admin.schoolHealth.never');
  const neverCount = row.never_succeeded_shard_count ?? 0;
  const delta = row.coverage_delta;
  return (
    <tr className="hover:bg-gray-50" data-testid={`school-row-${row.school}`}>
      <td className="px-4 py-3 font-medium text-gray-900">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="inline-flex items-center gap-1 hover:text-indigo-700"
        >
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          {row.school}
        </button>
      </td>
      <td className="px-4 py-3">
        <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-medium ${STATE_STYLES[row.state] ?? 'bg-gray-100 text-gray-700'}`}>
          {enumLabel(t, 'admin.schoolHealth.state', row.state)}
        </span>
        <span className="block mt-1 text-[11px] text-gray-400">
          {t('admin.schoolHealth.shardCounts', {
            fresh: row.fresh_shard_count,
            warn: row.warn_shard_count,
            stale: row.stale_shard_count,
            total: row.total_shard_count,
          })}
        </span>
      </td>
      <td className="px-4 py-3 text-gray-700" data-testid="oldest-success">
        {row.oldest_success_at === undefined ? (
          <span className="text-gray-400">—</span>
        ) : row.oldest_success_at === null && neverCount > 0 ? (
          <span className="text-red-700">{t('admin.schoolHealth.neverSucceeded', { count: neverCount })}</span>
        ) : (
          <Stamp iso={row.oldest_success_at} empty={never} t={t} />
        )}
      </td>
      <td className="px-4 py-3 text-gray-700" data-testid="newest-success">
        <Stamp iso={row.last_successful_school_activity} empty={never} t={t} />
      </td>
      <td className="px-4 py-3 text-[12px]">
        <span className={row.failed_shard_count || row.stale_shard_count ? 'text-red-700' : 'text-gray-500'}>
          {t('admin.schoolHealth.failedStale', {
            failed: row.failed_shard_count,
            stale: row.stale_shard_count,
          })}
        </span>
        {(row.failed_shard_count > 0 || row.stale_shard_count > 0) && (
          <span className="block text-[11px] text-gray-400">{t('admin.schoolHealth.reasonsBelow')}</span>
        )}
      </td>
      <td className="px-4 py-3 text-right tabular-nums" data-testid="coverage">
        {delta === undefined ? (
          <span className="text-gray-400">—</span>
        ) : (
          <>
            <span className={delta < 0 ? 'text-red-700 font-medium' : 'text-gray-700'}>{signed(delta)}</span>
            {row.coverage_current_count !== undefined && row.coverage_last_good_count !== undefined && (
              <span className="block text-[11px] text-gray-400">
                {t('admin.schoolHealth.coverageDetail', {
                  current: row.coverage_current_count.toLocaleString('en-US'),
                  lastGood: row.coverage_last_good_count.toLocaleString('en-US'),
                })}
              </span>
            )}
          </>
        )}
      </td>
      <td className="px-4 py-3 text-gray-500" data-testid="last-publish">
        <Stamp iso={row.last_publish_at} empty={never} t={t} />
      </td>
    </tr>
  );
}

function SourceDrillDown({
  rows, loading, error, t,
}: { rows: SourceHealthRow[] | undefined; loading: boolean; error: string | null; t: TFunc }) {
  const col = (name: string) => t(`admin.schoolHealth.sourceCols.${name}`);
  if (error) {
    return <p role="alert" className="text-[12px] text-red-700">{t('admin.schoolHealth.sourcesFailed', { error })}</p>;
  }
  if (!rows) {
    return loading ? <p className="text-[12px] text-gray-400">{t('admin.schoolHealth.sourcesLoading')}</p> : null;
  }
  if (rows.length === 0) {
    return <p className="text-[12px] text-gray-400 italic">{t('admin.schoolHealth.sourcesEmpty')}</p>;
  }
  const never = t('admin.schoolHealth.never');
  const sorted = [...rows].sort(
    (a, b) => (FRESHNESS_ORDER[a.freshness] ?? 0) - (FRESHNESS_ORDER[b.freshness] ?? 0)
      || a.source.localeCompare(b.source),
  );
  return (
    <table className="w-full text-[12px]">
      <thead className="text-[11px] uppercase tracking-wider text-gray-500">
        <tr>
          <th className="px-2 py-1.5 text-left">{col('source')}</th>
          <th className="px-2 py-1.5 text-left">{col('status')}</th>
          <th className="px-2 py-1.5 text-left">{col('lastSuccess')}</th>
          <th className="px-2 py-1.5 text-left">{col('lastAttempt')}</th>
          <th className="px-2 py-1.5 text-right">{col('records')}</th>
          <th className="px-2 py-1.5 text-left">{col('failureReason')}</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-200">
        {sorted.map((r) => (
          <tr key={r.source} data-testid={`source-row-${r.source}`}>
            <td className="px-2 py-1.5 font-mono text-gray-900">
              {r.source}
              {!r.eligible && (
                <span className="block font-sans text-[11px] text-gray-400">{t('admin.schoolHealth.notScheduled')}</span>
              )}
            </td>
            <td className="px-2 py-1.5">
              <span className={FRESHNESS_STYLES[r.freshness] ?? 'text-gray-700'}>
                {enumLabel(t, 'admin.schoolHealth.freshness', r.freshness)}
              </span>
              <span className="block text-[11px] text-gray-500">
                {enumLabel(t, 'admin.schoolHealth.status', r.status, '—')}
                {r.consecutive_failures > 0 && ` · ${t('admin.schoolHealth.consecutiveFailures', { n: r.consecutive_failures })}`}
              </span>
            </td>
            <td className="px-2 py-1.5 text-gray-700"><Stamp iso={r.last_success_at} empty={never} t={t} /></td>
            <td className="px-2 py-1.5 text-gray-500"><Stamp iso={r.last_attempt_at} empty={never} t={t} /></td>
            <td className="px-2 py-1.5 text-right tabular-nums text-gray-700">
              {r.current_record_count ?? '—'} / {r.last_good_record_count ?? '—'}
            </td>
            <td className="px-2 py-1.5 text-gray-700 break-words max-w-[24rem]">{r.failure_reason || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
