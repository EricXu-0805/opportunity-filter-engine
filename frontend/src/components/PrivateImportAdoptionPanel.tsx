'use client';

import Link from 'next/link';
import { useEffect, useRef } from 'react';
import { useT } from '@/i18n/client';
import { useAuthModal } from '@/lib/auth-modal-context';
import type { CustomImport } from '@/lib/custom-imports';
import type { usePrivateImportAdoption } from '@/lib/use-private-import-adoption';
import { privateImportErrorKey, privateImportSourceInfo } from '@/lib/private-import-ui';
import ImportOpportunityDetails from './ImportOpportunityDetails';

type Adoption = ReturnType<typeof usePrivateImportAdoption>;
export default function PrivateImportAdoptionPanel({ adoption, onReread }: {
  adoption: Adoption; onReread: (entry: CustomImport) => void;
}) {
  const { t } = useT(); const { openModal } = useAuthModal();
  const { state, confirm, cancel } = adoption;
  const region = useRef<HTMLElement>(null);
  useEffect(() => { if (state.status === 'loading') region.current?.scrollIntoView?.({ block: 'nearest' }); }, [state.status]);
  if (state.status === 'idle') return null;
  const review = 'review' in state ? state.review : null;
  const busy = state.status === 'saving';
  return <section ref={region} aria-label={t('privateImport.reviewTitle')} className="my-5 space-y-4 rounded-2xl border border-indigo-200 bg-white p-5 sm:p-6">
    <h2 className="text-lg font-semibold text-gray-900">{t('privateImport.reviewTitle')}</h2>
    <p className="text-sm text-gray-600">{t('privateImport.separateCopies')}</p>
    {state.status === 'loading' && <p role="status">{t('privateImport.checkingCopy')}</p>}
    {state.status === 'saving' && <p role="status">{t('privateImport.saving')}</p>}
    {state.status === 'error' && <div role="alert" className="space-y-2 text-sm text-red-700">
      <p>{t(privateImportErrorKey(state.code))}</p>
      {state.code === 'sign_in_required' && <button type="button" onClick={() => openModal({ phase: 'signin' })}
        className="font-semibold text-indigo-700">{t('privateImport.signIn')}</button>}
    </div>}
    {state.status === 'saved' ? <>
      <p role="status" className="text-sm text-emerald-800">{t('privateImport.saved')}</p>
      <Link className="text-sm text-indigo-700" href={`/private-imports/${encodeURIComponent(state.receipt.target.id)}`}>{t('applicationRecord.viewRecords')}</Link>
    </> : review && <>
      <p className="text-sm text-amber-800">{t('privateImport.unverified')}</p>
      <div className="grid gap-5 md:grid-cols-2">
        <section aria-label={t('privateImport.previousVersion')} className="min-w-0 space-y-3 rounded-xl border border-gray-200 p-4">
          <h3 className="font-medium text-gray-900">{t('privateImport.previousVersion')}</h3>
          {review.cloud?.target.opportunity ? <>
            <p className="break-words font-medium">{review.cloud.target.opportunity.title}</p>
            <ImportOpportunityDetails opportunity={review.cloud.target.opportunity} sourceInfo={privateImportSourceInfo(review.cloud.target)} t={t} />
          </> : <p className="text-sm text-gray-600">{t(review.cloud ? 'privateImport.deleted' : 'privateImport.noCloudCopy')}</p>}
        </section>
        <section aria-label={t('privateImport.newVersion')} className="min-w-0 space-y-3 rounded-xl border border-gray-200 p-4">
          <h3 className="font-medium text-gray-900">{t('privateImport.newVersion')}</h3>
          <p className="break-words font-medium">{review.candidate.title}</p>
          <ImportOpportunityDetails opportunity={review.candidate} t={t} />
        </section>
      </div>
    </>}
    <div className="flex flex-wrap gap-3">
      <button type="button" onClick={cancel} disabled={busy} className="rounded-lg border border-gray-300 px-4 py-2 text-sm disabled:opacity-50">{t(state.status === 'saved' ? 'privateImport.close' : 'privateImport.keepCopies')}</button>
      {state.status === 'review' && <button type="button" onClick={() => void confirm()} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white">
        {t(state.review.cloud ? 'privateImport.confirmUpdate' : 'privateImport.confirmSave')}
      </button>}
      {state.status === 'error' && state.local && state.code !== 'deleted' && state.code !== 'sign_in_required' && <button type="button" onClick={() => onReread(state.local!)}
        className="rounded-lg border border-indigo-300 px-4 py-2 text-sm font-semibold text-indigo-700">{t('privateImport.reread')}</button>}
    </div>
  </section>;
}
