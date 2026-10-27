"""合库：成分表候选 + 现有库 → 最终 foods.csv。
规则: 同物(同名或别名命中)并入原库保留原库数值; 油脂能量字段用宏量补; 剔除黑名单。
"""
from __future__ import annotations

import csv
import re

CAND = "/tmp/food_candidates.csv"
CUR = "/home/user/Doubao/chats/38449710648766978/jkd_repro/data/foods.csv"
OUT = "/tmp/foods_merged.csv"

# 黑名单: 怪名/纯配料/小众品种/干鲜歧义
DROP = set("""
五谷香 优糯米 团粉 早籼 早糯谷 晚籼 桂花藕粉 淀粉 煎炸粉 蚕豆淀粉 豌豆淀粉
豌豆粉丝 马铃薯全粉 魔芋精粉 三湖红橘 中华猕猴桃 乐陵枣 五月鲜桃 京白梨
伏苹果 倭锦苹果 冬果梨 余柑子 刺梨 大麻油 棉籽油 棕榈油 混合油 红花油
胡麻油 茶油 北风菌 牛眼睛菌 干巴菌 三七尖 棠梨花 南瓜粉 南瓜藤 奶柿子
小水萝卜 小西胡瓜 方瓜 根芹 抱子甘蓝 乌塌菜 乌菜 冬寒菜 叶甜菜 四棱豆
地衣 垅船豆 发芽豆 刀豆 分葱 慈姑 槟榔芋 豆薯 大薯 双孢蘑菇 海带菜 榛蘑
瓦罐鸡汤 毛蛋 华青鸡 沙鸡 公麻鸭 母麻鸭 北京填鸭 海鸭蛋 童子鸡 扒鸡 卤煮鸡
墨鱼 鱿鱼 鳗鲡 火鸡肝 火鸡肫 火鸡腿 猪耳 牛舌 牛尾
人乳 乌鱼蛋 乌龟 双髻鲨 刺泡鱼 口头鱼 堤鱼 回头鱼 尖嘴白 六角螺 口虾蛄
炸素虾 素大肠 素什锦 素火腿 素鸡丝卷 午餐肚 午餐肠 午餐鱼 大肉肠 大腊肠
儿童肠 三明治火腿 咖哩牛肉干 太仓肉松 鸡肉松 鸡血 鸡蛋粉 鸡蛋黄粉 鸭蛋白
鸭蛋黄 鹅蛋白 野山鸡 肉鸡 腊鹅 卤猪杂 墨鱼丸 墨鱼圈 枝竹 红豆沙 红豆馅
绿豆饼 绿豆面 小豆粥 烤麸
空锅饼 肚里黄 籼稻 籼糯米 粳糯米 紫红糯米 糜子 糜子米 苦荞麦粉 玉米糁
玉米面面条 马铃薯丁 甘薯片 甘薯粉 小麦胚粉 玉米淀粉
洋丝瓜苗 穿心莲 紫背天葵 番杏 白凤菜 红奶浆菌 青头菌 鸡枞花 香杏丁蘑
琼脂 球茎茴香 甜菜叶 甜菜根 樱桃萝卜缨 胡萝卜缨 芥菜头 秋黄瓜 笋瓜 白瓜
瓢儿白 盖菜 奶白菜 水萝卜 红旦旦萝卜 花叶萝卜 芹菜叶 芹菜茎 结球菊苣
苤蓝 苦菜 樱桃萝卜 羽衣甘蓝
印度苹果 国光苹果 吊蛋 子瓜 小西瓜 密云小枣 小叶橘 布朗 庆丰桃 旱久保桃
旱苹果 明月梨 早桃 早橘 早酥梨 晚桃 木梨 李子杏 杏干 桂圆肉 松子仁
栗子仁 南瓜子仁 麦胚油 辣椒油 豆油 鸡枞
扒猪脸 抗浪鱼 斑鳠 梅花参 文蛤丸 松江肠 火腿心肉 尖嘴鱼 塘水虾 大菱鲆鱼
梅童鱼 牛大肠 全脂甜炼乳 橡实 榛子仁 毛核桃 祝光苹果 秋里蒙苹果 红星苹果
磨盘柿 橘饼 白金瓜 白兰瓜 灵蜜瓜 白粉桃
""".split())

# 手动映射: 新行 name -> 原库 name (自动规则漏掉的同物)
MERGE = {
    "纯牛奶": "牛奶", "鲜牛奶": "牛奶", "炼乳": "牛奶", "橙": "橙子",
    "桃": "桃子", "甘薯": "红薯", "鲈鱼": "鱼肉", "鲑鱼": "三文鱼",
    "草鱼": "鱼肉", "鸡胸脯肉": "鸡胸肉", "虾皮": "虾", "虾米": "虾",
    "菜花": "西兰花", "白萝卜": "白菜", "葱": "小葱", "姜": "生姜",
    "奶油": "黄油", "芡粉": "淀粉", "橄榄": "橄榄",
}


def clean_key(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"[（(].*?[）)]", "", s)
    return re.sub(r"\s+", "", s)


def main() -> None:
    cur = list(csv.DictReader(open(CUR, encoding="utf-8")))
    # 原库索引: name -> row; alias -> name
    name_idx: dict[str, int] = {}
    alias_idx: dict[str, str] = {}
    for i, r in enumerate(cur):
        name_idx[clean_key(r["name"])] = i
        for a in str(r.get("aliases") or "").split("|"):
            k = clean_key(a)
            if k:
                alias_idx[k] = clean_key(r["name"])
    cand = list(csv.DictReader(open(CAND, encoding="utf-8")))

    added = 0
    merged = 0
    for r in cand:
        name = r["name"].strip()
        if name in DROP:
            continue
        kcal = float(r["kcal"]); fat = float(r["fat"])
        carb = float(r["carb"]); protein = float(r["protein"])
        # 油脂能量补全: kcal=0 但宏量齐全
        if kcal <= 0 and (fat >= 90 or (carb + protein + fat) > 90):
            kcal = round(4 * protein + 4 * carb + 9 * fat, 0)
        r["kcal"] = f"{kcal:.0f}"; r["fat"] = f"{fat:.1f}"
        r["carb"] = f"{carb:.1f}"; r["protein"] = f"{protein:.1f}"

        key = clean_key(name)
        target = MERGE.get(name)
        if target is None:
            if key in name_idx:
                target = cur[name_idx[key]]["name"]
            elif key in alias_idx:
                target = alias_idx[key]
            else:
                # 新行 aliases 命中原库 name/aliases
                for a in str(r.get("aliases") or "").split("|"):
                    k = clean_key(a)
                    if k in name_idx:
                        target = cur[name_idx[k]]["name"]
                        break
                    if k in alias_idx:
                        target = alias_idx[k]
                        break
        if target:
            # 合并: 把新行全名并入原行 aliases
            idx = name_idx.get(clean_key(target))
            if idx is None:
                idx = alias_idx.get(clean_key(target))
            if idx is not None:
                old_aliases = str(cur[idx].get("aliases") or "")
                extra = [str(r.get("src") or "")]
                extra += [a for a in str(r.get("aliases") or "").split("|") if a]
                new_aliases = "|".join(dict.fromkeys(
                    [x for x in old_aliases.split("|") + extra if x and clean_key(x) != clean_key(cur[idx]["name"])]
                ))
                cur[idx]["aliases"] = new_aliases
                merged += 1
                continue
        # 追加
        cur.append({
            "name": name,
            "aliases": str(r.get("aliases") or ""),
            "kcal": r["kcal"], "carb": r["carb"],
            "protein": r["protein"], "fat": r["fat"],
            "category": r["category"],
        })
        added += 1

    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["name", "aliases", "kcal", "carb", "protein", "fat", "category"])
        w.writeheader()
        w.writerows(cur)
    print(f"原库 {len(cur) - added - merged} -> 合并 {merged} 条, 新增 {added} 条, 最终 {len(cur)} 条")
    # 校验
    names = [clean_key(r["name"]) for r in cur]
    dup = {n for n in names if names.count(n) > 1}
    print("重复 name:", dup if dup else "无")
    bad = []
    for r in cur:
        k, c, p, f = float(r["kcal"]), float(r["carb"]), float(r["protein"]), float(r["fat"])
        calc = 4 * p + 4 * c + 9 * f
        if calc > 0 and abs(k - calc) / calc > 0.35:
            bad.append(f"{r['name']} {k}kcal vs {calc:.0f}")
    print("能量异常:", bad if bad else "无")


if __name__ == "__main__":
    main()
