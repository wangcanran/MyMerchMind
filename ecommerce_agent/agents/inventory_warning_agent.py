"""库存预警 Agent（规则版 baseline，对应 Issue 3.1 动态库存预警逻辑）。"""
import json
from typing import Dict, List, Optional

from ..llm import prompts
from ..llm.client import LLMClientError, OpenAICompatChatClient
from ..llm.json_util import parse_json_object


class InventoryWarningAgent:
    """基于规则生成库存预警。"""

    def __init__(
        self,
        llm_client: Optional[OpenAICompatChatClient] = None,
        use_llm: bool = False,
    ):
        self._llm = llm_client
        self._use_llm = bool(use_llm and llm_client is not None)

    def analyze(
        self,
        sku_metrics: List[Dict],
        replenishment_cycle_days: int = 7,
        overstock_days: int = 45,
        limit: int = 5,
    ) -> Dict:
        low_stock_alerts: List[Dict] = []
        overstock_alerts: List[Dict] = []

        for item in sku_metrics:
            daily_sales = item["daily_sales"]
            if daily_sales <= 0:
                continue

            current_stock = item["stock"]
            in_transit = item["in_transit"]
            current_coverage_days = current_stock / daily_sales
            total_coverage_days = (current_stock + in_transit) / daily_sales

            if current_coverage_days < replenishment_cycle_days:
                suggestion_qty = max(
                    int(daily_sales * replenishment_cycle_days * 2 - (current_stock + in_transit)),
                    0,
                )
                low_stock_alerts.append(
                    {
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "daily_sales": daily_sales,
                        "current_stock": current_stock,
                        "in_transit": in_transit,
                        "coverage_days": round(current_coverage_days, 1),
                        "suggest_replenish_qty": suggestion_qty,
                    }
                )

            if total_coverage_days > overstock_days:
                overstock_alerts.append(
                    {
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "daily_sales": daily_sales,
                        "current_stock": current_stock,
                        "in_transit": in_transit,
                        "total_coverage_days": round(total_coverage_days, 1),
                    }
                )

        low_stock_alerts = sorted(
            low_stock_alerts,
            key=lambda x: (x["coverage_days"], x["sku_id"]),
        )[:limit]

        overstock_alerts = sorted(
            overstock_alerts,
            key=lambda x: (-x["total_coverage_days"], x["sku_id"]),
        )[:limit]

        recommendations: List[str] = []
        if low_stock_alerts:
            first_low = low_stock_alerts[0]
            recommendations.append(
                f"优先补货 {first_low['sku_id']}（{first_low['name']}），当前仅可售 {first_low['coverage_days']} 天。"
            )
        if overstock_alerts:
            first_over = overstock_alerts[0]
            recommendations.append(
                f"对 {first_over['sku_id']}（{first_over['name']}）启动去化策略，当前总库存覆盖 {first_over['total_coverage_days']} 天。"
            )
        if not recommendations:
            recommendations.append("当前库存结构健康，无需额外干预。")

        data_source = "mock"
        llm_notes: Optional[Dict[str, str]] = None
        llm_error: Optional[str] = None
        if self._use_llm and self._llm is not None:
            try:
                payload = {
                    "low_stock_alerts": low_stock_alerts,
                    "overstock_alerts": overstock_alerts,
                    "replenishment_cycle_days": replenishment_cycle_days,
                    "overstock_days": overstock_days,
                }
                user_msg = prompts.INVENTORY_USER.format(
                    payload=json.dumps(payload, ensure_ascii=False),
                )
                raw = self._llm.chat(
                    [
                        {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.0,
                )
                parsed = parse_json_object(raw)
                note = parsed.get("priorities_note")
                if not isinstance(note, str) or not note.strip():
                    raise ValueError("缺少 priorities_note")
                llm_notes = {"priorities_note": note.strip()}
                data_source = "hybrid"
            except (LLMClientError, ValueError, TypeError) as e:
                llm_error = str(e)

        return {
            "low_stock_alerts": low_stock_alerts,
            "overstock_alerts": overstock_alerts,
            "recommendations": recommendations,
            "data_source": data_source,
            "llm_notes": llm_notes,
            "llm_error": llm_error,
        }
