import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockGetDeviceId = vi.fn<() => Promise<string | null>>();
const mockUpsert = vi.fn<(...args: unknown[]) => Promise<{ error: { message: string } | null }>>();
const mockDelete = vi.fn(() => ({
  eq: vi.fn(() => ({
    eq: vi.fn(() => Promise.resolve({ error: null })),
  })),
}));

vi.mock('./supabase', () => ({
  getDeviceId: () => mockGetDeviceId(),
  supabase: {
    from: (_table: string) => ({
      upsert: (...args: unknown[]) => mockUpsert(...args),
      delete: () => mockDelete(),
    }),
  },
}));

import {
  getPushStatus,
  isPushSupported,
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

beforeEach(() => {
  removeGlobals();
  mockGetDeviceId.mockReset();
  mockUpsert.mockReset();
  mockDelete.mockClear();
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

  it('returns "subscribed" when the service worker has an active push subscription', async () => {
    installNotification('granted');
    installPushManager();
    mockSubscription = {
      endpoint: 'https://push.example/sub',
      toJSON: () => ({ keys: { p256dh: 'p', auth: 'a' } }),
      unsubscribe: vi.fn(async () => true),
    };
    installServiceWorker({ hasRegistration: true });
    expect(await getPushStatus()).toBe('subscribed');
  });

  it('returns "default" when getRegistration throws (swallows the error)', async () => {
    installNotification('default');
    installPushManager();
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: {
        getRegistration: vi.fn(async () => { throw new Error('boom'); }),
      },
    });
    expect(await getPushStatus()).toBe('default');
  });
});

describe('subscribeToPush', () => {
  it('returns false when push is not supported', async () => {
    expect(await subscribeToPush('vapid-key')).toBe(false);
  });

  it('returns false when vapidPublicKey is the empty string', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    expect(await subscribeToPush('')).toBe(false);
  });

  it('returns false when the user denies the notification permission prompt', async () => {
    installNotification('default', 'denied');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    expect(await subscribeToPush('AAAA')).toBe(false);
  });

  it('returns false when getDeviceId resolves to null (no anonymous session)', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    mockGetDeviceId.mockResolvedValue(null);
    expect(await subscribeToPush('AAAA')).toBe(false);
  });

  it('upserts the subscription to push_subscriptions with the correct shape on success', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });

    const ok = await subscribeToPush('AAAA');

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
    installNotification('granted');
    installPushManager();
    mockSubscription = {
      endpoint: 'https://push.example/existing',
      toJSON: () => ({ keys: { p256dh: 'p', auth: 'a' } }),
      unsubscribe: vi.fn(async () => true),
    };
    installServiceWorker({ hasRegistration: true });

    const ok = await subscribeToPush('AAAA');

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

    expect(await subscribeToPush('AAAA')).toBe(false);
    expect(mockUpsert).not.toHaveBeenCalled();
  });

  it('returns false when the Supabase upsert returns an error (e.g. table does not exist)', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    mockUpsert.mockResolvedValue({ error: { message: 'relation does not exist' } });

    expect(await subscribeToPush('AAAA')).toBe(false);
  });
});

describe('unsubscribeFromPush', () => {
  it('is a no-op when push is not supported', async () => {
    await expect(unsubscribeFromPush()).resolves.toBeUndefined();
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it('is a no-op when there is no registration', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: false });
    await unsubscribeFromPush();
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it('is a no-op when there is no active subscription on the registration', async () => {
    installNotification('granted');
    installPushManager();
    installServiceWorker({ hasRegistration: true });
    mockSubscription = null;
    await unsubscribeFromPush();
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it('unsubscribes the browser-side subscription AND deletes the row from push_subscriptions on success', async () => {
    installNotification('granted');
    installPushManager();
    const browserUnsub = vi.fn(async () => true);
    mockSubscription = {
      endpoint: 'https://push.example/byebye',
      toJSON: () => ({ keys: { p256dh: 'p', auth: 'a' } }),
      unsubscribe: browserUnsub,
    };
    installServiceWorker({ hasRegistration: true });

    await unsubscribeFromPush();

    expect(browserUnsub).toHaveBeenCalledTimes(1);
    expect(mockDelete).toHaveBeenCalledTimes(1);
  });

  it('skips the supabase delete when getDeviceId returns null but still unsubscribes the browser', async () => {
    installNotification('granted');
    installPushManager();
    const browserUnsub = vi.fn(async () => true);
    mockSubscription = {
      endpoint: 'https://push.example/nodevice',
      toJSON: () => ({ keys: { p256dh: 'p', auth: 'a' } }),
      unsubscribe: browserUnsub,
    };
    installServiceWorker({ hasRegistration: true });
    mockGetDeviceId.mockResolvedValue(null);

    await unsubscribeFromPush();

    expect(browserUnsub).toHaveBeenCalledTimes(1);
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it('swallows thrown errors from the browser unsubscribe path', async () => {
    installNotification('granted');
    installPushManager();
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: {
        getRegistration: vi.fn(async () => { throw new Error('boom'); }),
      },
    });
    await expect(unsubscribeFromPush()).resolves.toBeUndefined();
  });
});
