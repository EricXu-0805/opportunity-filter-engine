'use client';

import { Sparkles } from 'lucide-react';
import Card from '@/components/Card';
import { formatRelativeAge } from './home-utils';
import type { TFunc } from './types';

export function LiveDatabaseCard({
  oppCount,
  lastUpdated,
  t,
}: {
  oppCount: number | null;
  lastUpdated: string | null;
  t: TFunc;
}) {
  return (
    <Card className="bg-gradient-to-br from-blue-600 to-blue-500 border-blue-500 text-white">
      <div className="flex items-center gap-3 mb-3">
        <Sparkles className="w-5 h-5 text-blue-200" />
        <span className="text-sm font-semibold text-blue-100">
          {t('home.cards.liveDatabase')}
        </span>
      </div>
      <p className="text-3xl font-extrabold">{oppCount ?? '...'}</p>
      <p className="text-sm text-blue-200 mt-1">{t('home.cards.liveDatabaseHint')}</p>
      {lastUpdated && (
        <p className="text-[11px] text-blue-200/70 mt-1.5">
          {t('home.cards.updatedPrefix')} {formatRelativeAge(lastUpdated)}
        </p>
      )}
    </Card>
  );
}
