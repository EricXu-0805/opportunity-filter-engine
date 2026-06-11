'use client';

import { AlertTriangle, CheckCircle2, Mail } from 'lucide-react';
import { StatCard } from './StatCard';
import type { SavedSearchHealth, TFunc } from './types';

export function SavedSearchHealthSection({ health, t }: { health: SavedSearchHealth | null; t: TFunc }) {
  if (!health) return null;
  const neverRun = health.refresh?.never_run ?? 0;
  const staleRuns = health.refresh?.stale_over_48h ?? 0;
  const neverSent = health.digest?.opted_in_never_sent ?? 0;
  return (
    <section className="mt-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3 flex items-center gap-2">
        <Mail className="w-4 h-4 text-blue-600" />
        {t('admin.savedSearch.title')}
      </h2>
      {health.status !== 'ok' ? (
        <p className="text-[13px] text-gray-400 italic">{t('admin.savedSearch.unconfigured')}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <StatCard label={t('admin.savedSearch.totalSearches')} value={health.searches?.total ?? 0} color="blue" />
            <StatCard label={t('admin.savedSearch.digestOptIn')} value={health.searches?.digest_opt_in ?? 0} color="gray" />
            <StatCard label={t('admin.savedSearch.neverRun')} value={neverRun} color={neverRun > 0 ? 'amber' : 'green'} />
            <StatCard label={t('admin.savedSearch.staleRuns')} value={staleRuns} color={staleRuns > 0 ? 'amber' : 'green'} />
            <StatCard label={t('admin.savedSearch.optedInNeverSent')} value={neverSent} color={neverSent > 0 ? 'amber' : 'green'} />
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-gray-400">
            <span>
              {t('admin.savedSearch.lastRefreshRun')}: {health.refresh?.last_run_at ? new Date(health.refresh.last_run_at).toLocaleString() : t('admin.savedSearch.never')}
            </span>
            <span>
              {t('admin.savedSearch.lastDigestSent')}: {health.digest?.last_sent_at ? new Date(health.digest.last_sent_at).toLocaleString() : t('admin.savedSearch.never')}
            </span>
            {health.resend_configured ? (
              <span className="inline-flex items-center gap-1 text-emerald-700 font-medium">
                <CheckCircle2 className="w-3 h-3" /> {t('admin.savedSearch.resendOk')}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-amber-700 font-medium">
                <AlertTriangle className="w-3 h-3" /> {t('admin.savedSearch.resendMissing')}
              </span>
            )}
          </div>
        </>
      )}
    </section>
  );
}
