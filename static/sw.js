// Service Worker for 健康搭子 PWA — 纯缓存，nginx 服务正确静态文件
const CACHE_NAME = 'jiankangdazi-v3';
const PRECACHE_URLS = ['/', '/manifest.json'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(PRECACHE_URLS)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/_stcore')) return;
  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.json') {
    e.respondWith(
      caches.match(e.request).then(c =>
        c || fetch(e.request).then(r => {
          if (r.ok) { caches.open(CACHE_NAME).then(x => x.put(e.request, r.clone())); }
          return r;
        })
      )
    );
    return;
  }
  if (url.pathname === '/' || url.pathname === '/index.html') {
    e.respondWith(
      fetch(e.request).then(r => {
        if (r.ok) caches.open(CACHE_NAME).then(c => c.put('/', r.clone()));
        return r;
      }).catch(() => caches.match('/'))
    );
  }
});
