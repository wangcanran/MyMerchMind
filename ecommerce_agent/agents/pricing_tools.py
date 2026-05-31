"""定价工具定义：供 Tool-based Pricing Agent 通过 function calling 调用。"""
from __future__ import annotations

import json
import math
import statistics
from typing import Any, Dict, List, Optional

# ─── 常量 ─────────────────────────────────────────────────────────────────────

DEFAULT_TARGET_GROSS_MARGIN = 0.45


def normalize_target_gross_margin(raw: Optional[float]) -> float:
    """企划情报用目标毛利率：默认 0.45；>1 视为百分数（如 40 → 0.40）；夹紧到 [0.05, 0.85]。"""
    if raw is None:
        return DEFAULT_TARGET_GROSS_MARGIN
    try:
        m = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TARGET_GROSS_MARGIN
    if m > 1.0:
        m = m / 100.0
    if m != m:  # NaN
        return DEFAULT_TARGET_GROSS_MARGIN
    return max(0.05, min(0.85, m))

# ─── Tool Schema（OpenAI function calling 格式）─────────────────────────────

PRICING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_competitor_summary",
            "description": "获取该SKU的竞品价格摘要：样本数、中位数、P25、P75、甜点价（销量最密集价格带的中位数）",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_id": {"type": "string", "description": "SKU编号"},
                },
                "required": ["sku_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_elasticity",
            "description": "基于历史价格-销量数据估算价格弹性系数。弹性>1表示价格敏感，<1表示不敏感。返回弹性值、置信度、R²",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_id": {"type": "string"},
                    "lookback_days": {"type": "integer", "description": "回看天数，默认30"},
                },
                "required": ["sku_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_price",
            "description": "根据策略计算建议价格。返回建议价、锚点来源、毛利率",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_id": {"type": "string"},
                    "strategy": {
                        "type": "string",
                        "enum": ["traffic", "profit", "clearance", "image"],
                        "description": "traffic=引流款卡竞品低位, profit=利润款取最优价, clearance=清仓快速出清, image=形象款维持高价",
                    },
                    "anchor_source": {
                        "type": "string",
                        "enum": ["sweet_spot", "competitor_median", "elasticity_optimal", "cost_plus"],
                        "description": "定价锚点来源",
                    },
                    "target_margin_pct": {
                        "type": "number",
                        "description": "目标毛利率(0-1)，仅cost_plus策略需要",
                    },
                    "seasonal_factor": {
                        "type": "number",
                        "description": "季节系数(0.5-1.5)，<1表示淡季需降价刺激",
                    },
                },
                "required": ["sku_id", "strategy", "anchor_source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_guardrail",
            "description": "对建议价格应用护栏约束：成本底线(cost×1.15)和单次调幅限制。返回约束后的最终价格和触发的护栏",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_id": {"type": "string"},
                    "suggested_price": {"type": "number", "description": "待约束的建议价格"},
                    "max_step_pct": {
                        "type": "number",
                        "description": "单次最大调幅(0-1)，默认0.15，清仓可设0.25",
                    },
                },
                "required": ["sku_id", "suggested_price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decide_no_action",
            "description": "决定不对该SKU调价，维持现价。用于：缺货SKU、健康SKU无外部驱动、高退货待诊断等场景",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_id": {"type": "string"},
                    "reason": {"type": "string", "description": "不调价的具体原因"},
                },
                "required": ["sku_id", "reason"],
            },
        },
    },
]


# ─── Tool 执行器 ─────────────────────────────────────────────────────────────

MIN_MARGIN_FACTOR = 1.15
MAX_STEP_PCT_NORMAL = 0.15
MAX_STEP_PCT_CLEARANCE = 0.25


class PricingToolExecutor:
    """执行定价工具调用，返回结构化结果。"""

    def __init__(
        self,
        sku: Dict[str, Any],
        competitor_prices: List[float],
        competitor_products: Optional[List[Dict]] = None,
    ):
        self.sku = sku
        self.competitor_prices = sorted([p for p in competitor_prices if p > 0])
        self.competitor_products = competitor_products or []
        self._competitor_summary: Optional[Dict] = None
        self._elasticity: Optional[Dict] = None

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "get_competitor_summary":
            return self._get_competitor_summary()
        elif tool_name == "estimate_elasticity":
            return self._estimate_elasticity(args.get("lookback_days", 30))
        elif tool_name == "calculate_price":
            return self._calculate_price(
                strategy=args["strategy"],
                anchor_source=args["anchor_source"],
                target_margin_pct=args.get("target_margin_pct"),
                seasonal_factor=args.get("seasonal_factor", 1.0),
            )
        elif tool_name == "apply_guardrail":
            return self._apply_guardrail(
                suggested_price=args["suggested_price"],
                max_step_pct=args.get("max_step_pct", MAX_STEP_PCT_NORMAL),
            )
        elif tool_name == "decide_no_action":
            return {
                "action": "hold",
                "sku_id": self.sku.get("sku_id", ""),
                "current_price": self.sku.get("price", 0),
                "reason": args.get("reason", ""),
            }
        return {"error": f"Unknown tool: {tool_name}"}

    def _get_competitor_summary(self) -> Dict[str, Any]:
        prices = self.competitor_prices
        if not prices:
            return {"sample_count": 0, "median": None, "p25": None, "p75": None, "sweet_spot": None}

        n = len(prices)
        median = prices[n // 2]
        p25 = prices[max(0, n // 4)]
        p75 = prices[min(n - 1, n * 3 // 4)]

        # Sweet spot: sales-weighted if products available
        sweet = None
        if self.competitor_products:
            sweet = self._sweet_spot_with_sales(self.competitor_products)
        if sweet is None and prices:
            sweet = self._sweet_spot(prices)

        self._competitor_summary = {
            "sample_count": n,
            "median": median,
            "p25": p25,
            "p75": p75,
            "sweet_spot": sweet,
            "price_range": f"¥{prices[0]}-¥{prices[-1]}",
        }
        return self._competitor_summary

    def _estimate_elasticity(self, lookback_days: int = 30) -> Dict[str, Any]:
        history = self.sku.get("price_history") or []
        if len(history) > lookback_days:
            history = history[-lookback_days:]

        points = []
        for rec in history:
            p = float(rec.get("price") or 0)
            q = float(rec.get("daily_sales") or 0)
            if p > 0 and q > 0:
                points.append((math.log(p), math.log(q)))

        if len(points) < 3:
            return {"elasticity": None, "confidence": "insufficient_data", "sample_count": len(points)}

        x_vals = [p[0] for p in points]
        y_vals = [p[1] for p in points]
        x_mean = sum(x_vals) / len(x_vals)
        y_mean = sum(y_vals) / len(y_vals)

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
        denominator = sum((x - x_mean) ** 2 for x in x_vals)
        if denominator == 0:
            return {"elasticity": None, "confidence": "no_variance", "sample_count": len(points)}

        slope = numerator / denominator
        elasticity = -slope  # 取正

        # R²
        ss_res = sum((y - (y_mean + slope * (x - x_mean))) ** 2 for x, y in zip(x_vals, y_vals))
        ss_tot = sum((y - y_mean) ** 2 for y in y_vals)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        if elasticity < 0.3 or elasticity > 10:
            return {"elasticity": None, "confidence": "out_of_range", "raw_value": round(elasticity, 2)}

        confidence = "high" if r_squared > 0.6 and len(points) >= 10 else "medium" if r_squared > 0.3 else "low"
        self._elasticity = {
            "elasticity": round(elasticity, 2),
            "confidence": confidence,
            "r_squared": round(r_squared, 3),
            "sample_count": len(points),
        }
        return self._elasticity

    def _calculate_price(
        self, strategy: str, anchor_source: str,
        target_margin_pct: Optional[float] = None, seasonal_factor: float = 1.0,
    ) -> Dict[str, Any]:
        cost = float(self.sku.get("cost_price") or 0)
        current = float(self.sku.get("price") or 0)
        summary = self._competitor_summary or self._get_competitor_summary()

        # Determine anchor price
        anchor = current
        if anchor_source == "sweet_spot" and summary.get("sweet_spot"):
            anchor = summary["sweet_spot"]
        elif anchor_source == "competitor_median" and summary.get("median"):
            anchor = summary["median"]
        elif anchor_source == "elasticity_optimal" and self._elasticity and self._elasticity.get("elasticity"):
            e = self._elasticity["elasticity"]
            anchor = cost * e / (e - 1) if e > 1 else current
        elif anchor_source == "cost_plus" and cost > 0:
            margin = target_margin_pct or 0.45
            anchor = cost / (1 - margin)

        # Apply strategy modifier
        if strategy == "traffic":
            suggested = anchor * 0.85
        elif strategy == "profit":
            suggested = anchor
        elif strategy == "clearance":
            suggested = anchor * 0.75
        elif strategy == "image":
            suggested = max(anchor * 1.1, current)
        else:
            suggested = anchor

        # Seasonal adjustment
        suggested = suggested * seasonal_factor

        # Cost floor
        cost_floor = cost * MIN_MARGIN_FACTOR if cost > 0 else 0
        if cost_floor and suggested < cost_floor:
            suggested = cost_floor

        suggested = int(round(suggested))
        margin = round((suggested - cost) / suggested * 100, 1) if suggested > 0 and cost > 0 else 0

        return {
            "suggested_price": suggested,
            "anchor_source": anchor_source,
            "anchor_price": int(round(anchor)),
            "strategy": strategy,
            "margin_pct": margin,
            "cost_floor": int(round(cost_floor)) if cost_floor else None,
            "seasonal_factor": seasonal_factor,
        }

    def _apply_guardrail(self, suggested_price: float, max_step_pct: float = 0.15) -> Dict[str, Any]:
        current = float(self.sku.get("price") or 0)
        cost = float(self.sku.get("cost_price") or 0)
        final = int(round(suggested_price))
        guardrails_triggered = []

        # Cost floor
        if cost > 0:
            floor = int(round(cost * MIN_MARGIN_FACTOR))
            if final < floor:
                guardrails_triggered.append(f"成本底线 ¥{floor}")
                final = floor

        # Step limit
        if current > 0:
            upper = int(current * (1 + max_step_pct))
            lower = int(current * (1 - max_step_pct))
            if final > upper:
                guardrails_triggered.append(f"单次涨幅上限 +{int(max_step_pct*100)}% = ¥{upper}")
                final = upper
            elif final < lower:
                guardrails_triggered.append(f"单次降幅上限 -{int(max_step_pct*100)}% = ¥{lower}")
                final = lower

        return {
            "final_price": final,
            "original_suggestion": int(round(suggested_price)),
            "guardrails_triggered": guardrails_triggered,
            "capped": len(guardrails_triggered) > 0,
        }

    @staticmethod
    def _sweet_spot(prices: List[float], bucket_width: float = 20) -> Optional[float]:
        if not prices:
            return None
        lo = min(prices)
        buckets: Dict[int, List[float]] = {}
        for p in prices:
            key = int((p - lo) / bucket_width)
            buckets.setdefault(key, []).append(p)
        best_key = max(buckets, key=lambda k: len(buckets[k]))
        return round(statistics.median(buckets[best_key]))

    @staticmethod
    def _sweet_spot_with_sales(products: List[Dict], bucket_width: float = 20) -> Optional[float]:
        priced = []
        for p in products:
            price = float(p.get("price") or 0)
            sales = float(p.get("sales") or p.get("monthly_sales") or 0)
            if price > 0:
                priced.append((price, max(sales, 1)))
        if not priced:
            return None
        lo = min(p[0] for p in priced)
        buckets: Dict[int, tuple] = {}
        for price, sales in priced:
            key = int((price - lo) / bucket_width)
            plist, stot = buckets.get(key, ([], 0.0))
            plist.append(price)
            buckets[key] = (plist, stot + sales)
        best_key = max(buckets, key=lambda k: buckets[k][1])
        return round(statistics.median(buckets[best_key][0]))
