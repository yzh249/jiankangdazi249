"""食物匹配、营养计算、BMR 与规则点评。"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

FOODS_PATH = Path(__file__).resolve().parent / "data" / "foods.csv"

ACTIVITY_LEVELS = {
    "久坐少动（几乎不运动）": 1.2,
    "轻度活动（每周 1-3 次）": 1.375,
    "中度活动（每周 3-5 次）": 1.55,
    "高度活动（每周 6-7 次）": 1.725,
}


@lru_cache(maxsize=1)
def load_foods() -> pd.DataFrame:
    df = pd.read_csv(FOODS_PATH, dtype={"aliases": str})
    df["aliases"] = df["aliases"].fillna("")
    return df


def _clean_name(name: str) -> str:
    s = str(name).strip().lower()
    s = re.sub(r"[（(].*?[）)]", "", s)
    s = re.sub(r"\d+(\.\d+)?\s*(克|g|ml|毫升|份|个|片|碗|杯|勺)", "", s)
    return s.replace(" ", "")


@lru_cache(maxsize=512)
def match_food(name: str) -> dict | None:
    """先在本地食物库里做包含匹配，再退化为模糊匹配，匹配不到就返回 None。"""
    key = _clean_name(name)
    if not key:
        return None
    df = load_foods()
    for _, row in df.iterrows():
        names = [row["name"], *[a for a in str(row["aliases"]).split("|") if a]]
        for n in names:
            if key == n or (len(n) >= 2 and (n in key or key in n)):
                return row.to_dict()
    candidates = list(df["name"]) + [
        a for al in df["aliases"] for a in str(al).split("|") if a
    ]
    close = difflib.get_close_matches(key, candidates, n=1, cutoff=0.6)
    if not close:
        return None
    return df[df["name"] == close[0]].iloc[0].to_dict()


def calc_item(food: dict | None, grams: float) -> dict:
    ratio = max(float(grams), 0) / 100
    if not food:
        return {"matched": False, "kcal": 0.0, "carb": 0.0, "protein": 0.0, "fat": 0.0}
    return {
        "matched": True,
        "kcal": round(float(food["kcal"]) * ratio, 1),
        "carb": round(float(food["carb"]) * ratio, 1),
        "protein": round(float(food["protein"]) * ratio, 1),
        "fat": round(float(food["fat"]) * ratio, 1),
    }


def analyze(rows: list[dict]) -> tuple[list[dict], dict]:
    """rows: [{'食物': ..., '克数': ...}]，返回明细与合计。"""
    details: list[dict] = []
    totals = {"kcal": 0.0, "carb": 0.0, "protein": 0.0, "fat": 0.0, "veg_grams": 0.0}
    for r in rows:
        raw_name = r.get("食物")
        raw_grams = r.get("克数")
        if raw_name is None or raw_grams is None:
            continue
        if pd.isna(raw_name) or pd.isna(raw_grams):
            continue
        name = str(raw_name).strip()
        try:
            grams = float(raw_grams)
        except (TypeError, ValueError):
            grams = 0.0
        if not name or grams <= 0:
            continue
        food = match_food(name)
        item = calc_item(food, grams)
        details.append({
            "食物": name,
            "克数": grams,
            "匹配": food["name"] if food else "未匹配（按 0 计算）",
            "热量": item["kcal"],
            "碳水": item["carb"],
            "蛋白": item["protein"],
            "脂肪": item["fat"],
            "类别": food["category"] if food else "",
            "matched": item["matched"],
        })
        for k in ("kcal", "carb", "protein", "fat"):
            totals[k] += item[k]
        if food and food["category"] == "蔬菜":
            totals["veg_grams"] += grams
    totals = {k: round(v, 1) for k, v in totals.items()}
    return details, totals


def rows_from_ai(foods: list[dict]) -> list[dict]:
    return [{"食物": f["name"], "克数": float(f.get("grams") or 0)} for f in foods]


# ---------- BMR 与目标 ----------

def calc_bmr(sex: str, weight: float, height: float, age: int) -> float:
    base = 10 * weight + 6.25 * height - 5 * age
    return round(base + (5 if sex == "男" else -161), 0)


def calorie_floor(sex: str, bmr: float) -> float:
    return round(max(bmr * 1.1, 1500 if sex == "男" else 1200), 0)


def suggest_target(bmr: float, activity_level: float, deficit: float, sex: str) -> tuple[float, float]:
    """返回 (建议目标, 下限)。"""
    floor = calorie_floor(sex, bmr)
    raw = bmr * activity_level - deficit
    return round(max(raw, floor), 0), floor


# ---------- 规则点评 ----------

def rule_review(totals: dict) -> list[str]:
    kcal = totals.get("kcal", 0)
    if kcal <= 0:
        return []
    tips: list[str] = []
    fat_ratio = totals["fat"] * 9 / kcal
    carb_ratio = totals["carb"] * 4 / kcal
    veg = totals.get("veg_grams", 0)

    if fat_ratio >= 0.35:
        tips.append(f"油脂占比约 {fat_ratio:.0%}，偏高了，下次可以少放点油或换成蒸、煮的做法。")
    if veg < 100:
        tips.append("蔬菜不到 100g，加一份青菜或凉拌菜会更均衡。")
    elif veg >= 200:
        tips.append("蔬菜吃得很足，这一点继续保持。")
    if totals["protein"] < 20:
        tips.append(f"蛋白质只有 {totals['protein']:.0f}g，可以加个鸡蛋、一块豆腐或一杯牛奶。")
    elif totals["protein"] >= 30:
        tips.append("蛋白质够用，饱腹感会更好。")
    if carb_ratio >= 0.7:
        tips.append("主食占比偏高，下次可以先吃菜和蛋白质再吃饭。")
    if not tips:
        tips.append("这一餐搭配挺均衡，继续按这个节奏来。")
    return tips[:3]


def daily_message(me_name: str, my_kcal: float, my_target: float,
                  partner_name: str, partner_kcal: float, partner_target: float) -> str:
    """每日双人对比的激励文案，温和不制造焦虑。"""
    my_gap = my_target - my_kcal
    pa_gap = partner_target - partner_kcal

    if my_gap >= 0 and pa_gap >= 0:
        return (f"{me_name} 还有 {my_gap:.0f} 千卡空间，{partner_name} 还有 {pa_gap:.0f} 千卡空间。"
                "今天你俩都稳稳在目标内，配合得不错。")
    if my_gap < 0 and pa_gap < 0:
        return (f"今天 {me_name} 超出 {abs(my_gap):.0f} 千卡，{partner_name} 超出 {abs(pa_gap):.0f} 千卡。"
                "偶尔一天不用太在意，明天一起把饮料或主食收一收就好。")
    if my_gap < 0:
        return (f"{me_name} 今天比目标多了 {abs(my_gap):.0f} 千卡，明天可以稍微清淡一点；"
                f"{partner_name} 还有 {pa_gap:.0f} 千卡空间，节奏很稳。")
    return (f"{partner_name} 今天比目标多了 {abs(pa_gap):.0f} 千卡，可以提醒 TA 明天清淡一点；"
            f"{me_name} 还有 {my_gap:.0f} 千卡空间，继续保持。")
