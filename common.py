"""页面公共壳：统一配置、登录校验、移动端样式、侧边栏。"""
import streamlit as st

import db
from sw_route import install_pwa, pwa_status, register_sw_component

MOBILE_CSS = """
<style>
@media (max-width: 820px) {
  .block-container { padding: 2.5rem 0.75rem 4rem 0.75rem; max-width: 100%; }
  h1 { font-size: 1.45rem; }
  h2 { font-size: 1.2rem; }
  h3 { font-size: 1.05rem; }
  div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 0.4rem; }
  div[data-testid="stColumn"] { min-width: 150px; flex: 1 1 45%; }
  div[data-testid="column"] { min-width: 150px; flex: 1 1 45%; }
  [data-testid="stMetricValue"] { font-size: 1.35rem; }
  .stButton button, .stFormSubmitButton button { min-height: 44px; font-size: 1rem; }
  input, textarea { font-size: 16px !important; }
}
</style>
"""


def setup(title: str, icon: str = "🥗") -> None:
    st.set_page_config(page_title=f"{title} · 健康搭子", page_icon=icon, layout="wide")
    db.init_db()
    install_pwa()
    register_sw_component()
    st.caption(f"{st.__version__} · {pwa_status()}")
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)


def require_login() -> int:
    if not st.session_state.get("user_id"):
        st.warning("请先登录再使用")
        if st.button("去登录", width="stretch"):
            st.switch_page("app.py")
        st.stop()
    return int(st.session_state["user_id"])


def sidebar() -> None:
    uid = int(st.session_state["user_id"])
    user = db.get_user(uid)
    partner_id = db.get_partner_id(uid)
    partner_name = db.get_user(partner_id)["public_id"] if partner_id else None

    with st.sidebar:
        st.markdown(f"### 🥗 {user['public_id'] if user else ''}")
        st.caption(f"👫 搭子：{partner_name}" if partner_name else "👫 还没绑定搭子")
        st.divider()
        with st.expander("⚙️ AI Key"):
            st.text_input(
                "智谱 API Key",
                key="zhipu_key",
                type="password",
                placeholder="粘贴后立即生效",
            )
            st.caption("只保存在当前会话。没有 Key 时使用规则点评。")
        if st.button("退出登录", width="stretch"):
            st.session_state.pop("user_id", None)
            st.switch_page("app.py")
