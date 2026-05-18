"""Baseline demo 编排器。"""
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional

from .agents.category_management_agent import CategoryManagementAgent
from .agents.inventory_warning_agent import InventoryWarningAgent
from .agents.pricing_agent import PricingAgent
from .agents.product_selection_agent import ProductSelectionAgent
from .agents.replenishment_calculator import ReplenishmentCalculator
from .agents.sales_review_agent import SalesReviewAgent
from .agents.slow_moving_agent import SlowMovingAgent
from .config.data_sources import DataSourceSettings
from .data.category_mapping import load_category_mapping
from .data.erp_adapter import ERPAdapter
from .data.file_loaders import (
    load_competitors_from_json,
    load_erp_skus_from_json,
    load_tags_from_json,
    load_trends_from_json,
)
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
        data_sources: Optional[DataSourceSettings] = None,
        category_mapping_path: Optional[Path] = None,
        selection_requirements_path: Optional[Path] = None,
        enable_selection: bool = False,
        enable_category_management: bool = False,
        enable_pricing: bool = False,
        erp_adapter: Optional[ERPAdapter] = None,
        trends_adapter: Optional[TrendsAdapter] = None,
        use_llm: bool = False,
    ):
        self.seed = seed
        self.top_n = top_n
        self.as_of = as_of
        self.replenishment_cycle_days = replenishment_cycle_days
        self.overstock_days = overstock_days
        self.category_mapping_path = category_mapping_path
        self.selection_requirements_path = selection_requirements_path
        self.enable_selection = enable_selection
        self.enable_category_management = enable_category_management
        self.enable_pricing = enable_pricing

        ds = data_sources or DataSourceSettings()
        self.data_integration = {
            "erp": "file" if ds.erp_json else "mock",
            "trends": "file" if ds.trends_json else "mock",
            "competitors": "file" if ds.competitors_json else "mock",
            "tags": "file" if ds.tags_json else "mock",
        }

        sku_table = load_erp_skus_from_json(ds.erp_json) if ds.erp_json else None
        trends = load_trends_from_json(ds.trends_json) if ds.trends_json else None
        competitors = load_competitors_from_json(ds.competitors_json) if ds.competitors_json else None
        tags = load_tags_from_json(ds.tags_json) if ds.tags_json else None

        self.erp_adapter = (
            erp_adapter
            if erp_adapter is not None
            else ERPAdapter(seed=seed, sku_table=sku_table, tags_table=tags, competitor_rows=competitors)
        )
        self.trends_adapter = trends_adapter if trends_adapter is not None else TrendsAdapter(seed=seed, trends=trends)
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
        self.llm_client = llm_client

        self.sales_agent = SalesReviewAgent(llm_client=llm_client, use_llm=effective_llm)
        self.inventory_agent = InventoryWarningAgent(llm_client=llm_client, use_llm=effective_llm)
        self.slow_moving_agent = SlowMovingAgent(llm_client=llm_client, use_llm=effective_llm)
        self.category_agent = CategoryManagementAgent(llm_client=llm_client, use_llm=effective_llm)
        self.pricing_agent = PricingAgent()
        self.replenishment_calc = ReplenishmentCalculator(
            llm_client=llm_client,
            use_llm=effective_llm,
        )

    def run(self) -> Dict:
        sku_metrics = self.erp_adapter.get_all_skus()
        top_trends = self.trends_adapter.get_top_trends(limit=max(self.top_n, 5))
        growing_trends = self.trends_adapter.get_growing_trends(limit=max(self.top_n, 5))

        product_selection: Dict[str, object] = {"skipped": True, "llm_error": None}
        suggested_categories: List[str] = []
        if self.enable_selection:
            def _fallback_recommendation() -> Dict[str, object]:
                kw = [str(x.get("keyword", "")).strip() for x in growing_trends[:3] if isinstance(x, dict)]
                kw = [x for x in kw if x]
                mapping = {
                    "美拉德": ["针织衫", "半身裙", "大衣"],
                    "老钱": ["西装外套", "衬衫", "风衣"],
                    "Y2K": ["短上衣", "牛仔裤", "短裙"],
                    "辣妹": ["短上衣", "迷你裙", "连衣裙"],
                }
                cats: List[str] = []
                for k in kw:
                    for token, cands in mapping.items():
                        if token in k:
                            for c in cands:
                                if c not in cats:
                                    cats.append(c)
                if not cats:
                    cats = ["连衣裙", "衬衫", "T恤"]
                rec_rows: List[Dict[str, object]] = []
                for i, c in enumerate(cats[:5], 1):
                    rec_rows.append(
                        {
                            "category": c,
                            "priority": "high" if i <= 2 else "medium",
                            "reason": "基于近期趋势关键词做规则降级映射（未启用/未配置大模型或知识图谱）。",
                            "specific_items": [],
                            "colors": [],
                            "materials": [],
                            "expected_demand": "medium",
                            "market_competition": "medium",
                        }
                    )
                return {
                    "cross_dimension_summary": f"趋势关注：{'、'.join(kw) if kw else '暂无'}；建议先用规则映射输出品类清单。",
                    "recommended_categories": rec_rows,
                    "style_direction": {
                        "primary_style": "韩系休闲",
                        "secondary_styles": ["通勤", "简约"],
                        "style_mix_suggestions": "保持基础款占比，并用 1-2 个趋势点做搭配引流。",
                    },
                    "inventory_allocation": {
                        "high_priority_ratio": 0.5,
                        "medium_priority_ratio": 0.3,
                        "low_priority_ratio": 0.2,
                        "reasoning": "降级模式下以稳健备货为主，避免对单一趋势押注过深。",
                    },
                    "marketing_suggestions": ["围绕趋势关键词做主题页/短视频", "先小批量测款再放量"],
                    "risk_assessment": {
                        "seasonal_risk": "medium",
                        "competition_risk": "medium",
                        "inventory_risk": "medium",
                    },
                    "confidence_score": 0.35,
                }

            criteria = {
                "season": "春季",
                "temperature_range": "15-20度",
                "target_style": "韩系休闲",
                "occasion": "日常通勤",
                "price_range": "平价",
                "target_audience": "年轻女性",
                "_skip_kg": True,
            }
            try:
                agent = ProductSelectionAgent(llm_client=self.llm_client)
                if self.selection_requirements_path:
                    selection_result = asyncio.run(
                        agent.analyze_from_requirements_path(self.selection_requirements_path)
                    )
                else:
                    selection_result = agent.analyze_sync(criteria)
            except Exception as e:
                selection_result = {
                    "criteria": criteria,
                    "error": str(e),
                    "llm_error": str(e),
                }

            rec = selection_result.get("recommendation")
            used_fallback = False
            if not isinstance(rec, dict):
                rec = _fallback_recommendation()
                used_fallback = True
            if isinstance(rec, dict):
                rows = rec.get("recommended_categories")
                if isinstance(rows, list):
                    for r in rows:
                        if not isinstance(r, dict):
                            continue
                        s = str(r.get("category", "")).strip()
                        if s and s not in suggested_categories:
                            suggested_categories.append(s)

            product_selection = {
                "skipped": False,
                "criteria": selection_result.get("parsed_criteria") or selection_result.get("criteria"),
                "suggested_categories": suggested_categories,
                "recommendation": rec if isinstance(rec, dict) else None,
                "data_source": "rules_fallback" if used_fallback else ("llm_only" if criteria.get("_skip_kg") else "kg+llm"),
                "llm_error": selection_result.get("llm_error"),
                "error": selection_result.get("error"),
            }

        category_management: Dict[str, object] = {"skipped": True}
        if self.enable_category_management:
            cat_mapping = None
            if self.category_mapping_path:
                cat_mapping = load_category_mapping(self.category_mapping_path)
            ps_payload = None
            if suggested_categories:
                ps_payload = {
                    "trend_picks": [
                        {
                            "keyword": "criteria",
                            "merch_mapping": {"suggested_categories": suggested_categories},
                        }
                    ]
                }
            category_management = self.category_agent.analyze(
                sku_metrics=sku_metrics,
                product_selection=ps_payload,
                category_mapping=cat_mapping,
                category_experiences=None,
                top_n=self.top_n,
            )

        pricing: Dict[str, object] = {"skipped": True}
        if self.enable_pricing:
            pricing = self.pricing_agent.analyze(
                category_management=category_management if isinstance(category_management, dict) else None,
                product_selection=product_selection if isinstance(product_selection, dict) else None,
                competitor_benchmarks=self.erp_adapter.list_competitor_benchmarks(),
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
            category_management.get("recommendations", []),
            pricing.get("recommendations", []),
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
                "data_integration": dict(self.data_integration),
                "llm_enabled": self.llm_enabled,
                "llm_notice": self.llm_notice,
            },
            "product_selection": product_selection,
            "category_management": category_management,
            "pricing": pricing,
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
