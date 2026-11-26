'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import Card from './Card';
import { useT } from '@/i18n/client';
import { downloadBlob } from '@/lib/browser-download';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange, type OwnerToken } from '@/lib/identity-owner';
import { AttachmentExportLimitError, exportTrackerAttachments } from '@/lib/tracker-attachment-export';

type Status = 'idle' | 'busy' | 'error' | 'empty' | 'complete';
export default function TrackerAttachmentExport({ uid }: { uid: string }) {
  const { t } = useT();
  const [status, setStatus] = useState<Status>('idle');
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [offer, setOffer] = useState<{ label: string; save: () => void } | null>(null);
  const [limit, setLimit] = useState<{ error: AttachmentExportLimitError; owner: OwnerToken } | null>(null);
  const canShowPath = useSyncExternalStore(onLocalOwnerStateChange,
    () => limit !== null && isOwnerTokenValid(limit.owner, uid), () => false);
  const [verifiedAt, setVerifiedAt] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);
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
        if (current.current === controller) { current.current = null; setOffer(null); setStatus('idle'); }
      }
    });
    setProgress({ done: 0, total: 0 });
    setLimit(null);
    setReceipt(null);
    setVerifiedAt(null);
    setStatus('busy');

    // Each volume needs its own download click, including browsers that block
    // automatic multiple downloads. Only one Blob is offered at a time.
    const offerDownload = (file: { filename: string; blob: Blob }, label: string,
      prepare: () => Promise<void | { filename: string; blob: Blob; verifiedAt: string }>) =>
      new Promise<void>((resolve, reject) => {
        let used = false;
        const abort = () => reject(new DOMException('Export cancelled', 'AbortError'));
        controller.signal.addEventListener('abort', abort, { once: true });
        if (!active()) { controller.signal.removeEventListener('abort', abort); abort(); return; }
        setOffer({ label, save: async () => {
          if (used || !active()) return;
          used = true;
          setOffer(null);
          try {
            const fresh = await prepare();
            if (!active()) throw new DOMException('Export cancelled', 'AbortError');
            downloadBlob(fresh ?? file);
            if (fresh) setVerifiedAt(fresh.verifiedAt);
            resolve();
          } catch (error) { reject(error); }
          finally { controller.signal.removeEventListener('abort', abort); }
        } });
      });
    try {
      const file = await exportTrackerAttachments(uid, token, controller.signal, (done, total) => {
        if (active()) setProgress({ done, total });
      }, part => offerDownload(part, t('account.attachmentExport.part', { part: part.number, total: part.total }), part.confirmBeforeDownload));
      if (!active()) return;
      if (!file) { setStatus('empty'); return; }
      if (file.parts) {
        await offerDownload(file, t('account.attachmentExport.receipt'), file.downloadFreshReceipt);
        if (!active()) return;
        setReceipt(file.filename);
      } else {
        downloadBlob(file);
        setVerifiedAt(file.verifiedAt);
      }
      setProgress({ done: file.count, total: file.count });
      setStatus('complete');
    } catch (error) {
      if (active()) {
        if (error instanceof AttachmentExportLimitError) setLimit({ error, owner: token });
        setStatus('error');
      }
    }
    finally {
      unsubscribe();
      if (current.current === controller) {
        if (!isOwnerTokenValid(token, uid)) setStatus('idle');
        current.current = null;
      }
    }
  }

  function cancel() { current.current?.abort(); current.current = null; setOffer(null); setStatus('idle'); }

  return <Card>
    <h2 className="text-lg font-bold text-gray-900">{t('account.attachmentExport.title')}</h2>
    <p className="my-2 text-sm text-gray-600">{t('account.attachmentExport.description')}</p>
    <button type="button" className="my-2 rounded-full border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50"
      onClick={status === 'busy' ? cancel : start}>
      {t(status === 'busy' ? 'account.attachmentExport.cancel' : status === 'error' ? 'account.attachmentExport.retry' : 'account.attachmentExport.start')}
    </button>
    {offer && <button type="button" onClick={offer.save}
      className="my-2 ml-2 rounded-full bg-indigo-700 px-4 py-2 text-sm font-medium text-white">{offer.label}</button>}
    <div role="status" className="text-sm text-gray-700">
      {status === 'busy' && (offer ? t('account.attachmentExport.partial') : progress.total ? t('account.attachmentExport.progress', progress) : t('account.attachmentExport.preparing'))}
      {status === 'empty' && t('account.attachmentExport.empty')}
      {status === 'error' && (limit && canShowPath ? t(limit.error.metadata ? 'account.attachmentExport.metadataLimit' : 'account.attachmentExport.limit', { path: limit.error.path }) : t('account.attachmentExport.failed'))}
      {status === 'error' && limit && canShowPath && <p>
        {t('account.attachmentExport.recovery')}{' '}
        <Link href="/tracker" className="font-medium text-indigo-700 underline">{t('account.attachmentExport.openTracker')}</Link>
      </p>}
      {status === 'complete' && <>
        <p>{t(receipt ? 'account.attachmentExport.multiComplete' : 'account.attachmentExport.complete', { count: progress.done })}</p>
        {verifiedAt && <p>{t('account.attachmentExport.checkedAt', { time: verifiedAt })}</p>}
        <code className="text-xs">shasum -a 256 -c {receipt ?? 'SHA256SUMS'}</code>
      </>}
    </div>
  </Card>;
}
