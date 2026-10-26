"""拦截 Streamlit 默认 manifest 请求，返回我们的 PWA manifest。"""
import base64
import gc

from pwa_head import PWA_HEAD_B64

_manifest_added = False


def _get_manifest_json() -> str:
    head = base64.b64decode(PWA_HEAD_B64).decode("utf-8")
    start = head.find("base64,")
    if start == -1:
        return "{}"
    start += len("base64,")
    end = head.find('"', start)
    manifest_b64 = head[start:end]
    return base64.b64decode(manifest_b64).decode("utf-8")


def install_manifest_route() -> None:
    global _manifest_added
    if _manifest_added:
        return
    try:
        from streamlit.web.server.starlette import UvicornServer

        app = None
        for obj in gc.get_objects():
            if isinstance(obj, UvicornServer):
                server = getattr(obj, "_server", None)
                if server is not None:
                    app = getattr(server, "app", None)
                if app is not None:
                    break

        if app is None:
            print("[PWA] Starlette app not found")
            return

        manifest_json = _get_manifest_json()

        from starlette.responses import Response
        from starlette.routing import Route

        async def manifest_handler(request):
            return Response(
                content=manifest_json,
                media_type="application/manifest+json",
                headers={"Cache-Control": "no-cache"},
            )

        new_route = Route("/-/build/manifest.json", manifest_handler)

        # 插入到路由列表最前面
        routes = getattr(app, "routes", None)
        if routes is not None:
            routes.insert(0, new_route)
            _manifest_added = True
            print("[PWA] manifest route installed via Starlette")
        else:
            print("[PWA] app.routes not found")
    except Exception as e:
        print(f"[PWA] install_manifest_route failed: {e}")
