"""登录 / 注册 / 首页。运行：streamlit run app.py"""
import streamlit as st

import db
from common import setup

setup("登录", "🥗")


def render_home(uid: int) -> None:
    user = db.get_user(uid)
    partner_id = db.get_partner_id(uid)
    profile = db.get_profile(uid)
    target = db.get_target(uid)
    today = db.today().isoformat()
    mine = db.day_total(uid, today)

    with st.sidebar:
        st.markdown(f"### 🥗 {user['nickname']}")
        if partner_id:
            st.caption(f"👫 搭子：{db.get_user(partner_id)['nickname']}")
        else:
            st.caption("👫 还没绑定搭子")
        st.divider()
        with st.expander("⚙️ AI Key"):
            st.text_input("智谱 API Key", key="zhipu_key", type="password",
                          placeholder="粘贴后立即生效")
            st.caption("只保存在当前会话。没有 Key 时使用规则点评。")
        if st.button("退出登录", width="stretch"):
            st.session_state.pop("user_id", None)
            st.rerun()

    st.title(f"你好，{user['nickname']} 👋")
    st.caption("今天也一起好好吃饭。数据只给你和搭子看。")

    if not profile:
        st.info("先设置身高体重和目标，热量进度才有意义。")
        st.page_link("pages/4_我的目标.py", label="去设置目标", icon="🎯")

    c1, c2, c3 = st.columns(3)
    c1.metric("今日摄入", f"{mine['kcal']:.0f} 千卡")
    c2.metric("每日目标", f"{target:.0f} 千卡")
    gap = target - mine["kcal"]
    c3.metric("剩余额度" if gap >= 0 else "已超出", f"{abs(gap):.0f} 千卡")

    st.progress(min(mine["kcal"] / target, 1.0) if target else 0.0,
                text=f"{mine['kcal']:.0f} / {target:.0f} 千卡")

    if partner_id:
        partner = db.get_user(partner_id)
        theirs = db.day_total(partner_id, today)
        diff = mine["kcal"] - theirs["kcal"]
        st.caption(
            f"搭子 {partner['nickname']} 今天吃了 {theirs['kcal']:.0f} 千卡，"
            + (f"你比 TA 多 {diff:.0f} 千卡。" if diff >= 0 else f"你比 TA 少 {abs(diff):.0f} 千卡。")
        )
    else:
        st.info("还没有搭子。生成一个邀请码，发给朋友就能互相监督。")
        st.page_link("pages/3_搭档.py", label="去绑定搭子", icon="🤝")

    st.divider()
    st.subheader("快速入口")
    l1, l2, l3, l4 = st.columns(4)
    with l1:
        st.page_link("pages/1_今日打卡.py", label="拍照打卡", icon="📸")
    with l2:
        st.page_link("pages/2_对比看板.py", label="对比看板", icon="📊")
    with l3:
        st.page_link("pages/3_搭档.py", label="搭档管理", icon="🤝")
    with l4:
        st.page_link("pages/4_我的目标.py", label="设置目标", icon="🎯")


if st.session_state.get("user_id"):
    render_home(int(st.session_state["user_id"]))
    st.stop()

st.title("🥗 健康搭子")
st.caption("双人饮食热量监督 · 拍照识别 · 互相可见 · 只给熟人用")

tab_login, tab_register = st.tabs(["登录", "注册"])

with tab_login:
    with st.form("login_form"):
        nick = st.text_input("昵称", placeholder="2-12 个字符")
        pin = st.text_input("4 位 PIN", type="password", max_chars=4)
        submitted = st.form_submit_button("登录", type="primary", width="stretch")
    if submitted:
        uid = db.verify_user(nick, pin)
        if uid:
            st.session_state["user_id"] = uid
            st.rerun()
        else:
            st.error("昵称或 PIN 不对")

with tab_register:
    with st.form("register_form"):
        nick = st.text_input("昵称", placeholder="和朋友互相认得出的名字")
        pin = st.text_input("设置 4 位数字 PIN", type="password", max_chars=4)
        submitted = st.form_submit_button("注册", type="primary", width="stretch")
    if submitted:
        nick = nick.strip()
        if not (2 <= len(nick) <= 12):
            st.error("昵称需要 2-12 个字符")
        elif not (len(pin) == 4 and pin.isdigit()):
            st.error("PIN 必须是 4 位数字")
        else:
            try:
                uid = db.create_user(nick, pin)
                st.session_state["user_id"] = uid
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

with st.expander("它能做什么"):
    st.markdown(
        """
        - 📸 拍张照片，自动识别食物和分量
        - ✍️ AI 估错一眼就能改，热量实时重算
        - 📊 和搭子并排看今天吃了多少
        - 🤖 温和的饮食点评，不制造焦虑
        """
    )
