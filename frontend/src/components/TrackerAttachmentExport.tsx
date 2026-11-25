'use client';

import { useEffect, useRef, useState } from 'react';
import Card from './Card';
import { useT } from '@/i18n/client';
import { downloadBlob } from '@/lib/browser-download';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange } from '@/lib/identity-owner';
import { exportTrackerAttachments } from '@/lib/tracker-attachment-export';

type Status = 'idle' | 'busy' | 'error' | 'empty' | 'complete';
export default function TrackerAttachmentExport({ uid }: { uid: string }) {
  const { t } = useT();
  const [status, setStatus] = useState<Status>('idle');
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const current = useRef<AbortController | null>(null);

  useEffect(() => () => { current.current?.abort(); current.current = null; }, [uid]);

  async function start() {
    if (current.current) return;
    const token = captureOwnerToken();
    if (!isOwnerTokenValid(token, uid)) { setStatus('error'); return; }
    const controller = new AbortController();
    current.current = controller;
    const active = () => current.current === controller && !controller.signal.aborted && isOwnerTokenValid(token, uid);
    const unsubscribe = onLocalOwnerStateChange(() => {
      if (!isOwnerTokenValid(token, uid)) {
        controller.abort();
        if (current.current === controller) { current.current = null; setStatus('idle'); }
      }
    });
    setProgress({ done: 0, total: 0 });
    setStatus('busy');
    try {
      const file = await exportTrackerAttachments(uid, token, controller.signal, (done, total) => {
        if (active()) setProgress({ done, total });
      });
      if (!active()) return;
      if (!file) { setStatus('empty'); return; }
      downloadBlob(file);
      setProgress({ done: file.count, total: file.count });
      setStatus('complete');
    } catch { if (active()) setStatus('error'); }
    finally {
      unsubscribe();
      if (current.current === controller) {
        if (!isOwnerTokenValid(token, uid)) setStatus('idle');
        current.current = null;
      }
    }
  }

  function cancel() { current.current?.abort(); current.current = null; setStatus('idle'); }

  return <Card>
    <h2 className="text-lg font-bold text-gray-900">{t('account.attachmentExport.title')}</h2>
    <p className="my-2 text-sm text-gray-600">{t('account.attachmentExport.description')}</p>
    <button type="button" className="my-2 rounded-full border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50"
      onClick={status === 'busy' ? cancel : start}>
      {t(status === 'busy' ? 'account.attachmentExport.cancel' : status === 'error' ? 'account.attachmentExport.retry' : 'account.attachmentExport.start')}
    </button>
    <div role="status" className="text-sm text-gray-700">
      {status === 'busy' && (progress.total ? t('account.attachmentExport.progress', progress) : t('account.attachmentExport.preparing'))}
      {status === 'empty' && t('account.attachmentExport.empty')}
      {status === 'error' && t('account.attachmentExport.failed')}
      {status === 'complete' && <>
        <p>{t('account.attachmentExport.complete', { count: progress.done })}</p>
        <code className="text-xs">shasum -a 256 -c SHA256SUMS</code>
      </>}
    </div>
  </Card>;
}
