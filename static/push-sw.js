self.addEventListener('push', event => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) {}
  event.waitUntil(self.registration.showNotification(payload.title || 'Movieboxd', {
    body: payload.body || 'Yeni bir bildirimin var.',
    icon: '/static/favicon.ico',
    badge: '/static/favicon.ico',
    data: { url: '/#notifications' },
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windows => {
    const existing = windows.find(client => client.url.startsWith(self.location.origin));
    return existing ? existing.focus() : clients.openWindow(event.notification.data?.url || '/');
  }));
});
