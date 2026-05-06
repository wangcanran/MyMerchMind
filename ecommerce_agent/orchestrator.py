"""Baseline demo 编排器。"""
from pathlib import Path
from typing import Dict, List, Optional

from .agents.inventory_warning_agent import InventoryWarningAgent
from .agents.replenishment_calculator import ReplenishmentCalculator
from .agents.sales_review_agent import SalesReviewAgent
from .agents.slow_moving_agent import SlowMovingAgent
from .data.erp_adapter import ERPAdapter
from .data.trends_adapter import TrendsAdapter
from .memory.feedback_store import FeedbackMemoryStore
from .llm import OpenAICompatChatClient, load_llm_config


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
        erp_adapter: Optional[ERPAdapter] = None,
        trends_adapter: Optional[TrendsAdapter] = None,
        use_llm: bool = False,
    ):
        self.seed = seed
        self.top_n = top_n
        self.as_of = as_of
        self.replenishment_cycle_days = replenishment_cycle_days
        self.overstock_days = overstock_days

        self.erp_adapter = erp_adapter if erp_adapter is not None else ERPAdapter(seed=seed)
        self.trends_adapter = trends_adapter if trends_adapter is not None else TrendsAdapter(seed=seed)
        self.memory = FeedbackMemoryStore(path=feedback_memory_path)

        llm_cfg = load_llm_config()
        llm_client: Optional[OpenAICompatChatClient] = None
        self.llm_notice: Optional[str] = None
        self.llm_enabled = False
        if use_llm:
            if llm_cfg.is_configured():
                llm_client = OpenAICompatChatClient(llm_cfg)
            else:
                self.llm_notice = "已请求 --llm，但未配置 LLM_API_KEY / OPENAI_API_KEY，已回退为规则模式。"
        effective_llm = use_llm and llm_client is not None
        self.llm_enabled = bool(effective_llm)

        self.sales_agent = SalesReviewAgent(llm_client=llm_client, use_llm=effective_llm)
        self.inventory_agent = InventoryWarningAgent(llm_client=llm_client, use_llm=effective_llm)
        self.slow_moving_agent = SlowMovingAgent(llm_client=llm_client, use_llm=effective_llm)
        self.replenishment_calc = ReplenishmentCalculator(
            llm_client=llm_client,
            use_llm=effective_llm,
        )

    def run(self) -> Dict:
        sku_metrics = self.erp_adapter.get_all_skus()
        top_trends = self.trends_adapter.get_top_trends(limit=max(self.top_n, 5))
        growing_trends = self.trends_adapter.get_growing_trends(limit=max(self.top_n, 5))

        product_selection = {
            "skipped": True,
            "message": (
                "选品 Agent 已与 Baseline 趋势 Demo 解耦。请用店铺风格、季节、地点、价位等构造 criteria，"
                "调用 ProductSelectionAgent.analyze_async / analyze_sync；与历史销售、竞品、定价、库存的对比"
                "在编排层串联现有 ERP / 竞品 / 补货模块。"
            ),
            "recommendations": [],
            "trend_picks": [],
            "tag_overlap_sample": [],
            "memory_hits": [],
            "data_source": "criteria_pipeline",
            "llm_error": None,
        }

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
                "llm_enabled": self.llm_enabled,
                "llm_notice": self.llm_notice,
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
