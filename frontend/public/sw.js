// Old registrations update this script even while the app is closed. Keep an
// untouched legacy install working until a page can verify its subscription.
// All new registrations use /sw.js?account=1 and always require a binding.
self.addEventListener('push', (event) => {
  event.waitUntil(displayReminder(event));
});

async function displayReminder(event) {
  let payload;
  try { payload = event.data?.json(); } catch { return; }
  if (!payload) return;
  const show = () => self.registration.showNotification(payload.title || 'JoinALab', {
    body: payload.body, icon: '/icon-192.png', badge: '/icon-192.png',
    tag: payload.tag || 'ofe-reminder', data: { url: payload.url || '/dashboard' },
  });
  const name = 'ofe-push-binding-v1';
  if (!self.location.search && !await caches.has(name)) return show();
  if (!payload.recipient || !navigator.locks) return;
  await navigator.locks.request('ofe-push-binding', async () => {
    const cache = await caches.open(name);
    const entry = await cache.match('/.ofe/push-owner');
    const binding = entry && await entry.json();
    if (binding?.enabled === true && binding.uid === payload.recipient) await show();
  });
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || '/dashboard';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (client.url.includes(url) && 'focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    }),
  );
});

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
