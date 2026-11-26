import { chromium, expect, test as base } from '@playwright/test';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// Headless Shell acknowledges a CDP notification grant but its native
// showNotification rejects it. Full Chromium reads the actual profile setting.
const test = base.extend({
  context: async ({ baseURL }, use) => {
    const profile = await mkdtemp(join(tmpdir(), 'ofe-push-test-'));
    try {
      await mkdir(join(profile, 'Default'));
      await writeFile(join(profile, 'Default', 'Preferences'), JSON.stringify({
        profile: { default_content_setting_values: { notifications: 1 } },
      }));
      const context = await chromium.launchPersistentContext(profile, { channel: 'chromium', baseURL });
      try { await use(context); } finally { await context.close(); }
    } finally {
      await rm(profile, { recursive: true, force: true });
    }
  },
});

// Chromium delivers these local payloads through the actual service worker.
// This does not contact a push provider or require an account or subscription.
test('the registered worker displays only the current account’s queued reminder', async ({ page, context, baseURL }) => {
  const origin = new URL(baseURL!).origin;
  await page.route('**/push-worker-check', route => route.fulfill({ contentType: 'text/html', body: '<title>Worker check</title>' }));
  const cdp = await context.newCDPSession(page);
  let registrationId = '';
  cdp.on('ServiceWorker.workerRegistrationUpdated', ({ registrations }) => {
    const registration = registrations.find(row => row.scopeURL === `${origin}/` && !row.isDeleted);
    if (registration) registrationId = registration.registrationId;
  });
  await cdp.send('ServiceWorker.enable');
  await page.goto('/push-worker-check');
  const workerReady = context.waitForEvent('serviceworker');
  await page.evaluate(async () => {
    await navigator.serviceWorker.register('/sw.js?account=1');
    await navigator.serviceWorker.ready;
    const cache = await caches.open('ofe-push-binding-v1');
    await cache.put('/.ofe/push-owner', new Response(JSON.stringify({ uid: 'B', enabled: true })));
  });
  const worker = await workerReady;
  const arrivals = await worker.evaluateHandle(() => {
    const recipients: string[] = [];
    self.addEventListener('push', event => {
      const { data } = event as Event & { data: { json(): { recipient: string } } };
      recipients.push(data.json().recipient);
    });
    return recipients;
  });
  await expect.poll(() => registrationId).not.toBe('');
  for (const recipient of ['A', 'B']) {
    await cdp.send('ServiceWorker.deliverPushMessage', {
      origin, registrationId,
      data: JSON.stringify({ recipient, title: 'Test reminder', tag: `receipt-${recipient}`, url: '/tracker' }),
    });
  }
  await expect.poll(async () => (await arrivals.jsonValue()).sort()).toEqual(['A', 'B']);
  await expect.poll(() => page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready;
    return (await registration.getNotifications()).map(item => item.tag).filter(tag => tag.startsWith('receipt-'));
  })).toEqual(['receipt-B']);
});
