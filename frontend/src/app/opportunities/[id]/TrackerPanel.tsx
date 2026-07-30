'use client';

import dynamic from 'next/dynamic';
import { useEffect, useState } from 'react';
import { BellRing, StickyNote } from 'lucide-react';
import type { InteractionRecord } from '@/lib/supabase';
import type { TFunc } from './types';

const MarkdownPreview = dynamic(() => import('@/components/MarkdownPreview'), { ssr: false });
const AttachmentsPanel = dynamic(() => import('@/components/AttachmentsPanel'), { ssr: false });
const StatusTimeline = dynamic(() => import('@/components/StatusTimeline'), { ssr: false });

export function TrackerPanel({
  detail,
  onSave,
  opportunityId,
  hasInteraction,
  t,
}: {
  detail: InteractionRecord | null;
  onSave: (patch: { notes?: string | null; remind_at?: string | null }) => Promise<void>;
  opportunityId: string;
  hasInteraction: boolean;
  t: TFunc;
}) {
  const [open, setOpen] = useState(!!(detail?.notes || detail?.remind_at));
  const [notes, setNotes] = useState(detail?.notes ?? '');
  const [remindAt, setRemindAt] = useState(detail?.remind_at ?? '');
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [notesMode, setNotesMode] = useState<'edit' | 'preview'>('edit');

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect --
       Sync internal editor state when the parent's `detail` updates
       (e.g. after the debounced save below round-trips through
       Supabase). Using key-remount would close the editor on every
       save — the wrong UX since the user might still be typing. */
    setNotes(detail?.notes ?? '');
    setRemindAt(detail?.remind_at ?? '');
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [detail?.notes, detail?.remind_at]);

  useEffect(() => {
    // Notes/reminders persist on the interactions row, so saving with no
    // status would have to invent one ('applied' = a send event the user
    // never reported). No status yet → no auto-save; the statusFirst hint
    // below asks the user to pick one instead.
    if (!hasInteraction) return;
    if (notes === (detail?.notes ?? '') && remindAt === (detail?.remind_at ?? '')) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- debounced save side effect; setSaveStatus must run sync to show 'saving…' before the 600ms timer fires
    setSaveStatus('saving');
    const timer = setTimeout(async () => {
      await onSave({
        notes: notes.trim() ? notes.trim().slice(0, 2000) : null,
        remind_at: remindAt || null,
      });
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 1500);
    }, 600);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notes, remindAt, hasInteraction]);

  const hasContent = !!(notes || remindAt);

  return (
    <div className="border-t border-gray-100 px-5 sm:px-8 py-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 text-[12px] text-gray-500 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
        aria-expanded={open}
      >
        <StickyNote className="w-3.5 h-3.5" aria-hidden="true" />
        <span className="font-medium">
          {hasContent ? t('detail.tracker.openButton') : t('detail.tracker.addButton')}
        </span>
        {hasContent && !open && (
          <span className="ml-auto text-[11px] text-gray-400">
            {notes && <span>{notes.length > 40 ? notes.slice(0, 40) + '…' : notes}</span>}
            {remindAt && (
              <span className="ml-2 inline-flex items-center gap-1 text-amber-600">
                <BellRing className="w-3 h-3" aria-hidden="true" />
                {remindAt}
              </span>
            )}
          </span>
        )}
        <span className="ml-auto text-[11px] text-gray-400" aria-live="polite">
          {saveStatus === 'saving' && t('common.saving')}
          {saveStatus === 'saved' && t('common.saved')}
        </span>
      </button>
      {open && (
        <div className="mt-3 space-y-3 animate-in">
          {!hasInteraction && (
            <p className="text-[11px] text-amber-600 bg-amber-50 border border-amber-100 rounded-lg px-2.5 py-1.5">
              {t('detail.tracker.statusFirst')}
            </p>
          )}
          {detail?.type && detail?.updated_at && (
            <StatusTimeline
              opportunityId={opportunityId}
              fallbackType={detail.type}
              fallbackUpdatedAt={detail.updated_at}
            />
          )}
          <div>
            <div role="tablist" aria-label={t('detail.tracker.notesTabsAria')} className="flex items-center gap-1 mb-1.5">
              <button
                type="button"
                role="tab"
                aria-selected={notesMode === 'edit'}
                onClick={() => setNotesMode('edit')}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
                  notesMode === 'edit'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                {t('detail.tracker.editTab')}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={notesMode === 'preview'}
                onClick={() => setNotesMode('preview')}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
                  notesMode === 'preview'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                {t('detail.tracker.previewTab')}
              </button>
            </div>
            {notesMode === 'edit' ? (
              <label className="block">
                <span className="sr-only">{t('detail.sections.description')}</span>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  maxLength={2000}
                  rows={3}
                  placeholder={t('detail.tracker.notesPlaceholder')}
                  className="w-full px-3 py-2 text-[13px] bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-400 resize-y"
                />
                <div className="flex justify-between mt-1 text-[10px] text-gray-400">
                  <span className="italic">{t('detail.tracker.markdownHint')}</span>
                  <span>{notes.length} / 2000</span>
                </div>
              </label>
            ) : (
              <div
                role="tabpanel"
                className="min-h-[5rem] px-3 py-2 text-[13px] bg-white border border-gray-200 rounded-lg prose prose-sm prose-gray max-w-none prose-headings:mt-2 prose-headings:mb-1 prose-p:my-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0 prose-pre:my-2 prose-pre:p-2 prose-pre:text-[12px]"
              >
                {notes.trim() ? (
                  <MarkdownPreview>{notes}</MarkdownPreview>
                ) : (
                  <p className="text-gray-400 italic text-[12px]">{t('detail.tracker.previewEmpty')}</p>
                )}
              </div>
            )}
          </div>
          <label className="flex items-center gap-2 text-[12px] text-gray-600">
            <BellRing className="w-3.5 h-3.5 text-amber-500" aria-hidden="true" />
            <span className="font-medium">{t('detail.tracker.remindLabel')}</span>
            <input
              type="date"
              value={remindAt}
              onChange={(e) => setRemindAt(e.target.value)}
              className="px-2 py-1 text-[12px] bg-white border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
            />
            {remindAt && (
              <button
                type="button"
                onClick={() => setRemindAt('')}
                className="text-[11px] text-gray-400 hover:text-red-500 transition-colors"
              >
                {t('common.clear')}
              </button>
            )}
          </label>
          {hasInteraction && (
            <div className="pt-2 border-t border-gray-50">
              <AttachmentsPanel opportunityId={opportunityId} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
