'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { getStorageStatus, onStorageStatusChange, type StorageStatus } from '@/lib/supabase';

export default function StorageStatusBanner() {
  const [status, setStatus] = useState<StorageStatus>('unknown');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function sync() {
      const s = getStorageStatus();
      setStatus(s.status);
      setError(s.error);
    }
    sync();
    return onStorageStatusChange(sync);
  }, []);

  if (status !== 'local-only') return null;

  return (
    <div
      role="alert"
      className="mb-6 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3"
    >
      <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" aria-hidden="true" />
      <div className="text-[13px] leading-relaxed">
        <p className="font-semibold text-amber-900">
          Saved locally only — not syncing to the cloud
        </p>
        <p className="text-amber-800 mt-1">
          Your favorites are being stored in this browser. They won&apos;t appear on other devices
          until cloud sync is restored.
        </p>
        {error && (
          <p className="text-[11px] text-amber-700 mt-1 font-mono break-all">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
