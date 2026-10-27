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


@lru_cache(maxsize=1)
def _food_index() -> tuple[list[dict], list[tuple[str, int]], list[tuple[str, int]]]:
    """预构建全局食物库索引: (rows, [(clean主名, 行号)], [(clean别名, 行号)])。"""
    df = load_foods()
    rows = df.to_dict("records")
    main, aliases = [], []
    for i, r in enumerate(rows):
        main.append((_clean_name(r["name"]), i))
        for a in str(r.get("aliases") or "").split("|"):
            k = _clean_name(a)
            if k:
                aliases.append((k, i))
    return rows, main, aliases


@lru_cache(maxsize=512)
def match_food(name: str) -> dict | None:
    """全局库匹配: 精确 > 主名包含(最长优先) > 别名包含 > 模糊。"""
    key = _clean_name(name)
    if not key:
        return None
    rows, main, aliases = _food_index()
    for k, i in main:
        if k == key:
            return rows[i]
    for k, i in aliases:
        if k == key:
            return rows[i]
    best = None
    for k, i in main:
        if len(k) >= 2 and (k in key or key in k):
            if best is None or len(k) > len(best[0]):
                best = (k, i)
    if best is None:
        for k, i in aliases:
            if len(k) >= 2 and (k in key or key in k):
                if best is None or len(k) > len(best[0]):
                    best = (k, i)
    if best:
        return rows[best[1]]
    candidates = [k for k, _ in main] + [k for k, _ in aliases]
    close = difflib.get_close_matches(key, candidates, n=1, cutoff=0.55)
    if close:
        for k, i in main + aliases:
            if k == close[0]:
                return rows[i]
    return None


def match_user_food(name: str, user_id: int) -> dict | None:
    """自定义食物库匹配（用户自录优先）。user_id 为空时跳过。"""
    if not user_id:
        return None
    import db
    key = _clean_name(name)
    if not key:
        return None
    foods = db.list_user_foods(user_id)
    for f in foods:
        if _clean_name(f["name"]) == key:
            return f
    best = None
    for f in foods:
        k = _clean_name(f["name"])
        if len(k) >= 2 and (k in key or key in k):
            if best is None or len(k) > len(best[0]):
                best = (k, f)
    if best:
        return best[1]
    close = difflib.get_close_matches(
        key, [_clean_name(f["name"]) for f in foods], n=1, cutoff=0.55
    )
    if close:
        for f in foods:
            if _clean_name(f["name"]) == close[0]:
                return f
    return None


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


def _est_item(est: dict | None, grams: float) -> dict | None:
    """AI 估算条目 -> 营养明细。est 缺失或无效返回 None。"""
    if not est:
        return None
    try:
        kcal_p100 = float(est.get("kcal_per_100g") or 0)
        carb_p100 = float(est.get("carb_per_100g") or 0)
        protein_p100 = float(est.get("protein_per_100g") or 0)
        fat_p100 = float(est.get("fat_per_100g") or 0)
    except (TypeError, ValueError):
        return None
    if kcal_p100 <= 0 and carb_p100 <= 0 and protein_p100 <= 0 and fat_p100 <= 0:
        return None
    ratio = max(float(grams), 0) / 100
    return {
        "matched": False,
        "estimated": True,
        "kcal": round(kcal_p100 * ratio, 1),
        "carb": round(carb_p100 * ratio, 1),
        "protein": round(protein_p100 * ratio, 1),
        "fat": round(fat_p100 * ratio, 1),
    }


def analyze(rows: list[dict], *, user_id: int | None = None,
            ai_est: dict[str, dict] | None = None) -> tuple[list[dict], dict]:
    """rows: [{'食物': ..., '克数': ...}]，返回明细与合计。

    匹配优先级: 自定义库 > 全局库 > AI 估算。ai_est: {食物名: 估算营养 dict}。
    """
    details: list[dict] = []
    totals = {"kcal": 0.0, "carb": 0.0, "protein": 0.0, "fat": 0.0, "veg_grams": 0.0}
    ai_est = ai_est or {}
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
        food = match_user_food(name, user_id)
        source, matched_name = "自定义库", None
        if food is None:
            food = match_food(name)
            source = "数据库"
        if food is not None:
            matched_name = food["name"]
            item = calc_item(food, grams)
            category = food.get("category") or "菜品"
        else:
            est = r.get("est") or ai_est.get(name) or next(
                (v for k, v in ai_est.items() if _clean_name(k) == _clean_name(name)), None
            )
            item = _est_item(est, grams)
            if item is not None:
                source, matched_name = "AI估算", name
                category = est.get("category", "菜品")
            else:
                item = calc_item(None, grams)
                source, matched_name = "未匹配", "未匹配（按 0 计算）"
                category = ""
        details.append({
            "食物": name,
            "克数": grams,
            "匹配": matched_name,
            "热量": item["kcal"],
            "碳水": item["carb"],
            "蛋白": item["protein"],
            "脂肪": item["fat"],
            "类别": category,
            "matched": item["matched"],
            "estimated": item.get("estimated", False),
            "来源": source,
        })
        for k in ("kcal", "carb", "protein", "fat"):
            totals[k] += item[k]
        if category == "蔬菜":
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


# ---------- 运动热量估算（MET 标准，禁止用户手填热量） ----------

# 运动类型 → MET 值（来源：ACSM 代谢当量参考值，1 MET = 3.5 mL O2/kg/min）
EXERCISE_MET = {
    "跑步": 8.3, "慢跑": 8.3, "快走": 4.3, "散步": 3.0, "骑行": 6.8,
    "游泳": 6.0, "力量训练": 6.0, "瑜伽": 3.0, "跳绳": 9.8, "球类运动": 6.0,
    "椭圆机": 5.0, "健身操": 5.5, "爬山": 6.5, "舞蹈": 5.0, "篮球": 6.5,
    "羽毛球": 5.5, "乒乓球": 4.0, "足球": 7.0, "其他": 4.0,
}

# 运动强度 → 热量调节系数
INTENSITY_FACTOR = {
    "低强度": 0.70, "中低强度": 0.85, "中强度": 1.00,
    "中高强度": 1.15, "高强度": 1.30,
}
INTENSITY_LEVELS = list(INTENSITY_FACTOR)


def met_for(name: str) -> float:
    """按运动名称匹配 MET（精确 → 包含 → 默认 4.0）。"""
    name = (name or "").strip()
    if not name:
        return 4.0
    if name in EXERCISE_MET:
        return EXERCISE_MET[name]
    for key, met in EXERCISE_MET.items():
        if key in name or name in key:
            return met
    return 4.0


def estimate_exercise_kcal(name: str, minutes: float, intensity: str = "中强度",
                           weight_kg: float = 60.0) -> float:
    """标准公式：kcal = MET × 3.5 × 体重kg × 时长min / 200，再按强度调系数。

    例：60kg、跑步 5 分钟、中强度 → 8.3×3.5×60×5/200 ≈ 44 千卡，杜绝 5 分钟 880 大卡的失真。"""
    met = met_for(name)
    factor = INTENSITY_FACTOR.get(intensity or "中强度", 1.0)
    kcal = met * 3.5 * max(float(weight_kg or 60), 30.0) * max(float(minutes or 1), 1.0) / 200 * factor
    return round(kcal, 1)


# ---------- 运动热量估算（MET 标准，禁止用户手填热量） ----------

# 运动类型 → MET 值（来源：ACSM 代谢当量参考值，1 MET = 3.5 mL O2/kg/min）
EXERCISE_MET = {
    "跑步": 8.3, "慢跑": 8.3, "快走": 4.3, "散步": 3.0, "骑行": 6.8,
    "游泳": 6.0, "力量训练": 6.0, "瑜伽": 3.0, "跳绳": 9.8, "球类运动": 6.0,
    "椭圆机": 5.0, "健身操": 5.5, "爬山": 6.5, "舞蹈": 5.0, "篮球": 6.5,
    "羽毛球": 5.5, "乒乓球": 4.0, "足球": 7.0, "其他": 4.0,
}

# 运动强度 → 热量调节系数
INTENSITY_FACTOR = {
    "低强度": 0.70, "中低强度": 0.85, "中强度": 1.00,
    "中高强度": 1.15, "高强度": 1.30,
}
INTENSITY_LEVELS = list(INTENSITY_FACTOR)


def met_for(name: str) -> float:
    """按运动名称匹配 MET（精确 → 包含 → 默认 4.0）。"""
    name = (name or "").strip()
    if not name:
        return 4.0
    if name in EXERCISE_MET:
        return EXERCISE_MET[name]
    for key, met in EXERCISE_MET.items():
        if key in name or name in key:
            return met
    return 4.0


def estimate_exercise_kcal(name: str, minutes: float, intensity: str = "中强度",
                           weight_kg: float = 60.0) -> float:
    """标准公式：kcal = MET × 3.5 × 体重kg × 时长min / 200，再按强度调系数。

    例：60kg、跑步 5 分钟、中强度 → 8.3×3.5×60×5/200 ≈ 44 千卡，杜绝 5 分钟 880 大卡的失真。"""
    met = met_for(name)
    factor = INTENSITY_FACTOR.get(intensity or "中强度", 1.0)
    kcal = met * 3.5 * max(float(weight_kg or 60), 30.0) * max(float(minutes or 1), 1.0) / 200 * factor
    return round(kcal, 1)
