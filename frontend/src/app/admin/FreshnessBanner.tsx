'use client';

import { useState } from 'react';
import { CheckCircle2 } from 'lucide-react';
import { humanAge } from './admin-utils';
import type { TFunc } from './types';

export function FreshnessBanner({ iso, t }: { iso: string; t: TFunc }) {
  const [ageHours] = useState(
    () => (Date.now() - new Date(iso).getTime()) / (1000 * 60 * 60),
  );
  const stale = ageHours >= 96;
  const warn = !stale && ageHours >= 72;
  const bg = stale
    ? 'bg-red-50 border-red-200 text-red-800'
    : warn
      ? 'bg-amber-50 border-amber-200 text-amber-800'
      : 'bg-emerald-50 border-emerald-200 text-emerald-800';
  return (
    <div className={`flex items-center gap-3 ${bg} border rounded-xl px-4 py-3 mb-6 text-sm`}>
      <CheckCircle2 className="w-4 h-4 shrink-0" />
      <span className="font-medium">{t('admin.freshness.label')}</span>
      <span>{humanAge(ageHours, t)}</span>
      {stale && <span className="ml-auto text-[12px]">⚠ {t('admin.freshness.stale')}</span>}
    </div>
  );
}
