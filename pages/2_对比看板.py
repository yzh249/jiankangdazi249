import altair as alt
import pandas as pd
import streamlit as st
from datetime import timedelta

import db
import nutrition
from common import setup, require_login, sidebar

setup("对比看板", "📊")
uid = require_login()
sidebar()

me = db.get_user(uid)
partner_id = db.get_partner_id(uid)
partner = db.get_user(partner_id) if partner_id else None
today = db.today()
today_str = today.isoformat()
my_target = db.get_target(uid)
mine = db.day_total(uid, today_str)

st.title("对比看板")

st.subheader("今日对照")
if partner:
    partner_target = db.get_target(partner_id)
    theirs = db.day_total(partner_id, today_str)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(f"我 · {me['public_id']}", f"{mine['kcal']:.0f} 千卡")
        st.progress(
            min(mine["kcal"] / my_target, 1.0) if my_target else 0.0,
            text=f"目标 {my_target:.0f} 千卡",
        )
    with c2:
        st.metric(f"搭子 · {partner['public_id']}", f"{theirs['kcal']:.0f} 千卡")
        st.progress(
            min(theirs["kcal"] / partner_target, 1.0) if partner_target else 0.0,
            text=f"目标 {partner_target:.0f} 千卡",
        )
    with c3:
        diff = mine["kcal"] - theirs["kcal"]
        st.metric("今日差值", f"{diff:+.0f} 千卡")
        st.caption("正数表示你比搭子吃得多")

    st.info(nutrition.daily_message(
        me["public_id"], mine["kcal"], my_target,
        partner["public_id"], theirs["kcal"], partner_target,
    ))
else:
    c1, c2 = st.columns(2)
    with c1:
        st.metric("我今日摄入", f"{mine['kcal']:.0f} 千卡")
        st.progress(
            min(mine["kcal"] / my_target, 1.0) if my_target else 0.0,
            text=f"目标 {my_target:.0f} 千卡",
        )
    with c2:
        st.info("还没有绑定搭子，绑定后这里会并排显示两个人的数据。")
        st.page_link("pages/3_搭档.py", label="去绑定搭子", icon="🤝")

st.divider()
st.subheader("历史趋势")
days = st.radio("范围", [7, 30], format_func=lambda d: f"近 {d} 天", horizontal=True)
start = (today - timedelta(days=days - 1)).isoformat()

rows = []
for person_id, label in [(uid, me["public_id"])] + (
    [(partner_id, partner["public_id"])] if partner else []
):
    for r in db.daily_totals(person_id, start, today_str):
        rows.append({"日期": r["d"], "热量": r["kcal"], "谁": label})

trend = pd.DataFrame(rows)
if trend.empty:
    st.info("这段时间还没有打卡数据。")
else:
    trend["日期"] = pd.to_datetime(trend["日期"])
    chart = alt.Chart(trend).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("日期:T", title=None, axis=alt.Axis(
            format="%m-%d", labelAngle=-45, labelOverlap="greedy",
            tickCount=min(days, 10),
        )),
        y=alt.Y("热量:Q", title="摄入热量（千卡）"),
        color=alt.Color("谁:N", title=None),
        tooltip=[
            alt.Tooltip("日期:T", format="%Y-%m-%d"),
            alt.Tooltip("谁:N"),
            alt.Tooltip("热量:Q", format=".0f"),
        ],
    ).properties(height=320)
    st.altair_chart(chart, width="stretch")

st.divider()
st.subheader("当天记录")
view_day = st.date_input("查看日期", value=today, key="history_day")
view_str = view_day.isoformat()

columns = st.columns(2) if partner else st.columns(1)
people = [(uid, me["public_id"])] + ([(partner_id, partner["public_id"])] if partner else [])
for col, (person_id, label) in zip(columns, people):
    with col:
        total = db.day_total(person_id, view_str)
        st.markdown(f"**{label}** · {total['kcal']:.0f} 千卡")
        meals = db.get_meals(person_id, view_str)
        if not meals:
            st.caption("这天没有记录。")
        for meal in meals:
            img = db.get_image(meal["image_path"])
            if img is not None:
                st.image(img, width=220)
            st.caption(
                f"{meal['meal_type']} · {meal['eaten_at'][11:16]} · {meal['kcal']:.0f} 千卡"
            )
            items = db.get_meal_items(meal["id"])
            if items:
                st.caption("、".join(f"{i['food_name']} {i['grams']:.0f}g" for i in items))
