'use client';

import { useMemo } from 'react';
import { ArrowLeft, ClipboardList, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import StorageStatusBanner from '@/components/StorageStatusBanner';
import { useT } from '@/i18n/client';
import type { InteractionType } from '@/lib/supabase';

import { TrackerCard } from './TrackerCard';
import { TRACKER_COLUMNS, useTrackerData } from './use-tracker-data';

const COLUMN_ACCENT: Record<InteractionType, string> = {
  applied: 'text-blue-700',
  replied: 'text-emerald-700',
  interviewing: 'text-violet-700',
  rejected: 'text-gray-500',
  dismissed: 'text-gray-400',
};

export default function TrackerPage() {
  const router = useRouter();
  const { t } = useT();
  const { items, loading, changeStatus, saveNotes, setReminder } = useTrackerData();

  const byColumn = useMemo(() => {
    const map = new Map<InteractionType, typeof items>();
    for (const status of TRACKER_COLUMNS) map.set(status, []);
    for (const it of items) {
      const col = map.get(it.record.type);
      if (col) col.push(it);
    }
    return map;
  }, [items]);

  const trackedCount = useMemo(
    () => items.filter((it) => TRACKER_COLUMNS.includes(it.record.type)).length,
    [items],
  );

  if (loading) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        <p className="text-[13px] text-gray-400">{t('tracker.loading')}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
      <button
        type="button"
        onClick={() => router.back()}
        className="mb-8 inline-flex items-center gap-2 text-[13px] text-gray-400 transition-colors duration-300 hover:text-gray-600"
      >
        <ArrowLeft className="h-4 w-4" />
        {t('tracker.back')}
      </button>

      <StorageStatusBanner />

      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gray-100">
          <ClipboardList className="h-5 w-5 text-gray-600" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">{t('tracker.title')}</h1>
          <p className="text-sm text-gray-400">{t('tracker.subtitle')}</p>
        </div>
      </div>

      {trackedCount === 0 ? (
        <div className="rounded-2xl border border-dashed border-gray-200 px-6 py-16 text-center">
          <p className="text-sm font-medium text-gray-600">{t('tracker.emptyTitle')}</p>
          <p className="mt-1 text-[13px] text-gray-400">{t('tracker.emptyBody')}</p>
          <Link
            href="/results"
            className="mt-5 inline-flex items-center rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
          >
            {t('tracker.emptyCta')}
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4 items-start">
          {TRACKER_COLUMNS.map((status) => {
            const colItems = byColumn.get(status) ?? [];
            return (
              <section key={status} className="rounded-2xl bg-gray-50/60 p-3">
                <h2 className={`mb-3 px-1 text-xs font-semibold uppercase tracking-wide ${COLUMN_ACCENT[status]}`}>
                  {t(`tracker.status.${status}`)}
                  <span className="ml-1.5 text-gray-400">{colItems.length}</span>
                </h2>
                <div className="space-y-3">
                  {colItems.map((it) => (
                    <TrackerCard
                      key={it.opp.id}
                      opp={it.opp}
                      status={it.record.type}
                      notes={it.record.notes}
                      remindAt={it.record.remind_at}
                      onChangeStatus={changeStatus}
                      onSaveNotes={saveNotes}
                      onSetReminder={setReminder}
                      t={t}
                    />
                  ))}
                  {colItems.length === 0 && (
                    <p className="px-1 py-6 text-center text-xs text-gray-300">{t('tracker.columnEmpty')}</p>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
