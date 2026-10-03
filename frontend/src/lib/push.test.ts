import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

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
    then: (onFulfilled: (value: QueryResult) => unknown, onRejected?: (reason: unknown) => unknown) =>
      result().then(onFulfilled, onRejected),
  };
  return builder;
}

vi.mock('./identity-owner', () => ({
  // These tests exercise push mechanics, not identity. The owner check is
  // proven in supabase-private-writes.test.ts against the real module.
  isOwnerTokenValid: (...args: unknown[]) => mockIsOwnerTokenValid(...args),
  OwnerMismatchError: class OwnerMismatchError extends Error {},
}));
const TOKEN = { uid: 'device-123', epoch: 0 } as never;
import { OwnerMismatchError } from './identity-owner';
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
  dropBrowserPushSubscription,
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
  mockGetDeviceId.mockReset();
  mockIsOwnerTokenValid.mockReset().mockReturnValue(true);
  mockUpsert.mockReset();
  mockDelete.mockClear();
  mockSelectResult.mockReset().mockResolvedValue({ data: null, error: null });
  mockDeleteResult.mockReset().mockResolvedValue({ error: null });
  mockGetSession.mockReset().mockResolvedValue({ data: { session: { user: { id: 'device-123' } } } });
  queries = [];
  mockSubscription = null;
  mockRegistration = null;
  mockGetDeviceId.mockResolvedValue('device-123');
  mockUpsert.mockResolvedValue({ error: null });
});

afterEach(() => {
  vi.restoreAllMocks();
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
    mockGetDeviceId.mockResolvedValue(null);

    expect(await getPushStatus()).toBe('default');
    expect(queries).toEqual([]);
  });

  it('rejects when the row lookup fails, rather than guessing either way', async () => {
    subscribedBrowser(browserSub('https://push.example/sub'));
    mockSelectResult.mockResolvedValue({ data: null, error: { message: 'connection reset' } });

    await expect(getPushStatus()).rejects.toThrow();
  });

  it('returns "default" when getRegistration throws (swallows the error)', async () => {
    installNotification('default');
    installPushManager();
    installUnreadableServiceWorker();
    expect(await getPushStatus()).toBe('default');
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

  it('returns false when getDeviceId resolves to null (no anonymous session)', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    mockGetDeviceId.mockResolvedValue(null);
    expect(await subscribeToPush('AAAA', TOKEN)).toBe(false);
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

  it('reuses the existing PushSubscription instead of re-subscribing', async () => {
    subscribedBrowser(browserSub('https://push.example/existing'));

    const ok = await subscribeToPush('AAAA', TOKEN);

    expect(ok).toBe(true);
    expect(mockUpsert).toHaveBeenCalledWith(
      expect.objectContaining({ endpoint: 'https://push.example/existing' }),
      expect.anything(),
    );
  });

  it('returns false when the subscription is missing endpoint/p256dh/auth', async () => {
    installNotification('granted');
    installPushManager();
    mockSubscription = {
      endpoint: '',
      toJSON: () => ({ keys: {} }),
      unsubscribe: vi.fn(async () => true),
    };
    installServiceWorker({ hasRegistration: true });

    expect(await subscribeToPush('AAAA', TOKEN)).toBe(false);
    expect(mockUpsert).not.toHaveBeenCalled();
  });

  it('returns false when the Supabase upsert returns an error (e.g. table does not exist)', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    mockUpsert.mockResolvedValue({ error: { message: 'relation does not exist' } });

    expect(await subscribeToPush('AAAA', TOKEN)).toBe(false);
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
    mockDeleteResult.mockImplementation(async () => { steps.push('row'); return { error: null }; });
    subscribedBrowser(browserSub('https://push.example/byebye', vi.fn(async () => { steps.push('browser'); return true; })));

    await unsubscribeFromPush(TOKEN);

    expect(steps).toEqual(['row', 'browser']);
    expect(queries).toEqual([{
      table: 'push_subscriptions',
      kind: 'delete',
      filters: { device_id: 'device-123', endpoint: 'https://push.example/byebye' },
    }]);
  });

  it('skips the supabase delete when getDeviceId returns null but still unsubscribes the browser', async () => {
    const browserUnsub = vi.fn(async () => true);
    subscribedBrowser(browserSub('https://push.example/nodevice', browserUnsub));
    mockGetDeviceId.mockResolvedValue(null);

    await unsubscribeFromPush(TOKEN);

    expect(browserUnsub).toHaveBeenCalledTimes(1);
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

    await expect(releasePushForSignOut()).resolves.toBe(true);

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

    await expect(releasePushForSignOut()).resolves.toBe(true);
    expect(queries).toEqual([]);
  });

  it('has nothing to release when the browser cannot do push', async () => {
    await expect(releasePushForSignOut()).resolves.toBe(true);
    expect(queries).toEqual([]);
  });

  it.each([
    ['the delete is refused', () => mockDeleteResult.mockResolvedValue({ error: { message: 'connection reset' } })],
    ['the delete request throws', () => mockDeleteResult.mockRejectedValue(new Error('offline'))],
    ['no session is left that could delete the row', () => mockGetSession.mockResolvedValue({ data: { session: null } })],
  ])('reports false when %s', async (_name, arrange) => {
    subscribedBrowser(browserSub('https://push.example/mine'));
    arrange();

    await expect(releasePushForSignOut()).resolves.toBe(false);
  });

  it('reports false when the browser subscription cannot be read', async () => {
    installNotification('granted');
    installPushManager();
    installUnreadableServiceWorker();

    await expect(releasePushForSignOut()).resolves.toBe(false);
  });
});

describe('dropBrowserPushSubscription', () => {
  it('unsubscribes the browser so the endpoint dies, writing no rows', async () => {
    const browserUnsub = vi.fn(async () => true);
    subscribedBrowser(browserSub('https://push.example/orphan', browserUnsub));

    await dropBrowserPushSubscription();

    expect(browserUnsub).toHaveBeenCalledTimes(1);
    expect(queries).toEqual([]);
  });

  it('resolves when the browser holds no subscription', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });

    await expect(dropBrowserPushSubscription()).resolves.toBeUndefined();
  });

  it('rejects when the browser keeps the subscription', async () => {
    subscribedBrowser(browserSub('https://push.example/orphan', vi.fn(async () => false)));

    await expect(dropBrowserPushSubscription()).rejects.toThrow();
  });
});
