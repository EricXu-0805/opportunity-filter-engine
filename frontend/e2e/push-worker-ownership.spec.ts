import { expect, test } from '@playwright/test';

// Chromium delivers these local payloads through the actual service worker.
// This does not contact a push provider or require an account or subscription.
test('the registered worker displays only the current account’s queued reminder', async ({ page, context, baseURL }) => {
  const origin = new URL(baseURL!).origin;
  await context.grantPermissions(['notifications'], { origin });
  await page.route('**/push-worker-check', route => route.fulfill({ contentType: 'text/html', body: '<title>Worker check</title>' }));
  const cdp = await context.newCDPSession(page);
  let registrationId = '';
  cdp.on('ServiceWorker.workerRegistrationUpdated', ({ registrations }) => {
    const registration = registrations.find(row => row.scopeURL === `${origin}/` && !row.isDeleted);
    if (registration) registrationId = registration.registrationId;
  });
  await cdp.send('ServiceWorker.enable');
  await page.goto('/push-worker-check');
  await page.evaluate(async () => {
    await navigator.serviceWorker.register('/sw.js?account=1');
    await navigator.serviceWorker.ready;
    const cache = await caches.open('ofe-push-binding-v1');
    await cache.put('/.ofe/push-owner', new Response(JSON.stringify({ uid: 'B', enabled: true })));
  });
  await expect.poll(() => registrationId).not.toBe('');
  for (const recipient of ['A', 'B']) {
    await cdp.send('ServiceWorker.deliverPushMessage', {
      origin, registrationId,
      data: JSON.stringify({ recipient, title: 'Test reminder', tag: `receipt-${recipient}`, url: '/tracker' }),
    });
  }
  await expect.poll(() => page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready;
    return (await registration.getNotifications()).map(item => item.tag).filter(tag => tag.startsWith('receipt-'));
  })).toEqual(['receipt-B']);
});
