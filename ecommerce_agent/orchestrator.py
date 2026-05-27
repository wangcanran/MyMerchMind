"""Baseline demo 编排器。"""
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .agents.category_management_agent import CategoryManagementAgent
from .agents.dynamic_pricing_agent import DynamicPricingAgent, normalize_target_gross_margin
from .agents.inventory_management_agent import InventoryManagementAgent
from .agents.sales_review_agent import SalesReviewAgent
from .config.data_sources import DataSourceSettings, load_data_source_settings
from .config.return_rate_thresholds import high_return_rate_pct, is_high_return
from .data.category_mapping import load_category_mapping
from .data.erp_adapter import ERPAdapter
from .data.sku_snapshot import deep_copy_sku_metrics
from .data.file_loaders import (
    load_competitors_from_json,
    load_erp_skus_from_json,
    load_tags_from_json,
    load_trends_from_json,
)
from .data.trends_adapter import TrendsAdapter
from .data.competitor_pricing_adapter import CompetitorPricingAPI
from .data.mock_competitors import list_competitor_rows as mock_competitor_rows
from .data.taobao_competitor_adapter import (
    TaobaoCompetitorAdapter,
    build_default_cache_path as taobao_competitor_cache_path,
)
from .memory.feedback_store import FeedbackMemoryStore
from .memory.experience_store import ExperienceStore, build_query_keys_from_run
from .memory.experience_draft_generator import generate_drafts_from_run
from .llm import OpenAICompatChatClient, load_llm_config
from .report_formatting import build_actions_display, m2_m3_structure_bridge_note


class DemoOrchestrator:
    """组织数据读取、Agent 分析与结果汇总。

    数据流概要
    ----------
    - **ERP**（``sku_metrics``）：在架 SKU 事实。
    - **M2 选品**（``product_selection``）：``suggested_categories`` 与结构化 ``recommendation``。
    - **M3 品类**：接收 M2 的 ``suggested_categories``（经 ``trend_picks`` / ``merch_mapping``），
      输出新品评估等决策（含 ``approve_new`` / ``keep_selling`` 等）。
    - **新品企划**（``new_product_planning``）：仅在 M3 之后生成；**只对**
      ``evaluate_new`` 中 ``decision=approve_new`` 的品类做竞品检索与 ``market_intel``。
      未启用品类管理或未产生 ``approve_new`` 时，企划条目为空（不再做 ERP 粗类去重）。
    - **在架定价**（``pricing``）：对 ERP SKU 使用 ``executable`` 微调现价。
    """

    def __init__(
        self,
        seed: int = 42,
        top_n: int = 5,
        as_of: str = "",
        replenishment_cycle_days: int = 7,
        overstock_days: int = 45,
        feedback_memory_path: Optional[Path] = None,
        experience_store_path: Optional[Path] = None,
        enable_experience_draft: bool = True,
        data_sources: Optional[DataSourceSettings] = None,
        category_mapping_path: Optional[Path] = None,
        selection_requirements_path: Optional[Path] = None,
        selection_requirements_text: Optional[str] = None,
        enable_selection: bool = False,
        enable_category_management: bool = False,
        enable_pricing: bool = False,
        erp_adapter: Optional[ERPAdapter] = None,
        trends_adapter: Optional[TrendsAdapter] = None,
        use_llm: bool = False,
        target_gross_margin: Optional[float] = None,
        uploaded_competitor_products: Optional[List[Dict]] = None,
    ):
        self.seed = seed
        self.top_n = top_n
        self.as_of = as_of
        self.replenishment_cycle_days = replenishment_cycle_days
        self.overstock_days = overstock_days
        self.category_mapping_path = category_mapping_path
        self.selection_requirements_path = selection_requirements_path
        self.selection_requirements_text = (selection_requirements_text or "").strip() or None
        self.enable_selection = enable_selection
        self.enable_category_management = enable_category_management
        self.enable_pricing = enable_pricing
        self._target_gross_margin = target_gross_margin

        # 用户上传的 SKU 级竞品数据：[{match_sku, competitors: [{title, price, sales}]}]
        # 按 match_sku 建索引，供旧品定价时直接查找竞品价格和销量。
        self._uploaded_competitor_map: Dict[str, List[Dict]] = {}
        for group in (uploaded_competitor_products or []):
            if not isinstance(group, dict):
                continue
            key = str(group.get("match_sku", "")).strip()
            comps = group.get("competitors")
            if key and isinstance(comps, list) and comps:
                self._uploaded_competitor_map[key] = comps

        # 调用方未显式传入时，主动读环境变量（ECOMMERCE_COMPETITORS_SOURCE 等），
        # 保证 `python -m ecommerce_agent.main` 这种没经过 load_data_source_settings
        # 的入口也能识别 taobao 数据源开关。
        ds = data_sources if data_sources is not None else load_data_source_settings()
        if ds.competitors_source == "taobao":
            competitors_label = "taobao_live"
        elif ds.competitors_json:
            competitors_label = "file"
        else:
            competitors_label = "mock"
        print(
            f"[orchestrator] data sources -> {ds.describe()} "
            f"(competitors_source={ds.competitors_source})"
        )
        self.data_integration = {
            "erp": "file" if ds.erp_json else "mock",
            "trends": "file" if ds.trends_json else "mock",
            "competitors": competitors_label,
            "tags": "file" if ds.tags_json else "mock",
        }
        self._competitors_source = ds.competitors_source

        sku_table = load_erp_skus_from_json(ds.erp_json) if ds.erp_json else None
        trends = load_trends_from_json(ds.trends_json) if ds.trends_json else None
        competitors = load_competitors_from_json(ds.competitors_json) if ds.competitors_json else None
        tags = load_tags_from_json(ds.tags_json) if ds.tags_json else None

        self.erp_adapter = (
            erp_adapter
            if erp_adapter is not None
            else ERPAdapter(seed=seed, sku_table=sku_table, tags_table=tags, competitor_rows=competitors)
        )

        # 竞品数据源：默认 mock；当 ds.competitors_source == "taobao" 时切到现场爬虫，
        # 抓不到/超时则自动降级回 mock，编排不会中断。
        self._taobao_competitor: Optional[TaobaoCompetitorAdapter] = None
        if ds.competitors_source == "taobao":
            fallback_prices_api = CompetitorPricingAPI()
            self._taobao_competitor = TaobaoCompetitorAdapter(
                cookie_string=ds.taobao_cookie,
                max_items=ds.taobao_max_items,
                cache_ttl_sec=ds.taobao_cache_ttl_sec,
                cache_path=taobao_competitor_cache_path(),
                fallback_benchmarks=(
                    competitors if competitors else mock_competitor_rows()
                ),
                fallback_prices_provider=(
                    fallback_prices_api.get_competitor_prices
                ),
                debug=True,
            )
            if not ds.taobao_cookie:
                print(
                    "[orchestrator] WARN taobao 数据源已开启，但未提供 TAOBAO_COOKIE，"
                    "未登录抓取大概率会被反爬拦截并降级到 mock。"
                )

        # 新品企划专用爬虫：即使旧品用上传/mock 数据，新品企划仍尝试淘宝爬虫获取竞品情报。
        # 当全局已是 taobao 模式时复用同一实例；否则单独创建（有 cookie 就爬，没有则降级 mock）。
        self._planning_competitor: Optional[TaobaoCompetitorAdapter] = self._taobao_competitor
        if self._planning_competitor is None and ds.taobao_cookie:
            self._planning_competitor = TaobaoCompetitorAdapter(
                cookie_string=ds.taobao_cookie,
                max_items=ds.taobao_max_items,
                cache_ttl_sec=ds.taobao_cache_ttl_sec,
                cache_path=taobao_competitor_cache_path(),
                fallback_benchmarks=(
                    competitors if competitors else mock_competitor_rows()
                ),
                fallback_prices_provider=CompetitorPricingAPI().get_competitor_prices,
                debug=True,
            )
            print("[orchestrator] 新品企划将使用淘宝爬虫获取竞品数据（旧品仍用上传/mock）")
        self.trends_adapter = trends_adapter if trends_adapter is not None else TrendsAdapter(seed=seed, trends=trends)
        self.memory = FeedbackMemoryStore(path=feedback_memory_path)
        self.experience_store = ExperienceStore(path=experience_store_path)
        self._enable_experience_draft = enable_experience_draft

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
        self.category_agent = CategoryManagementAgent(llm_client=llm_client, use_llm=effective_llm)
        self.inventory_management_agent = InventoryManagementAgent(
            llm_client=llm_client,
            use_llm=effective_llm,
        )
        self.dynamic_pricing_agent = DynamicPricingAgent(
            llm_client=llm_client,
            use_llm=effective_llm,
        )
        # SKU 级竞品价格来源：默认走 mock 文件；taobao 模式下复用适配器（接口签名一致）。
        self.competitor_pricing_api = (
            self._taobao_competitor
            if self._taobao_competitor is not None
            else CompetitorPricingAPI()
        )

    def run(self) -> Dict:
        sku_metrics = deep_copy_sku_metrics(self.erp_adapter.get_all_skus())
        top_trends = self.trends_adapter.get_top_trends(limit=max(self.top_n, 5))
        growing_trends = self.trends_adapter.get_growing_trends(limit=max(self.top_n, 5))

        # ── 经验检索：在 run 开始时构建查询键，供后续各模块注入 ──────────────
        trend_kws = [
            str(t.get("keyword", "")).strip()
            for t in (top_trends or [])[:5]
            if isinstance(t, dict)
        ]
        _price_tiers = list({
            self._price_tier_for_sku(s) for s in sku_metrics if self._price_tier_for_sku(s)
        })
        _return_signals = list({
            self._return_signal_for_sku(s) for s in sku_metrics if self._return_signal_for_sku(s)
        })
        _inventory_signals = list({
            self._inventory_signal_for_sku(s) for s in sku_metrics if self._inventory_signal_for_sku(s)
        })
        _channels = list({
            ch for s in sku_metrics
            for ch in (s.get("channel_sales") or {}).keys()
        })
        _experience_query = build_query_keys_from_run(
            as_of=str(self.as_of or ""),
            categories=list({
                self._extract_category_for_experience(s) for s in sku_metrics
                if self._extract_category_for_experience(s)
            }),
            trend_keywords=trend_kws,
            price_tiers=_price_tiers,
            return_signals=_return_signals,
            inventory_signals=_inventory_signals,
            conversion_signals=list({
                self._conversion_signal_for_sku(s) for s in sku_metrics if self._conversion_signal_for_sku(s)
            }),
            channels=_channels,
            tag_values=[
                v for s in sku_metrics
                for v in (self.erp_adapter.get_sku_tags(s.get("sku_id", "")) or {}).values()
                if v
            ],
            criteria_style=self._selection_criteria_style(),
            criteria_audience=self._selection_criteria_audience(),
        )
        retrieved_experiences = self.experience_store.retrieve(_experience_query, top_k=5)
        # 给每条经验标注全局引用编号（用于报告中的参考文献引用）
        for idx, exp in enumerate(retrieved_experiences, 1):
            exp["_ref_index"] = idx

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
                "_skip_kg": False,
            }
            # 惰性导入选品 Agent：其依赖 kg_builder → LightRAG；在 Py3.9 下部分存储实现模块
            # 若无 ``from __future__ import annotations``，顶层 import 会在注解求值时报 ``|`` 相关错误。
            # 未启用选品时不应为此拉全量图谱依赖。
            try:
                from .agents.product_selection_agent import ProductSelectionAgent

                agent = ProductSelectionAgent(llm_client=self.llm_client)
                if self.selection_requirements_path:
                    selection_result = asyncio.run(
                        agent.analyze_from_requirements_path(self.selection_requirements_path)
                    )
                elif self.selection_requirements_text:
                    selection_result = asyncio.run(
                        agent.analyze_from_requirements_text(self.selection_requirements_text)
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

            effective_crit = selection_result.get("parsed_criteria") or selection_result.get("criteria")
            if isinstance(effective_crit, dict):
                skip_kg_flag = bool(effective_crit.get("_skip_kg"))
            else:
                skip_kg_flag = bool(criteria.get("_skip_kg"))

            # LLM 有返回但 JSON 解析失败时，仍可能已用规则兜底出品类；此时不应标成「选品失败」
            sel_err = selection_result.get("error")
            sel_llm = selection_result.get("llm_error")
            raw_sel_err = sel_err
            raw_sel_llm = sel_llm

            def _looks_like_http_timeout(msg: object) -> bool:
                t = str(msg or "").lower()
                return "timeout" in t or "timed out" in t or "超时" in t

            timeout_hint: Optional[str] = None
            if _looks_like_http_timeout(raw_sel_err) or _looks_like_http_timeout(raw_sel_llm):
                timeout_hint = (
                    "选品阶段 HTTP 读取/连接超时：客户端已对超时自动重试；仍失败时可增大环境变量 "
                    "LLM_TIMEOUT_S 或 LLM_READ_TIMEOUT_S（如 180～300），或在需求 JSON 中设置 "
                    "`_skip_kg: true` 以减轻图谱与嵌入调用。"
                )

            parse_failed = sel_err == "Failed to parse recommendation"
            if parse_failed and suggested_categories:
                sel_err = None
                ds = "llm_parse_fallback"
            elif used_fallback:
                ds = "rules_fallback"
            else:
                if selection_result.get("kg_degraded"):
                    ds = "llm_only_kg_degraded"
                elif skip_kg_flag:
                    ds = "llm_only"
                else:
                    ds = "kg+llm"

            kg_note = ""
            if selection_result.get("kg_degraded"):
                kg_note = (
                    "知识图谱阶段曾失败并已降级：本次选品 LLM 在**无图谱摘录**（或仅含错误说明）下生成；"
                    "若需稳定走 kg+llm，请检查 kg_storage_v2、嵌入网关与 LightRAG 日志。"
                )

            product_selection = {
                "skipped": False,
                "criteria": effective_crit if isinstance(effective_crit, dict) else criteria,
                "suggested_categories": suggested_categories,
                "recommendation": rec if isinstance(rec, dict) else None,
                "data_source": ds,
                "llm_error": sel_llm,
                "error": sel_err,
                "selection_note": (
                    " ".join(
                        p
                        for p in (
                            (
                                "LLM 已返回内容但 JSON 解析失败，建议品类已用内置规则映射兜底；"
                                "可检查模型是否输出多余说明文字或非标准 JSON。"
                            )
                            if parse_failed and suggested_categories
                            else None,
                            timeout_hint,
                            kg_note if kg_note else None,
                        )
                        if p
                    )
                    or None
                ),
            }
            if isinstance(selection_result.get("requirements_preview"), str):
                product_selection["requirements_preview"] = selection_result["requirements_preview"]
            if isinstance(selection_result.get("requirements_file"), str):
                product_selection["requirements_file"] = selection_result["requirements_file"]
            if selection_result.get("kg_degraded"):
                product_selection["kg_degraded"] = True

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
                category_experiences=retrieved_experiences,
                top_n=self.top_n,
            )
            if isinstance(category_management, dict):
                bridge_note = m2_m3_structure_bridge_note(product_selection, category_management)
                if bridge_note:
                    category_management["m2_m3_bridge_note"] = bridge_note

        if self.enable_selection and isinstance(product_selection, dict) and not product_selection.get("skipped"):
            self._finalize_new_product_planning(product_selection, category_management)

        pricing: Dict[str, object] = {"skipped": True}
        if self.enable_pricing:
            pricing = self.run_pricing_analysis(
                sku_metrics,
                product_selection=product_selection,
                experiences=retrieved_experiences,
            )

        sales_review = self.sales_agent.analyze(
            sku_metrics=sku_metrics,
            top_trends=top_trends,
            growing_trends=growing_trends,
            top_n=self.top_n,
        )
        inventory_bundle = self.inventory_management_agent.analyze(
            sku_metrics=sku_metrics,
            replenishment_cycle_days=self.replenishment_cycle_days,
            overstock_days=self.overstock_days,
            limit=self.top_n,
        )
        inventory_review = inventory_bundle.get("inventory_review", {})
        slow_moving = inventory_bundle.get("slow_moving", {})
        replenishment = inventory_bundle.get("replenishment", {})
        inventory_management = inventory_bundle.get("management_summary", {})

        memory_snapshot = {
            "active_feedback_count": len(self.memory.list_active_items()),
            "product_selection_hits": len(product_selection.get("memory_hits", [])),
            "experience_store": self.experience_store.stats(),
            "retrieved_experience_count": len(retrieved_experiences),
            "retrieved_experiences": [
                {
                    "experience_id": e.get("experience_id"),
                    "title": e.get("title"),
                    "confidence": e.get("confidence"),
                    "_score": e.get("_score"),
                }
                for e in retrieved_experiences
            ],
        }

        pricing_recs: List[str] = []
        pricing_rows = [r for r in (pricing.get("pricing_suggestions") or []) if isinstance(r, dict)]

        def _pricing_gap_abs(row: Dict) -> float:
            cur = float(row.get("current_price") or 0)
            sug = float(row.get("suggested_price") or 0)
            if not cur or not sug:
                return 0.0
            return abs(float(sug) - float(cur)) / float(cur)

        ranked_pr = sorted(
            (
                r
                for r in pricing_rows
                if r.get("current_price") is not None
                and r.get("suggested_price") is not None
                and float(r.get("current_price") or 0) != float(r.get("suggested_price") or 0)
            ),
            key=_pricing_gap_abs,
            reverse=True,
        )
        price_action_cap = max(1, int(self.top_n))
        for r in ranked_pr[:price_action_cap]:
            sid = str(r.get("sku_id") or "").strip()
            name = str(r.get("name") or "").strip()
            label = f"{sid} {name}".strip() if sid else name
            if not label:
                continue
            sug = r.get("suggested_price")
            cur = r.get("current_price")
            strategy = str(r.get("strategy") or "").strip()
            if sug and cur and cur != sug:
                pricing_recs.append(
                    f"定价建议：{label} 现售 ¥{cur}，建议调至 ¥{sug}（{strategy}）。"
                )

        planning_recs = self._new_planning_action_lines(product_selection)
        high_return_recs = DemoOrchestrator._high_return_disposition_lines(sku_metrics)

        actions = self._merge_actions(
            product_selection.get("recommendations", []),
            category_management.get("recommendations", []),
            pricing_recs,
            high_return_recs,
            planning_recs,
            sales_review.get("recommendations", []),
            inventory_review.get("recommendations", []),
            slow_moving.get("recommendations", []),
            replenishment.get("recommendations", []),
        )
        actions_display = build_actions_display(actions, as_of_iso=str(self.as_of or ""))

        result: Dict = {
            "context": {
                "as_of": self.as_of,
                "seed": self.seed,
                "sku_count": len(sku_metrics),
                "trend_count": len(self.trends_adapter.data_source.trends),
                "top_n": self.top_n,
                "data_integration": dict(self.data_integration),
                "llm_enabled": self.llm_enabled,
                "llm_notice": self.llm_notice,
                "target_gross_margin": normalize_target_gross_margin(
                    self._target_gross_margin
                ),
                "reporting_rules": {
                    "sku_identity": "全报告以 sku_id 为主键；展示统一为「sku_id + 品名」，避免同名混淆。",
                    "price_baseline": "各模块读取的 SKU 指标为编排开始时的 ERP 深拷贝快照，不在 Agent 内回写改价。",
                    "slow_vs_top": "滞销清理池排除日销 Top5 SKU；高动销与高库龄并存时优先按补货/转化治理，不与清滞混标。",
                    "high_return": (
                        f"退货率≥{high_return_rate_pct():g}% 的每个 SKU 在行动清单中强制生成一条「高退货处置」动作；"
                        "阈值可由环境变量 ECOMMERCE_HIGH_RETURN_RATE 覆盖。"
                    ),
                    "decision_authority": (
                        "规则模块（M3.1 调价表、P1 库存阈值、M3.3 EOQ 等）输出为可执行基线与数字来源；"
                        "LLM 仅生成解读、协同话术与风险提示。若文字建议与规则数值或策略冲突，以规则为准，"
                        "LLM 内容需人工复核后方可作为执行依据。"
                    ),
                    "pricing_actions_scope": (
                        f"行动清单中的「定价建议」仅收录与现售偏差最大的前 {max(1, int(self.top_n))} 个 SKU，"
                        "与 Markdown 中 M3.1 展示范围一致；其余 SKU 的完整算价见 JSON pricing.pricing_suggestions。"
                    ),
                    "replenishment_qty_legend": (
                        "P1「建议补货」为按目标库存与覆盖缺口估算的短期补量；M3.3「建议订货」在规则中取 "
                        "max(建议补货件数, EOQ 约束上界, 紧急缓冲等) 作为采购参考批量，二者不必相等。"
                    ),
                },
            },
            "product_selection": product_selection,
            "category_management": category_management,
            "pricing": pricing,
            "sales_review": sales_review,
            "inventory_review": inventory_review,
            "slow_moving": slow_moving,
            "replenishment": replenishment,
            "inventory_management": inventory_management,
            "memory_snapshot": memory_snapshot,
            "actions": actions,
            "actions_display": actions_display,
            # 内部快照字段：供 draft 生成器使用，不对外文档承诺
            "_sku_metrics_snapshot": sku_metrics,
            "_top_trends": top_trends,
        }

        # ── 经验 draft 自动生成（失败不中断主流程）────────────────────────
        if self._enable_experience_draft:
            try:
                cat_mapping = None
                if self.category_mapping_path:
                    cat_mapping = load_category_mapping(self.category_mapping_path)
                all_tags = self.erp_adapter.get_all_sku_tags()
                new_drafts = generate_drafts_from_run(
                    result,
                    experience_store=self.experience_store,
                    seed=self.seed,
                    category_mapping=cat_mapping,
                    all_tags=all_tags,
                )
                if new_drafts:
                    result["memory_snapshot"]["new_draft_count"] = len(new_drafts)
            except Exception as _exp_err:  # noqa: BLE001
                result["memory_snapshot"]["experience_draft_error"] = str(_exp_err)

        return result

    # ── 经验检索辅助（复用 experience_store 里的推导函数）──────────────
    @staticmethod
    def _price_tier_for_sku(sku: Dict) -> str:
        from .memory.experience_store import _derive_price_tier
        return _derive_price_tier(sku.get("price"))

    @staticmethod
    def _return_signal_for_sku(sku: Dict) -> str:
        from .memory.experience_store import _derive_return_signal
        return _derive_return_signal(sku.get("return_rate"))

    @staticmethod
    def _inventory_signal_for_sku(sku: Dict) -> str:
        from .memory.experience_store import _derive_inventory_signal
        return _derive_inventory_signal(sku.get("stock_age_days"))

    @staticmethod
    def _conversion_signal_for_sku(sku: Dict) -> str:
        from .memory.experience_store import _derive_conversion_signal
        return _derive_conversion_signal(sku.get("conversion_rate"))

    @staticmethod
    def _extract_category_for_experience(sku: Dict) -> str:
        """从 SKU 名称提取品类大类（与经验库 search_keys.category 对齐）。"""
        name = str(sku.get("name", "")).strip()
        if not name:
            return ""
        if "连衣裙" in name:
            return "连衣裙"
        if "半身裙" in name or "半裙" in name:
            return "半身裙"
        if "衬衫" in name:
            return "衬衫"
        if "T恤" in name or "短袖" in name:
            return "T恤"
        if "外套" in name or "夹克" in name:
            return "外套"
        if "裤" in name:
            return "裤子"
        if "针织" in name or "开衫" in name:
            return "针织开衫"
        if "防晒" in name:
            return "防晒衫"
        return ""

    @staticmethod
    def _filter_experiences_for_sku(
        sku: Dict, experiences: Optional[List[Dict]]
    ) -> List[Dict]:
        """按品类/SKU ID/颜色过滤与该 SKU 相关的经验。"""
        if not experiences:
            return []

        sku_id = str(sku.get("sku_id", "")).strip()
        sku_name = str(sku.get("name", "")).strip()

        # 提取 SKU 的品类和颜色
        sku_category = ""
        for cat in ("连衣裙", "半身裙", "衬衫", "T恤", "外套", "裤", "针织", "开衫", "防晒"):
            if cat in sku_name:
                sku_category = cat
                break

        sku_color = ""
        for color in ("黑色", "白色", "米色", "咖啡色", "深棕色", "雾蓝", "烟灰", "奶咖", "莫兰迪", "淡紫", "浅卡其"):
            if color in sku_name:
                sku_color = color
                break

        relevant = []
        for exp in experiences:
            # 直接 SKU ID 匹配
            evidence = exp.get("evidence") or {}
            exp_sku_ids = evidence.get("sku_ids") or []
            if sku_id and sku_id in exp_sku_ids:
                relevant.append(exp)
                continue

            # 标题/叙事中包含 SKU 名称关键词
            title = str(exp.get("title", ""))
            narrative = str(exp.get("narrative", ""))
            text = title + narrative

            # 品类匹配
            search_keys = exp.get("search_keys") or {}
            exp_cats = search_keys.get("category") or []
            if sku_category and any(sku_category in c for c in exp_cats):
                relevant.append(exp)
                continue

            # 颜色匹配
            exp_tags = search_keys.get("tags") or {}
            exp_color = exp_tags.get("color", "")
            if sku_color and sku_color in (exp_color + text):
                relevant.append(exp)
                continue

        return relevant[:3]  # 最多 3 条

    def _selection_criteria_style(self) -> str:
        """从选品需求文本中提取风格关键词。"""
        text = self.selection_requirements_text or ""
        for kw in ("法式", "通勤", "休闲", "复古", "甜美", "简约", "轻熟", "度假"):
            if kw in text:
                return kw
        return ""

    def _selection_criteria_audience(self) -> str:
        """从选品需求文本中提取目标人群。"""
        text = self.selection_requirements_text or ""
        import re
        m = re.search(r"(\d{2}-\d{2}岁[^\n,，。]*)", text)
        return m.group(1) if m else ""

    @staticmethod
    def _selection_search_context(product_selection: Optional[Dict]) -> Dict[str, str]:
        """从选品结果里抽出用于淘宝竞品检索的上下文字段。"""
        out: Dict[str, str] = {}
        if not isinstance(product_selection, dict):
            return out
        criteria = product_selection.get("criteria") or {}
        if not isinstance(criteria, dict):
            return out
        for key in ("target_style", "target_audience", "occasion", "price_range"):
            v = str(criteria.get(key) or "").strip()
            if v:
                out[key] = v
        return out

    @staticmethod
    def _pure_new_m2_catalog_items(product_selection: Optional[Dict]) -> List[str]:
        """企划标题列表：与 ``new_product_planning.items`` 同源（仅 M3 ``approve_new``）。"""
        if not isinstance(product_selection, dict):
            return []
        npp = product_selection.get("new_product_planning")
        if isinstance(npp, dict) and isinstance(npp.get("items"), list):
            return [str(x).strip() for x in npp["items"] if str(x).strip()]
        return []

    @staticmethod
    def _high_return_disposition_lines(sku_metrics: List[Dict]) -> List[str]:
        """达到统一高退货阈值的 SKU 每人一条可执行处置，避免「识别了风险但行动清单无闭环」。"""
        rows = [x for x in (sku_metrics or []) if isinstance(x, dict)]
        risky = sorted(
            (r for r in rows if is_high_return(r.get("return_rate"))),
            key=lambda x: (-float(x.get("return_rate") or 0), str(x.get("sku_id", ""))),
        )
        out: List[str] = []
        for row in risky:
            sid = str(row.get("sku_id", "")).strip()
            nm = str(row.get("name", "")).strip()
            if not sid and not nm:
                continue
            label = f"{sid} {nm}".strip() if sid else nm
            rr = float(row.get("return_rate") or 0) * 100.0
            out.append(
                f"高退货处置：{label} · 退货率 {rr:.1f}% — "
                "暂停加量推广/投流，联动质检与详情页复核，必要时调价或下架测款。"
            )
        return out

    @staticmethod
    def _new_planning_action_lines(product_selection: object) -> List[str]:
        """新品企划行动句（含市场情报价要点，与报告同源）。"""
        out: List[str] = []
        if not isinstance(product_selection, dict) or product_selection.get("skipped"):
            return out
        npp = product_selection.get("new_product_planning")
        if not isinstance(npp, dict):
            return out
        entries = npp.get("entries")
        if isinstance(entries, list) and entries:
            for ent in entries[:8]:
                if not isinstance(ent, dict):
                    continue
                title = str(ent.get("title") or "").strip()
                if not title:
                    continue
                inf = ent.get("intel") if isinstance(ent.get("intel"), dict) else {}
                mi = inf.get("market_intel") if isinstance(inf.get("market_intel"), dict) else {}
                band = mi.get("reference_band")
                sweet = mi.get("sweet_spot")
                ceiling = mi.get("implied_cost_ceiling")
                tension = str(mi.get("sweet_vs_band_note") or "").strip()
                bits: List[str] = []
                if band:
                    bits.append(f"参考价带 ¥{band}")
                if sweet is not None:
                    bits.append(f"甜点锚点约 ¥{sweet}")
                if ceiling is not None:
                    bits.append(f"示意成本上限 ¥{ceiling}")
                tail = "；".join(bits) if bits else "暂无有效竞品价样本"
                line = f"新品企划（市场情报·非锁价）：{title} — {tail}。"
                if tension:
                    line += f" {tension}"
                out.append(line)
            return out
        for it in (npp.get("items") or [])[:8]:
            s = str(it).strip()
            if s:
                out.append(
                    f"新品企划（M3·approve_new）：{s} — 建议单独立项测款与竞品摸底，勿与在架 SKU 混算。"
                )
        return out

    def _competitor_search_suffix(self, product_selection: Optional[Dict]) -> str:
        from .data.taobao_competitor_adapter import TaobaoCompetitorAdapter as TCA

        ctx = self._selection_search_context(product_selection)
        if (self._competitors_source == "taobao" or self._planning_competitor is not None) and ctx:
            return TCA._build_search_suffix(ctx)
        return ""

    def _fetch_competitor_prices_for_query(
        self, query: str
    ) -> Tuple[List[float], Optional[List[Dict]]]:
        from .data.taobao_competitor_adapter import TaobaoCompetitorAdapter as TCA

        # 优先使用用户上传的 SKU 级竞品数据（精确匹配或包含匹配）
        uploaded = self._lookup_uploaded_competitors(query)
        if uploaded:
            prices = TCA._clean_prices([p.get("price") for p in uploaded])
            return prices, uploaded

        if self._taobao_competitor is not None:
            products = self._taobao_competitor._search_with_cache(query)
            return TCA._clean_prices([p.get("price") for p in products]), products
        prices = self.competitor_pricing_api.get_competitor_prices(query)
        return prices, None

    def _lookup_uploaded_competitors(self, query: str) -> Optional[List[Dict]]:
        """从用户上传的竞品数据中按 SKU 名称匹配。"""
        if not self._uploaded_competitor_map:
            return None
        q = query.strip()
        # 精确匹配
        if q in self._uploaded_competitor_map:
            return self._uploaded_competitor_map[q]
        # 包含匹配：query 包含 match_sku 或 match_sku 包含 query
        for key, comps in self._uploaded_competitor_map.items():
            if key in q or q in key:
                return comps
        return None

    def _fetch_planning_competitor_prices(
        self, query: str
    ) -> Tuple[List[float], Optional[List[Dict]]]:
        """新品企划专用：优先用爬虫获取竞品价格，降级到通用路径。"""
        from .data.taobao_competitor_adapter import TaobaoCompetitorAdapter as TCA

        if self._planning_competitor is not None:
            products = self._planning_competitor._search_with_cache(query)
            return TCA._clean_prices([p.get("price") for p in products]), products
        return self._fetch_competitor_prices_for_query(query)

    def _finalize_new_product_planning(
        self,
        product_selection: Dict[str, object],
        category_management: Dict[str, object],
    ) -> None:
        """在品类管理（新品评估）之后写入 ``new_product_planning`` 并附 ``market_intel``。

        仅包含 ``evaluate_new`` 中 ``decision=approve_new`` 的品类（M2 → M3 → 企划）。
        """
        items: List[str] = []
        use_m3 = isinstance(category_management, dict) and not category_management.get("skipped")
        planning_source = "category_management_skipped"

        if use_m3:
            decisions = category_management.get("decisions")
            ev = decisions.get("evaluate_new") if isinstance(decisions, dict) else None
            if isinstance(ev, dict) and isinstance(ev.get("candidates"), list):
                seen: Set[str] = set()
                for c in ev["candidates"]:
                    if not isinstance(c, dict):
                        continue
                    if str(c.get("decision", "")).strip() != "approve_new":
                        continue
                    cat = str(c.get("category", "")).strip()
                    if cat and cat not in seen:
                        seen.add(cat)
                        items.append(cat)
                planning_source = (
                    "category_management_approve_new"
                    if items
                    else "category_management_no_approve_new"
                )

        if items:
            note = (
                "以下条目来自选品（M2）→ 品类管理（M3）新品评估，且结论为 approve_new；"
                "每条附带企划向市场情报价（非锁价）。在架旧品调价见「SKU PRICING」。"
            )
        elif use_m3:
            note = (
                "M3 新品评估未产生 approve_new，暂无企划条目；"
                "在架旧品调价仍见「SKU PRICING」。"
            )
        else:
            note = (
                "未启用品类管理（M3）时无法从新品评估得到 approve_new，故不做新品企划；"
                "请使用 ``--full`` 或 API 中同时开启选品与品类管理。"
            )

        product_selection["new_product_planning"] = {
            "items": items,
            "criteria_snapshot": product_selection.get("criteria")
            if isinstance(product_selection.get("criteria"), dict)
            else None,
            "note": note,
            "planning_item_source": planning_source,
        }
        self._attach_new_product_planning_intel(product_selection)

    def _attach_new_product_planning_intel(self, product_selection: Dict) -> None:
        """为 M3 ``approve_new`` 企划行拉竞品并写入 ``market_intel``（企划价，非在架锁价）。"""
        npp = product_selection.get("new_product_planning")
        if not isinstance(npp, dict):
            return
        titles = [str(x).strip() for x in (npp.get("items") or []) if str(x).strip()]
        if not titles:
            npp["entries"] = []
            return
        suffix = self._competitor_search_suffix(product_selection)
        entries: List[Dict[str, object]] = []
        for i, title in enumerate(titles):
            query = f"{title} {suffix}".strip() if suffix else title
            prices, products = self._fetch_planning_competitor_prices(query)
            pseudo = {
                "sku_id": f"M3-NP-{i + 1:03d}",
                "name": title,
                "price": 0,
                "cost_price": 0,
                "daily_sales": 0,
                "stock": 0,
                "return_rate": 0.0,
            }
            intel = self.dynamic_pricing_agent.analyze(
                product_info=pseudo,
                competitor_prices=prices,
                store_cost_price=0.0,
                seasonal_factor=0.8,
                competitor_products=products,
                pricing_mode="market_intel",
                target_gross_margin=self._target_gross_margin,
            )
            intel["competitor_search_query"] = query
            intel["competitor_search_used_planning_suffix"] = bool(suffix)
            entries.append(
                {
                    "title": title,
                    "competitor_search_query": query,
                    "intel": intel,
                }
            )
        npp["entries"] = entries

    def run_pricing_analysis(
        self,
        sku_metrics: List[Dict],
        product_selection: Optional[Dict] = None,
        experiences: Optional[List[Dict]] = None,
    ) -> Dict:
        """对 ERP 在架 SKU 跑竞品价与动态定价（恒为 ``executable``，旧品类现价微调）。

        新品企划（M3 ``approve_new``）的市场情报见 ``product_selection.new_product_planning.entries``。
        ``summary.m2_suggestions_not_in_erp_skus`` 为企划标题列表（与 ``new_product_planning.items`` 同源）。
        """
        suffix = self._competitor_search_suffix(product_selection)

        m2_catalog_gaps = self._pure_new_m2_catalog_items(product_selection)

        # 计算日销量百分位，用于角色判定
        all_daily_sales = sorted([int(s.get("daily_sales") or 0) for s in sku_metrics])
        def _daily_sales_pct(ds: int) -> float:
            if not all_daily_sales:
                return 0.5
            below = sum(1 for x in all_daily_sales if x < ds)
            return below / len(all_daily_sales)

        results: List[Dict] = []
        for sku in sku_metrics:
            sku_id = str(sku.get("sku_id", "")).strip()
            sku_name = str(sku.get("name", "")).strip()

            # 优先从上传竞品数据中按 sku_id 精确查找
            uploaded = self._uploaded_competitor_map.get(sku_id)
            if uploaded is None and sku_name:
                uploaded = self._uploaded_competitor_map.get(sku_name)

            if uploaded:
                from .data.taobao_competitor_adapter import TaobaoCompetitorAdapter as TCA
                competitor_prices = TCA._clean_prices([p.get("price") for p in uploaded])
                competitor_products = uploaded
                base = sku_id
            elif self._competitors_source == "taobao":
                base = sku_name or sku_id
                competitor_prices, competitor_products = self._fetch_competitor_prices_for_query(base)
            else:
                base = sku_id or sku_name
                competitor_prices, competitor_products = self._fetch_competitor_prices_for_query(base)

            cost = float(sku.get("cost_price") or 0)
            ds = int(sku.get("daily_sales") or 0)

            # 过滤与该 SKU 相关的经验（按品类/颜色/价位带匹配）
            sku_experiences = self._filter_experiences_for_sku(sku, experiences)

            result = self.dynamic_pricing_agent.analyze(
                product_info=sku,
                competitor_prices=competitor_prices,
                store_cost_price=cost,
                seasonal_factor=0.8,
                competitor_products=competitor_products,
                pricing_mode="executable",
                daily_sales_percentile=_daily_sales_pct(ds),
                relevant_experiences=sku_experiences,
            )
            result["competitor_search_query"] = base
            result["competitor_search_used_planning_suffix"] = False
            results.append(result)

        skus_with_data = [
            r for r in results if r.get("competitor_summary", {}).get("sample_count", 0) > 0
        ]
        return {
            "pricing_suggestions": results,
            "summary": {
                "total_skus": len(results),
                "skus_with_competitor_data": len(skus_with_data),
                "data_source": "uploaded" if self._uploaded_competitor_map else self._competitors_source,
                "competitor_search_suffix": suffix or None,
                "skus_with_planning_suffix": 0,
                "m2_suggestions_not_in_erp_skus": m2_catalog_gaps,
            },
        }

    def _merge_actions(self, *groups: List[str]) -> List[str]:
        merged: List[str] = []
        for group in groups:
            for action in group:
                if action not in merged:
                    merged.append(action)
        return self._deduplicate_actions(merged)

    @staticmethod
    def _deduplicate_actions(actions: List[str]) -> List[str]:
        """语义去重：同一 SKU 的同类操作只保留最具体的一条。"""
        import re

        # 提取 action 中的 SKU ID
        def extract_skus(text: str) -> set:
            return set(re.findall(r"SKU\d+", text))

        # 操作类型分类
        def action_type(text: str) -> str:
            if "退货" in text or "退货率" in text:
                return "return"
            if "补货" in text or "replenish" in text:
                return "replenish"
            if "定价" in text or "调至" in text or "调价" in text:
                return "pricing"
            if "清货" in text or "满减" in text or "滞销" in text:
                return "clearance"
            return "other"

        # 按 (sku, type) 分组，保留最长（最具体）的那条
        seen: dict = {}  # key: (sku, type) -> (index, length)
        drop_indices: set = set()

        for i, action in enumerate(actions):
            skus = extract_skus(action)
            atype = action_type(action)
            if atype == "other" or not skus:
                continue
            for sku in skus:
                key = (sku, atype)
                if key in seen:
                    prev_idx, prev_len = seen[key]
                    if len(action) > prev_len:
                        # 当前更具体，丢弃之前的
                        drop_indices.add(prev_idx)
                        seen[key] = (i, len(action))
                    else:
                        # 之前更具体，丢弃当前
                        drop_indices.add(i)
                else:
                    seen[key] = (i, len(action))

        return [a for i, a in enumerate(actions) if i not in drop_indices]
