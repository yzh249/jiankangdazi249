"""页面公共壳：统一配置、登录校验、移动端样式、侧边栏。"""
import datetime as dt

import streamlit as st

import db

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
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)
    # PWA manifest & icons 托管在 Vercel（独立静态站）
    PWA_BASE = "https://jiankangdazi-pwa.vercel.app"
    st.markdown(
        f'<link rel="manifest" href="{PWA_BASE}/manifest.json" />'
        '<meta name="theme-color" content="#4caf50" />'
        '<meta name="apple-mobile-web-app-capable" content="yes" />'
        '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />'
        '<meta name="apple-mobile-web-app-title" content="健康搭子" />'
        f'<link rel="apple-touch-icon" href="{PWA_BASE}/icon-192.png" />',
        unsafe_allow_html=True,
    )

def require_login() -> int:
    if not st.session_state.get("user_id"):
        st.warning("请先登录再使用")
        if st.button("去登录", width="stretch"):
            st.switch_page("app.py")
        st.stop()
    return int(st.session_state["user_id"])


# ---------- 操作反馈 ----------

_FLASH_KEY = "_flash_messages"


def flash(message: str, kind: str = "success") -> None:
    """写入一条跨 rerun 保留的提示，由 show_flash 统一展示。"""
    st.session_state.setdefault(_FLASH_KEY, []).append((kind, message))


def show_flash() -> None:
    renderers = {
        "success": st.success,
        "error": st.error,
        "warning": st.warning,
        "info": st.info,
    }
    for kind, message in st.session_state.pop(_FLASH_KEY, []):
        renderers.get(kind, st.info)(message)


# ---------- 日期 / 时间 ----------

def build_datetime(day, clock) -> tuple[str | None, str | None]:
    """把日期 + 时间拼成记录时间；不允许未来时间。返回 (时间串, 错误)。"""
    if day is None or clock is None:
        return None, "请选择日期和时间"
    if day > db.today():
        return None, "不能记录未来的日期"
    moment = dt.datetime.combine(day, clock).replace(tzinfo=db.TZ)
    if moment > dt.datetime.now(db.TZ) + dt.timedelta(minutes=1):
        return None, "时间不能晚于当前时间"
    return moment.strftime("%Y-%m-%d %H:%M:%S"), None


def now_clock() -> dt.time:
    return dt.datetime.now(db.TZ).time().replace(second=0, microsecond=0)


def pick_range(key_prefix: str) -> tuple[dt.date, dt.date]:
    """近 7/30/90 天或自定义范围，返回 (起始日, 结束日)。"""
    today = db.today()
    options = [7, 30, 90]
    choice = st.radio(
        "时间范围",
        [*options, "custom"],
        index=1,
        horizontal=True,
        format_func=lambda v: f"近 {v} 天" if isinstance(v, int) else "自定义",
        key=f"{key_prefix}_range",
    )
    if isinstance(choice, int):
        return today - dt.timedelta(days=choice - 1), today
    picked = st.date_input(
        "自定义日期",
        value=(today - dt.timedelta(days=29), today),
        max_value=today,
        key=f"{key_prefix}_range_custom",
    )
    start, end = _normalize_range(picked, today)
    return start, end


def date_range(key: str, default_days: int = 30) -> tuple[dt.date, dt.date]:
    """归档用的日期范围选择，返回 (起始日, 结束日)。"""
    today = db.today()
    picked = st.date_input(
        "日期范围",
        value=(today - dt.timedelta(days=default_days - 1), today),
        max_value=today,
        key=key,
    )
    return _normalize_range(picked, today)


def _normalize_range(picked, fallback: dt.date) -> tuple[dt.date, dt.date]:
    if isinstance(picked, (tuple, list)):
        if len(picked) == 2:
            start, end = picked
        elif len(picked) == 1:
            start = end = picked[0]
        else:
            start = end = fallback
    elif picked:
        start = end = picked
    else:
        start = end = fallback
    if start > end:
        start, end = end, start
    return start, end


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
