"""从 LLM 返回文本中解析 JSON 对象。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict


def strip_markdown_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def parse_json_object(text: str) -> Dict[str, Any]:
    raw = strip_markdown_fence(text)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("JSON 根须为对象")
    return data
