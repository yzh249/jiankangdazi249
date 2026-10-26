import streamlit as st

import db
from common import setup, require_login, sidebar

setup("搭档管理", "🤝")
uid = require_login()
sidebar()

if "pair_flash" in st.session_state:
    st.success(st.session_state.pop("pair_flash"))

st.title("搭档管理")
partner_id = db.get_partner_id(uid)

if partner_id:
    partner = db.get_user(partner_id)
    pair = db.get_active_pair(uid)
    st.success(f"已经和 {partner['nickname']} 绑定（{pair['created_at'][:10]}）")
    st.caption("你们可以看到彼此的打卡记录和当日热量，但都不能修改对方的记录。")

    with st.expander("解除搭档关系"):
        st.caption("解绑后双方数据互相隔离，再也看不到对方的照片和饮食记录。")
        confirm = st.checkbox("我确认要解绑")
        if st.button("解除搭档", type="primary", disabled=not confirm):
            db.dissolve_pair(uid)
            st.session_state["pair_flash"] = "已解除搭档关系，双方数据已互相隔离。"
            st.rerun()
else:
    st.caption("一对一绑定：一个人同一时间只能有一个搭子。")
    invite = db.latest_invite(uid)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("我是发起方")
        st.caption("生成一个 6 位邀请码发给朋友，24 小时内有效。")
        if st.button("生成新的邀请码", width="stretch"):
            try:
                db.create_invite(uid)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if invite:
            st.code(invite["code"], language=None)
            st.caption(f"有效期至 {invite['expires_at'][:16]}")

    with c2:
        st.subheader("我是加入方")
        st.caption("输入朋友发来的邀请码，立刻绑定。")
        code = st.text_input("邀请码", max_chars=6, placeholder="例如 7KQ2M9")
        if st.button("绑定", type="primary", width="stretch"):
            ok, message = db.bind_invite(code, uid)
            if ok:
                st.session_state["pair_flash"] = "绑定成功"
                st.rerun()
            else:
                st.error(message)
