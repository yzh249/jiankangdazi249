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
    st.success(f"已经和 {partner['public_id']} 绑定（{pair['created_at'][:10]}）")
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
    st.subheader("输入对方 ID 直接绑定")
    st.caption("让对方先登录一次拿到 ID，然后你在这里输入即可。")
    partner_id_input = st.text_input("对方 ID", placeholder="例如 apple2024")
    if st.button("绑定搭子", type="primary", width="stretch"):
        ok, message = db.bind_by_public_id(uid, partner_id_input)
        if ok:
            st.session_state["pair_flash"] = message
            st.rerun()
        else:
            st.error(message)
