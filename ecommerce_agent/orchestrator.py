"""Baseline demo 编排器。"""
from pathlib import Path
from typing import Dict, List, Optional

from .agents.inventory_warning_agent import InventoryWarningAgent
from .agents.product_selection_agent import ProductSelectionAgent
from .agents.replenishment_calculator import ReplenishmentCalculator
from .agents.sales_review_agent import SalesReviewAgent
from .agents.slow_moving_agent import SlowMovingAgent
from .data.erp_adapter import ERPAdapter
from .data.trends_adapter import TrendsAdapter
from .memory.feedback_store import FeedbackMemoryStore


class DemoOrchestrator:
    """组织数据读取、Agent 分析与结果汇总。"""

    def __init__(
        self,
        seed: int = 42,
        top_n: int = 5,
        as_of: str = "",
        replenishment_cycle_days: int = 7,
        overstock_days: int = 45,
        feedback_memory_path: Optional[Path] = None,
    ):
        self.seed = seed
        self.top_n = top_n
        self.as_of = as_of
        self.replenishment_cycle_days = replenishment_cycle_days
        self.overstock_days = overstock_days

        self.erp_adapter = ERPAdapter(seed=seed)
        self.trends_adapter = TrendsAdapter(seed=seed)
        self.memory = FeedbackMemoryStore(path=feedback_memory_path)
        self.sales_agent = SalesReviewAgent()
        self.inventory_agent = InventoryWarningAgent()
        self.selection_agent = ProductSelectionAgent()
        self.slow_moving_agent = SlowMovingAgent()
        self.replenishment_calc = ReplenishmentCalculator()

    def run(self) -> Dict:
        sku_metrics = self.erp_adapter.get_all_skus()
        top_trends = self.trends_adapter.get_top_trends(limit=max(self.top_n, 5))
        growing_trends = self.trends_adapter.get_growing_trends(limit=max(self.top_n, 5))
        all_tags = self.erp_adapter.get_all_sku_tags()
        competitor_rows = self.erp_adapter.list_competitor_benchmarks()

        product_selection = self.selection_agent.analyze(
            top_trends=top_trends,
            growing_trends=growing_trends,
            sku_metrics=sku_metrics,
            all_sku_tags=all_tags,
            competitor_rows=competitor_rows,
            memory=self.memory,
            top_n=self.top_n,
        )

        sales_review = self.sales_agent.analyze(
            sku_metrics=sku_metrics,
            top_trends=top_trends,
            growing_trends=growing_trends,
            top_n=self.top_n,
        )
        inventory_review = self.inventory_agent.analyze(
            sku_metrics=sku_metrics,
            replenishment_cycle_days=self.replenishment_cycle_days,
            overstock_days=self.overstock_days,
            limit=self.top_n,
        )

        slow_moving = self.slow_moving_agent.analyze(sku_metrics=sku_metrics, limit=self.top_n)

        replenishment = self.replenishment_calc.suggest_for_low_stock(
            inventory_review.get("low_stock_alerts", []),
            limit=self.top_n,
        )

        memory_snapshot = {
            "active_feedback_count": len(self.memory.list_active_items()),
            "product_selection_hits": len(product_selection.get("memory_hits", [])),
        }

        actions = self._merge_actions(
            product_selection.get("recommendations", []),
            sales_review.get("recommendations", []),
            inventory_review.get("recommendations", []),
            slow_moving.get("recommendations", []),
            replenishment.get("recommendations", []),
        )

        return {
            "context": {
                "as_of": self.as_of,
                "seed": self.seed,
                "sku_count": len(sku_metrics),
                "trend_count": len(top_trends),
                "top_n": self.top_n,
            },
            "product_selection": product_selection,
            "sales_review": sales_review,
            "inventory_review": inventory_review,
            "slow_moving": slow_moving,
            "replenishment": replenishment,
            "memory_snapshot": memory_snapshot,
            "actions": actions,
        }

    def _merge_actions(self, *groups: List[str]) -> List[str]:
        merged: List[str] = []
        for group in groups:
            for action in group:
                if action not in merged:
                    merged.append(action)
        return merged
