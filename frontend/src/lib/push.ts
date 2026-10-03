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

async function browserSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration('/sw.js');
  return reg ? reg.pushManager.getSubscription() : null;
}

/**
 * 'subscribed' means the CURRENT identity gets reminders here: the browser
 * holds a subscription and this identity owns a push_subscriptions row for
 * its endpoint. The browser subscription alone outlives sign-out and account
 * switches, so on its own it says nothing about who is being notified.
 * Rejects when the row cannot be read.
 */
export async function getPushStatus(): Promise<PushStatus> {
  if (!isPushSupported()) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  let sub: PushSubscription | null;
  try {
    sub = await browserSubscription();
  } catch {
    return 'default';
  }
  if (!sub) return 'default';
  const deviceId = await getDeviceId();
  if (!deviceId) return 'default';
  const { data, error } = await supabase
    .from('push_subscriptions')
    .select('endpoint')
    .eq('device_id', deviceId)
    .eq('endpoint', sub.endpoint)
    .maybeSingle();
  if (error) throw new Error(`push status unreadable: ${error.message}`);
  return data ? 'subscribed' : 'default';
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

async function deletePushRow(uid: string, endpoint: string): Promise<boolean> {
  try {
    const { error } = await supabase
      .from('push_subscriptions')
      .delete()
      .eq('device_id', uid)
      .eq('endpoint', endpoint);
    return !error;
  } catch {
    return false;
  }
}

/**
 * Resolves once this account's reminders can no longer reach this browser:
 * its row is gone (nothing is sent) or the endpoint is dead (nothing
 * arrives). Rejects when neither happened, so the toggle keeps reading "on".
 */
export async function unsubscribeFromPush(token: OwnerToken): Promise<void> {
  if (!isPushSupported()) return;
  const sub = await browserSubscription();
  if (!sub) return;
  // Decide ownership before anything changes: a refused write is not
  // "unsubscribed", and the browser may be another account by now.
  const deviceId = await getDeviceId();
  if (deviceId && !isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
  // The row goes first. While it exists the reminders cron keeps sending to
  // the endpoint, and a send to an endpoint the browser already dropped is
  // counted as a failed delivery.
  const rowGone = !deviceId || await deletePushRow(deviceId, sub.endpoint);
  const endpointDead = await sub.unsubscribe().catch(() => false);
  if (!rowGone && !endpointDead) {
    throw new Error('push unsubscribe failed: the row and the browser subscription both remain');
  }
}

/**
 * Deletes this browser's push row for the account about to sign out. It has
 * to run before the sign-out: only that account's own session can delete the
 * row (RLS: device_id = auth.uid()). Resolves false when such a row may be
 * left behind; the caller then kills the endpoint once the sign-out is done.
 */
export async function releasePushForSignOut(): Promise<boolean> {
  if (!isPushSupported()) return true;
  try {
    const sub = await browserSubscription();
    if (!sub) return true;
    // The session being signed out, read as it is: getDeviceId would mint a
    // guest session if there were none.
    const { data: { session } } = await supabase.auth.getSession();
    const uid = session?.user?.id;
    return uid ? await deletePushRow(uid, sub.endpoint) : false;
  } catch {
    return false;
  }
}

/**
 * Kills this browser's push endpoint. For a row that outlived the session
 * able to delete it: the cron keeps sending to that row, and only a dead
 * endpoint stops the reminders arriving here.
 */
export async function dropBrowserPushSubscription(): Promise<void> {
  if (!isPushSupported()) return;
  const sub = await browserSubscription();
  if (sub && !(await sub.unsubscribe())) throw new Error('the browser kept its push subscription');
}
