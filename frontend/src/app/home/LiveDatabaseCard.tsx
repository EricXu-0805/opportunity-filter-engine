'use client';

import { Sparkles } from 'lucide-react';
import Card from '@/components/Card';
import { formatAgo } from '@/lib/humanize-time';
import type { TFunc } from './types';
import type { DatabaseStats } from './use-database-stats';

export function LiveDatabaseCard({
  oppCount,
  facultyCount,
  lastUpdated,
  status,
  t,
}: DatabaseStats & { t: TFunc }) {
  const updated = formatAgo(lastUpdated, t);
  const displayCount = (count: number | null) => count === null
    ? (status === 'loading' ? '…' : t('home.cards.countUnavailable'))
    : count.toLocaleString();
  return (
    <Card className="p-6 bg-gradient-to-br from-indigo-600 to-indigo-700 text-white border-none">
      <div className="flex items-center gap-3 mb-4">
        <Sparkles className="w-5 h-5 text-indigo-200" />
        <h3 className="font-semibold text-white">{t('home.cards.liveDatabase')}</h3>
      </div>
      <dl className="grid grid-cols-2 gap-4" aria-busy={status === 'loading'}>
        <div>
          <dt className="text-sm text-indigo-100">{t('home.cards.listingCount')}</dt>
          <dd className="mt-1 text-2xl font-extrabold break-words">{displayCount(oppCount)}</dd>
        </div>
        <div>
          <dt className="text-sm text-indigo-100">{t('home.cards.facultyCount')}</dt>
          <dd className="mt-1 text-2xl font-extrabold break-words">{displayCount(facultyCount)}</dd>
        </div>
      </dl>
      {status !== 'ready' && (
        <p role="status" className="text-sm text-indigo-100 mt-3">
          {t(status === 'loading' ? 'home.cards.statsLoading' : 'home.cards.statsUnavailable')}
        </p>
      )}
      <p className="text-xs text-indigo-100 mt-3 leading-relaxed">{t('home.cards.liveDatabaseHint')}</p>
      {status !== 'loading' && (
        <p className="text-xs text-indigo-100 mt-2">
          {updated
            ? <>{t('home.cards.updatedPrefix')} <time dateTime={lastUpdated!}>{updated}</time></>
            : t('home.cards.updateUnknown')}
        </p>
      )}
    </Card>
  );
}
