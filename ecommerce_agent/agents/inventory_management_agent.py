"""库存管理总控 Agent：整合预警、补货与清滞结果。"""
from typing import Any, Dict, List, Optional, Tuple

from ..llm.client import OpenAICompatChatClient
from .inventory_warning_agent import InventoryWarningAgent
from .replenishment_calculator import ReplenishmentCalculator
from .slow_moving_agent import SlowMovingAgent


class InventoryManagementAgent:
    """面向主编排的库存管理总控层。"""

    def __init__(
        self,
        llm_client: Optional[OpenAICompatChatClient] = None,
        use_llm: bool = False,
    ):
        self.inventory_warning_agent = InventoryWarningAgent(
            llm_client=llm_client,
            use_llm=use_llm,
        )
        self.slow_moving_agent = SlowMovingAgent(
            llm_client=llm_client,
            use_llm=use_llm,
        )
        self.replenishment_calculator = ReplenishmentCalculator(
            llm_client=llm_client,
            use_llm=use_llm,
        )

    def analyze(
        self,
        sku_metrics: List[Dict[str, Any]],
        *,
        replenishment_cycle_days: int = 7,
        overstock_days: int = 45,
        limit: int = 5,
    ) -> Dict[str, Any]:
        inventory_review = self.inventory_warning_agent.analyze(
            sku_metrics=sku_metrics,
            replenishment_cycle_days=replenishment_cycle_days,
            overstock_days=overstock_days,
            limit=limit,
        )
        slow_moving = self.slow_moving_agent.analyze(
            sku_metrics=sku_metrics,
            limit=limit,
        )
        replenishment = self.replenishment_calculator.suggest_for_low_stock(
            inventory_review.get("low_stock_alerts", []),
            limit=limit,
        )
        management_summary = self._build_management_summary(
            inventory_review=inventory_review,
            slow_moving=slow_moving,
            replenishment=replenishment,
        )
        return {
            "inventory_review": inventory_review,
            "slow_moving": slow_moving,
            "replenishment": replenishment,
            "management_summary": management_summary,
        }

    def _build_management_summary(
        self,
        *,
        inventory_review: Dict[str, Any],
        slow_moving: Dict[str, Any],
        replenishment: Dict[str, Any],
    ) -> Dict[str, Any]:
        action_board: List[Dict[str, Any]] = []
        order_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}

        for row in inventory_review.get("action_queue") or []:
            action_board.append(
                {
                    "priority": row.get("priority", "medium"),
                    "owner": row.get("owner", "运营"),
                    "source": "inventory_warning",
                    "sku_id": row.get("sku_id", ""),
                    "title": f"{row.get('action_type', 'action')} / {row.get('sku_id', '')}",
                    "reason": row.get("reason", ""),
                }
            )
        for row in (slow_moving.get("slow_moving_skus") or [])[:3]:
            action_board.append(
                {
                    "priority": "high",
                    "owner": "运营",
                    "source": "slow_moving",
                    "sku_id": row.get("sku_id", ""),
                    "title": f"{row.get('strategy', '去化')} / {row.get('sku_id', '')}",
                    "reason": row.get("reason", ""),
                }
            )
        for row in (replenishment.get("replenishment_rows") or [])[:3]:
            action_board.append(
                {
                    "priority": row.get("order_priority", "medium"),
                    "owner": "采购",
                    "source": "replenishment",
                    "sku_id": row.get("sku_id", ""),
                    "title": f"补货下单 / {row.get('sku_id', '')}",
                    "reason": row.get("order_trigger", ""),
                }
            )

        action_board.sort(
            key=lambda row: (
                order_rank.get(str(row.get("priority")), 9),
                str(row.get("owner", "")),
                str(row.get("sku_id", "")),
            )
        )
        deduped_board: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str, str]] = set()
        for row in action_board:
            key = (str(row.get("source")), str(row.get("owner")), str(row.get("sku_id")))
            if key in seen:
                continue
            seen.add(key)
            deduped_board.append(row)

        owner_lane_summary: Dict[str, int] = {}
        for row in deduped_board:
            owner = str(row.get("owner", "未指定"))
            owner_lane_summary[owner] = owner_lane_summary.get(owner, 0) + 1

        llm_digest_parts: List[str] = []
        inv_notes = inventory_review.get("llm_notes") or {}
        if isinstance(inv_notes, dict):
            for key in ("priorities_note", "replenishment_focus", "clearance_focus"):
                text = str(inv_notes.get(key, "")).strip()
                if text:
                    llm_digest_parts.append(text)
        slow_notes = slow_moving.get("llm_notes") or {}
        if isinstance(slow_notes, dict):
            text = str(slow_notes.get("coordination_note", "")).strip()
            if text:
                llm_digest_parts.append(text)
        replenishment_notes = replenishment.get("llm_notes") or {}
        if isinstance(replenishment_notes, dict):
            text = str(replenishment_notes.get("business_comment", "")).strip()
            if text:
                llm_digest_parts.append(text)

        management_recommendations = []
        if deduped_board:
            first_row = deduped_board[0]
            management_recommendations.append(
                f"先推进 {first_row['owner']} 的 {first_row['title']}，原因：{first_row['reason']}"
            )
        if inventory_review.get("inventory_health"):
            health = inventory_review["inventory_health"]
            management_recommendations.append(
                f"本轮库存总览：低库存 {health.get('low_stock_skus', 0)} 个，高库存 {health.get('overstock_skus', 0)} 个。"
            )
        if slow_moving.get("slow_moving_skus"):
            management_recommendations.append("高库龄低转化 SKU 需和补货动作一起看，避免一边清货一边加单。")
        if replenishment.get("replenishment_rows"):
            management_recommendations.append("补货单优先按高销量短覆盖 SKU 排产，避免全部 SKU 同时开单。")

        return {
            "inventory_health": inventory_review.get("inventory_health", {}),
            "owner_lane_summary": owner_lane_summary,
            "action_board": deduped_board[:10],
            "recommendations": management_recommendations,
            "llm_digest": "\n".join(llm_digest_parts[:3]) if llm_digest_parts else "",
        }
