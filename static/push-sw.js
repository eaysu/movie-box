self.addEventListener('push', event => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) {}
  event.waitUntil(self.registration.showNotification(payload.title || 'Movieboxd', {
    body: payload.body || 'Yeni bir bildirimin var.',
    icon: '/static/movieboxd-icon-192.png',
    badge: '/static/movieboxd-icon-192.png',
    data: { url: '/#notifications' },
  }));
});

// Movieboxd is an installable web app. The worker intentionally does not
// cache API responses; it only establishes the PWA scope and handles push.
self.addEventListener('fetch', () => {});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windows => {
    const existing = windows.find(client => client.url.startsWith(self.location.origin));
    return existing ? existing.focus() : clients.openWindow(event.notification.data?.url || '/');
  }));
});
