"""智能补货 / EOQ（Issue 3.3 Baseline：可解释公式）。"""
import json
import math
from typing import Dict, List, Optional

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
    annual_d = daily_demand * 365.0
    q = math.sqrt(2 * annual_d * ordering_cost / holding_cost_per_unit_per_year)
    q_adj = q * seasonal_factor
    return {
        "eoq_units": int(round(q_adj)),
        "eoq_raw": int(round(q)),
        "annual_demand": round(annual_d, 2),
        "seasonal_factor": seasonal_factor,
        "formula": "sqrt(2 * D * S / H) * seasonal_factor，其中 D 为年需求量",
        "data_source": "mock",
    }


class ReplenishmentCalculator:
    """对低库存预警批量给出 EOQ 建议（演示用固定成本参数）。"""

    def __init__(
        self,
        ordering_cost: float = 200.0,
        holding_cost_per_unit_per_year: float = 8.0,
        seasonal_factor: float = 1.05,
        llm_client: Optional[OpenAICompatChatClient] = None,
        use_llm: bool = False,
    ):
        self.ordering_cost = ordering_cost
        self.holding_cost_per_unit_per_year = holding_cost_per_unit_per_year
        self.seasonal_factor = seasonal_factor
        self._llm = llm_client
        self._use_llm = bool(use_llm and llm_client is not None)

    def suggest_for_low_stock(
        self,
        low_stock_alerts: List[Dict],
        *,
        limit: int = 10,
    ) -> Dict:
        rows: List[Dict] = []
        for row in low_stock_alerts[:limit]:
            daily = float(row.get("daily_sales", 0))
            eoq = compute_eoq(
                daily,
                self.ordering_cost,
                self.holding_cost_per_unit_per_year,
                self.seasonal_factor,
            )
            suggest = max(eoq["eoq_units"], int(row.get("suggest_replenish_qty", 0)))
            rows.append(
                {
                    "sku_id": row.get("sku_id"),
                    "name": row.get("name"),
                    "daily_sales": daily,
                    "eoq": eoq,
                    "suggested_order_qty": suggest,
                    "note": "EOQ 与预警补货量取较大值，避免断货",
                }
            )

        recommendations: List[str] = []
        if rows:
            r0 = rows[0]
            recommendations.append(
                f"补货计算：{r0['sku_id']} 建议订货约 {r0['suggested_order_qty']} 件（EOQ 参考 {r0['eoq']['eoq_units']}）"
            )
        else:
            recommendations.append("暂无低库存条目用于 EOQ 试算。")

        data_source = "mock"
        llm_replenishment_comment: Optional[str] = None
        llm_error: Optional[str] = None
        if self._use_llm and self._llm is not None and rows:
            try:
                user_msg = prompts.REPLENISHMENT_USER.format(
                    payload=json.dumps(rows, ensure_ascii=False),
                )
                raw = self._llm.chat(
                    [
                        {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.0,
                )
                parsed = parse_json_object(raw)
                bc = parsed.get("business_comment")
                if not isinstance(bc, str) or not bc.strip():
                    raise ValueError("缺少 business_comment")
                llm_replenishment_comment = bc.strip()
                recommendations.append(f"【LLM】{llm_replenishment_comment}")
                data_source = "hybrid"
            except (LLMClientError, ValueError, TypeError) as e:
                llm_error = str(e)

        return {
            "replenishment_rows": rows,
            "params": {
                "ordering_cost": self.ordering_cost,
                "holding_cost_per_unit_per_year": self.holding_cost_per_unit_per_year,
                "seasonal_factor": self.seasonal_factor,
            },
            "recommendations": recommendations,
            "data_source": data_source,
            "llm_replenishment_comment": llm_replenishment_comment,
            "llm_error": llm_error,
        }
