"""从中国食物成分表(第6版)数据构建扩展食物库候选行。
数据来源: github.com/Sanotsu/china-food-composition-data (OCR自《中国食物成分表》第6版PDF)
只做筛选/清洗/别名提取, 数值来自成分表, 不做任何编造。
"""
from __future__ import annotations

import json
import glob
import os
import re

SRC = "/tmp/china-food-composition-data/json_data_v3_20260825_qwen38max_kimi_k3"
OUT = "/tmp/food_candidates.csv"

# 排除不常见/不适合日常记录的分类
BLACKLIST_CATS = {
    "蔬菜类及其制品-野生蔬菜类",
    "其他类-其他",
    "畜肉类及其制品-马",
    "畜肉类及其制品-驴",
    "动物油脂类-动物油脂",
}

CAT_MAP = {
    "谷类及其制品": "主食",
    "薯类淀粉及其制品": "主食",
    "畜肉类及其制品": "蛋白质",
    "禽肉类及其制品": "蛋白质",
    "鱼虾蟹贝类": "蛋白质",
    "蛋类及其制品": "蛋白质",
    "干豆类及其制品": "蛋白质",
    "乳类及其制品": "蛋白质",
    "蔬菜类及其制品": "蔬菜",
    "菌藻类": "蔬菜",
    "水果类及其制品": "水果",
    "坚果种子类": "油脂",
    "植物油": "油脂",
}

# 每类配额（按大类）
CAP = {
    "谷类及其制品": 110, "薯类淀粉及其制品": 32,
    "畜肉类及其制品": 110, "禽肉类及其制品": 55,
    "鱼虾蟹贝类": 110, "蛋类及其制品": 26,
    "干豆类及其制品": 65, "乳类及其制品": 65,
    "蔬菜类及其制品": 230, "菌藻类": 45,
    "水果类及其制品": 120, "坚果种子类": 45, "植物油": 22,
}

# 明确不太适合直接记录为"食物"的后缀关键词(干/脱水/罐头/粉/面等部分情形)
WEAK_MARK = ["（干）", "(干)", "（脱水）", "(脱水)", "（罐头）", "（加工）", "（炒）", "（烤）"]

# 日常高频食物口语名（AI 识别/用户输入最常见），命中必选
COMMON = set("""
大米 粳米 籼米 糯米 糙米 黑米 红米 小米 黄米 玉米 玉米面 玉米粒 面粉 面条 挂面 切面 馒头 花卷 包子 饺子 馄饨 抄手 汤圆 年糕 米粉 米线 河粉 粉丝 粉条 凉皮 煎饼 烧饼 油条 面包 吐司 燕麦 燕麦片 麦片 荞麦 荞麦面 高粱米 意面 通心粉 藜麦 土豆 马铃薯 红薯 地瓜 紫薯 芋头 山药 木薯 藕粉 板栗
猪肉 猪里脊 里脊肉 猪瘦肉 猪排 排骨 小排 猪蹄 猪肘 猪肝 猪肚 猪心 猪血 猪耳 五花肉 牛肉 牛里脊 牛腩 牛腱 牛尾 牛舌 牛肚 牛肝 牛排 肥牛 羊肉 羊排 羊腿 羊杂 鸡肉 鸡胸肉 鸡腿 鸡翅 鸡爪 鸡肝 鸡胗 鸡心 鸭肉 鸭腿 鸭胸 鸭翅 鸭脖 鸭舌 鸭胗 鸭肝 烤鸭 鹅肉 鹅肝 鸽肉 鹌鹑 火鸡 培根 火腿 火腿肠 午餐肉 腊肉 腊肠 香肠 肉松 卤肉 酱牛肉 叉烧 烧鸭 烧鹅 烤鸡 炸鸡
草鱼 鲤鱼 鲫鱼 鲈鱼 鲢鱼 鳙鱼 罗非鱼 带鱼 黄花鱼 黄鱼 鲳鱼 鳕鱼 三文鱼 金枪鱼 沙丁鱼 鲅鱼 鳗鱼 鱿鱼 墨鱼 章鱼 海参 鲍鱼 扇贝 蛤蜊 花甲 蛏子 生蚝 牡蛎 螃蟹 大闸蟹 河蟹 海蟹 小龙虾 基围虾 河虾 海虾 虾仁 虾米 虾皮 鱼丸 蟹棒
鸡蛋 鸭蛋 鹅蛋 鹌鹑蛋 皮蛋 松花蛋 咸鸭蛋 茶叶蛋 豆腐 嫩豆腐 老豆腐 豆腐干 香干 千张 百叶 豆腐皮 油豆腐 豆腐脑 豆花 豆浆 腐竹 豆皮 黄豆 大豆 黑豆 青豆 绿豆 红豆 赤小豆 芸豆 豌豆 蚕豆 毛豆 扁豆 四季豆 豆角 豇豆 牛奶 全脂牛奶 脱脂牛奶 酸奶 奶酪 芝士 奶粉 奶油 炼乳
大白菜 小白菜 青菜 油菜 菠菜 生菜 油麦菜 莴笋 芹菜 韭菜 韭黄 空心菜 茼蒿 苋菜 芥菜 香菜 葱 小葱 大蒜 蒜苗 蒜薹 洋葱 大葱 姜 辣椒 青椒 彩椒 尖椒 番茄 西红柿 茄子 黄瓜 冬瓜 丝瓜 苦瓜 南瓜 西葫芦 白萝卜 胡萝卜 芦笋 竹笋 春笋 冬笋 豆芽 绿豆芽 黄豆芽 西兰花 菜花 花椰菜 卷心菜 包菜 甘蓝 紫甘蓝 娃娃菜 秋葵 茭白 荸荠 百合 海带 紫菜 裙带菜 木耳 黑木耳 银耳 香菇 蘑菇 平菇 杏鲍菇 金针菇 茶树菇 口蘑 猴头菇 草菇
苹果 梨 鸭梨 雪梨 桃子 桃 油桃 李子 杏 樱桃 车厘子 葡萄 提子 草莓 蓝莓 桑葚 树莓 猕猴桃 奇异果 香蕉 芭蕉 菠萝 凤梨 芒果 荔枝 龙眼 桂圆 榴莲 椰子 木瓜 火龙果 橙子 橙 橘子 橘 柑 柚子 葡萄柚 柠檬 西瓜 哈密瓜 甜瓜 香瓜 石榴 柿子 枣 红枣 冬枣 山楂 杨梅 枇杷 橄榄 杨桃 无花果
花生 花生米 核桃 腰果 杏仁 巴旦木 开心果 瓜子 葵花籽 南瓜子 松子 榛子 栗子 莲子 芝麻 白芝麻 黑芝麻 芝麻酱 食用油 花生油 菜籽油 大豆油 玉米油 橄榄油 葵花籽油 芝麻油 香油 猪油 椰子油 牛油果
薯片 薯条 饼干 曲奇 蛋糕 巧克力 糖果 冰淇淋 雪糕 奶茶 可乐 汽水 果汁 啤酒 白酒 红酒 咖啡 美式咖啡 拿铁 绿茶 红茶
""".split())


def clean_num(v):
    if v is None:
        return 0.0
    s = str(v).strip().replace("—", "").replace("－", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def extract_base(food_name: str) -> str:
    main = re.split(r"[［\[]", food_name)[0].strip()
    base = re.sub(r"[（(].*?[）)]", "", main).strip()
    base = re.sub(r"[\[\]]", "", base).strip()
    return base


def extract_aliases(food_name: str, base: str) -> str:
    parts = []
    if food_name and food_name != base:
        parts.append(food_name.strip())
    for m in re.findall(r"[［\[](.*?)[］\]]", food_name):
        for a in re.split(r"[、，,/|]", m):
            a = a.strip()
            if a and a != base and a not in parts:
                parts.append(a)
    return "|".join(parts)


def score(row: dict, cat: str, base: str, exists: set, whitelist: set) -> float:
    s = 0.0
    src = row.get("src") or ""
    alias_words = set(row.get("aliases", "").split("|"))
    if base in whitelist or alias_words & whitelist:
        s += 5.0
    if 2 <= len(base) <= 5:
        s += 2
    elif len(base) == 1:
        s -= 2  # "鸡""鸭""虾"这类太泛
    elif len(base) >= 8:
        s -= 1
    if "代表值" in src:
        s += 1.2
    if any(k in src for k in WEAK_MARK):
        s -= 1.0
    if base in exists:
        s -= 3.0  # 与现有库主名重复, 几乎不会选到
    if cat in ("谷类及其制品", "薯类淀粉及其制品", "蔬菜类及其制品"):
        s += 0.5  # 常见食材优先扩
    return s


def main() -> None:
    files = sorted(glob.glob(os.path.join(SRC, "merged_*.json")))
    picked = []
    for f in files:
        cat_full = os.path.basename(f).replace("merged_", "").replace(".json", "")
        if cat_full in BLACKLIST_CATS:
            continue
        top = cat_full.split("-")[0]
        category = CAT_MAP.get(top)
        if category is None:
            continue
        try:
            data = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for row in data:
            base = extract_base(row["foodName"])
            if not base or len(base) < 1:
                continue
            kcal = clean_num(row.get("energyKCal"))
            carb = clean_num(row.get("CHO"))
            protein = clean_num(row.get("protein"))
            fat = clean_num(row.get("fat"))
            if kcal <= 0 and carb <= 0 and protein <= 0 and fat <= 0:
                continue  # 空数据不要
            picked.append({
                "name": base,
                "aliases": extract_aliases(row["foodName"], base),
                "kcal": kcal, "carb": carb, "protein": protein, "fat": fat,
                "category": category,
                "cat_full": cat_full,
                "src": row["foodName"],
                "edible": clean_num(row.get("edible")),
                "score": 0.0,
            })
    # 现有库主名集合
    import pandas as pd
    cur = pd.read_csv("/home/user/Doubao/chats/38449710648766978/jkd_repro/data/foods.csv",
                      dtype={"aliases": str})
    exists = set(cur["name"].astype(str).str.strip())
    for p in picked:
        p["score"] = score(p, p["cat_full"], p["name"], exists, COMMON)
    # 按大类排序取前 N
    by_cat: dict[str, list] = {}
    for p in picked:
        by_cat.setdefault(p["cat_full"].split("-")[0], []).append(p)
    final = []
    for cat, rows in by_cat.items():
        rows.sort(key=lambda r: (-r["score"], r["src"]))
        top = CAP.get(cat, 20)
        final.extend(rows[:top])
    # 同 name 去重: 保留最高分一条, 合并其余条目的 src/aliases
    best: dict[str, dict] = {}
    for p in final:
        old = best.get(p["name"])
        if old is None or p["score"] > old["score"]:
            best[p["name"]] = dict(p)
            if old is not None:
                best[p["name"]]["src"] = old.get("src") or p["src"]
    final = list(best.values())
    # 按类别分组输出
    import csv
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "aliases", "kcal", "carb", "protein", "fat", "category", "src"])
        for p in sorted(final, key=lambda r: (r["category"], r["name"])):
            w.writerow([p["name"], p["aliases"], p["kcal"], p["carb"],
                        p["protein"], p["fat"], p["category"], p["src"]])
    print("候选总数:", len(final))
    from collections import Counter
    for c, n in Counter(p["category"] for p in final).most_common():
        print(f"  {c}: {n}")


if __name__ == "__main__":
    main()
