'use client';

import { RefreshCw, Zap } from 'lucide-react';
import type { TFunc, TriggerStatus } from './types';

export function RefreshTriggerSection({
  status,
  onTrigger,
  t,
}: {
  status: TriggerStatus;
  onTrigger: (mode: 'quick' | 'deep') => void;
  t: TFunc;
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
