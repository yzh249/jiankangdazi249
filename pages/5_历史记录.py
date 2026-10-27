"""历史记录：趋势统计（热量/体重折线图）+ 三类记录完整增删改查；搭子记录只读。"""
import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

import db
import nutrition
import ai_client
from common import (
    setup, require_login, sidebar, flash, show_flash,
    pick_range, build_datetime, now_clock,
)

setup("历史记录", "🗂️")
uid = require_login()
sidebar()
show_flash()

me = db.get_user(uid)
partner_id = db.get_partner_id(uid)
partner = db.get_user(partner_id) if partner_id else None
my_target = db.get_target(uid)

st.title("历史记录")
st.caption("自己的记录可以增删改查；搭子记录仅可查看，不能修改或删除。")

MEAL_TYPES = ["早餐", "午餐", "晚餐", "加餐"]

start, end = pick_range("hist")
start_s, end_s = start.isoformat(), end.isoformat()
range_days = (end - start).days + 1


# ---------- 统计图表 ----------

st.divider()
st.subheader("📈 数据趋势")
st.caption(f"统计范围：{start_s} ~ {end_s}，悬停折线可查看每日数据点详情。")

show_partner = False
if partner:
    show_partner = st.checkbox(
        "同时展示搭子数据（只读）", value=False, key="hist_show_partner"
    )

people = [(uid, me["public_id"])]
if partner and show_partner:
    people.append((partner_id, partner["public_id"]))


st.markdown("**① 每日摄入热量变化**")
kcal_rows = []
for pid, label in people:
    for r in db.daily_totals(pid, start_s, end_s):
        kcal_rows.append({"日期": r["d"], "摄入热量": float(r["kcal"]), "谁": label})
df_kcal = pd.DataFrame(kcal_rows)
if df_kcal.empty:
    st.info("所选时间段内没有饮食记录，暂无法绘制热量趋势图。")
else:
    df_kcal["日期"] = pd.to_datetime(df_kcal["日期"])
    kcal_line = alt.Chart(df_kcal).mark_line(point=True, strokeWidth=2.5).encode(
        x=alt.X("日期:T", title="日期", axis=alt.Axis(
            format="%m-%d", labelAngle=-45, labelOverlap="greedy",
            tickCount=min(range_days, 10),
        )),
        y=alt.Y("摄入热量:Q", title="每日摄入热量（千卡）"),
        color=alt.Color("谁:N", title=None),
        tooltip=[
            alt.Tooltip("日期:T", format="%Y-%m-%d"),
            alt.Tooltip("谁:N"),
            alt.Tooltip("摄入热量:Q", format=".0f"),
        ],
    )
    layers = [kcal_line]
    if my_target and my_target > 0:
        rule_df = pd.DataFrame({"目标热量": [my_target]})
        target_rule = alt.Chart(rule_df).mark_rule(
            strokeDash=[6, 4], color="#888"
        ).encode(y=alt.Y("目标热量:Q", title="每日摄入热量（千卡）"))
        layers.append(target_rule)
    st.altair_chart(
        alt.layer(*layers).properties(height=330),
        width="stretch",
    )
    if my_target and my_target > 0:
        st.caption("虚线为你的每日目标热量。")

st.markdown("**② 每日体重变化**")
weight_rows = []
for pid, label in people:
    for r in db.daily_weights(pid, start_s, end_s):
        weight_rows.append({"日期": r["d"], "体重": float(r["kg"]), "谁": label})
df_w = pd.DataFrame(weight_rows)
if df_w.empty:
    st.info("所选时间段内没有体重记录，暂无法绘制体重趋势图。")
else:
    df_w["日期"] = pd.to_datetime(df_w["日期"])
    weight_chart = alt.Chart(df_w).mark_line(point=True, strokeWidth=2.5).encode(
        x=alt.X("日期:T", title="日期", axis=alt.Axis(
            format="%m-%d", labelAngle=-45, labelOverlap="greedy",
            tickCount=min(range_days, 10),
        )),
        y=alt.Y("体重:Q", title="每日体重（kg）", scale=alt.Scale(zero=False)),
        color=alt.Color("谁:N", title=None),
        tooltip=[
            alt.Tooltip("日期:T", format="%Y-%m-%d"),
            alt.Tooltip("谁:N"),
            alt.Tooltip("体重:Q", format=".1f"),
        ],
    ).properties(height=330)
    st.altair_chart(weight_chart, width="stretch")


# ---------- 编辑 / 删除弹窗 ----------

@st.dialog("编辑饮食记录")
def edit_meal_dialog(meal_id: int):
    meal = db.get_meal(meal_id, uid)
    if not meal:
        st.error("记录不存在或已被删除。")
        return
    key = f"edit_meal_{meal_id}"
    if f"{key}_items" not in st.session_state:
        rows = db.get_meal_items(meal_id)
        st.session_state[f"{key}_items"] = [
            {"id": i + 1, "name": r["food_name"], "grams": float(r["grams"])}
            for i, r in enumerate(rows)
        ]
        st.session_state[f"{key}_seq"] = len(rows) or 1

    st.caption("修改名称或克数后，热量会实时重算。")
    items = st.session_state[f"{key}_items"]
    for item in list(items):
        c1, c2, c3 = st.columns([3, 2, 1], vertical_alignment="center")
        name = c1.text_input(
            f"食物{item['id']}", value=item["name"], key=f"{key}_food_{item['id']}",
            placeholder="食物名", label_visibility="collapsed",
        )
        grams = c2.number_input(
            f"克数{item['id']}", value=float(item["grams"] or 0),
            min_value=0.0, max_value=3000.0, step=10.0,
            key=f"{key}_grams_{item['id']}", label_visibility="collapsed",
        )
        if c3.button("✕", key=f"{key}_del_{item['id']}", help="删除这一行"):
            st.session_state[f"{key}_items"] = [
                i for i in items if i["id"] != item["id"]
            ]
            st.rerun()
        item["name"], item["grams"] = name, grams
    if st.button("＋ 添加食物", key=f"{key}_add", width="stretch"):
        seq = st.session_state.get(f"{key}_seq", 0) + 1
        st.session_state[f"{key}_seq"] = seq
        st.session_state[f"{key}_items"].append({"id": seq, "name": "", "grams": 100.0})
        st.rerun()

    with st.form(f"{key}_form"):
        day = st.date_input(
            "日期", value=dt.date.fromisoformat(meal["eaten_at"][:10]),
            max_value=db.today(), key=f"{key}_day",
        )
        clock = st.time_input(
            "时间",
            value=dt.datetime.strptime(meal["eaten_at"][11:16], "%H:%M").time(),
            key=f"{key}_clock",
        )
        idx = MEAL_TYPES.index(meal["meal_type"]) if meal["meal_type"] in MEAL_TYPES else 1
        meal_type = st.selectbox("餐次", MEAL_TYPES, index=idx, key=f"{key}_type")
        note = st.text_input("备注（可选）", value=meal["note"] or "", key=f"{key}_note")
        submitted = st.form_submit_button("保存修改", type="primary")

    if submitted:
        moment, err = build_datetime(day, clock)
        if err:
            st.error(err)
            return
        cleaned = [
            i for i in st.session_state.get(f"{key}_items", [])
            if (i["name"] or "").strip()
        ]
        if not cleaned:
            st.error("至少保留一条有效的食物明细。")
            return
        details, totals = nutrition.analyze(
            [{"食物": i["name"], "克数": i["grams"]} for i in cleaned],
            user_id=uid,
        )
        if not details:
            st.error("请填写有效的食物名称和克数。")
            return
        items_to_save = [{
            "food_name": d["食物"], "grams": d["克数"], "kcal": d["热量"],
            "carb": d["碳水"], "protein": d["蛋白"], "fat": d["脂肪"],
            "source": "manual",
        } for d in details]
        try:
            ok = db.update_meal(meal_id, uid, moment, meal_type, note, items_to_save)
        except Exception as exc:
            st.error(f"保存失败：{exc}")
            return
        if not ok:
            st.error("保存失败：记录不存在或无权修改。")
            return
        for k in (f"{key}_items", f"{key}_seq"):
            st.session_state.pop(k, None)
        flash(f"已更新饮食记录：{totals['kcal']:.0f} 千卡。")
        st.rerun()


@st.dialog("编辑运动记录")
def edit_exercise_dialog(exercise_id: int):
    ex = db.get_exercise(exercise_id, uid)
    if not ex:
        st.error("记录不存在或已被删除。")
        return
    with st.form(f"edit_ex_{exercise_id}_form"):
        c1, c2 = st.columns(2)
        ex_type = c1.selectbox(
            "运动类型", db.EXERCISE_TYPES, key=f"edit_ex_type_{exercise_id}",
            index=db.EXERCISE_TYPES.index(ex["exercise_type"])
            if ex["exercise_type"] in db.EXERCISE_TYPES else 0,
        )
        if ex_type == "其他":
            ex_type = c1.text_input(
                "具体运动", value=ex["exercise_type"] if ex["exercise_type"] not in db.EXERCISE_TYPES else "",
                key=f"edit_ex_custom_{exercise_id}", placeholder="例如：爬山",
            )
        duration_min = c2.number_input(
            "时长（分钟）", 1.0, 1440.0, float(ex["duration_min"]), 5.0,
            key=f"edit_ex_dur_{exercise_id}",
        )
        intensity = c2.selectbox(
            "运动强度", nutrition.INTENSITY_LEVELS,
            key=f"edit_ex_intensity_{exercise_id}",
            index=nutrition.INTENSITY_LEVELS.index(ex["intensity"])
            if ex.get("intensity") in nutrition.INTENSITY_LEVELS else 2,
        )
        st.caption(
            f"消耗热量由系统按「运动类型 + 时长 + 强度」自动估算"
            f"（当前记录为 {ex['kcal_burned']:.0f} 千卡，保存后按新参数重算）。"
        )
        day = st.date_input(
            "日期", value=dt.date.fromisoformat(ex["recorded_at"][:10]),
            max_value=db.today(), key=f"edit_ex_day_{exercise_id}",
        )
        clock = st.time_input(
            "时间",
            value=dt.datetime.strptime(ex["recorded_at"][11:16], "%H:%M").time(),
            key=f"edit_ex_clock_{exercise_id}",
        )
        note = st.text_input(
            "备注（可选）", value=ex["note"] or "", key=f"edit_ex_note_{exercise_id}"
        )
        submitted = st.form_submit_button("保存修改", type="primary")

    if submitted:
        moment, err = build_datetime(day, clock)
        if err:
            st.error(err)
            return
        if not (ex_type or "").strip():
            st.error("请填写运动类型")
            return
        latest = db.latest_weight(uid)
        weight = float(latest["weight_kg"]) if latest else 60.0
        ai_kcal = ai_client.estimate_exercise(ex_type.strip(), duration_min, intensity, weight)
        if ai_kcal is not None:
            kcal_burned = ai_kcal
        else:
            kcal_burned = nutrition.estimate_exercise_kcal(
                ex_type.strip(), duration_min, intensity, weight)
        try:
            ok = db.update_exercise(
                exercise_id, uid, moment, ex_type.strip(),
                duration_min, kcal_burned, note, intensity,
            )
        except Exception as exc:
            st.error(f"保存失败：{exc}")
            return
        if not ok:
            st.error("保存失败：记录不存在或无权修改。")
            return
        flash(f"已更新运动记录：{ex_type.strip()} · {duration_min:.0f} 分钟。")
        st.rerun()


@st.dialog("编辑体重记录")
def edit_weight_dialog(weight_id: int):
    w = db.get_weight(weight_id, uid)
    if not w:
        st.error("记录不存在或已被删除。")
        return
    with st.form(f"edit_w_{weight_id}_form"):
        day = st.date_input(
            "日期", value=dt.date.fromisoformat(w["record_date"]),
            max_value=db.today(), key=f"edit_w_day_{weight_id}",
        )
        kg = st.number_input(
            "体重（kg）", 20.0, 400.0, float(w["weight_kg"]), 0.1,
            key=f"edit_w_kg_{weight_id}",
        )
        note = st.text_input(
            "备注（可选）", value=w["note"] or "", key=f"edit_w_note_{weight_id}"
        )
        submitted = st.form_submit_button("保存修改", type="primary")

    if submitted:
        if day > db.today():
            st.error("不能记录未来的日期")
            return
        try:
            ok = db.update_weight(weight_id, uid, day.isoformat(), kg, note)
        except Exception as exc:
            st.error(f"保存失败：{exc}")
            return
        if not ok:
            st.error("保存失败：该日期已有其他体重记录（每人每天只能一条），请先修改那一条。")
            return
        flash(f"已更新体重记录：{kg:.1f} kg（{day.isoformat()}）。")
        st.rerun()


@st.dialog("删除确认")
def confirm_delete_dialog(title: str, action):
    st.write(f"确定要删除这条{title}吗？删除后不可恢复。")
    c1, c2 = st.columns(2)
    if c1.button("取消", width="stretch"):
        st.rerun()
    if c2.button("确认删除", type="primary", width="stretch"):
        try:
            ok = action()
        except Exception as exc:
            st.error(f"删除失败：{exc}")
            return
        if not ok:
            st.error("删除失败：记录不存在或无权删除。")
            return
        flash(f"已删除该{title}。")
        st.rerun()


# ---------- 记录展示 ----------

def _render_record(rec_type: str, r: dict, own: bool) -> None:
    if rec_type == "饮食记录":
        with st.expander(
            f"🍚 {r['meal_type']} · {r['kcal']:.0f} 千卡 · {r['eaten_at']}",
            key=f"hist_meal_{r['id']}",
        ):
            img = db.get_image(r["image_path"])
            if img is not None:
                st.image(img, width=220)
            for i in db.get_meal_items(r["id"]):
                st.markdown(f"- {i['food_name']} {i['grams']:.0f}g · {i['kcal']:.0f} 千卡")
            if r["note"]:
                st.caption(f"备注：{r['note']}")
            if own:
                _action_buttons("饮食记录", r["id"])
            else:
                st.caption("🔒 搭子记录只读，不可修改或删除")
    elif rec_type == "运动记录":
        with st.expander(
            f"🏃 {r['exercise_type']} · {r['duration_min']:.0f} 分钟 · "
            f"{r['kcal_burned']:.0f} 千卡 · {r['recorded_at']}",
            key=f"hist_ex_{r['id']}",
        ):
            if r["note"]:
                st.caption(f"备注：{r['note']}")
            if own:
                _action_buttons("运动记录", r["id"])
            else:
                st.caption("🔒 搭子记录只读，不可修改或删除")
    else:
        with st.expander(
            f"⚖️ {r['weight_kg']:.1f} kg · {r['record_date']}",
            key=f"hist_w_{r['id']}",
        ):
            if r["note"]:
                st.caption(f"备注：{r['note']}")
            if own:
                _action_buttons("体重记录", r["id"])
            else:
                st.caption("🔒 搭子记录只读，不可修改或删除")


def _action_buttons(rec_type: str, rec_id: int) -> None:
    c1, c2 = st.columns(2)
    with c1:
        if st.button("✏️ 编辑", key=f"act_edit_{rec_type}_{rec_id}", width="stretch"):
            if rec_type == "饮食记录":
                edit_meal_dialog(rec_id)
            elif rec_type == "运动记录":
                edit_exercise_dialog(rec_id)
            else:
                edit_weight_dialog(rec_id)
    with c2:
        if st.button("🗑️ 删除", key=f"act_del_{rec_type}_{rec_id}", width="stretch"):
            if rec_type == "饮食记录":
                confirm_delete_dialog("饮食记录", lambda: db.delete_meal(rec_id, uid))
            elif rec_type == "运动记录":
                confirm_delete_dialog("运动记录", lambda: db.delete_exercise(rec_id, uid))
            else:
                confirm_delete_dialog("体重记录", lambda: db.delete_weight(rec_id, uid))


# ---------- 记录管理 ----------

st.divider()
st.subheader("📋 记录管理")
st.caption(f"显示范围：{start_s} ~ {end_s}")

rec_type = st.segmented_control(
    "记录类型", db.RECORD_TYPES, default="饮食记录", key="hist_rec_type"
) or "饮食记录"

own_rows, their_rows = [], []
if rec_type == "饮食记录":
    own_rows = db.list_meals(uid, start_s, end_s)
    their_rows = db.list_meals(partner_id, start_s, end_s) if partner else []
elif rec_type == "运动记录":
    own_rows = db.list_exercises(uid, start_s, end_s)
    their_rows = db.list_exercises(partner_id, start_s, end_s) if partner else []
else:
    own_rows = db.list_weights(uid, start_s, end_s)
    their_rows = db.list_weights(partner_id, start_s, end_s) if partner else []

if not own_rows and not their_rows:
    st.info("这个时间段内没有相关记录。")
else:
    for r in own_rows:
        _render_record(rec_type, r, own=True)
    for r in their_rows:
        _render_record(rec_type, r, own=False)
