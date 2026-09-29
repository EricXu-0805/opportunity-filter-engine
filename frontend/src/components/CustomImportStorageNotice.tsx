'use client';

import { useEffect, useRef, useState } from 'react';
import { useT } from '@/i18n/client';
import { captureCustomImportRecovery, resetCustomImports, type CustomImportStorageState,
  type CustomImportWriteFailureReason } from '@/lib/custom-imports';
import { captureOwnerToken, isOwnerTokenValid, isTokenOwnerStillCurrent, onLocalOwnerStateChange, type OwnerToken } from '@/lib/identity-owner';
import { customImportFailureKey, canRetryCustomImport } from '@/lib/custom-import-feedback';

type Recovery = { raw: string; token: OwnerToken };

export default function CustomImportStorageNotice({ state }: { state: CustomImportStorageState }) {
  const { t } = useT();
  const [review, setReview] = useState<Recovery | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<CustomImportWriteFailureReason | null>(null);
  const [downloadRequested, setDownloadRequested] = useState(false);
  const intent = useRef<symbol | null>(null);
  useEffect(() => {
    const clear = () => {
      intent.current = null; setReview(null); setPending(false); setError(null); setDownloadRequested(false);
    };
    const stop = onLocalOwnerStateChange(clear);
    return () => { intent.current = null; stop(); };
  }, []);

  function capture(): Recovery | null {
    const token = captureOwnerToken();
    const result = captureCustomImportRecovery(token);
    if (!result.ok) { setError(result.reason); return null; }
    return { raw: result.raw, token };
  }

  function downloadBackup() {
    if (intent.current) return;
    const snapshot = capture();
    if (!snapshot || !isOwnerTokenValid(snapshot.token, snapshot.token.uid)) return;
    let url: string | undefined;
    try {
      // A JSON string preserves every code unit, including malformed Unicode
      // in a damaged value. Never execute or render the untrusted stored text.
      const data = JSON.stringify({ format: 'ofe-imports-recovery-v1', raw: snapshot.raw });
      url = URL.createObjectURL(new Blob([data], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url; link.download = 'opportunity-imports-backup.json';
      document.body.appendChild(link); link.click(); link.remove();
      setDownloadRequested(true);
    } catch { setError('storage_failed'); }
    finally { if (url) URL.revokeObjectURL(url); }
  }

  async function confirmReset() {
    if (!review || intent.current || (error && !canRetryCustomImport(error))) return;
    const active = Symbol('reset'); intent.current = active; setPending(true);
    const result = await resetCustomImports(review.raw, review.token)
      .catch(() => ({ ok: false, reason: 'storage_failed' } as const));
    if (intent.current !== active || !isTokenOwnerStillCurrent(review.token)) return;
    intent.current = null; setPending(false);
    if (result.ok) { setReview(null); setError(null); setDownloadRequested(false); }
    else setError(result.reason);
  }

  if (state.status === 'ready') return null;
  const damaged = state.status === 'damaged';
  const needsReview = error !== null && !canRetryCustomImport(error);
  return <section aria-label={t('import.storageTitle')} className="mb-6 space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
    <p role="alert">{t(damaged ? 'import.storageDamaged' : customImportFailureKey(state.reason))}</p>
    {damaged && <p>{t('import.storagePreserved')}</p>}
    {error && <p role="alert" className="text-red-700">{t(customImportFailureKey(error))}</p>}
    {downloadRequested && <p role="status">{t('import.backupRequested')}</p>}
    {damaged && <div className="flex flex-wrap gap-3">
      <button type="button" onClick={downloadBackup} disabled={pending} className="rounded-lg border border-amber-400 px-3 py-2 disabled:opacity-50">{t('import.exportBackup')}</button>
      {!review && <button type="button" onClick={() => { const value = capture(); if (value) { setReview(value); setError(null); } }} disabled={pending}
        className="rounded-lg border border-amber-400 px-3 py-2">{t('import.reviewReset')}</button>}
    </div>}
    {damaged && review && <div role="group" aria-label={t('import.reviewReset')} className="space-y-3 border-t border-amber-200 pt-3">
      <p>{t('import.resetWarning')}</p>
      <div className="flex flex-wrap gap-3">
        <button type="button" disabled={pending} onClick={() => { setReview(null); setError(null); }} className="rounded-lg border px-3 py-2">{t('import.cancelReset')}</button>
        {needsReview && <button type="button" disabled={pending} onClick={() => { const value = capture(); if (value) { setReview(value); setError(null); } }}
          className="rounded-lg border px-3 py-2">{t('import.rereadReset')}</button>}
        <button type="button" disabled={pending || needsReview} aria-busy={pending} onClick={confirmReset}
          className="rounded-lg bg-red-700 px-3 py-2 text-white disabled:opacity-50">{t(pending ? 'import.resetting' : 'import.confirmReset')}</button>
      </div>
    </div>}
    {!damaged && <button type="button" onClick={() => window.dispatchEvent(new Event('storage'))}
      className="rounded-lg border border-amber-400 px-3 py-2">{t('common.retry')}</button>}
  </section>;
}
