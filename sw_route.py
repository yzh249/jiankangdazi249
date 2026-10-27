"""PWA 入口：用同源 iframe 注入 meta 标签 + 注册 Service Worker。

Docker+nginx 部署时，nginx 直接服务 /manifest.json、/sw.js、/static/*，
不需要 Python 层拦截。纯客户端注册 + SW 缓存离线。
"""


def install_pwa() -> None:
    pass


def register_sw_and_meta() -> None:
    import streamlit.components.v1 as components

    js = r"""
(function () {
  try {
    var head = parent.document.head;
    function addMeta(name, content) {
      var existing = head.querySelector('meta[name="' + name + '"]');
      if (existing) { existing.setAttribute('content', content); return; }
      var m = document.createElement('meta');
      m.name = name; m.content = content; head.appendChild(m);
    }
    function addLink(rel, href, attrs) {
      var existing = head.querySelector('link[rel="' + rel + '"][href="' + href + '"]');
      if (existing) return;
      var l = document.createElement('link'); l.rel = rel; l.href = href;
      if (attrs) for (var k in attrs) l.setAttribute(k, attrs[k]);
      head.appendChild(l);
    }
    addMeta('theme-color', '#4caf50');
    addMeta('mobile-web-app-capable', 'yes');
    addMeta('apple-mobile-web-app-capable', 'yes');
    addMeta('apple-mobile-web-app-status-bar-style', 'black-translucent');
    addMeta('apple-mobile-web-app-title', '健康搭子');
    addLink('apple-touch-icon', '/static/icon-192.png');
    addLink('manifest', '/manifest.json');
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js', {scope: '/'}).catch(function(){});
    }
  } catch (e) {}
})();
"""
    components.html(js, height=0)
