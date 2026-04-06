"""Baseline demo 编排器。"""
from typing import Dict, List

from .agents.inventory_warning_agent import InventoryWarningAgent
from .agents.sales_review_agent import SalesReviewAgent
from .data.erp_adapter import ERPAdapter
from .data.trends_adapter import TrendsAdapter


class DemoOrchestrator:
    """组织数据读取、Agent 分析与结果汇总。"""

    def __init__(
        self,
        seed: int = 42,
        top_n: int = 5,
        as_of: str = "",
        replenishment_cycle_days: int = 7,
        overstock_days: int = 45,
    ):
        self.seed = seed
        self.top_n = top_n
        self.as_of = as_of
        self.replenishment_cycle_days = replenishment_cycle_days
        self.overstock_days = overstock_days

        self.erp_adapter = ERPAdapter(seed=seed)
        self.trends_adapter = TrendsAdapter(seed=seed)
        self.sales_agent = SalesReviewAgent()
        self.inventory_agent = InventoryWarningAgent()

    def run(self) -> Dict:
        sku_metrics = self.erp_adapter.get_all_skus()
        top_trends = self.trends_adapter.get_top_trends(limit=max(self.top_n, 5))
        growing_trends = self.trends_adapter.get_growing_trends(limit=max(self.top_n, 5))

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

        actions = self._merge_actions(
            sales_review.get("recommendations", []),
            inventory_review.get("recommendations", []),
        )

        return {
            "context": {
                "as_of": self.as_of,
                "seed": self.seed,
                "sku_count": len(sku_metrics),
                "trend_count": len(top_trends),
                "top_n": self.top_n,
            },
            "sales_review": sales_review,
            "inventory_review": inventory_review,
            "actions": actions,
        }

    def _merge_actions(self, sales_actions: List[str], inventory_actions: List[str]) -> List[str]:
        merged: List[str] = []
        for action in sales_actions + inventory_actions:
            if action not in merged:
                merged.append(action)
        return merged
