"""滞销品清理 Agent（Issue 3.2 Baseline）。"""
import json
from typing import Dict, List, Optional

from ..llm import prompts
from ..llm.client import LLMClientError, OpenAICompatChatClient
from ..llm.json_util import parse_json_object


class SlowMovingAgent:
    """库龄与转化率双条件扫描 + 清理策略。"""

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
        *,
        age_days_threshold: int = 60,
        conversion_threshold: float = 0.01,
        limit: int = 10,
    ) -> Dict:
        data_source = "mock"
        candidates: List[Dict] = []
        for item in sku_metrics:
            age = int(item.get("stock_age_days", 0))
            conv = float(item.get("conversion_rate", 1.0))
            if age > age_days_threshold and conv < conversion_threshold:
                strategy, reason = self._pick_strategy(item)
                est_value = int(item["stock"]) * max(item["daily_sales"], 1)
                candidates.append(
                    {
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "stock_age_days": age,
                        "conversion_rate": conv,
                        "current_stock": item["stock"],
                        "daily_sales": item["daily_sales"],
                        "est_inventory_pressure": est_value,
                        "strategy": strategy,
                        "reason": reason,
                        "data_source": data_source,
                    }
                )

        candidates.sort(key=lambda x: (-x["stock_age_days"], x["sku_id"]))
        candidates = candidates[:limit]

        recommendations: List[str] = []
        if candidates:
            top = candidates[0]
            recommendations.append(
                f"滞销清理优先：{top['sku_id']}（{top['name']}）— {top['strategy']}，{top['reason']}"
            )
        else:
            recommendations.append("当前无满足库龄与转化率双阈值的滞销 SKU（演示阈值可调整）。")

        llm_notes: Optional[Dict[str, str]] = None
        llm_error: Optional[str] = None
        if self._use_llm and self._llm is not None:
            try:
                user_msg = prompts.SLOW_MOVING_USER.format(
                    payload=json.dumps(
                        {"candidates": candidates, "thresholds": {"age_days": age_days_threshold, "conversion_rate": conversion_threshold}},
                        ensure_ascii=False,
                    ),
                )
                raw = self._llm.chat(
                    [
                        {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.0,
                )
                parsed = parse_json_object(raw)
                note = parsed.get("coordination_note")
                if not isinstance(note, str) or not note.strip():
                    raise ValueError("缺少 coordination_note")
                llm_notes = {"coordination_note": note.strip()}
                data_source = "hybrid"
            except (LLMClientError, ValueError, TypeError) as e:
                llm_error = str(e)

        return {
            "slow_moving_skus": candidates,
            "recommendations": recommendations,
            "thresholds": {
                "age_days": age_days_threshold,
                "conversion_rate": conversion_threshold,
            },
            "data_source": data_source,
            "llm_notes": llm_notes,
            "llm_error": llm_error,
        }

    def _pick_strategy(self, item: Dict) -> tuple:
        stock = int(item["stock"])
        in_transit = int(item.get("in_transit", 0))
        daily = int(item["daily_sales"])

        if in_transit > 0 and stock > 200:
            return "跨仓调拨", "在途有货且仓内积压高，优先调拨平衡周转"
        if daily <= 3:
            return "直播间秒杀", "动销极低，适合限时秒杀清库存"
        if stock > 120:
            return "满减促销", "库存深且转化弱，建议阶梯满减带动出清"
        return "满减促销", "以券促转化，观察一周再评估是否转秒杀"
