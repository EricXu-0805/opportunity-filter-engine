'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useT } from '@/i18n/client';
import { useAuthModal } from '@/lib/auth-modal-context';
import { usePrivateImportList } from '@/lib/use-private-import-list';
import type { PrivateImportTarget } from '@/lib/private-import-target-api';
import { privateImportErrorKey, privateImportSourceInfo, privateImportSourceUrl } from '@/lib/private-import-ui';
import ImportOpportunityDetails from './ImportOpportunityDetails';

export default function PrivateImportList() {
  const { t } = useT(); const { openModal } = useAuthModal();
  const { state, refresh, loadMore, open, close, remove } = usePrivateImportList();
  const [deleteReview, setDeleteReview] = useState<PrivateImportTarget | null>(null);
  const detail = state.detail;
  const deleting = detail.status === 'ready' && detail.deleting;
  const activeReview = detail.status === 'ready' && deleteReview === detail.target;
  const btn = 'rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 disabled:opacity-50';
  return <section aria-label={t('privateImport.listTitle')} className="my-8 space-y-4 rounded-2xl border border-gray-200 bg-white p-5 sm:p-6">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-lg font-semibold text-gray-900">{t('privateImport.listTitle')}</h2><p className="mt-1 text-sm text-gray-600">{t('privateImport.listNote')}</p></div>
      {state.status !== 'loading' && state.status !== 'sign_in_required' && <button type="button" className={btn} disabled={deleting} onClick={() => void refresh()}>{t('privateImport.refresh')}</button>}
    </div>
    {state.status === 'loading' && <p role="status" className="text-sm text-gray-600">{t('privateImport.loading')}</p>}
    {state.status === 'sign_in_required' && <div className="space-y-3 text-sm text-gray-600">
      <p>{t('privateImport.signInRequired')}</p><button type="button" onClick={() => openModal({ phase: 'signin' })} className={btn}>{t('privateImport.signIn')}</button>
    </div>}
    {state.status === 'error' && <div role="alert" className="text-sm text-red-700">{t(privateImportErrorKey(state.code ?? 'unavailable'))}</div>}
    {state.deleted && <p role="status" className="text-sm text-gray-700">{t('privateImport.deleteComplete')}</p>}
    {state.status === 'ready' && <>
      {state.items.length === 0 && !state.cursor && <p className="text-sm text-gray-600">{t('privateImport.empty')}</p>}
      <div className="space-y-3">{state.items.map(item => <article key={item.id} className="space-y-2 rounded-xl border border-gray-200 p-4">
        <h3 className="break-words font-medium text-gray-900">{item.title}</h3>
        {item.organization && <p className="break-words text-sm text-gray-600">{item.organization}</p>}
        <p className="text-xs text-amber-800">{t('privateImport.unverified')}</p>
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className={btn} disabled={deleting} onClick={() => { setDeleteReview(null); void open(item.id); }}>{t('privateImport.openSource')}</button>
          <Link href={`/private-imports/${encodeURIComponent(item.id)}`} className="text-sm text-indigo-700">{t('applicationRecord.viewRecords')}</Link>
        </div>
      </article>)}</div>
      {state.more === 'error' && <p role="alert" className="text-sm text-red-700">{t('privateImport.moreFailed')} {t(privateImportErrorKey(state.code ?? 'unavailable'))}</p>}
      {state.cursor && <button type="button" className={btn} disabled={state.more === 'loading' || deleting} onClick={() => void loadMore()}>{t(state.more === 'loading' ? 'privateImport.loadingMore' : state.more === 'error' ? 'privateImport.retryMore' : 'privateImport.loadMore')}</button>}
    </>}
    {detail.status !== 'closed' && <section aria-label={t('privateImport.detailTitle')} className="space-y-4 border-t border-gray-200 pt-4">
      <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">{t('privateImport.detailTitle')}</h3><button type="button" className={btn} disabled={deleting} onClick={close}>{t('privateImport.close')}</button></div>
      {detail.status === 'loading' && <p role="status">{t('privateImport.loadingSource')}</p>}
      {detail.status === 'error' && <div role="alert" className="space-y-2 text-sm text-red-700"><p>{t(privateImportErrorKey(detail.code))}</p><button className={btn} onClick={() => void open(detail.id)}>{t('privateImport.reread')}</button></div>}
      {detail.status === 'ready' && detail.target.opportunity && <>
        <p className="break-words text-lg font-medium">{detail.target.opportunity.title}</p>
        <p className="text-sm text-amber-800">{t('privateImport.unverified')}</p>
        <ImportOpportunityDetails opportunity={detail.target.opportunity} sourceInfo={privateImportSourceInfo(detail.target)} t={t} />
        {privateImportSourceUrl(detail.target.opportunity) && <a className="text-sm text-indigo-700" target="_blank" rel="noopener noreferrer" href={privateImportSourceUrl(detail.target.opportunity)!}>{t('privateImport.viewSource')}</a>}
        {detail.deleteError && <p role="alert" className="text-sm text-red-700">{t(privateImportErrorKey(detail.deleteError))}</p>}
        {deleting && <p role="status">{t('privateImport.deleting')}</p>}
        {activeReview ? <div role="group" aria-label={t('privateImport.reviewDelete')} className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-sm text-red-900">{t('privateImport.deleteWarning')}</p>
          <div className="flex flex-wrap gap-3">
            <button type="button" className={btn} disabled={deleting} onClick={() => setDeleteReview(null)}>{t('privateImport.keepCloudCopy')}</button>
            {detail.deleteError ? <button type="button" className={btn} onClick={() => { setDeleteReview(null); void open(detail.target.id); }}>{t('privateImport.reread')}</button>
              : <button type="button" disabled={deleting} className="rounded-lg bg-red-700 px-3 py-2 text-sm text-white disabled:opacity-50" onClick={() => void remove(deleteReview!)}>{t('privateImport.confirmDelete')}</button>}
          </div>
        </div> : <button type="button" className={btn} onClick={() => setDeleteReview(detail.target)}>{t('privateImport.reviewDelete')}</button>}
      </>}
    </section>}
  </section>;
}
