"""库存工具定义：供 Tool-based Inventory Agent 通过 function calling 调用。"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


INVENTORY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_sku_inventory_status",
            "description": "获取SKU库存状态：可售库存、在途、覆盖天数、7天均销、波动率",
            "parameters": {
                "type": "object",
                "properties": {"sku_id": {"type": "string"}},
                "required": ["sku_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_replenishment",
            "description": "计算补货建议：目标库存、补货点、建议补货量、EOQ",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_id": {"type": "string"},
                    "replenishment_cycle_days": {"type": "integer", "description": "补货周期(天)，默认7"},
                    "safety_stock_days": {"type": "number", "description": "安全库存天数，默认3"},
                },
                "required": ["sku_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assess_overstock_risk",
            "description": "评估高库存风险：压力分数、建议清仓策略、去化周期",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_id": {"type": "string"},
                    "overstock_threshold_days": {"type": "integer", "description": "高库存阈值(天)，默认45"},
                },
                "required": ["sku_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decide_inventory_action",
            "description": "输出最终库存决策：补货/去化/观察/冻结",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["replenish", "clearance", "hold", "freeze_po"]},
                    "qty": {"type": "integer", "description": "补货数量（仅replenish时需要）"},
                    "strategy": {"type": "string", "description": "策略描述"},
                    "reasoning": {"type": "string"},
                },
                "required": ["sku_id", "action", "reasoning"],
            },
        },
    },
]


class InventoryToolExecutor:
    """执行库存工具调用。"""

    def __init__(self, sku: Dict[str, Any], replenishment_cycle_days: int = 7, overstock_days: int = 45):
        self.sku = sku
        self.replenishment_cycle_days = replenishment_cycle_days
        self.overstock_days = overstock_days
        self._status: Optional[Dict] = None

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "get_sku_inventory_status":
            return self._get_status()
        elif tool_name == "calculate_replenishment":
            return self._calculate_replenishment(
                args.get("replenishment_cycle_days", self.replenishment_cycle_days),
                args.get("safety_stock_days", 3),
            )
        elif tool_name == "assess_overstock_risk":
            return self._assess_overstock(args.get("overstock_threshold_days", self.overstock_days))
        elif tool_name == "decide_inventory_action":
            return {
                "sku_id": self.sku.get("sku_id", ""),
                "action": args["action"],
                "qty": args.get("qty", 0),
                "strategy": args.get("strategy", ""),
                "reasoning": args["reasoning"],
            }
        return {"error": f"Unknown tool: {tool_name}"}

    def _get_status(self) -> Dict[str, Any]:
        sku = self.sku
        ds = int(sku.get("daily_sales") or 0)
        stock = int(sku.get("stock") or 0)
        in_transit = int(sku.get("in_transit") or 0)
        stock_position = stock + in_transit

        # 7天均销和波动率
        history = sku.get("price_history") or []
        avg_daily_7d = ds
        volatility = 0.0
        if isinstance(history, list) and len(history) >= 7:
            recent = [int(r.get("daily_sales") or 0) for r in history[-7:] if isinstance(r, dict)]
            if recent:
                avg_daily_7d = round(sum(recent) / len(recent), 1)
                mean_val = sum(recent) / len(recent)
                if mean_val > 0:
                    variance = sum((x - mean_val) ** 2 for x in recent) / len(recent)
                    volatility = round((variance ** 0.5) / mean_val, 2)

        effective_daily = avg_daily_7d if avg_daily_7d > 0 else ds
        coverage = round(stock / effective_daily, 1) if effective_daily > 0 else 999
        total_coverage = round(stock_position / effective_daily, 1) if effective_daily > 0 else 999

        self._status = {
            "sku_id": sku.get("sku_id", ""),
            "name": sku.get("name", ""),
            "stock": stock,
            "in_transit": in_transit,
            "stock_position": stock_position,
            "daily_sales": ds,
            "avg_daily_7d": avg_daily_7d,
            "sales_volatility": volatility,
            "coverage_days": coverage,
            "total_coverage_days": total_coverage,
            "stock_age_days": int(sku.get("stock_age_days") or 0),
            "return_rate_pct": round(float(sku.get("return_rate") or 0) * 100, 1),
        }
        return self._status

    def _calculate_replenishment(self, cycle_days: int, safety_days: float) -> Dict[str, Any]:
        status = self._status or self._get_status()
        effective_daily = status["avg_daily_7d"]
        if effective_daily <= 0:
            return {"suggest_qty": 0, "reason": "日销为0，无需补货"}

        target_days = cycle_days + safety_days + (1.5 if effective_daily >= 25 else 0.5)
        target_units = int(math.ceil(effective_daily * target_days))
        reorder_point = int(math.ceil(effective_daily * (cycle_days + safety_days)))
        suggest_qty = max(0, target_units - status["stock_position"])

        # EOQ
        annual_demand = effective_daily * 365
        ordering_cost = 50
        holding_cost = float(self.sku.get("cost_price") or 50) * 0.2
        eoq = int(math.sqrt(2 * annual_demand * ordering_cost / max(holding_cost, 1)))

        return {
            "target_stock_days": round(target_days, 1),
            "target_stock_units": target_units,
            "reorder_point_units": reorder_point,
            "suggest_qty": suggest_qty,
            "eoq": eoq,
            "current_stock_position": status["stock_position"],
        }

    def _assess_overstock(self, threshold_days: int) -> Dict[str, Any]:
        status = self._status or self._get_status()
        total_cov = status["total_coverage_days"]
        is_overstock = total_cov > threshold_days
        excess_days = max(0, total_cov - threshold_days)

        if not is_overstock:
            return {"is_overstock": False, "pressure_score": 0, "strategy": "none"}

        # 压力分数
        age = status["stock_age_days"]
        rr = status["return_rate_pct"]
        pressure = min(100, excess_days * 1.2 + age * 0.3 + rr * 2)

        strategy = "满减促销"
        if pressure > 70:
            strategy = "降价清仓"
        elif rr > 10:
            strategy = "私域渠道清仓"

        return {
            "is_overstock": True,
            "total_coverage_days": total_cov,
            "excess_days": round(excess_days, 1),
            "pressure_score": round(pressure, 1),
            "recommended_strategy": strategy,
            "stock_age_days": age,
        }
