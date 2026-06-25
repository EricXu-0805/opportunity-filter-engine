'use client';

import { useEffect, useState } from 'react';
import { Bell, BellOff } from 'lucide-react';
import { getPushStatus, subscribeToPush, unsubscribeFromPush, isPushSupported, type PushStatus } from '@/lib/push';

export default function PushToggle() {
  const [status, setStatus] = useState<PushStatus | 'loading'>('loading');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isPushSupported()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- isPushSupported() checks navigator.serviceWorker (undefined during SSR), so the support test must run post-hydration; useState initializer would cause a hydration mismatch
      setStatus('unsupported');
      return;
    }
    getPushStatus().then(setStatus).catch(() => setStatus('default'));
  }, []);

  if (status === 'loading' || status === 'unsupported' || status === 'denied') {
    return null;
  }

  const vapidKey = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY;
  if (!vapidKey) return null;

  const subscribed = status === 'subscribed';

  async function handleClick() {
    setBusy(true);
    try {
      if (subscribed) {
        await unsubscribeFromPush();
        setStatus('default');
      } else {
        const ok = await subscribeToPush(vapidKey!);
        setStatus(ok ? 'subscribed' : 'default');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={busy}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-40 ${
        subscribed
          ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
          : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300'
      }`}
      aria-pressed={subscribed}
    >
      {subscribed ? <Bell className="w-3 h-3" aria-hidden="true" /> : <BellOff className="w-3 h-3" aria-hidden="true" />}
      <span>{subscribed ? 'Notifications on' : 'Enable notifications'}</span>
    </button>
  );
}
