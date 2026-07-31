'use client';

import { Zap } from 'lucide-react';
import type { TFunc, TriggerStatus } from './types';

export function RefreshTriggerSection({
  t,
}: {
  status: TriggerStatus;
  onTrigger: (mode: 'quick' | 'deep') => void;
  t: TFunc;
}) {
  return (
    <section className="mt-10 bg-white rounded-2xl border border-gray-100 p-5">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3 flex items-center gap-2">
        <Zap className="w-4 h-4 text-indigo-600" />
        {t('admin.triggerRefresh')}
      </h2>
      <p className="text-[12px] text-amber-800">
        {t('admin.triggerRefreshDisabled')}
      </p>
    </section>
  );
}
