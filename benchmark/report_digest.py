"""将编排器输出压成可版本化的摘要，用于 L3 回归。"""
from __future__ import annotations

import json
from typing import Any, Dict


def digest_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """抽取稳定、可人工 diff 的字段（不含自然语言长文）。"""
    ctx = report.get("context") or {}
    inv = report.get("inventory_review") or {}
    sales = report.get("sales_review") or {}
    slow = report.get("slow_moving") or {}
    replen = report.get("replenishment") or {}
    mem = report.get("memory_snapshot") or {}
    sel = report.get("product_selection") or {}

    def _ids(rows: Any, key: str = "sku_id") -> list:
        if not isinstance(rows, list):
            return []
        out = []
        for r in rows:
            if isinstance(r, dict) and key in r:
                out.append(r[key])
        return out

    low = inv.get("low_stock_alerts") or []
    over = inv.get("overstock_alerts") or []
    return {
        "context": {
            "seed": ctx.get("seed"),
            "sku_count": ctx.get("sku_count"),
            "trend_count": ctx.get("trend_count"),
            "top_n": ctx.get("top_n"),
        },
        "inventory_low_stock_ids": _ids(low),
        "inventory_overstock_ids": _ids(over),
        "sales_top_sku_ids": _ids(sales.get("top_skus") or []),
        "sales_high_return_ids": _ids(sales.get("high_return_skus") or []),
        "slow_moving_ids": _ids(slow.get("slow_moving_skus") or []),
        "replenishment_sku_ids": _ids(replen.get("replenishment_rows") or []),
        "memory_snapshot": dict(mem),
        "product_selection_trend_keyword": (
            (sel.get("trend_picks") or [{}])[0].get("keyword") if sel.get("trend_picks") else None
        ),
        "actions_count": len(report.get("actions") or []),
    }


def digest_to_json(report: Dict[str, Any]) -> str:
    return json.dumps(digest_report(report), ensure_ascii=False, indent=2, sort_keys=True)
