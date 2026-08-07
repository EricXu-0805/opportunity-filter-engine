'use client';

import { Loader2 } from 'lucide-react';
import { useT } from '@/i18n/client';

export default function OpportunityDetailLoading() {
  const { t } = useT();
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4" role="status">
      <Loader2 className="w-6 h-6 text-gray-400 animate-spin" aria-hidden="true" />
      <p className="text-[13px] text-gray-400">{t('detail.loading')}</p>
    </div>
  );
}
