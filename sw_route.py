"""拦截 Streamlit 默认 manifest 请求，返回我们的 PWA manifest。"""
import base64
import json

from pwa_head import PWA_HEAD_B64

_manifest_added = False


def _get_manifest_json() -> str:
    """从 PWA_HEAD 里提取 manifest data URI 并解码。"""
    head = base64.b64decode(PWA_HEAD_B64).decode("utf-8")
    # PWA_HEAD 格式: <link rel="manifest" href="data:application/manifest+json;base64,...">
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
        from streamlit.runtime import get_instance

        runtime = get_instance()
        server = getattr(runtime, "_server", None)
        if server is None:
            return
        app = getattr(server, "_app", None)
        if app is None:
            return

        manifest_json = _get_manifest_json()

        import tornado.web

        class ManifestHandler(tornado.web.RequestHandler):
            def get(self):
                self.set_header("Content-Type", "application/manifest+json")
                self.set_header("Cache-Control", "no-cache")
                self.write(manifest_json)

        # 插入到路由最前面，覆盖 Streamlit 默认 manifest
        from tornado.routing import Rule, PathMatches

        rule = Rule(PathMatches(r"/-/build/manifest\.json"), ManifestHandler)
        if hasattr(app, "default_router") and hasattr(app.default_router, "rules"):
            app.default_router.rules.insert(0, rule)
            _manifest_added = True
            print("[PWA] manifest route installed")
        elif hasattr(app, "add_handlers"):
            app.add_handlers(r".*", [(r"/-/build/manifest\.json", ManifestHandler)])
            _manifest_added = True
            print("[PWA] manifest route added (fallback)")
    except Exception as e:
        print(f"[PWA] install_manifest_route failed: {e}")
