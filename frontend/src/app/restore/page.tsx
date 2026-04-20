'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import { verifyRestoreLink } from '@/lib/api';

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
  const d = searchParams.get('d');
  const t = searchParams.get('t');
  const s = searchParams.get('s');
  const [state, setState] = useState<'verifying' | 'ok' | 'error'>('verifying');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!d || !t || !s) {
      setState('error');
      setError('Missing link parameters');
      return;
    }
    verifyRestoreLink({ d, t, s })
      .then((res) => {
        if (res.ok && res.device_id) {
          try {
            localStorage.setItem('ofe_restored_device_id', res.device_id);
          } catch { /* quota */ }
          setState('ok');
          setTimeout(() => router.push('/'), 1600);
        } else {
          setState('error');
          setError('Link invalid');
        }
      })
      .catch((e) => {
        setState('error');
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes('400')) setError('Link expired or tampered with. Request a new one.');
        else if (msg.includes('503')) setError('Restore service is disabled.');
        else setError('Could not verify link.');
      });
  }, [d, t, s, router]);

  return (
    <div className="max-w-md mx-auto px-4 sm:px-6 lg:px-8 py-20">
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 text-center">
        {state === 'verifying' && (
          <>
            <Loader2 className="w-10 h-10 text-blue-500 animate-spin mx-auto mb-4" />
            <h1 className="text-[17px] font-semibold text-gray-900">Verifying your link...</h1>
            <p className="text-[13px] text-gray-500 mt-1">This takes a second.</p>
          </>
        )}
        {state === 'ok' && (
          <>
            <CheckCircle className="w-10 h-10 text-emerald-500 mx-auto mb-4" />
            <h1 className="text-[17px] font-semibold text-gray-900">Link verified</h1>
            <p className="text-[13px] text-gray-500 mt-1">
              Cross-device sync requires a Supabase-backed account (not yet shipped).
              For now, reopen the email on your original device to continue where you left off.
            </p>
          </>
        )}
        {state === 'error' && (
          <>
            <AlertCircle className="w-10 h-10 text-red-500 mx-auto mb-4" />
            <h1 className="text-[17px] font-semibold text-gray-900">Couldn&apos;t restore</h1>
            <p className="text-[13px] text-red-600 mt-1">{error}</p>
            <button
              type="button"
              onClick={() => router.push('/')}
              className="mt-6 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 text-white text-[13px] font-semibold hover:bg-blue-700"
            >
              Go to home
            </button>
          </>
        )}
      </div>
    </div>
  );
}
