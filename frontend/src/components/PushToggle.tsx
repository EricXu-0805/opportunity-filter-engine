'use client';

import { useEffect, useState } from 'react';
import { captureOwnerToken, isLocalOwnerReadyNow, isTokenOwnerStillCurrent, onLocalOwnerStateChange, OwnerMismatchError } from '@/lib/identity-owner';
import { Bell, BellOff } from 'lucide-react';
import { getPushStatus, subscribeToPush, unsubscribeFromPush, isPushSupported, type PushStatus } from '@/lib/push';
import { getVapidPublicKey } from '@/lib/api';
import { useT } from '@/i18n/client';

export default function PushToggle() {
  const { t } = useT();
  const [status, setStatus] = useState<PushStatus | 'loading'>('loading');
  const [busy, setBusy] = useState(false);
  // Clickable before any identity has resolved on a fresh /dashboard load —
  // a token captured then is the null sentinel and every write is refused.
  // The dashboard's own data load establishes the identity; this only watches.
  const [ownerReady, setOwnerReady] = useState(isLocalOwnerReadyNow);
  useEffect(() => onLocalOwnerStateChange(() => setOwnerReady(isLocalOwnerReadyNow())), []);
  // The server's own key, not a build-time copy of it. The private half that
  // signs every push lives on the backend, so a subscription minted against
  // any other key is accepted by the browser and then never delivered to —
  // and NEXT_PUBLIC_* is inlined at build time, so a Vercel variable that is
  // unset or has drifted from Render's cannot be noticed at runtime. `null`
  // means the server has no key: no control, because none could work.
  const [vapidKey, setVapidKey] = useState<string | null>(null);

  useEffect(() => {
    if (!isPushSupported()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- isPushSupported() checks navigator.serviceWorker (undefined during SSR), so the support test must run post-hydration; useState initializer would cause a hydration mismatch
      setStatus('unsupported');
      return;
    }
    getPushStatus().then(setStatus).catch(() => setStatus('default'));
    getVapidPublicKey().then(setVapidKey).catch(() => setVapidKey(null));
  }, []);

  if (status === 'loading' || status === 'unsupported' || status === 'denied') {
    return null;
  }

  const subscribed = status === 'subscribed';
  // Unsubscribing needs no key; only minting one does.
  if (!vapidKey && !subscribed) return null;

  async function handleClick() {
    // The permission dialog is a long window; the browser can be a different
    // account when it closes. The endpoint is bound to whoever clicked.
    const token = captureOwnerToken();
    setBusy(true);
    try {
      if (subscribed) {
        await unsubscribeFromPush(token);
        if (!isTokenOwnerStillCurrent(token)) return;
        setStatus('default');
      } else {
        const ok = await subscribeToPush(vapidKey!, token);
        if (!isTokenOwnerStillCurrent(token)) return;
        setStatus(ok ? 'subscribed' : 'default');
      }
    } catch (err) {
      if (!(err instanceof OwnerMismatchError)) throw err;
      // A refusal for the same account reads as "not subscribed" rather than
      // a silent no-op; a refusal after a switch paints nothing.
      if (isTokenOwnerStillCurrent(token)) setStatus('default');
    } finally {
      // A busy flag carries no account data; it is reset either way.
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={busy || !ownerReady}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-40 ${
        subscribed
          ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
          : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300'
      }`}
      aria-pressed={subscribed}
    >
      {subscribed ? <Bell className="w-3 h-3" aria-hidden="true" /> : <BellOff className="w-3 h-3" aria-hidden="true" />}
      <span>{subscribed ? t('dashboard.push.on') : t('dashboard.push.enable')}</span>
    </button>
  );
}
