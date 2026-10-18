'use strict';
self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener('push', (event) => {
  event.waitUntil(
    self.registration.showNotification('JobPilot needs your help', {
      body: 'Open JobPilot to continue an application.',
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      tag: 'jobpilot-intervention',
    }),
  );
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (clients) => {
      for (const client of clients) {
        if (new URL(client.url).origin === self.location.origin) return client.focus();
      }
      return self.clients.openWindow('/');
    }),
  );
});
