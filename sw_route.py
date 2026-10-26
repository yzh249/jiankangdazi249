"""PWA 注入层：包装 uvicorn 的 loaded_app，在 ASGI 层拦截请求。

拦截内容：
- /-/build/manifest.json、/manifest.json  -> 我们的 PWA manifest
- /sw.js                                  -> Service Worker（带 Service-Worker-Allowed: /）
- /-/build/favicon_256.png、/favicon.ico、/static/icon-*.png -> 应用图标
- GET /（首页 HTML）-> 在 </head> 前注入 PWA meta + SW 注册脚本
"""
import base64
import gc

from pwa_head import (
    ICON192M_B64,
    ICON192_B64,
    ICON512M_B64,
    ICON512_B64,
    MANIFEST_B64,
    SW_B64,
)

_installed = False


def _b64(data: str) -> bytes:
    return base64.b64decode(data)


_PATHS = {
    "/-/build/manifest.json": (_b64(MANIFEST_B64), "application/manifest+json", None),
    "/manifest.json": (_b64(MANIFEST_B64), "application/manifest+json", None),
    "/sw.js": (_b64(SW_B64), "application/javascript", {"Service-Worker-Allowed": "/"}),
    "/-/build/favicon_256.png": (_b64(ICON192_B64), "image/png", None),
    "/favicon.ico": (_b64(ICON192_B64), "image/png", None),
    "/static/icon-192.png": (_b64(ICON192_B64), "image/png", None),
    "/static/icon-512.png": (_b64(ICON512_B64), "image/png", None),
    "/static/icon-192-maskable.png": (_b64(ICON192M_B64), "image/png", None),
    "/static/icon-512-maskable.png": (_b64(ICON512M_B64), "image/png", None),
}

_HEAD_TAGS = (
    '<meta name="theme-color" content="#4caf50">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
    '<meta name="apple-mobile-web-app-title" content="健康搭子">'
    '<link rel="apple-touch-icon" sizes="192x192" href="/static/icon-192.png">'
    '<script>navigator.serviceWorker.register("/sw.js",{scope:"/"}).catch(function(){});</script>'
).encode("utf-8")


async def _send_bytes(send, body: bytes, ctype: str, extra=None) -> None:
    headers = [
        (b"content-type", ctype.encode("ascii")),
        (b"cache-control", b"no-cache"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    for k, v in (extra or {}).items():
        headers.append((k.encode("ascii"), v.encode("ascii")))
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _finalize_html(holder):
    start = holder["start"]
    body = b"".join(holder["chunks"])
    if start is None:
        return {"type": "http.response.start", "status": 200, "headers": []}, body
    ctype_ok = False
    has_encoding = False
    for k, v in start.get("headers") or []:
        nk = k.decode("latin-1").lower()
        if nk == "content-type":
            ctype_ok = b"text/html" in v
        elif nk == "content-encoding":
            has_encoding = True
    if (
        start.get("status") == 200
        and ctype_ok
        and not has_encoding
        and 0 < len(body) < 2_000_000
        and b"</head>" in body
    ):
        body = body.replace(b"</head>", _HEAD_TAGS + b"</head>", 1)
        hdrs = [
            (k, v)
            for k, v in start["headers"]
            if k.decode("latin-1").lower() != "content-length"
        ]
        hdrs.append((b"content-length", str(len(body)).encode("ascii")))
        start = dict(start)
        start["headers"] = hdrs
    return start, body


async def _send_html_injected(app, scope, receive, send) -> None:
    holder = {"start": None, "chunks": []}

    async def capture(message):
        mtype = message.get("type")
        if mtype == "http.response.start":
            holder["start"] = message
        elif mtype == "http.response.body":
            holder["chunks"].append(message.get("body") or b"")
            if not message.get("more_body", False):
                start, body = _finalize_html(holder)
                await send(start)
                await send({"type": "http.response.body", "body": body})

    await app(scope, receive, capture)


def _wrap_asgi(app):
    async def wrapped(scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") == "GET":
            path = scope.get("path", "")
            hit = _PATHS.get(path)
            if hit is not None:
                try:
                    body, ctype, extra = hit
                    await _send_bytes(send, body, ctype, extra)
                    return
                except Exception as e:
                    print(f"[PWA] static intercept error: {e}")
            elif path in ("/", "/index.html"):
                await _send_html_injected(app, scope, receive, send)
                return
        await app(scope, receive, send)

    wrapped._pwa_wrapped = True
    return wrapped


def _install_via_uvicorn() -> bool:
    try:
        import uvicorn
    except Exception as e:
        print(f"[PWA] uvicorn import failed: {e}")
        return False
    servers = [o for o in gc.get_objects() if isinstance(o, uvicorn.Server)]
    print(f"[PWA] uvicorn.Server instances: {len(servers)}")
    for srv in servers:
        cfg = getattr(srv, "config", None)
        app = getattr(cfg, "loaded_app", None) if cfg is not None else None
        if app is None:
            continue
        if getattr(app, "_pwa_wrapped", False):
            return True
        cfg.loaded_app = _wrap_asgi(app)
        print("[PWA] wrapped uvicorn config.loaded_app")
        return True
    return False


def _install_via_starlette() -> bool:
    try:
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Route
    except Exception as e:
        print(f"[PWA] starlette import failed: {e}")
        return False

    def _handler(body, ctype, extra):
        async def handler(request):
            return Response(content=body, media_type=ctype, headers=extra or {})
        return handler

    done = False
    for obj in gc.get_objects():
        if isinstance(obj, Starlette):
            try:
                routes = obj.router.routes
                if any(getattr(r, "path", None) == "/sw.js" for r in routes):
                    return True
                for path, (body, ctype, extra) in reversed(list(_PATHS.items())):
                    routes.insert(0, Route(path, _handler(body, ctype, extra), methods=["GET"]))
                done = True
                print("[PWA] starlette routes inserted")
            except Exception as e:
                print(f"[PWA] starlette route insert failed: {e}")
    return done


def install_pwa() -> None:
    global _installed
    if _installed:
        return
    try:
        ok = _install_via_uvicorn()
        if not ok:
            ok = _install_via_starlette()
        if ok:
            _installed = True
            print("[PWA] install ok")
        else:
            print("[PWA] install pending, retry on next run")
    except Exception as e:
        print(f"[PWA] install error: {e}")


def register_sw_component() -> None:
    """首次访问兜底：用同源 iframe 注册 Service Worker。"""
    try:
        import streamlit.components.v1 as components

        components.html(
            '<script>navigator.serviceWorker.register("/sw.js",{scope:"/"}).catch(function(){});</script>',
            height=0,
        )
    except Exception:
        pass
