// Service Worker for 健康搭子 PWA
const CACHE_NAME = 'jiankangdazi-v2';
const PRECACHE_URLS = ['/', '/-/build/manifest.json'];

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
// 策略：图标/manifest 走缓存优先，页面导航走网络优先（失败回缓存壳），其余全部直连网络。
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 只处理 GET
  if (event.request.method !== 'GET') return;

  // Streamlit 通信通道（websocket / _stcore）必须走网络，不缓存
  if (url.pathname.startsWith('/_stcore')) return;

  // 图标与 manifest：cache-first（这些路径由服务端拦截层返回，稳定不变）
  const cacheable =
    url.pathname.startsWith('/static/icon-') ||
    url.pathname === '/-/build/manifest.json' ||
    url.pathname === '/manifest.json';
  if (cacheable) {
    event.respondWith(
      caches.match(event.request).then((cached) =>
        cached ||
        fetch(event.request).then((resp) => {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE_NAME).then((c) => c.put(event.request, clone));
          }
          return resp;
        })
      )
    );
    return;
  }

  // 页面导航：network-first，失败回缓存壳
  if (url.pathname === '/' || url.pathname === '/index.html') {
    event.respondWith(
      fetch(event.request)
        .then((resp) => {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE_NAME).then((c) => c.put('/', clone));
          }
          return resp;
        })
        .catch(() => caches.match('/').then((r) => r || new Response('离线中，请检查网络', { status: 504 })))
    );
  }
  // 其余请求（/static/js 等）不接管，走浏览器默认行为
});
