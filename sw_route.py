"""通过 Streamlit 内部 Tornado 服务器添加 /sw.js 路由，使 service worker 可以注册。"""
import streamlit as st
from pwa_head import SW_B64
import base64

_sw_added = False


def add_sw_route() -> None:
    """尝试向 Streamlit 的 Tornado app 添加 /sw.js 路由。失败则静默跳过。"""
    global _sw_added
    if _sw_added:
        return
    try:
        from streamlit.runtime import get_instance

        runtime = get_instance()
        server = getattr(runtime, "_server", None)
        if server is None:
            return
        tornado_app = getattr(server, "_app", None)
        if tornado_app is None:
            return

        sw_code = base64.b64decode(SW_B64).decode("utf-8")

        import tornado.web

        class SWHandler(tornado.web.RequestHandler):
            def get(self):
                self.set_header("Content-Type", "application/javascript")
                self.set_header("Service-Worker-Allowed", "/")
                self.write(sw_code)

        tornado_app.add_handlers(r".*", [(r"/sw\.js", SWHandler)])
        _sw_added = True
        print("[PWA] /sw.js route added")
    except Exception as e:
        print(f"[PWA] add_sw_route failed: {e}")
