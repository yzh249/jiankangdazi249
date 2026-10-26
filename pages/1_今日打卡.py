import streamlit as st

import ai_client
import db
import nutrition
from common import setup, require_login, sidebar

setup("今日打卡", "📸")
uid = require_login()
sidebar()

if "last_review" in st.session_state:
    st.success(st.session_state.pop("last_review"))

target = db.get_target(uid)
st.title("今日打卡")


def set_items(pairs) -> None:
    """pairs: [(食物名, 克数)]，为空时给一行空白。"""
    seq = 0
    items = []
    for name, grams in pairs:
        seq += 1
        items.append({"id": seq, "name": name, "grams": float(grams or 0)})
    if not items:
        seq += 1
        items.append({"id": seq, "name": "", "grams": 100.0})
    st.session_state["row_seq"] = seq
    st.session_state["items_gen"] = st.session_state.get("items_gen", 0) + 1
    st.session_state["items"] = items


def add_item() -> None:
    seq = st.session_state.get("row_seq", 0) + 1
    st.session_state["row_seq"] = seq
    st.session_state["items"].append({"id": seq, "name": "", "grams": 100.0})


tab_new, tab_today = st.tabs(["📸 新打卡", "📋 今日记录"])

with tab_new:
    meal_type = st.selectbox("餐次", ["早餐", "午餐", "晚餐", "加餐"], index=1)
    day = st.date_input("日期", value=db.today())
    note = st.text_input("备注（可选）", placeholder="比如：食堂二楼 / 和朋友聚餐")

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
            result = ai_client.recognize_food(pic.getvalue(), pic.type or "image/jpeg")
        if result["ok"]:
            set_items([(f["name"], f["grams"]) for f in result["foods"]])
            st.session_state["ai_conf"] = result["overall_confidence"]
            st.session_state["ai_raw"] = result["raw"]
            if result["overall_confidence"] < 0.5:
                st.warning("AI 对这张图不太确定，建议逐项核对分量。")
        else:
            st.error(f"{result['error']}，可以先手动填写。")
            set_items([])

    if b2.button("✍️ 手动填写", width="stretch"):
        set_items([])
        st.session_state["ai_conf"] = None
        st.session_state["ai_raw"] = None

    if pic is not None:
        st.image(pic, caption="本次照片", width="stretch")

    items = st.session_state.get("items")
    if items is None:
        st.info("上传照片后点「AI 识别」，或直接点「手动填写」。")
    else:
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
            current.append({"食物": name, "克数": grams})

        if st.button("＋ 再加一种食物", width="stretch"):
            add_item()
            st.rerun()

        details, totals = nutrition.analyze(current)
        if not details:
            st.info("至少填一行有效的食物和克数。")
        else:
            for d in details:
                mark = "✅" if d["matched"] else "⚠️ 未匹配"
                st.markdown(
                    f"- {d['食物']} {d['克数']:.0f}g · **{d['热量']:.0f} 千卡** {mark}"
                )
            if any(not d["matched"] for d in details):
                st.warning("有食物没匹配到营养库（按 0 计算），换个更常见的名字试试。")

            m1, m2 = st.columns(2)
            m1.metric("热量", f"{totals['kcal']:.0f} 千卡")
            m2.metric("蛋白质", f"{totals['protein']:.0f} g")
            st.caption(
                f"碳水 {totals['carb']:.0f}g · 脂肪 {totals['fat']:.0f}g · "
                f"蔬菜 {totals['veg_grams']:.0f}g"
            )

            if st.button("✅ 保存这条打卡", type="primary", width="stretch"):
                img_path = (
                    db.save_image(pic.getvalue(), pic.type or "image/jpeg", uid)
                    if pic else None
                )
                items_to_save = [{
                    "food_name": d["食物"],
                    "grams": d["克数"],
                    "kcal": d["热量"],
                    "carb": d["碳水"],
                    "protein": d["蛋白"],
                    "fat": d["脂肪"],
                    "source": "ai" if st.session_state.get("ai_conf") is not None else "manual",
                } for d in details]
                eaten_at = f"{day.isoformat()} {db.now()[11:16]}:00"
                db.add_meal(uid, eaten_at, meal_type, img_path, note, items_to_save,
                            st.session_state.get("ai_conf"), st.session_state.get("ai_raw"))

                review = " ".join(nutrition.rule_review(totals))
                if ai_client.configured():
                    polished = ai_client.comment_meal(
                        totals, [d["食物"] for d in details]
                    )
                    if polished:
                        review = polished
                st.session_state["last_review"] = (
                    f"已保存：{totals['kcal']:.0f} 千卡。\n\n**点评：**{review}"
                )
                for key in ("items", "ai_conf", "ai_raw"):
                    st.session_state.pop(key, None)
                st.session_state["uploader_ver"] = (
                    st.session_state.get("uploader_ver", 0) + 1
                )
                st.rerun()

with tab_today:
    today = db.today().isoformat()
    total = db.day_total(uid, today)
    st.progress(
        min(total["kcal"] / target, 1.0) if target else 0.0,
        text=f"今日 {total['kcal']:.0f} / {target:.0f} 千卡",
    )
    if total["kcal"] > target:
        st.caption(f"今天超出目标 {total['kcal'] - target:.0f} 千卡，明天稍微收一收就好。")

    meals = db.get_meals(uid, today)
    if not meals:
        st.info("今天还没有打卡记录。")
    for meal in meals:
        with st.expander(
            f"{meal['meal_type']} · {meal['kcal']:.0f} 千卡 · {meal['eaten_at'][11:16]}"
        ):
            img = db.get_image(meal["image_path"])
            if img is not None:
                st.image(img, width="stretch")
            for i in db.get_meal_items(meal["id"]):
                st.markdown(f"- {i['food_name']} {i['grams']:.0f}g · {i['kcal']:.0f} 千卡")
            if meal["note"]:
                st.caption(f"备注：{meal['note']}")
            if st.button("删除这条", key=f"del_{meal['id']}", width="stretch"):
                db.delete_meal(meal["id"], uid)
                st.rerun()
