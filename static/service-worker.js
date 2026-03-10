/* Orrbit Service Worker — cache static assets, offline fallback */

const CACHE_NAME = 'orrbit-v4';
const STATIC_ASSETS = [
  '/static/css/style.css',
  '/static/js/browse.js',
  '/static/js/root.js',
  '/static/js/settings.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// Install: pre-cache static assets
self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(n) { return n !== CACHE_NAME; })
             .map(function(n) { return caches.delete(n); })
      );
    })
  );
  self.clients.claim();
});

// Fetch: network-first for API/pages, cache-first for static assets
self.addEventListener('fetch', function(event) {
  var url = new URL(event.request.url);

  // Never cache API calls or POST requests
  if (event.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return;

  // Static assets: cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then(function(cached) {
        return cached || fetch(event.request).then(function(response) {
          if (response.ok) {
            var clone = response.clone();
            caches.open(CACHE_NAME).then(function(cache) {
              cache.put(event.request, clone);
            });
          }
          return response;
        });
      })
    );
    return;
  }

  // Pages: network-first with offline fallback
  event.respondWith(
    fetch(event.request).catch(function() {
      return caches.match(event.request).then(function(cached) {
        return cached || new Response(
          '<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Offline</title><style>body{background:#1a1a1a;color:#e0e0e0;font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}div{text-align:center}h1{font-size:1.5rem}p{color:#888}</style></head><body><div><h1>Offline</h1><p>Check your connection and try again.</p></div></body></html>',
          { headers: { 'Content-Type': 'text/html' } }
        );
      });
    })
  );
});
