import { supabase, getDeviceId } from './supabase';
import { isOwnerTokenValid, mergeGrantPending, OwnerMismatchError, type OwnerToken } from './identity-owner';

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

function canBindPush(): boolean {
  return typeof navigator.locks?.request === 'function' && typeof globalThis.caches?.open === 'function';
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

// `serviceWorker.ready` may resolve to the *old* active worker during an
// upgrade. Do not rely on a binding that the current worker cannot enforce.
async function accountWorker(existing?: ServiceWorkerRegistration) {
  const expected = new URL(OWNER_WORKER, location.origin).href;
  if (existing?.active?.scriptURL === expected && existing.active.state === 'activated') return existing;
  const reg = await navigator.serviceWorker.register(OWNER_WORKER);
  const worker = [reg.installing, reg.waiting, reg.active].find(candidate => candidate?.scriptURL === expected);
  if (!worker) throw new Error('The account notification worker is unavailable');
  if (worker.state !== 'activated') await new Promise<void>((resolve, reject) => {
    const finish = () => {
      if (worker.state !== 'activated' && worker.state !== 'redundant') return;
      clearTimeout(timer);
      worker.removeEventListener('statechange', finish);
      if (worker.state === 'activated') resolve();
      else reject(new Error('The account notification worker failed to activate'));
    };
    const timer = setTimeout(() => {
      worker.removeEventListener('statechange', finish);
      reject(new Error('Timed out waiting for the account notification worker'));
    }, 8000);
    worker.addEventListener('statechange', finish);
    finish();
  });
  return reg;
}

interface PushBinding { uid: string; enabled: boolean; signingOut?: string; recoverPublicKey?: string }

async function storedBinding(cache: Cache): Promise<PushBinding | null> {
  const response = await cache.match(PUSH_OWNER_KEY);
  if (!response) return null;
  const value = await response.json();
  if (typeof value?.uid !== 'string' || typeof value?.enabled !== 'boolean') {
    throw new Error('Unreadable browser notification binding');
  }
  return value;
}

function saveBinding(cache: Cache, uid: string, enabled: boolean, signingOut?: string, recoverPublicKey?: string) {
  return cache.put(PUSH_OWNER_KEY, new Response(JSON.stringify({ uid, enabled, signingOut, recoverPublicKey })));
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

async function publishSubscription(uid: string, sub: PushSubscription) {
  const keys = sub.toJSON().keys;
  if (!sub.endpoint || !keys?.p256dh || !keys.auth) throw new Error('The browser returned an incomplete notification subscription');
  if (await liveUid() !== uid) throw new OwnerMismatchError();
  const { error } = await supabase.from('push_subscriptions').upsert(
    { device_id: uid, endpoint: sub.endpoint, p256dh: keys.p256dh, auth: keys.auth },
    { onConflict: 'device_id,endpoint' },
  );
  if (error) throw new Error(`Could not save the notification subscription: ${error.message}`);
  if (await liveUid() !== uid) throw new OwnerMismatchError();
}

// An explicit enrollment and a logout are both user actions. Keep the whole
// auth round-trip ordered across tabs, even while the push binding lock is
// released for Supabase callbacks and the service worker.
export async function withPushSessionLock<T>(operation: () => Promise<T>): Promise<T> {
  if (typeof navigator.locks?.request !== 'function') return operation();
  let started = false;
  try {
    return await navigator.locks.request('ofe-push-session-change', () => { started = true; return operation(); });
  } catch (error) {
    if (started) throw error;
    // Privacy settings can expose the API but reject lock acquisition. The
    // action still checks its own binding or captured endpoint before use.
    return operation();
  }
}

// Called under PUSH_LOCK. A legacy subscription has no local binding: adopt
// it only after this account reads its own matching database row. A known
// foreign endpoint is blocked in the worker before any network operation.
async function reconcileSubscription(sub: PushSubscription, uid: string | null, cache: Cache, enrolling = false) {
  const binding = await storedBinding(cache);
  // Other tabs may observe A while A's logout request is still pending. Only
  // its failure receipt or a later explicit enrollment can unmute it.
  if (uid && binding?.uid === uid && binding.recoverPublicKey && binding.recoverPublicKey === sub.toJSON().keys?.p256dh) {
    await publishSubscription(uid, sub);
    await saveBinding(cache, uid, true);
    return true;
  }
  if (!enrolling && binding?.uid === uid && binding.signingOut) return false;
  // Read before any row: the grant is cleared only after the merge committed,
  // so a row that is missing while no grant was pending is really not ours.
  const merging = mergeGrantPending();
  if (uid && (!binding || binding.uid === uid) && await ownsEndpoint(uid, sub.endpoint)) {
    if (await liveUid() !== uid) throw new OwnerMismatchError();
    if (!binding?.enabled) await saveBinding(cache, uid, true);
    return true;
  }
  if (await liveUid() !== uid) throw new OwnerMismatchError();
  await saveBinding(cache, binding?.uid ?? '', false);
  // A guest who signs in to their account is the same person: the sign-in
  // merge moves their row to the account, after the event that brought us
  // here. A switch to another account finds no row: a row is readable by its
  // owner only, and enrolling makes a fresh endpoint.
  if (uid && binding && binding.uid !== uid && await ownsEndpoint(uid, sub.endpoint)) {
    if (await liveUid() !== uid) throw new OwnerMismatchError();
    await saveBinding(cache, uid, true);
    return true;
  }
  // Left muted, not retired, until /auth/callback has the merge's answer.
  if (uid && binding?.uid !== uid && merging && !enrolling) return false;
  if (!await sub.unsubscribe()) throw new Error('The previous browser notification subscription is still active');
  await cache.delete(PUSH_OWNER_KEY);
  return false;
}

// A browser with Push but no cross-tab locking or worker-readable storage
// cannot enroll safely. It still must retire the existing endpoint. Capture
// the object once so a delayed retry cannot look up a different subscription.
async function retireUnsupportedSubscription(sub: PushSubscription | null) {
  if (typeof globalThis.caches?.open === 'function') {
    try { await saveBinding(await caches.open(PUSH_CACHE), '', false); }
    catch { /* An unavailable cache must not prevent physical retirement. */ }
  }
  if (sub && !await sub.unsubscribe()) throw new Error('The browser kept its previous notification subscription');
}

async function retireUnsupportedForClick(token: OwnerToken) {
  const sub = await browserSubscription();
  const uid = await liveUid();
  if (!uid || !isOwnerTokenValid(token, uid)) throw new OwnerMismatchError();
  await retireUnsupportedSubscription(sub);
}

// Always observe the live session inside the cross-tab lock. An old tab's
// queued cleanup may run after another account has already enabled reminders.
export async function synchronizePushOwner(): Promise<void> {
  if (!isPushSupported()) return;
  if (!canBindPush()) return retireUnsupportedSubscription(await browserSubscription());
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
      await accountWorker(reg);
    }
  });
}

export async function getPushStatus(): Promise<PushStatus> {
  if (!isPushSupported()) return 'unsupported';
  if (!canBindPush()) {
    await retireUnsupportedSubscription(await browserSubscription());
    return 'unsupported';
  }
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
  if (!canBindPush()) {
    await retireUnsupportedForClick(token);
    return false;
  }
  // Permission must still be requested in the click's user activation.
  if (await Notification.requestPermission() !== 'granted') return false;
  const uid = await getDeviceId();
  if (!uid) throw new Error('No account is available to save the notification subscription');
  return withPushSessionLock(() => navigator.locks.request(PUSH_LOCK, async () => {
    if (!isOwnerTokenValid(token, uid) || await liveUid() !== uid) throw new OwnerMismatchError();
    const cache = await caches.open(PUSH_CACHE);
    const reg = await accountWorker();
    const previous = await reg.pushManager.getSubscription();
    if (previous && await reconcileSubscription(previous, uid, cache, true)) return true;
    if (!previous) await cache.delete(PUSH_OWNER_KEY);
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey).buffer as ArrayBuffer,
    });
    if (!sub.endpoint || sub.endpoint === previous?.endpoint) throw new Error('The browser did not create a fresh notification subscription');
    if (!isOwnerTokenValid(token, uid)) throw new OwnerMismatchError();
    await publishSubscription(uid, sub);
    if (!isOwnerTokenValid(token, uid)) throw new OwnerMismatchError();
    await saveBinding(cache, uid, true);
    return true;
  }));
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
  if (!canBindPush()) return retireUnsupportedForClick(token);
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

export interface PushSignOutRelease {
  outcome: 'no-subscription' | 'server-row-removed' | 'browser-unsubscribed' | 'endpoint-changed' | 'muted';
  restore?: () => Promise<void>;
}

async function retireCapturedForSignOut(reg: ServiceWorkerRegistration, sub: PushSubscription, uid: string | null): Promise<PushSignOutRelease> {
  if (await liveUid() !== uid) throw new OwnerMismatchError();
  if ((await reg.pushManager.getSubscription())?.endpoint !== sub.endpoint) return { outcome: 'endpoint-changed' };
  if (await sub.unsubscribe().catch(() => false)) return { outcome: 'browser-unsubscribed' };
  if ((await reg.pushManager.getSubscription())?.endpoint !== sub.endpoint) return { outcome: 'endpoint-changed' };
  throw new Error('The browser kept its previous notification subscription');
}

/** Mute queued reminders before leaving A. This receipt can re-enable the
 * exact original binding if logout fails and the same session still owns it. */
export async function releasePushForSignOut(expectedUid: string | null): Promise<PushSignOutRelease> {
  if (!isPushSupported()) return { outcome: 'no-subscription' };
  const registration = await navigator.serviceWorker.getRegistration('/sw.js');
  if (!registration) return { outcome: 'no-subscription' };
  const sub = await registration.pushManager.getSubscription();
  if (!sub) {
    // No transport is attached. A previously bound worker may still have a
    // queued message. Retire only that account's known binding when possible;
    // do not provision or upgrade anything as a prerequisite for signing out.
    try {
      if (await globalThis.caches?.has(PUSH_CACHE) && typeof navigator.locks?.request === 'function') {
        return await navigator.locks.request(PUSH_LOCK, async (): Promise<PushSignOutRelease> => {
          if (await registration.pushManager.getSubscription()) return { outcome: 'endpoint-changed' };
          const cache = await caches.open(PUSH_CACHE);
          const prior = await storedBinding(cache);
          if (prior?.uid === expectedUid && prior.enabled && await liveUid() === expectedUid) {
            await saveBinding(cache, expectedUid, false);
          }
          return { outcome: 'no-subscription' };
        });
      }
    } catch { /* A browser without an endpoint can still sign out offline. */ }
    return { outcome: 'no-subscription' };
  }
  const uid = await liveUid();
  if (uid && uid !== expectedUid) throw new OwnerMismatchError();
  const retire = () => retireCapturedForSignOut(registration, sub, uid);
  if (!canBindPush()) return retire();
  let started = false;
  try {
    return await navigator.locks.request(PUSH_LOCK, async (): Promise<PushSignOutRelease> => {
      started = true;
      if (await liveUid() !== uid) throw new OwnerMismatchError();
      if ((await registration.pushManager.getSubscription())?.endpoint !== sub.endpoint) return { outcome: 'endpoint-changed' };
      let cache: Cache;
      let prior: PushBinding | null;
      const signingOut = crypto.randomUUID();
      try {
        await accountWorker(registration);
        cache = await caches.open(PUSH_CACHE);
        prior = await storedBinding(cache);
        if (await liveUid() !== uid) throw new OwnerMismatchError();
        // A queued push must stay muted even if no further auth event runs here.
        await saveBinding(cache, uid ?? '', false, signingOut);
      } catch (error) {
        if (error instanceof OwnerMismatchError) throw error;
        return retire();
      }
      if (!uid) return { outcome: 'muted' };
      // For a legacy row we have no local permission receipt. An unreadable
      // row must not be deleted and later recreated on a guess.
      const wasEnabled = prior?.uid === uid && prior.enabled || await ownsEndpoint(uid, sub.endpoint).catch(() => false);
      const released = wasEnabled && await deletePushRow(uid, sub.endpoint);
      if (await liveUid() !== uid) throw new OwnerMismatchError();
      return {
        outcome: released ? 'server-row-removed' : 'muted',
        restore: async () => {
          await navigator.locks.request(PUSH_LOCK, async () => {
            const binding = await storedBinding(cache);
            if (binding?.signingOut !== signingOut || await liveUid() !== uid) return;
            if (!wasEnabled) { await cache.delete(PUSH_OWNER_KEY); return; }
            const current = await browserSubscription();
            if (!current || current.endpoint !== sub.endpoint) return;
            const publicKey = current.toJSON().keys?.p256dh;
            if (!publicKey) throw new Error('The browser lost its notification keys');
            // Only the public key is kept for recovery. The next online or auth
            // observation retries this exact subscription if the write fails.
            await saveBinding(cache, uid, false, signingOut, publicKey);
            await publishSubscription(uid, current);
            await saveBinding(cache, uid, true);
          });
        },
      };
    });
  } catch (error) {
    if (started) throw error;
    return retire();
  }
}
