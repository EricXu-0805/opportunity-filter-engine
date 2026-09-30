'use client';

import { useEffect, useState, useSyncExternalStore } from 'react';
import { getStatusChanges, type InteractionType, type StatusChange } from '@/lib/supabase';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange } from '@/lib/identity-owner';
import { formatAgo } from '@/lib/humanize-time';
import { useT } from '@/i18n/client';

const STATUS_COLORS: Record<string, { dot: string; pill: string }> = {
  applied: { dot: 'bg-indigo-500', pill: 'bg-indigo-50 text-indigo-700' },
  replied: { dot: 'bg-violet-500', pill: 'bg-violet-50 text-violet-700' },
  interviewing: { dot: 'bg-amber-500', pill: 'bg-amber-50 text-amber-700' },
  rejected: { dot: 'bg-gray-400', pill: 'bg-gray-100 text-gray-600' },
  dismissed: { dot: 'bg-gray-300', pill: 'bg-gray-50 text-gray-400' },
};

interface Props {
  opportunityId: string;
  fallbackType: InteractionType;
  /** Reload hint only; never evidence of when the status occurred. */
  fallbackUpdatedAt?: string;
}

function ownerSnapshot(): string {
  const token = captureOwnerToken();
  return JSON.stringify([token.uid, token.epoch, token.generation, isOwnerTokenValid(token, token.uid)]);
}
function subscribeOwner(changed: () => void): () => void {
  const stop = onLocalOwnerStateChange(changed);
  window.addEventListener('storage', changed);
  return () => { stop(); window.removeEventListener('storage', changed); };
}
type History = { scope: string; status: 'ready' | 'error'; rows: StatusChange[] };

export default function StatusTimeline({ opportunityId, fallbackType, fallbackUpdatedAt }: Props) {
  const { t } = useT();
  const owner = useSyncExternalStore(subscribeOwner, ownerSnapshot, () => 'server');
  // The parent remounts TrackerPanel on identity changes. Until that happens,
  // even its fallback status may still belong to the previous account.
  const [fallbackOwner] = useState(owner);
  const [retry, setRetry] = useState(0);
  const scope = JSON.stringify([opportunityId, owner, fallbackType, fallbackUpdatedAt, retry]);
  const [history, setHistory] = useState<History | null>(null);
  const token = captureOwnerToken();
  const ownerReady = token.uid !== null && isOwnerTokenValid(token, token.uid);
  const view = history?.scope === scope ? history : null;
  const rows = view?.status === 'ready' ? view.rows : [];

  useEffect(() => {
    let active = true;
    const origin = captureOwnerToken();
    void Promise.resolve().then(() => {
      if (!active || !origin.uid || !isOwnerTokenValid(origin, origin.uid)) throw new Error('history owner unavailable');
      return getStatusChanges(opportunityId);
    }).then(changes => {
      if (active && isOwnerTokenValid(origin, origin.uid)) setHistory({ scope, status: 'ready', rows: changes });
    }, () => {
      if (active) setHistory({ scope, status: 'error', rows: [] });
    });
    return () => { active = false; };
  }, [opportunityId, scope]);

  function statusLabel(type: InteractionType): string {
    const label = t(`detail.tracker.statusLabels.${type}`);
    return label === `detail.tracker.statusLabels.${type}` ? type : label;
  }
  return (
    <div data-testid="status-timeline">
      <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
        {t('detail.tracker.timeline.title')}
      </h3>
      {!view && <p role="status" className="text-xs text-gray-500">{t('detail.tracker.timeline.loading')}</p>}
      {view?.status === 'error' && <div role="alert" className="text-xs text-amber-800">
        <p>{t('detail.tracker.timeline.error')}</p>
        <button type="button" onClick={() => setRetry(value => value + 1)}
          className="mt-1 rounded underline underline-offset-2 focus-visible:ring-2 focus-visible:ring-indigo-500">
          {t('detail.tracker.timeline.retry')}
        </button>
      </div>}
      {view?.status === 'ready' && rows.length === 0 && <p className="text-xs text-gray-500">{t('detail.tracker.timeline.empty')}</p>}
      {rows.length === 0 && ownerReady && fallbackOwner === owner && <p className="mt-1 text-xs text-gray-600">
        {t('detail.tracker.timeline.currentStatus')}: <span>{statusLabel(fallbackType)}</span>
      </p>}
      {rows.length > 0 && <ol className="space-y-1.5">
        {rows.map((row, i) => {
          const colors = STATUS_COLORS[row.toStatus] ?? { dot: 'bg-gray-300', pill: 'bg-gray-50 text-gray-500' };
          const label = statusLabel(row.toStatus);
          const age = formatAgo(row.changedAt, t);
          const isLast = i === rows.length - 1;
          return (
            <li key={`${row.toStatus}-${row.changedAt}-${i}`} className="relative flex items-center gap-2 text-[11px]">
              <span className={`w-2 h-2 rounded-full ${colors.dot} shrink-0`} aria-hidden="true" />
              {!isLast && (
                <span className="absolute left-[3px] top-3 w-0.5 h-3 bg-gray-200" aria-hidden="true" />
              )}
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium ${colors.pill}`}>
                {label}
              </span>
              {age && <span className="text-gray-400">· {age}</span>}
            </li>
          );
        })}
      </ol>}
    </div>
  );
}
