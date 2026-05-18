"""从 LLM 返回文本中解析 JSON 对象。"""
from __future__ import annotations

import ast
import json
import re
from typing import Any, Dict


def strip_markdown_fence(text: str) -> str:
    t = (text or "").replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _extract_first_json_object(text: str) -> str | None:
    s = text
    depth = 0
    start: int | None = None
    in_str = False
    esc = False

    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
            continue

        if ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                candidate = s[start : i + 1]
                try:
                    obj = json.loads(candidate)
                except json.JSONDecodeError:
                    start = None
                    continue
                if isinstance(obj, dict):
                    return candidate
                start = None
                continue

    return None


def _extract_first_brace_object(text: str) -> str | None:
    s = text
    depth = 0
    start: int | None = None
    in_str = False
    esc = False

    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
            continue

        if ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                return s[start : i + 1]

    return None


def _strip_trailing_commas(s: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", s)


def parse_json_object(text: str) -> Dict[str, Any]:
    raw = strip_markdown_fence(text)
    if not raw.strip():
        raise ValueError("空响应")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        candidate = _extract_first_json_object(raw) or _extract_first_brace_object(raw)
        if not candidate:
            raise
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            repaired = _strip_trailing_commas(candidate)
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                try:
                    data = ast.literal_eval(candidate)
                except Exception as e:
                    raise ValueError(f"JSON 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("JSON 根须为对象")
    return data
