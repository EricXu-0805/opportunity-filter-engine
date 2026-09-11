import { supabase, getDeviceId } from './supabase';
import { isOwnerTokenValid, OwnerMismatchError, type OwnerToken } from './identity-owner';

export type PushStatus = 'unsupported' | 'denied' | 'default' | 'subscribed';

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function isPushSupported(): boolean {
  return typeof window !== 'undefined'
    && 'serviceWorker' in navigator
    && 'PushManager' in window
    && 'Notification' in window;
}

export async function getPushStatus(): Promise<PushStatus> {
  if (!isPushSupported()) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  try {
    const reg = await navigator.serviceWorker.getRegistration('/sw.js');
    if (!reg) return Notification.permission === 'granted' ? 'default' : 'default';
    const sub = await reg.pushManager.getSubscription();
    if (sub) return 'subscribed';
    return Notification.permission === 'granted' ? 'default' : 'default';
  } catch {
    return 'default';
  }
}

export async function subscribeToPush(vapidPublicKey: string, token: OwnerToken): Promise<boolean> {
  if (!isPushSupported()) return false;
  if (!vapidPublicKey) return false;

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return false;

  const deviceId = await getDeviceId();
  if (!deviceId) return false;
  // The permission dialog above is a long, real window: the browser can be a
  // different account by the time it closes. Bind the endpoint to whoever clicked.
  if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();

  const reg = await navigator.serviceWorker.register('/sw.js');
  await navigator.serviceWorker.ready;

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey).buffer as ArrayBuffer,
    });
  }

  const json = sub.toJSON();
  const { endpoint } = sub;
  const p256dh = json.keys?.p256dh ?? '';
  const auth = json.keys?.auth ?? '';
  if (!endpoint || !p256dh || !auth) return false;
  if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();

  const { error } = await supabase
    .from('push_subscriptions')
    .upsert(
      { device_id: deviceId, endpoint, p256dh, auth },
      { onConflict: 'device_id,endpoint' },
    );
  if (error) {
    if (error.message.includes('does not exist')) {
      return false;
    }
    return false;
  }
  return true;
}

export async function unsubscribeFromPush(token: OwnerToken): Promise<void> {
  if (!isPushSupported()) return;
  try {
    const reg = await navigator.serviceWorker.getRegistration('/sw.js');
    if (!reg) return;
    const sub = await reg.pushManager.getSubscription();
    if (!sub) return;
    const endpoint = sub.endpoint;
    // Decide ownership BEFORE dropping the browser-level subscription: a
    // refusal after it would leave a dead endpoint with its row still live
    // for the reminders cron and the toggle still reading "on".
    const deviceId = await getDeviceId();
    if (deviceId && !isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    await sub.unsubscribe();
    if (deviceId) {
      await supabase
        .from('push_subscriptions')
        .delete()
        .eq('device_id', deviceId)
        .eq('endpoint', endpoint);
    }
  } catch (err) {
    // A refused write is not "unsubscribed": the browser is another account
    // now, and the caller must not paint the old one's result.
    if (err instanceof OwnerMismatchError) throw err;
    /* everything else stays best-effort */
  }
}
