"""智能补货 / EOQ（增强版：目标库存、优先级与采购确认点）。"""
import json
import math
from typing import Any, Dict, List, Optional

from ..llm import prompts
from ..llm.client import LLMClientError, OpenAICompatChatClient
from ..llm.json_util import parse_json_object


def compute_eoq(
    daily_demand: float,
    ordering_cost: float,
    holding_cost_per_unit_per_year: float,
    seasonal_factor: float = 1.0,
) -> Dict:
    """经典 EOQ：Q = sqrt(2 D S / H)，D 为年需求量。"""
    if daily_demand <= 0 or ordering_cost <= 0 or holding_cost_per_unit_per_year <= 0:
        return {
            "eoq_units": 0,
            "annual_demand": 0.0,
            "seasonal_factor": seasonal_factor,
            "note": "参数无效，无法计算 EOQ",
        }
    annual_demand = daily_demand * 365.0
    eoq_raw = math.sqrt(2 * annual_demand * ordering_cost / holding_cost_per_unit_per_year)
    eoq_adjusted = eoq_raw * seasonal_factor
    return {
        "eoq_units": int(round(eoq_adjusted)),
        "eoq_raw": int(round(eoq_raw)),
        "annual_demand": round(annual_demand, 2),
        "seasonal_factor": seasonal_factor,
        "formula": "sqrt(2 * D * S / H) * seasonal_factor，其中 D 为年需求量",
        "data_source": "mock",
    }


class ReplenishmentCalculator:
    """对低库存预警批量给出更完整的补货建议。"""

    def __init__(
        self,
        ordering_cost: float = 200.0,
        holding_cost_per_unit_per_year: float = 8.0,
        seasonal_factor: float = 1.05,
        lead_time_days: int = 3,
        llm_client: Optional[OpenAICompatChatClient] = None,
        use_llm: bool = False,
    ):
        self.ordering_cost = ordering_cost
        self.holding_cost_per_unit_per_year = holding_cost_per_unit_per_year
        self.seasonal_factor = seasonal_factor
        self.lead_time_days = max(int(lead_time_days), 1)
        self._llm = llm_client
        self._use_llm = bool(use_llm and llm_client is not None)

    def suggest_for_low_stock(
        self,
        low_stock_alerts: List[Dict],
        *,
        limit: int = 10,
    ) -> Dict:
        rows: List[Dict[str, Any]] = []
        for row in low_stock_alerts[:limit]:
            daily_demand = float(row.get("daily_sales", 0))
            eoq = compute_eoq(
                daily_demand,
                self.ordering_cost,
                self.holding_cost_per_unit_per_year,
                self.seasonal_factor,
            )
            stock_position = int(row.get("stock_position", 0))
            target_stock_units = int(row.get("target_stock_units", 0))
            reorder_point_units = int(row.get("reorder_point_units", 0))
            coverage_gap_days = float(row.get("coverage_gap_days", 0.0))
            urgency_level = str(row.get("urgency_level", "medium"))
            shortage_to_target = max(target_stock_units - stock_position, 0)
            lead_time_buffer_units = int(math.ceil(daily_demand * self.lead_time_days))
            order_up_to_units = max(target_stock_units, reorder_point_units + lead_time_buffer_units)
            bounded_eoq_qty = min(
                eoq.get("eoq_units", 0),
                max(order_up_to_units - stock_position, shortage_to_target + lead_time_buffer_units),
            )
            if stock_position >= target_stock_units:
                suggested_order_qty = 0
                order_trigger = (
                    f"库存位置 {stock_position} 已覆盖目标库存 {target_stock_units}，"
                    "当前以跟进入库与履约为主，无需新增采购。"
                )
            else:
                suggested_order_qty = max(
                    int(row.get("suggest_replenish_qty", 0)),
                    shortage_to_target,
                    bounded_eoq_qty,
                    lead_time_buffer_units if urgency_level in {"critical", "high"} else 0,
                )
                order_trigger = (
                    f"库存位置 {stock_position} 低于补货点 {reorder_point_units}"
                    if stock_position < reorder_point_units
                    else f"库存位置 {stock_position} 仍低于目标库存 {target_stock_units}"
                )
            rows.append(
                {
                    "sku_id": row.get("sku_id"),
                    "name": row.get("name"),
                    "daily_sales": daily_demand,
                    "stock_position": stock_position,
                    "target_stock_units": target_stock_units,
                    "order_up_to_units": order_up_to_units,
                    "reorder_point_units": reorder_point_units,
                    "coverage_gap_days": coverage_gap_days,
                    "lead_time_days": self.lead_time_days,
                    "order_priority": urgency_level,
                    "order_trigger": order_trigger,
                    "eoq": eoq,
                    "suggested_order_qty": suggested_order_qty,
                    "note": (
                        "综合 EOQ、目标库存缺口与交期缓冲量，并约束在合理 order-up-to 区间内；"
                        "若在途已覆盖目标库存，则不新增采购。"
                    ),
                }
            )

        recommendations: List[str] = []
        if rows:
            first_row = rows[0]
            recommendations.append(
                f"补货计算：{first_row['sku_id']} 建议订货约 {first_row['suggested_order_qty']} 件（EOQ {first_row['eoq']['eoq_units']} / 目标库存 {first_row['target_stock_units']}）。"
            )
        else:
            recommendations.append("暂无低库存条目用于 EOQ 试算。")

        data_source = "mock"
        llm_replenishment_comment: Optional[str] = None
        llm_notes: Optional[Dict[str, Any]] = None
        llm_error: Optional[str] = None
        if self._use_llm and self._llm is not None and rows:
            try:
                llm_notes = self._build_llm_notes(rows[:5])
                llm_replenishment_comment = llm_notes["business_comment"]
                recommendations.append(f"【LLM】{llm_replenishment_comment}")
                data_source = "hybrid"
            except (LLMClientError, ValueError, TypeError) as exc:
                llm_error = str(exc)

        return {
            "replenishment_rows": rows,
            "params": {
                "ordering_cost": self.ordering_cost,
                "holding_cost_per_unit_per_year": self.holding_cost_per_unit_per_year,
                "seasonal_factor": self.seasonal_factor,
                "lead_time_days": self.lead_time_days,
            },
            "recommendations": recommendations,
            "data_source": data_source,
            "llm_replenishment_comment": llm_replenishment_comment,
            "llm_notes": llm_notes,
            "llm_error": llm_error,
        }

    def _build_llm_notes(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        user_msg = prompts.REPLENISHMENT_USER.format(
            payload=json.dumps(rows, ensure_ascii=False),
        )
        messages = [
            {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
            {"role": "user", "content": user_msg},
        ]
        raw: Optional[str] = None
        parsed: Optional[Dict[str, Any]] = None
        last_error: Optional[Exception] = None
        for attempt in range(2):
            try:
                try:
                    raw = self._llm.chat(
                        messages,
                        temperature=0.0,
                        response_format={"type": "json_object"},
                    )
                except TypeError:
                    raw = self._llm.chat(messages, temperature=0.0)
                parsed = parse_json_object(raw)
                break
            except (LLMClientError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt == 0:
                    messages = [
                        {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
                        {
                            "role": "user",
                            "content": (
                                "请严格只输出一个 JSON 对象，且必须包含 business_comment / procurement_watchouts。\n\n"
                                + user_msg
                            ),
                        },
                    ]
                    continue
                raise
        if parsed is None:
            raise last_error or ValueError("补货 LLM 摘要解析失败")

        business_comment = str(parsed.get("business_comment", "")).strip()
        watchouts_raw = parsed.get("procurement_watchouts")
        procurement_watchouts: List[str] = []
        if isinstance(watchouts_raw, list):
            for item in watchouts_raw:
                text = str(item).strip()
                if text:
                    procurement_watchouts.append(text)

        if not business_comment:
            raise ValueError("缺少 business_comment")
        if not procurement_watchouts:
            procurement_watchouts = [
                "确认高优先级 SKU 的交期与最小起订量是否支持本轮补货节奏。",
                "核对在途单与现货库存，避免重复下单。",
                "确认是否存在面料、辅料或产能瓶颈导致交期延长。",
            ]
        return {
            "business_comment": business_comment,
            "procurement_watchouts": procurement_watchouts[:5],
        }
