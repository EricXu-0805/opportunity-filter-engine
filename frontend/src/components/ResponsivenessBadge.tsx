'use client';

import { useEffect, useState } from 'react';
import { MailCheck } from 'lucide-react';
import { useT } from '@/i18n/client';
import type { ResponsivenessSignal } from '@/lib/api';
import { getResponsivenessSignal, showsHeardBackBadge } from '@/lib/responsiveness';

export default function ResponsivenessBadge({
  opportunityId,
  size = 'card',
}: {
  opportunityId: string;
  size?: 'card' | 'detail';
}) {
  const { t } = useT();
  const [signal, setSignal] = useState<ResponsivenessSignal | null>(null);

  useEffect(() => {
    let alive = true;
    getResponsivenessSignal(opportunityId).then((s) => {
      if (alive) setSignal(s);
    });
    return () => {
      alive = false;
    };
  }, [opportunityId]);

  if (!showsHeardBackBadge(signal)) return null;

  const cls =
    size === 'detail'
      ? 'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700'
      : 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-50/80 text-emerald-600';

  return (
    <span className={cls}>
      <MailCheck className="w-3 h-3" aria-hidden="true" />
      {t('card.heardBack')}
    </span>
  );
}
