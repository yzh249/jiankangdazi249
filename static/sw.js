// Service Worker for 健康搭子 PWA
const CACHE_NAME = 'jiankangdazi-v1';
const PRECACHE_URLS = ['/', '/static/manifest.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Streamlit 是服务端渲染，核心数据必须在线获取。
// 策略：静态资源优先走缓存，其他请求走网络，失败时回退缓存壳。
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 只缓存 GET
  if (event.request.method !== 'GET') return;

  // 静态文件 /static/* 走 cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then((cached) =>
        cached ||
        fetch(event.request).then((resp) => {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(event.request, clone));
          return resp;
        }).catch(() => cached)
      )
    );
    return;
  }

  // Streamlit 通信通道（websocket / _stcore）必须走网络，不缓存
  if (url.pathname.startsWith('/_stcore')) return;

  // 其他（页面导航）走 network-first，失败回缓存壳
  event.respondWith(
    fetch(event.request)
      .then((resp) => {
        if (resp.ok && event.request.destination === 'document') {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put('/', clone));
        }
        return resp;
      })
      .catch(() => caches.match('/').then((r) => r || new Response('离线中，请检查网络', { status: 504 })))
  );
});
