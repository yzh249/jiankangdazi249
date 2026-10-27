import streamlit as st

import ai_client
import db
import nutrition
from common import (
    setup, require_login, sidebar, flash, show_flash,
    build_datetime, now_clock,
)

setup("今日打卡", "📸")
uid = require_login()
sidebar()
show_flash()

target = db.get_target(uid)
st.title("今日打卡")


# ---------- 饮食记录：食物明细行编辑 ----------

def set_items(pairs) -> None:
    """pairs: [(食物名, 克数)] 或 [(食物名, 克数, AI估算dict)]，为空时给一行空白。"""
    seq = 0
    items = []
    for entry in pairs:
        seq += 1
        if len(entry) >= 3:
            name, grams, est = entry[0], entry[1], entry[2]
        else:
            name, grams, est = entry[0], entry[1], None
        items.append({"id": seq, "name": name, "grams": float(grams or 0), "est": est})
    if not items:
        seq += 1
        items.append({"id": seq, "name": "", "grams": 100.0, "est": None})
    st.session_state["row_seq"] = seq
    st.session_state["items_gen"] = st.session_state.get("items_gen", 0) + 1
    st.session_state["items"] = items


def add_item() -> None:
    seq = st.session_state.get("row_seq", 0) + 1
    st.session_state["row_seq"] = seq
    st.session_state["items"].append({"id": seq, "name": "", "grams": 100.0, "est": None})


def render_meal_form() -> None:
    with st.expander("📚 我的食物库（自定义）"):
        my_foods = db.list_user_foods(uid)
        if my_foods:
            for f in my_foods:
                c1, c2 = st.columns([5, 1], vertical_alignment="center")
                c1.markdown(
                    f"**{f['name']}** · {f['kcal']:.0f} 千卡/100g"
                    f"（碳水 {f['carb']:.0f} · 蛋白 {f['protein']:.0f} · 脂肪 {f['fat']:.0f}）"
                )
                if c2.button("删", key=f"del_uf_{f['id']}", help="删除这条自定义食物"):
                    try:
                        if db.delete_user_food(f["id"], uid):
                            flash(f"已删除「{f['name']}」")
                        else:
                            flash("删除失败：记录不存在", "error")
                    except Exception as exc:
                        flash(f"删除失败：{exc}", "error")
                    st.rerun()
        else:
            st.caption("还没有自定义食物。把常吃但库里没有的菜录进来，以后识别或计算会优先用它。")
        with st.form("add_user_food_form"):
            f_name = st.text_input("食物名", key="uf_name",
                                   placeholder="如：外婆家红烧肉")
            fc1, fc2, fc3, fc4, fc5 = st.columns(5)
            f_kcal = fc1.number_input("千卡/100g", 0.0, 1000.0, 200.0, key="uf_kcal")
            f_carb = fc2.number_input("碳水g", 0.0, 100.0, 10.0, key="uf_carb")
            f_protein = fc3.number_input("蛋白g", 0.0, 100.0, 10.0, key="uf_protein")
            f_fat = fc4.number_input("脂肪g", 0.0, 100.0, 10.0, key="uf_fat")
            f_cat = fc5.selectbox("类别", ["主食", "蛋白质", "蔬菜", "水果", "油脂", "菜品", "饮品", "零食"],
                                  index=5, key="uf_cat")
            if st.form_submit_button("保存到我的食物库"):
                if not (f_name or "").strip():
                    st.error("请填写食物名")
                else:
                    ok, msg = db.add_user_food(
                        uid, f_name, f_kcal, f_carb, f_protein, f_fat, f_cat
                    )
                    flash(msg, "success" if ok else "error")
                    if ok:
                        st.rerun()

    meal_type = st.selectbox(
        "餐次", ["早餐", "午餐", "晚餐", "加餐"], index=1, key="meal_type_new"
    )
    day = st.date_input("日期", value=db.today(), max_value=db.today(), key="meal_day_new")
    clock = st.time_input("时间", value=now_clock(), key="meal_clock_new")
    note = st.text_input("文字备注辅助（选填）", key="meal_note_new",
                         placeholder="例：一碗米饭 + 红烧肉 + 炒青菜，约1人份。写清楚能帮 AI 更准识别，也会存进记录备注")

    if not ai_client.configured():
        st.caption("ℹ️ 没配置 AI Key，可以直接手动填写；配置后支持拍照识别。")

    uploader_key = f"uploader_{st.session_state.get('uploader_ver', 0)}"
    pic = st.file_uploader(
        "食物照片（单张，可拍照）",
        type=["jpg", "jpeg", "png", "webp"],
        key=uploader_key,
    )

    b1, b2 = st.columns(2)
    if b1.button("🔍 AI 识别", disabled=pic is None, width="stretch"):
        with st.spinner("正在识别…"):
            result = ai_client.recognize_food(
                pic.getvalue(), pic.type or "image/jpeg", hint=note
            )
        if result["ok"]:
            set_items([
                (f["name"], f["grams"], f.get("est")) for f in result["foods"]
            ])
            st.session_state["ai_conf"] = result["overall_confidence"]
            st.session_state["ai_raw"] = result["raw"]
            st.session_state["ai_est"] = {
                f["name"]: f["est"] for f in result["foods"] if f.get("est")
            }
            st.session_state["ai_low_conf"] = [
                f["name"] for f in result["foods"] if f["confidence"] < 0.5
            ]
            if result["overall_confidence"] < 0.5:
                st.warning("AI 对这张图不太确定，建议逐项核对分量。")
        else:
            st.error(f"{result['error']}，可以先手动填写。")
            set_items([])

    if b2.button("✍️ 手动填写", width="stretch"):
        set_items([])
        for key in ("ai_conf", "ai_raw", "ai_est", "ai_low_conf"):
            st.session_state.pop(key, None)

    if pic is not None:
        st.image(pic, caption="本次照片", width="stretch")

    items = st.session_state.get("items")
    if items is None:
        st.info("上传照片后点「AI 识别」，或直接点「手动填写」。")
        return

    st.caption("AI 可能有误差：直接改名字或克数，热量会实时重算。")
    gen = st.session_state.get("items_gen", 0)
    current = []
    for item in list(items):
        c1, c2, c3 = st.columns([3, 2, 1], vertical_alignment="center")
        name = c1.text_input(
            f"食物{item['id']}", value=item["name"],
            key=f"food_{gen}_{item['id']}", placeholder="食物名",
            label_visibility="collapsed",
        )
        grams = c2.number_input(
            f"克数{item['id']}", value=float(item["grams"] or 0),
            min_value=0.0, max_value=3000.0, step=10.0,
            key=f"grams_{gen}_{item['id']}", label_visibility="collapsed",
        )
        if c3.button("✕", key=f"del_item_{gen}_{item['id']}", help="删除这一行"):
            st.session_state["items"] = [
                i for i in items if i["id"] != item["id"]
            ]
            st.rerun()
        item["name"], item["grams"] = name, grams
        current.append({"食物": name, "克数": grams, "est": item.get("est")})

    if st.button("＋ 再加一种食物", width="stretch"):
        add_item()
        st.rerun()

    details, totals = nutrition.analyze(
        current, user_id=uid, ai_est=st.session_state.get("ai_est")
    )
    if not details:
        st.info("至少填一行有效的食物和克数。")
        return
    low_conf = set(st.session_state.get("ai_low_conf") or [])
    for d in details:
        if d["matched"]:
            mark = f"✅ 匹配「{d['匹配']}」"
        elif d["estimated"]:
            mark = "🤖 AI 估算（非标准库，可能有误差）"
        else:
            mark = "⚠️ 未匹配（按 0 计算）"
        if d["食物"] in low_conf:
            mark += " ⚠️低置信度"
        st.markdown(
            f"- {d['食物']} {d['克数']:.0f}g · **{d['热量']:.0f} 千卡** {mark}"
        )
    if any(not d["matched"] and not d["estimated"] for d in details):
        st.warning("有食物既不在营养库、也没有 AI 估算（按 0 计算），换个更常见的名字，"
                   "或在下方「我的食物库」里录一个自定义食物。")
    elif any(d["estimated"] for d in details):
        st.caption("🤖 AI 估算项基于模型常识给出，日常参考够用，精确记录可改成库内食物名。")

    m1, m2 = st.columns(2)
    m1.metric("热量", f"{totals['kcal']:.0f} 千卡")
    m2.metric("蛋白质", f"{totals['protein']:.0f} g")
    st.caption(
        f"碳水 {totals['carb']:.0f}g · 脂肪 {totals['fat']:.0f}g · "
        f"蔬菜 {totals['veg_grams']:.0f}g"
    )

    if st.button("✅ 保存这条打卡", type="primary", width="stretch"):
        moment, err = build_datetime(day, clock)
        if err:
            st.error(err)
            return
        img_path = None
        try:
            if pic is not None:
                img_path = db.save_image(pic.getvalue(), pic.type or "image/jpeg", uid)
            items_to_save = [{
                "food_name": d["食物"],
                "grams": d["克数"],
                "kcal": d["热量"],
                "carb": d["碳水"],
                "protein": d["蛋白"],
                "fat": d["脂肪"],
                "source": "ai" if st.session_state.get("ai_conf") is not None else "manual",
            } for d in details]
            db.add_meal(uid, moment, meal_type, img_path, note, items_to_save,
                        st.session_state.get("ai_conf"), st.session_state.get("ai_raw"))
        except Exception as exc:
            flash(f"保存失败：{exc}", "error")
            st.rerun()

        review = " ".join(nutrition.rule_review(totals))
        if ai_client.configured():
            polished = ai_client.comment_meal(
                totals, [d["食物"] for d in details]
            )
            if polished:
                review = polished
        flash(f"已保存饮食记录：{totals['kcal']:.0f} 千卡。\n\n**点评：**{review}")
        for key in ("items", "ai_conf", "ai_raw", "ai_est", "ai_low_conf"):
            st.session_state.pop(key, None)
        st.session_state["uploader_ver"] = (
            st.session_state.get("uploader_ver", 0) + 1
        )
        st.rerun()


# ---------- 运动记录 ----------

def _exercise_weight() -> float:
    """估算用体重：取最近一次记录，没有则默认 60kg。"""
    latest = db.latest_weight(uid)
    return float(latest["weight_kg"]) if latest else 60.0


def calc_exercise_kcal(ex_type: str, duration_min: float, intensity: str):
    """运动消耗热量：AI 综合判断优先，标准 MET 公式兜底，用户不可手填。"""
    weight = _exercise_weight()
    ai_kcal = ai_client.estimate_exercise(ex_type, duration_min, intensity, weight)
    if ai_kcal is not None:
        return ai_kcal, "AI 综合估算"
    return nutrition.estimate_exercise_kcal(ex_type, duration_min, intensity, weight), "标准 MET 估算"


def render_exercise_form() -> None:
    st.caption("记录一次运动：热量由系统按「运动类型 + 时长 + 强度」自动估算，无需手动填写。")
    c1, c2 = st.columns(2)
    ex_type = c1.selectbox("运动类型", db.EXERCISE_TYPES, key="ex_type_new")
    if ex_type == "其他":
        ex_type = c1.text_input("具体运动", key="ex_custom_new", placeholder="例如：爬山")
    duration_min = c2.number_input(
        "时长（分钟）", 1.0, 1440.0, 30.0, 5.0, key="ex_dur_new"
    )
    intensity = c2.selectbox(
        "运动强度", nutrition.INTENSITY_LEVELS, index=2, key="ex_intensity_new"
    )
    day = st.date_input("日期", value=db.today(), max_value=db.today(), key="ex_day_new")
    clock = st.time_input("时间", value=now_clock(), key="ex_clock_new")
    note = st.text_input("备注（可选）", key="ex_note_new",
                         placeholder="比如：夜跑 5 公里")

    b1, b2 = st.columns(2)
    if b1.button("🔢 预览消耗热量", width="stretch"):
        if not (ex_type or "").strip():
            st.error("请先填写运动类型")
        else:
            kcal, method = calc_exercise_kcal(ex_type.strip(), duration_min, intensity)
            st.success(f"预计消耗约 **{kcal:.0f} 千卡**（{method}）")

    if b2.button("✅ 保存运动记录", type="primary", width="stretch"):
        moment, err = build_datetime(day, clock)
        if err:
            st.error(err)
            return
        if not (ex_type or "").strip():
            st.error("请填写运动类型")
            return
        kcal, method = calc_exercise_kcal(ex_type.strip(), duration_min, intensity)
        try:
            db.add_exercise(uid, moment, ex_type.strip(), duration_min, kcal, note, intensity)
        except Exception as exc:
            flash(f"保存失败：{exc}", "error")
            st.rerun()
        flash(
            f"已保存运动记录：{ex_type.strip()} · {duration_min:.0f} 分钟 · "
            f"约 {kcal:.0f} 千卡（{method}）。"
        )
        st.rerun()


# ---------- 体重记录 ----------

def render_weight_form() -> None:
    st.caption("记录当天体重。同一天重复保存会覆盖当天记录。")
    profile = db.get_profile(uid)
    default_w = float((profile or {}).get("weight") or 60.0)
    latest = db.latest_weight(uid)
    if latest:
        default_w = float(latest["weight_kg"])
    weight_kg = st.number_input(
        "体重（kg）", 20.0, 400.0, default_w, 0.1, key="wt_kg_new"
    )
    day = st.date_input("日期", value=db.today(), max_value=db.today(), key="wt_day_new")
    note = st.text_input("备注（可选）", key="wt_note_new",
                         placeholder="比如：晨起空腹")

    if st.button("✅ 保存体重记录", type="primary", width="stretch"):
        if day > db.today():
            st.error("不能记录未来的日期")
            return
        existed = db.get_weight_for_date(uid, day.isoformat())
        try:
            db.save_weight(uid, day.isoformat(), weight_kg, note)
        except Exception as exc:
            flash(f"保存失败：{exc}", "error")
            st.rerun()
        msg = f"已保存体重：{weight_kg:.1f} kg（{day.isoformat()}）。"
        if existed:
            msg += "当天原有记录已覆盖。"
        flash(msg)
        st.rerun()


# ---------- 页面主体 ----------

tab_new, tab_today = st.tabs(["📝 新建记录", "📋 今日记录"])

with tab_new:
    rec_type = st.segmented_control(
        "记录类型", db.RECORD_TYPES, default="饮食记录", key="rec_type_new"
    ) or "饮食记录"
    if rec_type == "饮食记录":
        render_meal_form()
    elif rec_type == "运动记录":
        render_exercise_form()
    else:
        render_weight_form()

with tab_today:
    today = db.today().isoformat()
    total = db.day_total(uid, today)
    st.progress(
        min(total["kcal"] / target, 1.0) if target else 0.0,
        text=f"今日 {total['kcal']:.0f} / {target:.0f} 千卡",
    )
    if total["kcal"] > target:
        st.caption(f"今天超出目标 {total['kcal'] - target:.0f} 千卡，明天稍微收一收就好。")

    ex_total = db.day_exercise_total(uid, today)
    if ex_total["kcal"] > 0:
        st.caption(
            f"今日运动消耗约 {ex_total['kcal']:.0f} 千卡"
            f"（{ex_total['minutes']:.0f} 分钟）。"
        )

    st.markdown("**🍚 饮食记录**")
    meals = db.get_meals(uid, today)
    if not meals:
        st.caption("今天还没有饮食记录。")
    for meal in meals:
        with st.expander(
            f"{meal['meal_type']} · {meal['kcal']:.0f} 千卡 · {meal['eaten_at'][11:16]}",
            key=f"today_meal_{meal['id']}",
        ):
            img = db.get_image(meal["image_path"])
            if img is not None:
                st.image(img, width="stretch")
            for i in db.get_meal_items(meal["id"]):
                st.markdown(f"- {i['food_name']} {i['grams']:.0f}g · {i['kcal']:.0f} 千卡")
            if meal["note"]:
                st.caption(f"备注：{meal['note']}")
            if st.button("删除这条", key=f"del_meal_{meal['id']}", width="stretch"):
                try:
                    if not db.delete_meal(meal["id"], uid):
                        flash("删除失败：记录不存在或无权删除", "error")
                    else:
                        flash("已删除这条饮食记录。")
                except Exception as exc:
                    flash(f"删除失败：{exc}", "error")
                st.rerun()

    st.markdown("**🏃 运动记录**")
    exercises = db.get_exercises(uid, today)
    if not exercises:
        st.caption("今天还没有运动记录。")
    for ex in exercises:
        with st.expander(
            f"{ex['exercise_type']} · {ex['duration_min']:.0f} 分钟 · "
            f"{ex['kcal_burned']:.0f} 千卡 · {ex['recorded_at'][11:16]}",
            key=f"today_ex_{ex['id']}",
        ):
            if ex["note"]:
                st.caption(f"备注：{ex['note']}")
            if st.button("删除这条", key=f"del_ex_{ex['id']}", width="stretch"):
                try:
                    if not db.delete_exercise(ex["id"], uid):
                        flash("删除失败：记录不存在或无权删除", "error")
                    else:
                        flash("已删除这条运动记录。")
                except Exception as exc:
                    flash(f"删除失败：{exc}", "error")
                st.rerun()

    st.markdown("**⚖️ 体重记录**")
    w = db.get_weight_for_date(uid, today)
    if not w:
        st.caption("今天还没有记录体重。")
    else:
        with st.expander(
            f"{w['weight_kg']:.1f} kg · {w['record_date']}",
            key=f"today_w_{w['id']}",
        ):
            if w["note"]:
                st.caption(f"备注：{w['note']}")
            if st.button("删除这条", key=f"del_w_{w['id']}", width="stretch"):
                try:
                    if not db.delete_weight(w["id"], uid):
                        flash("删除失败：记录不存在或无权删除", "error")
                    else:
                        flash("已删除这条体重记录。")
                except Exception as exc:
                    flash(f"删除失败：{exc}", "error")
                st.rerun()
