"""AI 调用唯一入口：视觉识别 + 点评润色。没有 Key 时优雅降级，不抛异常。"""
from __future__ import annotations

import base64
import json
import os
import re

import requests

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
VISION_MODEL = "glm-4v-flash"
TEXT_MODEL = "glm-4-flash"
TIMEOUT = 60

RECOGNIZE_PROMPT = """你是营养师助手，请识别这张食物照片。
只输出一个 JSON，不要解释、不要代码块标记，格式：
{"foods":[{"name":"食物名","grams":估计熟重克数,"confidence":0到1}],"overall_confidence":0到1,"note":"可选"}
要求：
1. name 用中文常见名，尽量简单，例如 米饭、鸡胸肉、西兰花。
2. grams 按图中可见分量估计（熟重），单份通常 50-300 克。
3. 看不清或拿不准时把 confidence 调低，不要编造不存在的食物。
4. 最多 8 项；如果完全看不出是食物，返回空的 foods。"""

REVIEW_PROMPT = """你是一个温和的饮食搭子，不是医生。根据下面这一餐的数据，写 2 句话点评。
要求：口语化、具体、不制造负罪感，不要说“暴食/失败/超标惩罚”，不做疾病或营养诊断。
只输出点评正文，不要加标题或引号。"""


def api_key() -> str:
    import streamlit as st

    try:
        key = st.session_state.get("zhipu_key")
        if key:
            return str(key).strip()
    except Exception:
        pass
    key = os.getenv("ZHIPU_API_KEY", "").strip()
    if key:
        return key
    try:
        return str(st.secrets.get("ZHIPU_API_KEY", "")).strip()
    except Exception:
        return ""


def configured() -> bool:
    return bool(api_key())


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return str(content)


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _chat(model: str, messages: list[dict]) -> str:
    resp = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
        },
        json={"model": model, "messages": messages, "temperature": 0.2},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return _content_text(data["choices"][0]["message"]["content"])


def recognize_food(image_bytes: bytes, mime: str = "image/jpeg") -> dict:
    """返回 {ok, foods, overall_confidence, raw, error}，任何失败都不抛异常。"""
    if not api_key():
        return {
            "ok": False,
            "foods": [],
            "overall_confidence": 0.0,
            "raw": None,
            "error": "还没有配置 AI Key（左侧栏 ⚙️ 可粘贴，或设置环境变量 ZHIPU_API_KEY）",
        }
    try:
        b64 = base64.b64encode(image_bytes).decode()
        content = _chat(VISION_MODEL, [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": RECOGNIZE_PROMPT},
            ],
        }])
    except Exception as exc:  # 网络、额度、鉴权等一律降级
        return {
            "ok": False,
            "foods": [],
            "overall_confidence": 0.0,
            "raw": None,
            "error": f"AI 调用失败（{exc}）",
        }

    data = _parse_json(content)
    if not data:
        return {
            "ok": False,
            "foods": [],
            "overall_confidence": 0.0,
            "raw": content,
            "error": "AI 返回内容不是有效 JSON",
        }

    foods = []
    for item in (data.get("foods") or [])[:8]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            grams = float(item.get("grams") or 0)
        except (TypeError, ValueError):
            grams = 0.0
        try:
            conf = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        foods.append({"name": name, "grams": grams, "confidence": conf})

    try:
        overall = float(data.get("overall_confidence") or 0)
    except (TypeError, ValueError):
        overall = 0.0

    return {
        "ok": True,
        "foods": foods,
        "overall_confidence": overall,
        "raw": content,
        "error": "",
    }


def comment_meal(totals: dict, foods: list[str]) -> str | None:
    """单餐点评。没 Key 或调用失败返回 None，由调用方回退到规则文案。"""
    if not api_key():
        return None
    summary = (
        f"这一餐食物：{'、'.join(foods)}\n"
        f"总热量 {totals['kcal']:.0f} 千卡，碳水 {totals['carb']:.0f}g，"
        f"蛋白质 {totals['protein']:.0f}g，脂肪 {totals['fat']:.0f}g，"
        f"蔬菜 {totals.get('veg_grams', 0):.0f}g。"
    )
    try:
        return _chat(TEXT_MODEL, [
            {"role": "system", "content": REVIEW_PROMPT},
            {"role": "user", "content": summary},
        ]).strip()
    except Exception:
        return None
