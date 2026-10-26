import streamlit as st

import db
import nutrition
from common import setup, require_login, sidebar

setup("我的目标", "🎯")
uid = require_login()
sidebar()

if "profile_flash" in st.session_state:
    st.success(st.session_state.pop("profile_flash"))

st.title("我的目标")
profile = db.get_profile(uid)

if profile:
    c1, c2, c3 = st.columns(3)
    c1.metric("基础代谢 BMR", f"{profile['bmr']:.0f} 千卡")
    c2.metric("每日目标", f"{profile['target_kcal']:.0f} 千卡")
    c3.metric("热量缺口", f"{profile['deficit']:.0f} 千卡")
    st.caption("BMR 用 Mifflin-St Jeor 公式估算，只作参考，不构成医疗建议。")

activities = list(nutrition.ACTIVITY_LEVELS)
current_activity = (profile or {}).get("activity_level") or 1.375
activity_index = min(
    range(len(activities)),
    key=lambda i: abs(nutrition.ACTIVITY_LEVELS[activities[i]] - current_activity),
)
sex_default = (profile or {}).get("sex") or "女"

with st.form("profile_form"):
    c1, c2 = st.columns(2)
    height = c1.number_input("身高（cm）", 120.0, 230.0,
                             float((profile or {}).get("height") or 165), 1.0)
    weight = c2.number_input("体重（kg）", 30.0, 200.0,
                             float((profile or {}).get("weight") or 60), 0.5)
    age = c1.number_input("年龄", 12, 90, int((profile or {}).get("age") or 25), 1)
    sex = c2.radio("性别", ["女", "男"],
                   index=0 if sex_default == "女" else 1, horizontal=True)
    activity = st.selectbox("活动水平", activities, index=activity_index)
    deficit = st.slider("每天的热量缺口", 200, 800,
                        int((profile or {}).get("deficit") or 400), 50)
    custom = st.checkbox("我自己指定每日目标热量（不勾选则按公式推荐）", value=False)
    custom_target = st.number_input("自定义目标（千卡）", 1000, 4000,
                                    int((profile or {}).get("target_kcal") or 1800), 50)
    submitted = st.form_submit_button("保存目标", type="primary")

if submitted:
    bmr = nutrition.calc_bmr(sex, weight, height, age)
    suggested, floor = nutrition.suggest_target(
        bmr, nutrition.ACTIVITY_LEVELS[activity], deficit, sex
    )
    final = float(custom_target) if custom else suggested
    if final < floor:
        st.warning(f"为了避免极端节食，目标已按健康下限 {floor:.0f} 千卡处理。")
        final = floor
    db.save_profile(uid, height, weight, age, sex,
                    nutrition.ACTIVITY_LEVELS[activity], bmr, final, deficit)
    st.session_state["profile_flash"] = (
        f"已保存：BMR {bmr:.0f} 千卡，每日目标 {final:.0f} 千卡。"
    )
    st.rerun()
