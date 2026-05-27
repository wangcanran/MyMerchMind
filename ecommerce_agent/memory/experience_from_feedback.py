"""
从策略反馈生成有指导价值的经验。

当商家对已执行策略提交反馈（效果+原因）后，
自动生成 active 经验条目，跳过 draft 审批流程。
search_keys 从策略的 run 上下文自动补全，确保经验能被正确检索命中。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

_MODULE_LABELS = {
    "selection": "选品",
    "pricing": "定价",
    "inventory": "库存",
    "replenishment": "补货",
    "slow_moving": "滞销处理",
    "category": "品类管理",
    "other": "运营",
}

_OUTCOME_LABELS = {
    "good": "效果好",
    "average": "效果一般",
    "poor": "效果差",
}

_SEASON_MAP = {
    (3, 4, 5): "spring",
    (6, 7, 8): "summer",
    (9, 10, 11): "autumn",
    (12, 1, 2): "winter",
}


def _infer_season(as_of: str) -> str:
    """从日期字符串推断季节。"""
    try:
        month = int(as_of.split("-")[1])
    except (IndexError, ValueError):
        return ""
    for months, season in _SEASON_MAP.items():
        if month in months:
            return season
    return ""


def _infer_price_tier(desc: str) -> str:
    """从描述中提取价格并推断价位带。"""
    prices = re.findall(r"[¥￥]?\s*(\d+)", desc)
    if not prices:
        return ""
    price = max(int(p) for p in prices)
    if price <= 100:
        return "0-100"
    elif price <= 200:
        return "100-200"
    elif price <= 500:
        return "200-500"
    else:
        return "500+"


def _infer_channel(desc: str) -> str:
    """从描述中推断主渠道。"""
    if "直播" in desc or "live" in desc:
        return "live"
    if "私域" in desc or "private" in desc:
        return "private"
    if "货架" in desc or "shelf" in desc:
        return "shelf"
    return ""


def _extract_search_keys_from_strategy(strategy: Dict[str, Any]) -> Dict[str, Any]:
    """从策略描述和上下文中提取完整的 search_keys。"""
    desc = strategy.get("description", "")
    as_of = strategy.get("as_of", "")
    module = strategy.get("module", "other")

    # 品类提取
    categories = []
    for cat in ["连衣裙", "T恤", "外套", "裤子", "衬衫", "针织", "卫衣", "开衫", "半身裙", "风衣"]:
        if cat in desc:
            categories.append(cat)

    # 颜色提取
    colors = []
    for color in ["黑色", "白色", "咖啡色", "深棕色", "米色", "灰色", "蓝色", "红色"]:
        if color in desc:
            colors.append(color)

    # 材质提取
    materials = []
    for mat in ["涤纶", "天丝", "棉", "羊毛", "牛仔", "雪纺", "真丝", "亚麻"]:
        if mat in desc:
            materials.append(mat)

    # 风格提取
    styles = []
    for style in ["通勤", "休闲", "韩系", "美拉德", "静奢", "辣妹", "复古"]:
        if style in desc:
            styles.append(style)

    # 信号推断
    return_signal = "elevated" if "退货" in desc else "normal"
    inventory_signal = "overstocked" if any(k in desc for k in ["滞销", "库存", "去化", "库龄"]) else "normal"
    conversion_signal = "low" if "转化" in desc and "低" in desc else ""

    # 构建 tags
    tags: Dict[str, str] = {}
    if colors:
        tags["color"] = colors[0]
    if materials:
        tags["material"] = materials[0]
    if styles:
        tags["style"] = styles[0]

    return {
        "season": _infer_season(as_of),
        "category": categories,
        "price_tier": _infer_price_tier(desc),
        "channel_dominant": _infer_channel(desc),
        "return_signal": return_signal,
        "inventory_signal": inventory_signal,
        "conversion_signal": conversion_signal,
        "tags": tags,
        "trend_keywords": styles,  # 风格词也作为趋势词
        "criteria_style": styles[0] if styles else "",
        "criteria_audience": "",
    }


def generate_experience_from_feedback(
    strategy: Dict[str, Any],
    feedback: Dict[str, Any],
    experience_store: Any,
) -> Optional[Dict[str, Any]]:
    """将策略+反馈转化为 active 经验。

    search_keys 从策略的 as_of 日期和描述文本自动推断：
    - season: 从 as_of 月份推断
    - price_tier: 从描述中的价格数字推断
    - category/tags: 从描述中的品类/颜色/材质/风格关键词提取
    - channel: 从描述中的渠道关键词推断
    - return_signal/inventory_signal: 从描述语义推断

    Args:
        strategy: StrategyRecord dict
        feedback: FeedbackRecord dict (embedded in strategy)
        experience_store: ExperienceStore instance

    Returns:
        新创建的经验条目，失败返回 None。
    """
    if not strategy or not feedback:
        return None

    module = strategy.get("module", "other")
    module_label = _MODULE_LABELS.get(module, "运营")
    description = strategy.get("description", "")
    outcome = feedback.get("outcome", "average")
    outcome_label = _OUTCOME_LABELS.get(outcome, outcome)
    reason = feedback.get("reason", "")

    # 构建有指导价值的 narrative
    narrative = (
        f"【{module_label}策略反馈】{description} — "
        f"执行结果：{outcome_label}。"
    )
    if reason:
        narrative += f"商家反馈：{reason}。"

    # 根据效果设定 confidence
    if outcome in ("good", "poor"):
        confidence = "high"
    else:
        confidence = "medium"

    # 构建 title
    if outcome == "good":
        title = f"有效策略：{description[:20]}"
    elif outcome == "poor":
        title = f"无效策略：{description[:20]}"
    else:
        title = f"策略参考：{description[:20]}"

    # 提取 search_keys（自动从策略上下文补全）
    search_keys = _extract_search_keys_from_strategy(strategy)

    # 构建 evidence
    evidence = {
        "strategy_id": strategy.get("strategy_id", ""),
        "run_id": strategy.get("run_id", ""),
        "as_of": strategy.get("as_of", ""),
        "sku_ids": re.findall(r"SKU\d+", description),
        "kpi_snapshot": feedback.get("kpi_data", {}),
    }

    # 直接写入 active（有人工归因，跳过 draft）
    entry = experience_store.append_human(
        title=title[:30],
        narrative=narrative,
        search_keys=search_keys,
        evidence=evidence,
        confidence=confidence,
    )

    # 补充 source 标记
    if entry:
        entry["source"] = "strategy_feedback"
        experience_store.save()

    return entry
