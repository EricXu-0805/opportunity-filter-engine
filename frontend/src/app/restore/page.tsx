'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import { verifyRestoreLink } from '@/lib/api';
import { useT } from '@/i18n/client';

export default function RestorePage() {
  return (
    <Suspense fallback={null}>
      <RestoreInner />
    </Suspense>
  );
}

function RestoreInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useT();
  const d = searchParams.get('d');
  const token = searchParams.get('t');
  const s = searchParams.get('s');
  const hasAllParams = !!(d && token && s);
  const [verifyState, setVerifyState] = useState<'verifying' | 'ok' | 'error'>('verifying');
  const [verifyError, setVerifyError] = useState<string | null>(null);

  const state = hasAllParams ? verifyState : 'error';
  const error = hasAllParams ? verifyError : t('restore.errMissingParams');

  useEffect(() => {
    if (!hasAllParams) return;
    verifyRestoreLink({ d: d!, t: token!, s: s! })
      .then((res) => {
        if (res.ok && res.device_id) {
          try {
            localStorage.setItem('ofe_restored_device_id', res.device_id);
          } catch { /* quota */ }
          setVerifyState('ok');
          setTimeout(() => router.push('/'), 1600);
        } else {
          setVerifyState('error');
          setVerifyError(t('restore.errLinkInvalid'));
        }
      })
      .catch((e) => {
        setVerifyState('error');
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes('400')) setVerifyError(t('restore.errLinkExpired'));
        else if (msg.includes('503')) setVerifyError(t('restore.errDisabled'));
        else setVerifyError(t('restore.errVerifyFailed'));
      });
  }, [hasAllParams, d, token, s, router, t]);

  return (
    <div className="max-w-md mx-auto px-4 sm:px-6 lg:px-8 py-20">
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 text-center">
        {state === 'verifying' && (
          <>
            <Loader2 className="w-10 h-10 text-indigo-500 animate-spin mx-auto mb-4" />
            <h1 className="text-[17px] font-semibold text-gray-900">{t('restore.verifying')}</h1>
            <p className="text-[13px] text-gray-500 mt-1">{t('restore.verifyingHint')}</p>
          </>
        )}
        {state === 'ok' && (
          <>
            <CheckCircle className="w-10 h-10 text-emerald-500 mx-auto mb-4" />
            <h1 className="text-[17px] font-semibold text-gray-900">{t('restore.verified')}</h1>
            <p className="text-[13px] text-gray-500 mt-1">
              {t('restore.verifiedBody')}
            </p>
          </>
        )}
        {state === 'error' && (
          <>
            <AlertCircle className="w-10 h-10 text-red-500 mx-auto mb-4" />
            <h1 className="text-[17px] font-semibold text-gray-900">{t('restore.cantRestore')}</h1>
            <p className="text-[13px] text-red-600 mt-1">{error}</p>
            <button
              type="button"
              onClick={() => router.push('/')}
              className="mt-6 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 text-white text-[13px] font-semibold hover:bg-indigo-700"
            >
              {t('restore.goHome')}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
