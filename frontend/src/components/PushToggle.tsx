'use client';

import { useEffect, useState } from 'react';
import { captureOwnerToken, isLocalOwnerReadyNow, isTokenOwnerStillCurrent, onLocalOwnerStateChange, OwnerMismatchError } from '@/lib/identity-owner';
import { Bell, BellOff } from 'lucide-react';
import { getPushStatus, subscribeToPush, unsubscribeFromPush, isPushSupported, type PushStatus } from '@/lib/push';
import { getVapidPublicKey } from '@/lib/api';
import { useT } from '@/i18n/client';

export default function PushToggle() {
  const { t } = useT();
  const [observation, setObservation] = useState<{ epoch: number; status: PushStatus | 'unreadable' } | null>(null);
  const [readAttempt, setReadAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  // Clickable before any identity has resolved on a fresh /dashboard load —
  // a token captured then is the null sentinel and every write is refused.
  // The dashboard's own data load establishes the identity; this only watches.
  const [ownerReady, setOwnerReady] = useState(isLocalOwnerReadyNow);
  // The status describes an account, not the browser: its subscription
  // outlives a sign-out, the account's row behind it does not. Every owner
  // transition moves the epoch, so the status is re-read for each one.
  const [ownerEpoch, setOwnerEpoch] = useState(() => captureOwnerToken().epoch);
  useEffect(() => onLocalOwnerStateChange(() => {
    setOwnerReady(isLocalOwnerReadyNow());
    setOwnerEpoch(captureOwnerToken().epoch);
  }), []);
  // The epoch a change failed under; the message is that account's alone.
  const [failedEpoch, setFailedEpoch] = useState<number | null>(null);
  // The server's own key, not a build-time copy of it. The private half that
  // signs every push lives on the backend, so a subscription minted against
  // any other key is accepted by the browser and then never delivered to —
  // and NEXT_PUBLIC_* is inlined at build time, so a Vercel variable that is
  // unset or has drifted from Render's cannot be noticed at runtime. `null`
  // means the server has no key: no control, because none could work.
  const [vapidKey, setVapidKey] = useState<string | null>(null);

  useEffect(() => {
    if (!isPushSupported()) return;
    getVapidPublicKey().then(setVapidKey).catch(() => setVapidKey(null));
  }, []);

  useEffect(() => {
    if (!isPushSupported()) return;
    const token = captureOwnerToken();
    let current = true;
    const publish = (status: PushStatus | 'unreadable') => {
      if (current && isTokenOwnerStillCurrent(token)) setObservation({ epoch: token.epoch, status });
    };
    getPushStatus().then(publish, () => publish('unreadable'));
    return () => { current = false; };
  }, [ownerEpoch, readAttempt]);

  const status = observation?.epoch === ownerEpoch ? observation.status : 'loading';
  if (status === 'unreadable') {
    return (
      <span className="flex flex-wrap items-center justify-end gap-2 text-xs">
        <span role="alert" className="text-gray-600">{t('dashboard.push.unreadable')}</span>
        <button type="button" className="rounded underline" onClick={() => {
          setObservation(null);
          setReadAttempt(attempt => attempt + 1);
        }}>{t('common.retry')}</button>
      </span>
    );
  }
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
    setFailedEpoch(null);
    try {
      if (subscribed) {
        await unsubscribeFromPush(token);
        if (!isTokenOwnerStillCurrent(token)) return;
        setObservation({ epoch: token.epoch, status: 'default' });
      } else {
        const ok = await subscribeToPush(vapidKey!, token);
        if (!isTokenOwnerStillCurrent(token)) return;
        if (ok) setObservation({ epoch: token.epoch, status: 'subscribed' });
        else {
          setObservation(null);
          setReadAttempt(attempt => attempt + 1);
        }
      }
    } catch (err) {
      // A refusal after a switch paints nothing.
      if (!isTokenOwnerStillCurrent(token)) return;
      // A refusal for the same account reads as "not subscribed" rather than
      // a silent no-op.
      if (err instanceof OwnerMismatchError) setObservation({ epoch: token.epoch, status: 'default' });
      // Anything else left the subscription as it was (unsubscribe rejects
      // only while reminders can still arrive), so the toggle keeps its
      // state and says the change failed.
      else setFailedEpoch(token.epoch);
    } finally {
      // A busy flag carries no account data; it is reset either way.
      setBusy(false);
    }
  }

  return (
    <span className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
      {failedEpoch === ownerEpoch && (
        <span role="alert" className="text-[11px] text-red-600">{t(subscribed ? 'common.error' : 'dashboard.push.enableFailed')}</span>
      )}
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
    </span>
  );
}
