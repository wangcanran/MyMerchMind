"""从 JSON 文件加载外部数据，与 mock 结构对齐。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _split_channel_default(daily_sales: int) -> Dict[str, int]:
    if daily_sales <= 0:
        return {"live": 0, "private": 0, "shelf": 0}
    third = daily_sales // 3
    return {
        "live": third,
        "private": third,
        "shelf": daily_sales - 2 * third,
    }


def _normalize_sku_record(sku_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    daily = int(raw.get("daily_sales", 0) or 0)
    name = str(raw.get("name") or "未命名SKU")
    stock = int(raw.get("stock", 0) or 0)
    in_transit = int(raw.get("in_transit", 0) or 0)
    return_rate = float(raw.get("return_rate", 0.05) or 0.0)
    conversion = float(raw.get("conversion_rate", 0.01) or 0.0)
    stock_age = int(raw.get("stock_age_days", 30) or 0)

    raw_price = raw.get("price")
    price: Optional[float] = float(raw_price) if raw_price is not None else None
    raw_cost = raw.get("cost_price")
    cost_price: Optional[float] = float(raw_cost) if raw_cost is not None else None

    ch = raw.get("channel_sales")
    if isinstance(ch, dict):
        channel_sales = {
            "live": int(ch.get("live", 0) or 0),
            "private": int(ch.get("private", 0) or 0),
            "shelf": int(ch.get("shelf", 0) or 0),
        }
    else:
        channel_sales = _split_channel_default(daily)

    reviews = raw.get("review_snippets")
    if isinstance(reviews, list):
        review_snippets = [str(x) for x in reviews]
    else:
        review_snippets = []

    pw = raw.get("prior_week_total_units")
    pm = raw.get("prior_month_total_units")
    if pw is None:
        prior_week_total_units = max(0, int(daily * 7))
    else:
        prior_week_total_units = int(pw)
    if pm is None:
        prior_month_total_units = max(0, int(daily * 30))
    else:
        prior_month_total_units = int(pm)

    return {
        "name": name,
        "price": price,
        "cost_price": cost_price,
        "daily_sales": daily,
        "stock": stock,
        "in_transit": in_transit,
        "return_rate": return_rate,
        "channel_sales": channel_sales,
        "conversion_rate": conversion,
        "stock_age_days": stock_age,
        "review_snippets": review_snippets,
        "prior_week_total_units": prior_week_total_units,
        "prior_month_total_units": prior_month_total_units,
    }


def load_erp_skus_from_json(path: Path) -> Dict[str, Dict[str, Any]]:
    """加载 ERP SKU 字典。支持 {\"skus\": { \"SKU001\": {...} }} 或 {\"skus\": [ {\"sku_id\":...}, ... ] }。"""
    text = path.read_text(encoding="utf-8")
    root = json.loads(text)
    if not isinstance(root, dict) or "skus" not in root:
        raise ValueError(f"{path}: 根对象需包含 \"skus\" 键")

    raw_skus = root["skus"]
    out: Dict[str, Dict[str, Any]] = {}

    if isinstance(raw_skus, dict):
        for sku_id, body in raw_skus.items():
            if not isinstance(body, dict):
                raise ValueError(f"{path}: skus[{sku_id!r}] 须为对象")
            sid = str(sku_id)
            out[sid] = _normalize_sku_record(sid, body)
    elif isinstance(raw_skus, list):
        for i, body in enumerate(raw_skus):
            if not isinstance(body, dict):
                raise ValueError(f"{path}: skus[{i}] 须为对象")
            sid = str(body.get("sku_id", "")).strip()
            if not sid:
                raise ValueError(f"{path}: skus[{i}] 缺少 sku_id")
            norm = dict(body)
            norm.pop("sku_id", None)
            out[sid] = _normalize_sku_record(sid, norm)
    else:
        raise ValueError(f"{path}: \"skus\" 须为对象或数组")

    if not out:
        raise ValueError(f"{path}: 未加载到任何 SKU")
    return out


def load_trends_from_json(path: Path) -> List[Dict[str, Any]]:
    """加载趋势列表；按 heat_score 降序排序。"""
    text = path.read_text(encoding="utf-8")
    root = json.loads(text)
    if not isinstance(root, dict) or "trends" not in root:
        raise ValueError(f"{path}: 根对象需包含 \"trends\" 数组")
    rows = root["trends"]
    if not isinstance(rows, list):
        raise ValueError(f"{path}: \"trends\" 须为数组")
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: trends[{i}] 须为对象")
        kw = str(row.get("keyword", "")).strip()
        if not kw:
            raise ValueError(f"{path}: trends[{i}] 缺少 keyword")
        ts = row.get("timestamp")
        if ts is None:
            ts = datetime.now().isoformat()
        else:
            ts = str(ts)
        out.append(
            {
                "keyword": kw,
                "platform": str(row.get("platform", "外部导入")),
                "heat_score": float(row.get("heat_score", 0) or 0),
                "growth_rate": float(row.get("growth_rate", 0) or 0),
                "timestamp": ts,
            }
        )
    out.sort(key=lambda x: x["heat_score"], reverse=True)
    return out


_COMP_KEYS = (
    "category_key",
    "competitor_new_skus_30d",
    "price_band",
    "ours_new_skus_30d",
    "gap_note",
)


def load_competitors_from_json(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    root = json.loads(text)
    if not isinstance(root, dict) or "rows" not in root:
        raise ValueError(f"{path}: 根对象需包含 \"rows\" 数组")
    rows = root["rows"]
    if not isinstance(rows, list):
        raise ValueError(f"{path}: \"rows\" 须为数组")
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: rows[{i}] 须为对象")
        item: Dict[str, Any] = {}
        for k in _COMP_KEYS:
            if k not in row:
                raise ValueError(f"{path}: rows[{i}] 缺少字段 {k!r}")
            item[k] = row[k]
        out.append(item)
    return out


def load_tags_from_json(path: Path) -> Dict[str, Dict[str, str]]:
    """扁平结构：{\"SKU001\": {\"collar\":...,\"material\":...,\"style\":...,\"color\":...}}。"""
    text = path.read_text(encoding="utf-8")
    root = json.loads(text)
    if not isinstance(root, dict) or "tags" not in root:
        raise ValueError(f"{path}: 根对象需包含 \"tags\" 对象")
    tags = root["tags"]
    if not isinstance(tags, dict):
        raise ValueError(f"{path}: \"tags\" 须为对象")
    out: Dict[str, Dict[str, str]] = {}
    for sku_id, body in tags.items():
        if not isinstance(body, dict):
            raise ValueError(f"{path}: tags[{sku_id!r}] 须为对象")
        sid = str(sku_id)
        out[sid] = {
            "collar": str(body.get("collar", "")),
            "material": str(body.get("material", "")),
            "style": str(body.get("style", "")),
            "color": str(body.get("color", "")),
        }
    return out
