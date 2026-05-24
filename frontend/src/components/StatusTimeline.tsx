'use client';

import { useEffect, useState } from 'react';
import { getStatusChanges, type InteractionType, type StatusChange } from '@/lib/supabase';
import { useT } from '@/i18n/client';

const STATUS_COLORS: Record<string, { dot: string; pill: string }> = {
  applied: { dot: 'bg-blue-500', pill: 'bg-blue-50 text-blue-700' },
  replied: { dot: 'bg-violet-500', pill: 'bg-violet-50 text-violet-700' },
  interviewing: { dot: 'bg-amber-500', pill: 'bg-amber-50 text-amber-700' },
  rejected: { dot: 'bg-gray-400', pill: 'bg-gray-100 text-gray-600' },
  dismissed: { dot: 'bg-gray-300', pill: 'bg-gray-50 text-gray-400' },
};

function formatRelativeAge(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0 || Number.isNaN(ms)) return '';
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

interface Props {
  opportunityId: string;
  fallbackType: InteractionType;
  fallbackUpdatedAt: string;
}

export default function StatusTimeline({ opportunityId, fallbackType, fallbackUpdatedAt }: Props) {
  const { t } = useT();
  const [changes, setChanges] = useState<StatusChange[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getStatusChanges(opportunityId).then((c) => {
      if (!cancelled) setChanges(c);
    });
    return () => { cancelled = true; };
  }, [opportunityId, fallbackType, fallbackUpdatedAt]);

  const rows: Array<{ type: InteractionType; at: string }> =
    changes && changes.length > 0
      ? changes.map((c) => ({ type: c.toStatus, at: c.changedAt }))
      : [{ type: fallbackType, at: fallbackUpdatedAt }];

  return (
    <div>
      <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
        {t('detail.tracker.timeline.title')}
      </h3>
      <ol className="space-y-1.5">
        {rows.map((row, i) => {
          const colors = STATUS_COLORS[row.type] ?? { dot: 'bg-gray-300', pill: 'bg-gray-50 text-gray-500' };
          const label = t(`detail.tracker.statusLabels.${row.type}`);
          const fallbackLabel = label === `detail.tracker.statusLabels.${row.type}` ? row.type : label;
          const isLast = i === rows.length - 1;
          return (
            <li key={`${row.type}-${row.at}-${i}`} className="relative flex items-center gap-2 text-[11px]">
              <span className={`w-2 h-2 rounded-full ${colors.dot} shrink-0`} aria-hidden="true" />
              {!isLast && (
                <span className="absolute left-[3px] top-3 w-0.5 h-3 bg-gray-200" aria-hidden="true" />
              )}
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium ${colors.pill}`}>
                {fallbackLabel}
              </span>
              <span className="text-gray-400">· {formatRelativeAge(row.at)}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
