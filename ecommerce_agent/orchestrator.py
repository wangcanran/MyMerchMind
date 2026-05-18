"""Baseline demo 编排器。"""
import json
from pathlib import Path
from typing import Dict, List, Optional

from .agents.category_management_agent import CategoryManagementAgent
from .agents.inventory_warning_agent import InventoryWarningAgent
from .agents.product_selection_agent import ProductSelectionAgent
from .agents.replenishment_calculator import ReplenishmentCalculator
from .agents.sales_review_agent import SalesReviewAgent
from .agents.slow_moving_agent import SlowMovingAgent
from .data.erp_adapter import ERPAdapter
from .data.trends_adapter import TrendsAdapter
from .data.category_mapping import load_category_mapping
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
        sku_scenario: str = "default",
        feedback_memory_path: Optional[Path] = None,
        category_mapping_path: Optional[Path] = None,
        erp_adapter: Optional[ERPAdapter] = None,
        trends_adapter: Optional[TrendsAdapter] = None,
        use_llm: bool = False,
        llm_scope: str = "all",
    ):
        self.seed = seed
        self.top_n = top_n
        self.as_of = as_of
        self.replenishment_cycle_days = replenishment_cycle_days
        self.overstock_days = overstock_days
        self.sku_scenario = (sku_scenario or "default").strip().lower()

        self.erp_adapter = (
            erp_adapter if erp_adapter is not None else ERPAdapter(seed=seed, sku_scenario=self.sku_scenario)
        )
        self.trends_adapter = trends_adapter if trends_adapter is not None else TrendsAdapter(seed=seed)
        self.memory = FeedbackMemoryStore(path=feedback_memory_path)
        self.experience_memory_notice: Optional[str] = None
        self._persist_experiences = feedback_memory_path is not None
        if self._persist_experiences:
            try:
                if isinstance(feedback_memory_path, Path) and not feedback_memory_path.exists():
                    self.memory.save()
            except Exception:
                pass
        self.category_mapping_notice: Optional[str] = None
        self.category_mapping = None
        if isinstance(category_mapping_path, Path) and str(category_mapping_path).strip():
            try:
                self.category_mapping = load_category_mapping(category_mapping_path)
            except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as e:
                self.category_mapping_notice = f"类目映射加载失败：{e}，已回退为关键词规则。"
                self.category_mapping = None

        llm_cfg = load_llm_config()
        llm_client: Optional[OpenAICompatChatClient] = None
        self.llm_notice: Optional[str] = None
        self.llm_enabled = False
        if use_llm:
            if llm_cfg.is_configured():
                llm_client = OpenAICompatChatClient(llm_cfg)
            else:
                self.llm_notice = "已请求 --llm，但未配置 MOARK_API_KEY / LLM_API_KEY / OPENAI_API_KEY，已回退为规则模式。"
        effective_llm = use_llm and llm_client is not None
        scope = (llm_scope or "all").strip().lower()
        if scope not in {"all", "category"}:
            scope = "all"
        self.llm_enabled = bool(effective_llm)
        self._llm_scope = scope

        enable_all = effective_llm and self._llm_scope == "all"
        enable_category = effective_llm and self._llm_scope in {"all", "category"}

        self.sales_agent = SalesReviewAgent(llm_client=llm_client, use_llm=enable_all)
        self.inventory_agent = InventoryWarningAgent(llm_client=llm_client, use_llm=enable_all)
        self.selection_agent = ProductSelectionAgent(llm_client=llm_client, use_llm=enable_all)
        self.category_agent = CategoryManagementAgent(llm_client=llm_client, use_llm=enable_category)
        self.slow_moving_agent = SlowMovingAgent(llm_client=llm_client, use_llm=enable_all)
        self.replenishment_calc = ReplenishmentCalculator(
            llm_client=llm_client,
            use_llm=enable_all,
        )

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

        category_management = self.category_agent.analyze(
            sku_metrics=sku_metrics,
            product_selection=product_selection,
            category_mapping=self.category_mapping,
            category_experiences=self.memory.list_active_category_experiences(),
            top_n=self.top_n,
        )
        self._persist_category_experiences(category_management)

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

        guardrail_actions = self._collect_guardrail_actions(category_management)
        actions = self._merge_actions(
            guardrail_actions,
            product_selection.get("recommendations", []),
            category_management.get("recommendations", []),
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
                "sku_scenario": self.sku_scenario,
                "llm_enabled": self.llm_enabled,
                "llm_scope": self._llm_scope,
                "llm_notice": self.llm_notice,
                "category_mapping_notice": self.category_mapping_notice,
                "experience_memory_notice": self.experience_memory_notice,
            },
            "product_selection": product_selection,
            "category_management": category_management,
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

    def _collect_guardrail_actions(self, category_management: Dict) -> List[str]:
        decisions = category_management.get("decisions") if isinstance(category_management, dict) else None
        if not isinstance(decisions, dict):
            return []

        def iter_rows(key: str, field: str) -> List[Dict]:
            card = decisions.get(key)
            if not isinstance(card, dict):
                return []
            rows = card.get(field)
            if not isinstance(rows, list):
                return []
            return [r for r in rows if isinstance(r, dict)]

        items: List[Dict[str, str]] = []
        for row in iter_rows("audit_existing", "results") + iter_rows("retire", "candidates"):
            cat = str(row.get("category", "")).strip()
            eg = row.get("experience_guardrail") if isinstance(row.get("experience_guardrail"), dict) else None
            if not cat or not isinstance(eg, dict):
                continue
            acts = eg.get("guardrail_actions")
            if isinstance(acts, list):
                for a in acts:
                    if not isinstance(a, dict):
                        continue
                    action = str(a.get("action", "")).strip()
                    owner = str(a.get("owner", "")).strip()
                    if action:
                        items.append({"type": "action", "owner": owner or "未指定", "category": cat, "text": action})
            checks = eg.get("guardrail_checks")
            if isinstance(checks, list):
                for ck in checks:
                    s = str(ck).strip()
                    if s:
                        items.append({"type": "check", "owner": "检查项", "category": cat, "text": s})

        dedup = set()
        out: List[str] = []
        for it in sorted(items, key=lambda x: (x["owner"], x["category"], x["type"], x["text"])):
            key = (it["type"], it["owner"], it["category"], it["text"])
            if key in dedup:
                continue
            dedup.add(key)
            if it["type"] == "action":
                out.append(f"【经验动作】({it['owner']}) {it['text']} — {it['category']}")
            else:
                out.append(f"【经验检查】{it['text']} — {it['category']}")
        return out

    def _persist_category_experiences(self, category_management: Dict) -> None:
        try:
            if not self._persist_experiences:
                self.experience_memory_notice = "未指定 feedback_memory 路径，品类经验未落盘（避免修改默认示例文件）。"
                return
            candidates = category_management.get("experience_candidates_all")
            if not isinstance(candidates, list) or not candidates:
                return
            added = 0
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                self.memory.append_category_experience(c)
                added += 1
            if added:
                self.memory.save()
                self.experience_memory_notice = f"已落盘品类经验 {added} 条。"
        except Exception as e:
            self.experience_memory_notice = f"品类经验落盘失败：{e}"
