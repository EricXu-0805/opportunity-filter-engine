'use client';

import { useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { RotateCw } from 'lucide-react';
import { useT } from '@/i18n/client';

export default function OpportunityUnavailable() {
  const { t } = useT();
  const router = useRouter();
  const [isRetrying, startRetry] = useTransition();

  return (
    <div className="max-w-xl mx-auto px-4 sm:px-6 lg:px-8 py-16 text-center">
      <div className="w-12 h-12 mx-auto mb-4 rounded-2xl bg-gray-100 flex items-center justify-center">
        <RotateCw className="w-6 h-6 text-gray-400" aria-hidden="true" />
      </div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2 tracking-tight">
        {t('detail.unavailable.title')}
      </h1>
      <p className="text-[14px] text-gray-500 mb-6 max-w-md mx-auto leading-relaxed">
        {t('detail.unavailable.message')}
      </p>
      <button
        type="button"
        onClick={() => startRetry(() => { router.refresh(); })}
        disabled={isRetrying}
        aria-busy={isRetrying}
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 text-white text-[14px] font-semibold hover:bg-indigo-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-wait disabled:opacity-70"
      >
        <RotateCw className={`w-4 h-4 ${isRetrying ? 'animate-spin' : ''}`} aria-hidden="true" />
        {isRetrying ? t('detail.unavailable.retrying') : t('common.retry')}
      </button>
    </div>
  );
}
