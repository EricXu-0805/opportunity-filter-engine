import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { worker } from './push-worker.test-utils';

const mockGetDeviceId = vi.fn<() => Promise<string | null>>();
const mockGetSession = vi.fn<() => Promise<{ data: { session: { user: { id: string } } | null } }>>();
const mockIsOwnerTokenValid = vi.fn<(...args: unknown[]) => boolean>();
const mockUpsert = vi.fn<(...args: unknown[]) => Promise<{ error: { message: string } | null }>>();
type QueryResult = { data?: unknown; error: { message: string } | null };
const mockSelectResult = vi.fn<() => Promise<QueryResult>>();
const mockDeleteResult = vi.fn<() => Promise<QueryResult>>();
const mockDelete = vi.fn((table: string) => recordQuery(table, 'delete', () => mockDeleteResult()));

/** Every select/delete issued against Supabase, with the eq filters it carried. */
let queries: Array<{ table: string; kind: 'select' | 'delete'; filters: Record<string, unknown> }> = [];
function recordQuery(table: string, kind: 'select' | 'delete', result: () => Promise<QueryResult>) {
  const entry = { table, kind, filters: {} as Record<string, unknown> };
  queries.push(entry);
  const builder = {
    eq: (column: string, value: unknown) => { entry.filters[column] = value; return builder; },
    maybeSingle: () => result(),
    select: () => result(),
    then: (onFulfilled: (value: QueryResult) => unknown, onRejected?: (reason: unknown) => unknown) =>
      result().then(onFulfilled, onRejected),
  };
  return builder;
}

vi.mock('./identity-owner', async () => ({
  // These tests exercise push mechanics, not identity. The owner check is
  // proven in supabase-private-writes.test.ts against the real module.
  isOwnerTokenValid: (...args: unknown[]) => mockIsOwnerTokenValid(...args),
  OwnerMismatchError: class OwnerMismatchError extends Error {},
  mergeGrantPending: (await vi.importActual<typeof import('./identity-owner')>('./identity-owner')).mergeGrantPending,
}));
const TOKEN = { uid: 'device-123', epoch: 0 } as never;
import { OwnerMismatchError } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
vi.mock('./supabase', () => ({
  getDeviceId: () => mockGetDeviceId(),
  supabase: {
    auth: { getSession: () => mockGetSession() },
    from: (table: string) => ({
      upsert: (...args: unknown[]) => mockUpsert(...args),
      delete: () => mockDelete(table),
      select: () => recordQuery(table, 'select', () => mockSelectResult()),
    }),
  },
}));

import {
  synchronizePushOwner,
  getPushStatus,
  isPushSupported,
  releasePushForSignOut,
  subscribeToPush,
  unsubscribeFromPush,
} from './push';

type PushSub = {
  endpoint: string;
  toJSON: () => { keys?: { p256dh?: string; auth?: string } };
  unsubscribe: () => Promise<boolean>;
};

let mockSubscription: PushSub | null = null;
let mockRegistration: unknown = null;
let cached: string | null;
function account(uid: string | null) {
  mockGetSession.mockResolvedValue({ data: { session: uid ? { user: { id: uid } } : null } });
  mockGetDeviceId.mockResolvedValue(uid);
}

function browserSub(endpoint: string, unsubscribe: () => Promise<boolean> = vi.fn(async () => true)): PushSub {
  return { endpoint, toJSON: () => ({ keys: { p256dh: 'p', auth: 'a' } }), unsubscribe };
}

function removeGlobals() {
  delete (globalThis as Record<string, unknown>).Notification;
  delete (globalThis as Record<string, unknown>).PushManager;
  delete (navigator as unknown as Record<string, unknown>).serviceWorker;
}

function installNotification(perm: NotificationPermission, requestResult?: NotificationPermission) {
  Object.defineProperty(globalThis, 'Notification', {
    configurable: true,
    writable: true,
    value: Object.assign(class FakeNotification {}, {
      permission: perm,
      requestPermission: vi.fn(async () => requestResult ?? perm),
    }),
  });
}

function installPushManager() {
  Object.defineProperty(globalThis, 'PushManager', {
    configurable: true,
    writable: true,
    value: class FakePushManager {},
  });
}

function installServiceWorker(opts: { hasRegistration: boolean; registerThrows?: boolean }) {
  const subscribeFn = vi.fn(async (_opts: unknown) => {
    const newSub: PushSub = {
      endpoint: 'https://push.example/abc',
      toJSON: () => ({ keys: { p256dh: 'p256-key', auth: 'auth-key' } }),
      unsubscribe: vi.fn(async () => true),
    };
    mockSubscription = newSub;
    return newSub;
  });
  mockRegistration = opts.hasRegistration
    ? {
        active: { scriptURL: new URL('/sw.js?account=1', location.origin).href, state: 'activated' },
        pushManager: {
          getSubscription: vi.fn(async () => mockSubscription),
          subscribe: subscribeFn,
        },
      }
    : null;
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: {
      register: vi.fn(async () => {
        if (opts.registerThrows) throw new Error('register failed');
        mockRegistration = {
          active: { scriptURL: new URL('/sw.js?account=1', location.origin).href, state: 'activated' },
        pushManager: {
            getSubscription: vi.fn(async () => mockSubscription),
            subscribe: subscribeFn,
          },
        };
        return mockRegistration;
      }),
      getRegistration: vi.fn(async () => mockRegistration),
      ready: Promise.resolve(mockRegistration),
    },
  });
}

function installUnreadableServiceWorker() {
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: {
      getRegistration: vi.fn(async () => { throw new Error('boom'); }),
    },
  });
}

/** A granted browser holding `sub` as its push subscription. */
function subscribedBrowser(sub: PushSub) {
  installNotification('granted');
  installPushManager();
  mockSubscription = sub;
  installServiceWorker({ hasRegistration: true });
}

beforeEach(() => {
  removeGlobals();
  cached = null;
  vi.stubGlobal('caches', { has: async () => cached !== null, open: async () => ({
    match: async () => cached === null ? undefined : new Response(cached),
    put: async (_key: string, response: Response) => { cached = await response.text(); },
    delete: async () => { cached = null; return true; },
  }) });
  mockGetDeviceId.mockReset();
  mockIsOwnerTokenValid.mockReset().mockReturnValue(true);
  mockUpsert.mockReset();
  mockDelete.mockClear();
  mockSelectResult.mockReset().mockResolvedValue({ data: null, error: null });
  mockDeleteResult.mockReset().mockImplementation(async () => ({ data: [{ endpoint: mockSubscription?.endpoint }], error: null }));
  mockGetSession.mockReset().mockResolvedValue({ data: { session: { user: { id: 'device-123' } } } });
  queries = [];
  mockSubscription = null;
  mockRegistration = null;
  mockGetDeviceId.mockResolvedValue('device-123');
  mockUpsert.mockResolvedValue({ error: null });
  localStorage.removeItem(STORAGE_KEYS.MERGE_GRANT);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('isPushSupported', () => {
  it('returns true when window + serviceWorker + PushManager + Notification all present', () => {
    installNotification('default');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    expect(isPushSupported()).toBe(true);
  });

  it('returns false when PushManager is missing from window', () => {
    installNotification('default');
    expect(isPushSupported()).toBe(false);
  });

  it('returns false when Notification is missing from window', () => {
    installPushManager();
    expect(isPushSupported()).toBe(false);
  });
});

describe('getPushStatus', () => {
  it('returns "unsupported" when push APIs are missing', async () => {
    expect(await getPushStatus()).toBe('unsupported');
  });

  it('returns "denied" when Notification.permission is denied', async () => {
    installNotification('denied');
    installPushManager();
    installServiceWorker({ hasRegistration: false });
    expect(await getPushStatus()).toBe('denied');
  });

  it('returns "default" when there is no service-worker registration', async () => {
    installNotification('default');
    installPushManager();
    installServiceWorker({ hasRegistration: false });
    expect(await getPushStatus()).toBe('default');
  });

  it('returns "subscribed" when the current account owns a row for the browser\'s subscription', async () => {
    subscribedBrowser(browserSub('https://push.example/sub'));
    mockSelectResult.mockResolvedValue({ data: { endpoint: 'https://push.example/sub' }, error: null });

    expect(await getPushStatus()).toBe('subscribed');
    expect(queries).toEqual([{
      table: 'push_subscriptions',
      kind: 'select',
      filters: { device_id: 'device-123', endpoint: 'https://push.example/sub' },
    }]);
  });

  // The browser subscription outlives a sign-out or an account switch; the
  // row is what the reminders cron sends to. A subscription whose row belongs
  // to someone else (or to nobody) is not this account being notified.
  it('returns "default" when the browser is subscribed but the current account owns no row for it', async () => {
    subscribedBrowser(browserSub('https://push.example/previous-account'));
    mockSelectResult.mockResolvedValue({ data: null, error: null });

    expect(await getPushStatus()).toBe('default');
  });

  it('returns "default" when there is no identity that could own a row', async () => {
    subscribedBrowser(browserSub('https://push.example/sub'));
    account(null);

    expect(await getPushStatus()).toBe('default');
    expect(queries).toEqual([]);
  });

  it('rejects when the row lookup fails, rather than guessing either way', async () => {
    subscribedBrowser(browserSub('https://push.example/sub'));
    mockSelectResult.mockResolvedValue({ data: null, error: { message: 'connection reset' } });

    await expect(getPushStatus()).rejects.toThrow();
  });

  it('rejects when the browser cannot read its existing registration', async () => {
    installNotification('default');
    installPushManager();
    installUnreadableServiceWorker();
    await expect(getPushStatus()).rejects.toThrow('boom');
  });
});

describe('subscribeToPush', () => {
  it('returns false when push is not supported', async () => {
    expect(await subscribeToPush('vapid-key', TOKEN)).toBe(false);
  });

  it('returns false when vapidPublicKey is the empty string', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    expect(await subscribeToPush('', TOKEN)).toBe(false);
  });

  it('returns false when the user denies the notification permission prompt', async () => {
    installNotification('default', 'denied');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    expect(await subscribeToPush('AAAA', TOKEN)).toBe(false);
  });

  it('reports a failure when getDeviceId resolves to null (no anonymous session)', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    mockGetDeviceId.mockResolvedValue(null);
    await expect(subscribeToPush('AAAA', TOKEN)).rejects.toThrow();
  });

  it('upserts the subscription to push_subscriptions with the correct shape on success', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });

    const ok = await subscribeToPush('AAAA', TOKEN);

    expect(ok).toBe(true);
    expect(mockUpsert).toHaveBeenCalledWith(
      {
        device_id: 'device-123',
        endpoint: 'https://push.example/abc',
        p256dh: 'p256-key',
        auth: 'auth-key',
      },
      { onConflict: 'device_id,endpoint' },
    );
  });

  it('adopts an existing legacy subscription only when its owner row was verified', async () => {
    const sub = browserSub('https://push.example/existing');
    subscribedBrowser(sub);
    mockSelectResult.mockResolvedValue({ data: { endpoint: sub.endpoint }, error: null });
    expect(await subscribeToPush('AAAA', TOKEN)).toBe(true);
    expect(sub.unsubscribe).not.toHaveBeenCalled();
    expect(mockUpsert).not.toHaveBeenCalled();
    expect(JSON.parse(cached!)).toEqual({ uid: 'device-123', enabled: true });
  });

  it('replaces a legacy subscription with no matching owner row before enrolling B', async () => {
    const sub = browserSub('https://push.example/old');
    subscribedBrowser(sub);
    account('B');
    expect(await subscribeToPush('AAAA', TOKEN)).toBe(true);
    expect(sub.unsubscribe).toHaveBeenCalledOnce();
    expect(mockUpsert).toHaveBeenCalledWith(expect.objectContaining({ device_id: 'B', endpoint: 'https://push.example/abc' }), expect.anything());
  });

  it('refuses to register an endpoint that the browser kept after retirement', async () => {
    subscribedBrowser(browserSub('https://push.example/abc'));
    await expect(subscribeToPush('AAAA', TOKEN)).rejects.toThrow('fresh');
    expect(mockUpsert).not.toHaveBeenCalled();
  });

  it('reports a failure when the Supabase upsert returns an error (e.g. table does not exist)', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    mockUpsert.mockResolvedValue({ error: { message: 'relation does not exist' } });

    await expect(subscribeToPush('AAAA', TOKEN)).rejects.toThrow();
  });
});

describe('unsubscribeFromPush', () => {
  it('is a no-op when push is not supported', async () => {
    await expect(unsubscribeFromPush(TOKEN)).resolves.toBeUndefined();
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it('is a no-op when there is no registration', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: false });
    await unsubscribeFromPush(TOKEN);
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it('is a no-op when there is no active subscription on the registration', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    mockSubscription = null;
    await unsubscribeFromPush(TOKEN);
    expect(mockDelete).not.toHaveBeenCalled();
  });

  // While the row exists the reminders cron keeps sending to the endpoint,
  // and a send to an endpoint the browser already dropped is counted as a
  // failed delivery. So the row goes first.
  it('deletes this account\'s row for the endpoint, then drops the browser subscription', async () => {
    const steps: string[] = [];
    mockDeleteResult.mockImplementation(async () => { steps.push('row'); return { data: [{ endpoint: 'https://push.example/byebye' }], error: null }; });
    subscribedBrowser(browserSub('https://push.example/byebye', vi.fn(async () => { steps.push('browser'); return true; })));

    await unsubscribeFromPush(TOKEN);

    expect(steps).toEqual(['row', 'browser']);
    expect(queries).toEqual([{
      table: 'push_subscriptions',
      kind: 'delete',
      filters: { device_id: 'device-123', endpoint: 'https://push.example/byebye' },
    }]);
  });

  it('does not retire a live endpoint on a stale click after the session disappears', async () => {
    const sub = browserSub('https://push.example/nodevice');
    subscribedBrowser(sub);
    account(null);
    await expect(unsubscribeFromPush(TOKEN)).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(sub.unsubscribe).not.toHaveBeenCalled();
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it('refuses BEFORE touching the browser subscription when the account changed', async () => {
    // Dropping the browser subscription and then refusing the row delete left
    // a dead endpoint whose row stayed live for the reminders cron, with the
    // toggle still reading "on" for whoever was on screen.
    const browserUnsub = vi.fn(async () => true);
    subscribedBrowser(browserSub('https://push.example/someone-elses', browserUnsub));
    mockIsOwnerTokenValid.mockReturnValue(false);

    await expect(unsubscribeFromPush(TOKEN)).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(browserUnsub).not.toHaveBeenCalled();
    expect(mockDelete).not.toHaveBeenCalled();
  });

  // Done means nothing more reaches this browser for the account: either its
  // row is gone (nothing is sent) or the endpoint is dead (nothing arrives).
  it('resolves when the row is gone even though the browser kept its subscription', async () => {
    const browserUnsub = vi.fn(async () => { throw new Error('push service unreachable'); });
    subscribedBrowser(browserSub('https://push.example/kept', browserUnsub));

    await expect(unsubscribeFromPush(TOKEN)).resolves.toBeUndefined();
    expect(mockDelete).toHaveBeenCalledTimes(1);
    expect(browserUnsub).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['is refused', () => mockDeleteResult.mockResolvedValue({ error: { message: 'connection reset' } })],
    ['throws', () => mockDeleteResult.mockRejectedValue(new Error('offline'))],
  ])('resolves when the row delete %s but the browser dropped the endpoint', async (_name, arrange) => {
    const browserUnsub = vi.fn(async () => true);
    subscribedBrowser(browserSub('https://push.example/dead', browserUnsub));
    arrange();

    await expect(unsubscribeFromPush(TOKEN)).resolves.toBeUndefined();
    expect(browserUnsub).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['the delete is refused and the browser keeps the subscription',
      () => mockDeleteResult.mockResolvedValue({ error: { message: 'connection reset' } }),
      vi.fn(async () => false)],
    ['the delete request throws and the browser unsubscribe throws',
      () => mockDeleteResult.mockRejectedValue(new Error('offline')),
      vi.fn(async () => { throw new Error('push service unreachable'); })],
  ])('rejects when %s: reminders still reach this browser', async (_name, arrange, browserUnsub) => {
    subscribedBrowser(browserSub('https://push.example/still-live', browserUnsub));
    arrange();

    await expect(unsubscribeFromPush(TOKEN)).rejects.toThrow();
  });

  it('rejects when the browser subscription cannot be read', async () => {
    installNotification('granted');
    installPushManager();
    installUnreadableServiceWorker();
    await expect(unsubscribeFromPush(TOKEN)).rejects.toThrow('boom');
  });
});

describe('releasePushForSignOut', () => {
  // Only the account's own session can delete its row (RLS: device_id =
  // auth.uid()), so this runs before the sign-out ends that session.
  it('deletes the signed-in account\'s row for this browser\'s endpoint and keeps the endpoint', async () => {
    const browserUnsub = vi.fn(async () => true);
    subscribedBrowser(browserSub('https://push.example/mine', browserUnsub));
    mockGetSession.mockResolvedValue({ data: { session: { user: { id: 'account-uid' } } } });

    cached = JSON.stringify({ uid: 'account-uid', enabled: true });
    await expect(releasePushForSignOut('account-uid')).resolves.toMatchObject({ outcome: 'server-row-removed' });

    expect(queries).toEqual([{
      table: 'push_subscriptions',
      kind: 'delete',
      filters: { device_id: 'account-uid', endpoint: 'https://push.example/mine' },
    }]);
    expect(browserUnsub).not.toHaveBeenCalled();
    // Reads the session it is signing out; it never mints a guest one to do it.
    expect(mockGetDeviceId).not.toHaveBeenCalled();
  });

  it('has nothing to release when the browser holds no subscription', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });

    await expect(releasePushForSignOut('device-123')).resolves.toMatchObject({ outcome: 'no-subscription' });
    expect(queries).toEqual([]);
  });

  it.each([false, true])('signs out without an endpoint even if caches and worker installation are refused (registration: %s)', async hasRegistration => {
    installNotification('granted'); installPushManager();
    installServiceWorker({ hasRegistration, registerThrows: true });
    const open = vi.fn().mockRejectedValue(new Error('private storage refused'));
    vi.stubGlobal('caches', { has: async () => true, open });
    await expect(releasePushForSignOut('A')).resolves.toEqual({ outcome: 'no-subscription' });
    expect(navigator.serviceWorker.register).not.toHaveBeenCalled();
    if (!hasRegistration) expect(open).not.toHaveBeenCalled();
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it('mutes only A’s known leftover binding when there is no physical endpoint', async () => {
    installNotification('granted'); installPushManager(); installServiceWorker({ hasRegistration: true });
    account('A'); cached = JSON.stringify({ uid: 'A', enabled: true });
    await releasePushForSignOut('A');
    expect(JSON.parse(cached!)).toEqual({ uid: 'A', enabled: false });
    cached = JSON.stringify({ uid: 'B', enabled: true });
    await releasePushForSignOut('A');
    expect(JSON.parse(cached!)).toEqual({ uid: 'B', enabled: true });
  });

  it('leaves a newly attached B subscription alone during best-effort empty cleanup', async () => {
    installNotification('granted'); installPushManager(); installServiceWorker({ hasRegistration: true });
    const b = browserSub('https://push.example/B'); account('A');
    cached = JSON.stringify({ uid: 'B', enabled: true });
    vi.spyOn(caches, 'has').mockImplementationOnce(async () => { mockSubscription = b; return true; });
    await expect(releasePushForSignOut('A')).resolves.toEqual({ outcome: 'endpoint-changed' });
    expect(b.unsubscribe).not.toHaveBeenCalled();
    expect(JSON.parse(cached!)).toEqual({ uid: 'B', enabled: true });
  });

  it.each(['cache', 'worker'])('physically retires the captured old endpoint when %s preparation fails', async failure => {
    const sub = browserSub('https://push.example/A'); subscribedBrowser(sub); account('A');
    if (failure === 'cache') vi.stubGlobal('caches', { open: async () => { throw new Error('unavailable'); } });
    else {
      (mockRegistration as { active: { scriptURL: string } }).active.scriptURL = location.origin + '/sw.js';
      vi.mocked(navigator.serviceWorker.register).mockRejectedValueOnce(new Error('offline'));
    }
    await expect(releasePushForSignOut('A')).resolves.toEqual({ outcome: 'browser-unsubscribed' });
    expect(sub.unsubscribe).toHaveBeenCalledOnce(); expect(mockDelete).not.toHaveBeenCalled();
  });

  it('does not retire a new endpoint that appeared while the upgrade failed', async () => {
    const a = browserSub('https://push.example/A'); const b = browserSub('https://push.example/B');
    subscribedBrowser(a); account('A');
    (mockRegistration as { active: { scriptURL: string } }).active.scriptURL = location.origin + '/sw.js';
    vi.mocked(navigator.serviceWorker.register).mockImplementationOnce(async () => {
      mockSubscription = b; throw new Error('update unavailable');
    });
    await expect(releasePushForSignOut('A')).resolves.toEqual({ outcome: 'endpoint-changed' });
    expect(a.unsubscribe).not.toHaveBeenCalled(); expect(b.unsubscribe).not.toHaveBeenCalled();
  });

  it('has nothing to release when the browser cannot do push', async () => {
    await expect(releasePushForSignOut('device-123')).resolves.toMatchObject({ outcome: 'no-subscription' });
    expect(queries).toEqual([]);
  });

  it.each([
    ['the delete is refused', () => mockDeleteResult.mockResolvedValue({ error: { message: 'connection reset' } })],
    ['RLS returned no deleted row', () => mockDeleteResult.mockResolvedValue({ data: [], error: null })],
    ['the delete request throws', () => mockDeleteResult.mockRejectedValue(new Error('offline'))],
    ['no session is left that could delete the row', () => mockGetSession.mockResolvedValue({ data: { session: null } })],
  ])('reports false when %s', async (_name, arrange) => {
    subscribedBrowser(browserSub('https://push.example/mine'));
    cached = JSON.stringify({ uid: 'device-123', enabled: true });
    arrange();

    await expect(releasePushForSignOut('device-123')).resolves.toMatchObject({ outcome: 'muted' });
  });

  it('cannot delete B’s notification row when an old A sign-out resumes', async () => {
    subscribedBrowser(browserSub('https://push.example/B'));
    account('B');
    await expect(releasePushForSignOut('A')).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it('reports a safety failure if the existing worker cannot be inspected', async () => {
    installNotification('granted'); installPushManager(); installUnreadableServiceWorker();
    await expect(releasePushForSignOut('device-123')).rejects.toThrow('boom');
  });

  it('mutes an already queued reminder before logout, without requiring any subsequent auth event', async () => {
    subscribedBrowser(browserSub('https://push.example/A'));
    account('A');
    cached = JSON.stringify({ uid: 'A', enabled: true });
    const receipt = await releasePushForSignOut('A');
    expect(receipt.outcome).toBe('server-row-removed');
    const sleeping = worker(JSON.parse(cached!));
    await sleeping.send('A');
    expect(sleeping.showNotification).not.toHaveBeenCalled();
    // A second tab can still observe the old session until logout completes.
    mockSelectResult.mockResolvedValue({ data: { endpoint: 'https://push.example/A' }, error: null });
    await synchronizePushOwner();
    expect(JSON.parse(cached!).enabled).toBe(false);
    // If logout fails, A recovers the same physical subscription and reminders.
    await receipt.restore!();
    expect(mockUpsert).toHaveBeenCalledWith(expect.objectContaining({ device_id: 'A', endpoint: 'https://push.example/A' }), expect.anything());
    const restored = worker(JSON.parse(cached!));
    await restored.send('A');
    expect(restored.showNotification).toHaveBeenCalledOnce();
  });

  it('recovers the same A subscription on reconnect when the first restoration write fails', async () => {
    subscribedBrowser(browserSub('https://push.example/A')); account('A');
    cached = JSON.stringify({ uid: 'A', enabled: true });
    const receipt = await releasePushForSignOut('A');
    mockUpsert.mockRejectedValueOnce(new Error('offline'));
    await expect(receipt.restore!()).rejects.toThrow('offline');
    expect(JSON.parse(cached!).enabled).toBe(false);
    await synchronizePushOwner();
    expect(mockUpsert).toHaveBeenCalledTimes(2);
    expect(JSON.parse(cached!)).toEqual({ uid: 'A', enabled: true });
  });

  it('a delayed failed-logout receipt cannot rebind B’s endpoint to A', async () => {
    subscribedBrowser(browserSub('https://push.example/A')); account('A');
    cached = JSON.stringify({ uid: 'A', enabled: true });
    const receipt = await releasePushForSignOut('A');
    account('B');
    await subscribeToPush('AAAA', TOKEN);
    mockUpsert.mockClear();
    await receipt.restore!();
    expect(mockUpsert).not.toHaveBeenCalled();
    expect(JSON.parse(cached!)).toEqual({ uid: 'B', enabled: true });
  });
});

describe('synchronizePushOwner', () => {
  it.each([null, 'B'])('retires A on session expiry or a direct switch to %s', async (uid) => {
    const old = browserSub('https://push.example/A');
    subscribedBrowser(old);
    cached = JSON.stringify({ uid: 'A', enabled: true });
    account(uid);
    await synchronizePushOwner();
    expect(old.unsubscribe).toHaveBeenCalledOnce();
    expect(mockDelete).not.toHaveBeenCalled();
    expect(cached).toBeNull();
  });

  it('blocks queued A messages even when the provider refuses to retire its endpoint', async () => {
    const old = browserSub('https://push.example/A', vi.fn(async () => false));
    subscribedBrowser(old);
    cached = JSON.stringify({ uid: 'A', enabled: true });
    account('B');
    await expect(synchronizePushOwner()).rejects.toThrow();
    expect(JSON.parse(cached!)).toEqual({ uid: 'A', enabled: false });
    await expect(subscribeToPush('AAAA', TOKEN)).rejects.toThrow();
    expect(mockUpsert).not.toHaveBeenCalled();
  });

  it('preserves B when cleanup queued during A sign-out runs after B enrolled', async () => {
    const old = browserSub('https://push.example/A');
    subscribedBrowser(old);
    cached = JSON.stringify({ uid: 'A', enabled: true });
    account('B');
    const enrolling = subscribeToPush('AAAA', TOKEN);
    await enrolling;
    const fresh = mockSubscription!;
    mockSelectResult.mockResolvedValue({ data: { endpoint: fresh.endpoint }, error: null });
    await synchronizePushOwner();
    expect(old.unsubscribe).toHaveBeenCalledOnce();
    expect(fresh.unsubscribe).not.toHaveBeenCalled();
    expect(JSON.parse(cached!)).toEqual({ uid: 'B', enabled: true });
  });

  it('clears a stale delivery binding when the browser no longer has any subscription', async () => {
    installNotification('granted'); installPushManager(); installServiceWorker({ hasRegistration: true });
    cached = JSON.stringify({ uid: 'A', enabled: true });
    account(null);
    await synchronizePushOwner();
    expect(cached).toBeNull();
  });
});

// Signing a guest in to their own account is not a change of person: the
// sign-in merge moves the guest's push row to the account (redeem_merge_grant),
// and /auth/callback redeems the grant after the SIGNED_IN event has fired.
describe('a guest with reminders signs in to their account', () => {
  const ENDPOINT = 'https://push.example/G';
  const mergeStillPending = () => localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, JSON.stringify({ token: 'grant', minted_at: Date.now() }));
  const mergeAnswered = () => localStorage.removeItem(STORAGE_KEYS.MERGE_GRANT);
  const rowMovedToAccount = () => mockSelectResult.mockResolvedValue({ data: { endpoint: ENDPOINT }, error: null });
  function guestSignsInToA() {
    const sub = browserSub(ENDPOINT, vi.fn(async () => { mockSubscription = null; return true; }));
    subscribedBrowser(sub);
    cached = JSON.stringify({ uid: 'G', enabled: true });
    account('A');
    return sub;
  }

  it('keeps the subscription for the account that now owns its row', async () => {
    const sub = guestSignsInToA();
    rowMovedToAccount();
    await synchronizePushOwner();
    expect(sub.unsubscribe).not.toHaveBeenCalled();
    expect(queries).toEqual([{ table: 'push_subscriptions', kind: 'select', filters: { device_id: 'A', endpoint: ENDPOINT } }]);
    expect(JSON.parse(cached!)).toEqual({ uid: 'A', enabled: true });
    expect(await getPushStatus()).toBe('subscribed');
    const bound = worker(JSON.parse(cached!));
    await bound.send('A');
    expect(bound.showNotification).toHaveBeenCalledOnce();
  });

  it('holds the subscription, showing nothing, until the merge has answered', async () => {
    const sub = guestSignsInToA();
    mergeStillPending();
    await synchronizePushOwner();
    expect(sub.unsubscribe).not.toHaveBeenCalled();
    const held = worker(JSON.parse(cached!));
    await held.send('G');
    await held.send('A');
    expect(held.showNotification).not.toHaveBeenCalled();
    expect(await getPushStatus()).toBe('default');
    expect(sub.unsubscribe).not.toHaveBeenCalled();

    mergeAnswered();
    rowMovedToAccount();
    await synchronizePushOwner();
    expect(sub.unsubscribe).not.toHaveBeenCalled();
    expect(JSON.parse(cached!)).toEqual({ uid: 'A', enabled: true });
  });

  it('retires the held subscription when the merge moved nothing to the account', async () => {
    const sub = guestSignsInToA();
    mergeStillPending();
    await synchronizePushOwner();
    mergeAnswered();
    await synchronizePushOwner();
    expect(sub.unsubscribe).toHaveBeenCalledOnce();
    expect(cached).toBeNull();
  });

  it('does not take a row read from before the merge finished as its answer', async () => {
    const sub = guestSignsInToA();
    mergeStillPending();
    mockSelectResult.mockImplementationOnce(async () => { mergeAnswered(); return { data: null, error: null }; });
    await synchronizePushOwner();
    expect(sub.unsubscribe).not.toHaveBeenCalled();
    rowMovedToAccount();
    await synchronizePushOwner();
    expect(JSON.parse(cached!)).toEqual({ uid: 'A', enabled: true });
  });

  it('lets the account enable reminders itself without waiting for the merge', async () => {
    const sub = guestSignsInToA();
    mockGetDeviceId.mockResolvedValue('A');
    mergeStillPending();
    expect(await subscribeToPush('AAAA', TOKEN)).toBe(true);
    expect(sub.unsubscribe).toHaveBeenCalledOnce();
    expect(mockUpsert).toHaveBeenCalledWith(expect.objectContaining({ device_id: 'A', endpoint: 'https://push.example/abc' }), expect.anything());
  });

  it('blocks the previous owner before reading the row, so an unreadable row shows nobody anything', async () => {
    const sub = guestSignsInToA();
    mockSelectResult.mockResolvedValue({ data: null, error: { message: 'connection reset' } });
    await expect(synchronizePushOwner()).rejects.toThrow('connection reset');
    expect(JSON.parse(cached!)).toEqual({ uid: 'G', enabled: false });
    expect(sub.unsubscribe).not.toHaveBeenCalled();
  });

  it('a pending merge does not keep a subscription once nobody is signed in', async () => {
    const sub = guestSignsInToA();
    account(null);
    mergeStillPending();
    await synchronizePushOwner();
    expect(sub.unsubscribe).toHaveBeenCalledOnce();
    expect(queries).toEqual([]);
  });
});

describe('legacy browsers without an ownership backend', () => {
  it.each(['locks', 'caches'])('attempts physical cleanup and surfaces refusal without %s', async missing => {
    const definition = Object.getOwnPropertyDescriptor(navigator, 'locks');
    if (missing === 'caches') vi.stubGlobal('caches', undefined);
    else Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
    try {
      const sub = browserSub('https://push.example/legacy', vi.fn(async () => false));
      subscribedBrowser(sub); account('A');
      await expect(releasePushForSignOut('A')).rejects.toThrow('kept');
      await expect(synchronizePushOwner()).rejects.toThrow('kept');
      await expect(unsubscribeFromPush(TOKEN)).rejects.toThrow('kept');
      expect(sub.unsubscribe).toHaveBeenCalledTimes(3);
      expect(mockUpsert).not.toHaveBeenCalled();
    } finally {
      if (missing === 'locks' && definition) Object.defineProperty(navigator, 'locks', definition);
    }
  });
});
