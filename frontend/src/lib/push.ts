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
    && 'Notification' in window
    && typeof navigator.locks?.request === 'function'
    && typeof globalThis.caches?.open === 'function';
}

async function browserSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration('/sw.js');
  return reg ? reg.pushManager.getSubscription() : null;
}

// The service worker reads the same binding when all pages are closed. Only
// the account id is persisted here, never a session token or a push endpoint.
const OWNER_WORKER = '/sw.js?account=1';
const PUSH_LOCK = 'ofe-push-binding';
const PUSH_CACHE = 'ofe-push-binding-v1';
const PUSH_OWNER_KEY = '/.ofe/push-owner';

interface PushBinding { uid: string; enabled: boolean }

async function storedBinding(cache: Cache): Promise<PushBinding | null> {
  const response = await cache.match(PUSH_OWNER_KEY);
  if (!response) return null;
  const value = await response.json();
  if (typeof value?.uid !== 'string' || typeof value?.enabled !== 'boolean') {
    throw new Error('Unreadable browser notification binding');
  }
  return value;
}

function saveBinding(cache: Cache, uid: string, enabled: boolean) {
  return cache.put(PUSH_OWNER_KEY, new Response(JSON.stringify({ uid, enabled })));
}

async function ownsEndpoint(uid: string, endpoint: string): Promise<boolean> {
  const { data, error } = await supabase.from('push_subscriptions').select('endpoint')
    .eq('device_id', uid).eq('endpoint', endpoint).maybeSingle();
  if (error) throw new Error(`push status unreadable: ${error.message}`);
  return data?.endpoint === endpoint;
}

async function liveUid(): Promise<string | null> {
  const { data, error } = await supabase.auth.getSession();
  if (error) throw error;
  return data.session?.user.id ?? null;
}

// Called under PUSH_LOCK. A legacy subscription has no local binding: adopt
// it only after this account reads its own matching database row. A known
// foreign endpoint is blocked in the worker before any network operation.
async function reconcileSubscription(sub: PushSubscription, uid: string | null, cache: Cache) {
  const binding = await storedBinding(cache);
  if (uid && (!binding || binding.uid === uid) && await ownsEndpoint(uid, sub.endpoint)) {
    if (await liveUid() !== uid) throw new OwnerMismatchError();
    if (!binding?.enabled) await saveBinding(cache, uid, true);
    return true;
  }
  if (await liveUid() !== uid) throw new OwnerMismatchError();
  await saveBinding(cache, binding?.uid ?? '', false);
  if (!await sub.unsubscribe()) throw new Error('The previous browser notification subscription is still active');
  await cache.delete(PUSH_OWNER_KEY);
  return false;
}

// Always observe the live session inside the cross-tab lock. An old tab's
// queued cleanup may run after another account has already enabled reminders.
export async function synchronizePushOwner(): Promise<void> {
  if (!isPushSupported()) return;
  await navigator.locks.request(PUSH_LOCK, async () => {
    const reg = await navigator.serviceWorker.getRegistration('/sw.js');
    const sub = await reg?.pushManager.getSubscription();
    if (!reg || !sub) {
      if (await caches.has(PUSH_CACHE)) await (await caches.open(PUSH_CACHE)).delete(PUSH_OWNER_KEY);
      return;
    }
    const cache = await caches.open(PUSH_CACHE);
    try {
      await reconcileSubscription(sub, await liveUid(), cache);
    } finally {
      // Switch the script URL on the same root scope, preserving the browser
      // subscription. Dormant pre-upgrade devices keep their legacy worker.
      if (reg.active?.scriptURL !== new URL(OWNER_WORKER, location.origin).href) {
        await navigator.serviceWorker.register(OWNER_WORKER);
      }
    }
  });
}

export async function getPushStatus(): Promise<PushStatus> {
  if (!isPushSupported()) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  return navigator.locks.request(PUSH_LOCK, async () => {
    const sub = await browserSubscription();
    if (!sub) return 'default';
    const uid = await liveUid();
    return await reconcileSubscription(sub, uid, await caches.open(PUSH_CACHE)) ? 'subscribed' : 'default';
  });
}

export async function subscribeToPush(vapidPublicKey: string, token: OwnerToken): Promise<boolean> {
  if (!isPushSupported() || !vapidPublicKey) return false;
  // Permission must still be requested in the click's user activation.
  if (await Notification.requestPermission() !== 'granted') return false;
  const uid = await getDeviceId();
  if (!uid) throw new Error('No account is available to save the notification subscription');
  return navigator.locks.request(PUSH_LOCK, async () => {
    if (!isOwnerTokenValid(token, uid) || await liveUid() !== uid) throw new OwnerMismatchError();
    const cache = await caches.open(PUSH_CACHE);
    const reg = await navigator.serviceWorker.register(OWNER_WORKER);
    await navigator.serviceWorker.ready;
    const previous = await reg.pushManager.getSubscription();
    if (previous && await reconcileSubscription(previous, uid, cache)) return true;
    if (!previous) await cache.delete(PUSH_OWNER_KEY);
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey).buffer as ArrayBuffer,
    });
    const { endpoint } = sub;
    const keys = sub.toJSON().keys;
    if (!endpoint || !keys?.p256dh || !keys.auth || endpoint === previous?.endpoint) {
      throw new Error('The browser did not create a fresh notification subscription');
    }
    if (!isOwnerTokenValid(token, uid) || await liveUid() !== uid) throw new OwnerMismatchError();
    const { error } = await supabase.from('push_subscriptions').upsert(
      { device_id: uid, endpoint, p256dh: keys.p256dh, auth: keys.auth },
      { onConflict: 'device_id,endpoint' },
    );
    if (error) throw new Error(`Could not save the notification subscription: ${error.message}`);
    if (!isOwnerTokenValid(token, uid) || await liveUid() !== uid) throw new OwnerMismatchError();
    await saveBinding(cache, uid, true);
    return true;
  });
}

async function deletePushRow(uid: string, endpoint: string): Promise<boolean> {
  try {
    const { data, error } = await supabase
      .from('push_subscriptions')
      .delete()
      .eq('device_id', uid)
      .eq('endpoint', endpoint).select('endpoint');
    return !error && data?.some(row => row.endpoint === endpoint) === true;
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
  await navigator.locks.request(PUSH_LOCK, async () => {
    const sub = await browserSubscription();
    if (!sub) return;
    const uid = await liveUid();
    if (!uid || !isOwnerTokenValid(token, uid)) throw new OwnerMismatchError();
    const cache = await caches.open(PUSH_CACHE);
    const rowGone = await deletePushRow(uid, sub.endpoint);
    const endpointDead = await sub.unsubscribe().catch(() => false);
    if (!rowGone && !endpointDead) throw new Error('Could not unsubscribe from notifications');
    await saveBinding(cache, uid, false);
  });
}

/**
 * Deletes this browser's push row for the account about to sign out. It has
 * to run before the sign-out: only that account's own session can delete the
 * row (RLS: device_id = auth.uid()). Resolves false when such a row may be
 * left behind; the caller then kills the endpoint once the sign-out is done.
 */
export async function releasePushForSignOut(expectedUid: string | null): Promise<boolean> {
  if (!isPushSupported()) return true;
  try {
    return await navigator.locks.request(PUSH_LOCK, async () => {
      const sub = await browserSubscription();
      if (!sub) return true;
      const uid = await liveUid();
      if (uid && uid !== expectedUid) throw new OwnerMismatchError();
      return uid ? deletePushRow(uid, sub.endpoint) : false;
    });
  } catch (error) {
    if (error instanceof OwnerMismatchError) throw error;
    return false;
  }
}
