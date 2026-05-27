"""从 run() 输出中自动提取经验草稿（auto_draft）。

规则
----
每条 draft 来自**系统可采集的信号**，不做主观归因；
叙事正文只描述观测到的数字事实，边界与归因留给人工编辑。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .experience_store import (
    ExperienceStore,
    _derive_season,
    _derive_price_tier,
    _derive_return_signal,
    _derive_inventory_signal,
    _derive_conversion_signal,
    _derive_channel_dominant,
    _make_run_id,
)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _cat_for_sku(sku_name: str, category_mapping: Optional[Dict[str, str]]) -> str:
    if not category_mapping:
        return ""
    for keyword, cat in category_mapping.items():
        if keyword in (sku_name or ""):
            return cat
    return ""


def _tag_values(tags: Dict[str, str]) -> List[str]:
    return [v for v in tags.values() if v]


# ---------------------------------------------------------------------------
# 各类信号 → draft
# ---------------------------------------------------------------------------

def _drafts_from_high_return(
    sku_metrics: List[Dict[str, Any]],
    *,
    as_of: str,
    run_id: str,
    category_mapping: Optional[Dict[str, str]],
    all_tags: Optional[Dict[str, Dict[str, str]]],
    high_return_threshold: float = 0.08,
) -> List[Dict[str, Any]]:
    """高退货 SKU → draft（退货 + 转化 + 渠道信号）。"""
    drafts = []
    for sku in sku_metrics:
        rr = float(sku.get("return_rate") or 0)
        if rr < high_return_threshold:
            continue
        sku_id = str(sku.get("sku_id", ""))
        name = str(sku.get("name", ""))
        tags = (all_tags or {}).get(sku_id, {})
        cat = _cat_for_sku(name, category_mapping)
        price = sku.get("price")
        drafts.append({
            "title": f"高退货观测：{name or sku_id}（退货率 {rr*100:.1f}%）",
            "narrative": (
                f"SKU {sku_id}（{name}）在 {as_of} 报告中退货率为 {rr*100:.1f}%，"
                f"日均销售 {sku.get('daily_sales', '-')} 件，"
                f"转化率 {(sku.get('conversion_rate') or 0)*100:.2f}%，"
                f"主销渠道 {_derive_channel_dominant(sku.get('channel_sales')) or '未知'}。"
                "具体归因（色差/版型/材质/描述失实等）需结合评价与退货原因人工补充。"
            ),
            "search_keys": {
                "season": _derive_season(as_of),
                "category": [cat] if cat else [],
                "price_tier": _derive_price_tier(price),
                "channel_dominant": _derive_channel_dominant(sku.get("channel_sales")),
                "return_signal": _derive_return_signal(rr),
                "inventory_signal": _derive_inventory_signal(sku.get("stock_age_days")),
                "conversion_signal": _derive_conversion_signal(sku.get("conversion_rate")),
                "tags": dict(tags),
                "trend_keywords": [],
                "criteria_style": "",
                "criteria_audience": "",
            },
            "evidence": {
                "run_id": run_id,
                "as_of": as_of,
                "sku_ids": [sku_id],
                "kpi_snapshot": {
                    "daily_sales": sku.get("daily_sales"),
                    "return_rate": rr,
                    "conversion_rate": sku.get("conversion_rate"),
                    "stock_age_days": sku.get("stock_age_days"),
                    "price": price,
                },
            },
            "confidence": "low",
            "source": "auto_draft",
        })
    return drafts


def _drafts_from_slow_moving(
    slow_moving: Dict[str, Any],
    *,
    as_of: str,
    run_id: str,
    category_mapping: Optional[Dict[str, str]],
    all_tags: Optional[Dict[str, Dict[str, str]]],
) -> List[Dict[str, Any]]:
    """慢动销/滞销 SKU → draft。"""
    drafts = []
    # SlowMovingAgent 输出键为 slow_moving_skus
    candidates = (
        slow_moving.get("slow_moving_skus")
        or slow_moving.get("candidates")
        or []
    )
    for sku in candidates:
        if not isinstance(sku, dict):
            continue
        sku_id = str(sku.get("sku_id", ""))
        name = str(sku.get("name", ""))
        tags = (all_tags or {}).get(sku_id, {})
        cat = _cat_for_sku(name, category_mapping)
        age = sku.get("stock_age_days")
        drafts.append({
            "title": f"滞销观测：{name or sku_id}（库龄 {age or '-'} 天）",
            "narrative": (
                f"SKU {sku_id}（{name}）在 {as_of} 报告中库龄 {age} 天，"
                f"日均销售 {sku.get('daily_sales', '-')} 件，"
                f"在库 {sku.get('stock', '-')} 件。"
                "具体原因（趋势退热/定价偏高/备货失误等）需结合市场与运营人工判断。"
            ),
            "search_keys": {
                "season": _derive_season(as_of),
                "category": [cat] if cat else [],
                "price_tier": _derive_price_tier(sku.get("price")),
                "channel_dominant": _derive_channel_dominant(sku.get("channel_sales")),
                "return_signal": _derive_return_signal(sku.get("return_rate")),
                "inventory_signal": _derive_inventory_signal(age),
                "conversion_signal": _derive_conversion_signal(sku.get("conversion_rate")),
                "tags": dict(tags),
                "trend_keywords": [],
                "criteria_style": "",
                "criteria_audience": "",
            },
            "evidence": {
                "run_id": run_id,
                "as_of": as_of,
                "sku_ids": [sku_id],
                "kpi_snapshot": {
                    "daily_sales": sku.get("daily_sales"),
                    "return_rate": sku.get("return_rate"),
                    "stock": sku.get("stock"),
                    "stock_age_days": age,
                },
            },
            "confidence": "low",
            "source": "auto_draft",
        })
    return drafts


def _drafts_from_approve_new(
    product_selection: Dict[str, Any],
    *,
    as_of: str,
    run_id: str,
    trend_keywords: List[str],
) -> List[Dict[str, Any]]:
    """M3 approve_new 企划 → draft（记录「曾决定上新」，供后续对比动销）。"""
    npp = product_selection.get("new_product_planning")
    if not isinstance(npp, dict):
        return []
    items = [str(x).strip() for x in (npp.get("items") or []) if str(x).strip()]
    if not items:
        return []
    criteria = product_selection.get("criteria") or {}
    return [{
        "title": f"新品企划决策：{'、'.join(items[:3])}{'…' if len(items) > 3 else ''}",
        "narrative": (
            f"{as_of} 报告中 M3 评估产生 approve_new，品类：{', '.join(items)}。"
            "建议在上新 30 天后回写动销结果，判断企划决策质量。"
        ),
        "search_keys": {
            "season": _derive_season(as_of),
            "category": items,
            "price_tier": "",
            "channel_dominant": "",
            "return_signal": "",
            "inventory_signal": "",
            "conversion_signal": "",
            "tags": {},
            "trend_keywords": trend_keywords[:5],
            "criteria_style": str((criteria or {}).get("target_style") or "").strip(),
            "criteria_audience": str((criteria or {}).get("target_audience") or "").strip(),
        },
        "evidence": {
            "run_id": run_id,
            "as_of": as_of,
            "sku_ids": [],
            "kpi_snapshot": {},
        },
        "confidence": "low",
        "source": "auto_draft",
    }]


def _drafts_from_pricing_anomaly(
    pricing: Dict[str, Any],
    *,
    as_of: str,
    run_id: str,
    large_deviation_threshold: float = 0.20,
) -> List[Dict[str, Any]]:
    """定价偏差超过阈值的 SKU → draft（记录「大幅调价建议」）。"""
    drafts = []
    for row in (pricing.get("pricing_suggestions") or []):
        if not isinstance(row, dict):
            continue
        cur = float(row.get("current_price") or 0)
        sug = float(row.get("suggested_price") or 0)
        if not cur or not sug:
            continue
        gap = abs(sug - cur) / cur
        if gap < large_deviation_threshold:
            continue
        sku_id = str(row.get("sku_id", ""))
        name = str(row.get("name", ""))
        drafts.append({
            "title": f"定价大幅偏差：{name or sku_id}（现 ¥{cur}→建议 ¥{sug}，偏差 {gap*100:.0f}%）",
            "narrative": (
                f"SKU {sku_id}（{name}）在 {as_of} 报告中，"
                f"规则定价建议从 ¥{cur} 调至 ¥{sug}（{row.get('strategy', '')}），"
                f"偏差 {gap*100:.0f}%。"
                "实际是否执行调价、调价后转化与毛利变化需人工后续补录。"
            ),
            "search_keys": {
                "season": _derive_season(as_of),
                "category": [],
                "price_tier": _derive_price_tier(cur),
                "channel_dominant": "",
                "return_signal": "",
                "inventory_signal": "",
                "conversion_signal": "",
                "tags": {},
                "trend_keywords": [],
                "criteria_style": "",
                "criteria_audience": "",
            },
            "evidence": {
                "run_id": run_id,
                "as_of": as_of,
                "sku_ids": [sku_id],
                "kpi_snapshot": {
                    "current_price": cur,
                    "suggested_price": sug,
                    "strategy": row.get("strategy"),
                    "price_deviation_pct": round(gap * 100, 1),
                },
            },
            "confidence": "low",
            "source": "auto_draft",
        })
    return drafts


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def generate_drafts_from_run(
    run_result: Dict[str, Any],
    *,
    experience_store: ExperienceStore,
    seed: int = 42,
    category_mapping: Optional[Dict[str, str]] = None,
    all_tags: Optional[Dict[str, Dict[str, str]]] = None,
    high_return_threshold: float = 0.08,
    pricing_deviation_threshold: float = 0.20,
    save: bool = True,
) -> List[Dict[str, Any]]:
    """从 run() 结果提取所有 auto_draft 并写入 ExperienceStore。

    不会重复写入：同一 run_id + sku_id 组合已存在则跳过。
    返回本次新增的 draft 列表。
    """
    as_of = str((run_result.get("context") or {}).get("as_of") or "")
    run_id = _make_run_id(as_of, seed)

    existing_run_ids = {
        e.get("evidence", {}).get("run_id")
        for e in experience_store.list_all()
    }
    if run_id in existing_run_ids:
        return []

    erp_skus: List[Dict] = run_result.get("_sku_metrics_snapshot") or []

    ps = run_result.get("product_selection") or {}
    criteria = ps.get("criteria") or {} if isinstance(ps, dict) else {}

    trend_keywords: List[str] = []
    for t in (run_result.get("_top_trends") or [])[:5]:
        kw = str(t.get("keyword", "")).strip() if isinstance(t, dict) else ""
        if kw:
            trend_keywords.append(kw)

    all_drafts: List[Dict[str, Any]] = []

    all_drafts += _drafts_from_high_return(
        erp_skus,
        as_of=as_of,
        run_id=run_id,
        category_mapping=category_mapping,
        all_tags=all_tags,
        high_return_threshold=high_return_threshold,
    )

    all_drafts += _drafts_from_slow_moving(
        run_result.get("slow_moving") or {},
        as_of=as_of,
        run_id=run_id,
        category_mapping=category_mapping,
        all_tags=all_tags,
    )

    all_drafts += _drafts_from_approve_new(
        ps if isinstance(ps, dict) else {},
        as_of=as_of,
        run_id=run_id,
        trend_keywords=trend_keywords,
    )

    all_drafts += _drafts_from_pricing_anomaly(
        run_result.get("pricing") or {},
        as_of=as_of,
        run_id=run_id,
        large_deviation_threshold=pricing_deviation_threshold,
    )

    added = []
    for draft in all_drafts:
        entry = experience_store.append_draft(
            title=draft["title"],
            narrative=draft["narrative"],
            search_keys=draft["search_keys"],
            evidence=draft["evidence"],
            source=draft.get("source", "auto_draft"),
            confidence=draft.get("confidence", "low"),
        )
        added.append(entry)

    if save and added:
        experience_store.save()

    return added
