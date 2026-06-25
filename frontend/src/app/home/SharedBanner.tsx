'use client';

import { Share2 } from 'lucide-react';
import type { TFunc } from './types';

export function SharedBanner({
  message,
  onDismiss,
  t,
}: {
  message: string | null;
  onDismiss: () => void;
  t: TFunc;
}) {
  if (!message) return null;
  return (
    <div className="max-w-3xl mx-auto mb-8 flex items-start gap-3 px-4 py-3 bg-indigo-50 border border-indigo-200 rounded-xl">
      <Share2 className="w-4 h-4 text-indigo-600 mt-0.5 shrink-0" />
      <p className="text-[13px] text-indigo-800 leading-relaxed">{message}</p>
      <button
        type="button"
        onClick={onDismiss}
        className="text-indigo-600 hover:text-indigo-800 text-[12px] font-medium shrink-0"
      >
        {t('common.dismiss')}
      </button>
    </div>
  );
}
