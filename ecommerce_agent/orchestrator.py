"""Baseline demo 编排器。"""
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .agents.category_management_agent import CategoryManagementAgent
from .agents.pricing_tools import normalize_target_gross_margin
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
        progress_callback: Optional[callable] = None,
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
        self._progress_callback = progress_callback

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
        self.data_integration = {
            "erp": "uploaded" if erp_adapter is not None else ("file" if ds.erp_json else "mock"),
            "trends": "file" if ds.trends_json else "mock",
            "competitors": "uploaded" if uploaded_competitor_products else competitors_label,
            "tags": "file" if ds.tags_json else "mock",
        }
        print(
            f"[orchestrator] data sources -> "
            f"erp={self.data_integration['erp']}, "
            f"trends={self.data_integration['trends']}, "
            f"competitors={self.data_integration['competitors']}, "
            f"tags={self.data_integration['tags']}"
        )
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

        self.category_agent = CategoryManagementAgent(llm_client=llm_client, use_llm=effective_llm)
        # SKU 级竞品价格来源：默认走 mock 文件；taobao 模式下复用适配器（接口签名一致）。
        self.competitor_pricing_api = (
            self._taobao_competitor
            if self._taobao_competitor is not None
            else CompetitorPricingAPI()
        )

    def _emit_progress(self, step: str, current: int, total: int):
        if self._progress_callback:
            self._progress_callback(step, current, total)

    def run(self) -> Dict:
        self._emit_progress("加载数据", 1, 8)
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
        self._emit_progress("选品策略", 2, 8)
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
            self._emit_progress("品类管理", 3, 8)
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

        self._emit_progress("定价分析", 4, 8)
        pricing: Dict[str, object] = {"skipped": True}
        if self.enable_pricing:
            pricing = self._run_pricing_v2(sku_metrics, retrieved_experiences)

        self._emit_progress("销售分析", 5, 8)
        from .agents.sales_agent_v2 import SalesAgentV2
        sales_agent_v2 = SalesAgentV2(self.llm_client)
        sales_review = sales_agent_v2.analyze(sku_metrics, top_trends, growing_trends, retrieved_experiences)

        self._emit_progress("库存分析", 6, 8)
        from .agents.inventory_agent_v2 import InventoryAgentV2
        inv_agent = InventoryAgentV2(self.llm_client, self.replenishment_cycle_days, self.overstock_days)
        inv_results = []
        for idx, sku in enumerate(sku_metrics):
            self._emit_progress(f"库存分析 ({idx+1}/{len(sku_metrics)})", 6, 8)
            inv_results.append(inv_agent.analyze_sku(sku, retrieved_experiences))

        # 从 V2 结果构建兼容旧格式的输出
        low_stock_alerts = [r for r in inv_results if r["action"] == "replenish"]
        overstock_alerts = [r for r in inv_results if r["action"] == "clearance"]
        inventory_review = {
            "low_stock_alerts": [{
                "sku_id": r["sku_id"], "name": r["name"],
                "coverage_days": r["coverage_days"], "total_coverage_days": r["total_coverage_days"],
                "suggest_replenish_qty": r["qty"], "urgency_score": 80 if r["coverage_days"] < 3 else 60,
                "avg_daily_7d": r["avg_daily_7d"], "sales_volatility": r["sales_volatility"],
                "daily_sales": r["avg_daily_7d"],
            } for r in low_stock_alerts],
            "overstock_alerts": [{
                "sku_id": r["sku_id"], "name": r["name"],
                "total_coverage_days": r["total_coverage_days"],
                "recommended_action": r["strategy"], "pressure_score": 60,
                "daily_sales": r["avg_daily_7d"],
            } for r in overstock_alerts],
            "inventory_health": {
                "low_stock_skus": len(low_stock_alerts),
                "overstock_skus": len(overstock_alerts),
                "healthy_skus": len(sku_metrics) - len(low_stock_alerts) - len(overstock_alerts),
                "avg_total_coverage_days": round(sum(r["total_coverage_days"] for r in inv_results) / max(len(inv_results), 1), 1),
            },
            "recommendations": [r["reasoning"] for r in inv_results if r["action"] != "hold"][:3],
        }
        slow_moving = {"slow_moving_skus": [], "recommendations": []}
        replenishment = {"replenishment_rows": low_stock_alerts, "recommendations": []}
        inventory_management = {}

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

        self._emit_progress("生成行动建议", 7, 8)
        # ── 结构化 Action 整合（SKU 级别）──────────────────────────────────
        action_registry = self._build_action_registry(
            sku_metrics, sales_review, inventory_review,
            slow_moving, replenishment, pricing, category_management
        )
        action_registry = self._resolve_conflicts(action_registry)
        scored_actions = self._prioritize_actions(action_registry)
        structured_actions = self._generate_action_text(scored_actions)

        # 非 SKU 级别的建议（品类、新品企划、LLM 行动要点）
        planning_recs = self._new_planning_action_lines(product_selection)
        category_recs = [r for r in (category_management.get("recommendations") or []) if isinstance(r, str)]
        llm_bullets = []
        if isinstance(sales_review.get("llm_executive_brief"), dict):
            llm_bullets = sales_review["llm_executive_brief"].get("action_bullets", [])

        # 收集被阻止的 SKU，过滤 llm_bullets 中与之矛盾的内容
        blocked_skus = set()
        for sid, entry in action_registry.items():
            if entry.get("blocked_decisions"):
                blocked_skus.add(sid)
        filtered_llm_bullets = [
            b for b in llm_bullets
            if not any(sid in b for sid in blocked_skus)
        ]

        actions = (
            structured_actions
            + [f"【企划】{r}" for r in planning_recs]
            + [f"【品类】{r}" for r in category_recs]
            + [f"【LLM】{b}" for b in filtered_llm_bullets]
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
            "_daily_series": self._build_daily_series(sku_metrics),
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

        self._emit_progress("完成", 8, 8)
        return result

    def _build_daily_series(self, sku_metrics: List[Dict]) -> Dict:
        """从 SKU 的 price_history 聚合出逐日总销量和逐渠道销量序列。"""
        from collections import defaultdict
        daily_totals: Dict[str, int] = defaultdict(int)
        channel_dailies: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        has_history = 0
        for sku in sku_metrics:
            history = sku.get("price_history")
            if not isinstance(history, list):
                continue
            has_history += 1
            ch_sales = sku.get("channel_sales") or {}
            total_ch = sum(ch_sales.values()) or 1
            for record in history:
                if not isinstance(record, dict):
                    continue
                d = record.get("date", "")
                ds = int(record.get("daily_sales") or 0)
                daily_totals[d] += ds
                # 优先使用逐日渠道数据，否则按比例拆分
                ch_daily = record.get("channel_daily")
                if isinstance(ch_daily, dict):
                    for ch_name, ch_val in ch_daily.items():
                        channel_dailies[ch_name][d] += int(ch_val)
                else:
                    for ch_name, ch_val in ch_sales.items():
                        channel_dailies[ch_name][d] += int(ds * ch_val / total_ch)

        # 按日期排序，取最近 14 天
        sorted_dates = sorted(daily_totals.keys())[-14:]
        result = {
            "dates": sorted_dates,
            "total_sales": [daily_totals[d] for d in sorted_dates],
            "channels": {
                ch: [channel_dailies[ch].get(d, 0) for d in sorted_dates]
                for ch in channel_dailies
            },
        }
        print(f"[_build_daily_series] skus={len(sku_metrics)}, with_history={has_history}, dates={len(sorted_dates)}, channels={list(result['channels'].keys())}, sample_total={result['total_sales'][:3]}, sample_live={result['channels'].get('live', [])[:3]}")
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
            ds = int(row.get("daily_sales") or 0)
            stock = int(row.get("stock") or 0)
            out.append(
                f"高退货处置：{label} · 退货率 {rr:.1f}%，日销 {ds} 件，库存 {stock} 件 — "
                f"立即暂停加量推广/投流，启动质检+详情页复核。"
            )
        return out

    def _build_action_registry(self, sku_metrics, sales_review, inventory_review,
                                slow_moving, replenishment, pricing, category_management):
        """按 SKU 聚合所有模块的结构化决策。"""
        from .agents.sales_review_agent import SalesReviewAgent
        registry: Dict[str, Dict] = {}

        for alert in (inventory_review.get("low_stock_alerts") or []):
            sid = alert.get("sku_id")
            if not sid:
                continue
            registry.setdefault(sid, {"decisions": [], "data": {}})
            if alert.get("suggest_replenish_qty", 0) > 0:
                registry[sid]["decisions"].append({
                    "module": "inventory", "type": "replenish",
                    "qty": alert["suggest_replenish_qty"],
                    "urgency": alert.get("urgency_score", 0),
                    "coverage_days": alert.get("coverage_days", 0),
                })

        for alert in (inventory_review.get("overstock_alerts") or []):
            sid = alert.get("sku_id")
            if not sid:
                continue
            registry.setdefault(sid, {"decisions": [], "data": {}})
            registry[sid]["decisions"].append({
                "module": "inventory", "type": "clearance",
                "action": alert.get("recommended_action", "满减促销"),
                "pressure": alert.get("pressure_score", 0),
                "coverage_days": alert.get("total_coverage_days", 0),
                "strategy": alert.get("recommended_action", "满减促销"),
            })

        for r in (pricing.get("pricing_suggestions") or []):
            sid = r.get("sku_id")
            if not sid:
                continue
            cur = r.get("current_price")
            sug = r.get("suggested_price")
            if not cur or not sug or cur == sug:
                continue
            registry.setdefault(sid, {"decisions": [], "data": {}})
            registry[sid]["decisions"].append({
                "module": "pricing", "type": "reprice",
                "from_price": cur, "to_price": sug,
                "strategy": r.get("strategy", ""),
                "role": r.get("role", ""),
                "cost_price": r.get("cost_price", 0),
            })

        for sku in (sales_review.get("high_return_skus") or []):
            sid = sku.get("sku_id")
            if not sid:
                continue
            registry.setdefault(sid, {"decisions": [], "data": {}})
            registry[sid]["decisions"].append({
                "module": "sales_review", "type": "high_return",
                "return_rate_pct": sku.get("return_rate_pct", 0),
            })

        for item in (slow_moving.get("slow_moving_skus") or []):
            sid = item.get("sku_id")
            if not sid:
                continue
            registry.setdefault(sid, {"decisions": [], "data": {}})
            registry[sid]["decisions"].append({
                "module": "slow_moving", "type": "clearance",
                "strategy": item.get("strategy", "满减促销"),
                "stock_age_days": item.get("stock_age_days", 0),
                "coverage_days": 0,
            })

        sku_map = {str(s.get("sku_id", "")): s for s in sku_metrics}
        sku_trends = SalesReviewAgent._compute_sku_trends(sku_metrics)
        for sid in registry:
            s = sku_map.get(sid, {})
            registry[sid]["data"] = {
                "name": s.get("name", ""),
                "daily_sales": s.get("daily_sales", 0),
                "stock": s.get("stock", 0),
                "in_transit": s.get("in_transit", 0),
                "return_rate": float(s.get("return_rate") or 0),
                "trend": sku_trends.get(sid, {}).get("trend", "unknown"),
                "growth_7d_pct": sku_trends.get(sid, {}).get("growth_7d_pct", 0),
                "price": s.get("price", 0),
                "cost_price": s.get("cost_price", 0),
            }
        return registry

    def _resolve_conflicts(self, registry: Dict) -> Dict:
        """检测并解决同一 SKU 的决策冲突。"""
        for sid, entry in registry.items():
            decisions = entry["decisions"]
            data = entry["data"]
            types = {d["type"] for d in decisions}
            stock = data.get("stock", 0)
            in_transit = data.get("in_transit", 0)
            ds = data.get("daily_sales", 0)
            # 用可售库存（不含在途）计算覆盖天数，与库存 Agent 口径一致
            coverage = stock / ds if ds > 0 else 999

            # ── 规则1: 补货 + 去化/清仓 → 看趋势决定 ──
            if "replenish" in types and "clearance" in types:
                if data["trend"] == "declining":
                    decisions[:] = [d for d in decisions if d["type"] != "replenish"]
                    entry["conflict_resolved"] = "趋势下降，取消补货保留清仓"
                else:
                    decisions[:] = [d for d in decisions if d["type"] != "clearance"]
                    entry["conflict_resolved"] = "趋势正常，保留补货取消清仓"

            # ── 规则2: 补货 + 高退货 → 先解决退货再补货 ──
            if "replenish" in types and "high_return" in types:
                for d in decisions:
                    if d["type"] == "replenish":
                        d["condition"] = "待退货率降至8%以下后再执行补货"
                        d["priority_override"] = "deferred"

            # ── 规则3: 非清仓调价 + 清仓 → 清仓优先 ──
            if "reprice" in types and "clearance" in types:
                for d in decisions:
                    if d["type"] == "reprice" and "清仓" not in str(d.get("strategy", "")):
                        d["priority_override"] = "superseded_by_clearance"

            # ── 规则4: 缺货 SKU 不得调价（覆盖 < 3 天不降价，覆盖 < 5 天不涨价）──
            if "reprice" in types and coverage < 5:
                for d in decisions:
                    if d["type"] == "reprice":
                        from_p = float(d.get("from_price") or 0)
                        to_p = float(d.get("to_price") or 0)
                        if to_p < from_p and coverage < 3:
                            d["priority_override"] = "blocked_low_stock"
                            entry.setdefault("conflict_resolved", "")
                            entry["conflict_resolved"] += f"；库存仅覆盖{coverage:.1f}天，阻止降价（缺货不降价）"
                        elif to_p > from_p and coverage < 5:
                            d["priority_override"] = "blocked_low_stock"
                            entry.setdefault("conflict_resolved", "")
                            entry["conflict_resolved"] += f"；库存仅覆盖{coverage:.1f}天，阻止涨价（缺货涨价抑制需求）"

            # ── 规则5: 健康 SKU 不得无依据降价 ──
            if "reprice" in types:
                rr = data.get("return_rate", 0)
                is_healthy = 7 <= coverage <= 45 and data["trend"] != "declining" and rr < 0.08
                if is_healthy:
                    for d in decisions:
                        if d["type"] == "reprice":
                            from_p = float(d.get("from_price") or 0)
                            to_p = float(d.get("to_price") or 0)
                            # 健康 SKU 降价需要有竞品驱动或清仓理由，否则阻止
                            strategy = str(d.get("strategy", "")).lower()
                            is_clearance = "清仓" in strategy or "clearance" in strategy
                            if to_p < from_p and not is_clearance:
                                drop_pct = (from_p - to_p) / from_p
                                if drop_pct < 0.20:  # 降幅 < 20% 且非清仓 → 阻止
                                    d["priority_override"] = "blocked_healthy"
                                    entry.setdefault("conflict_resolved", "")
                                    entry["conflict_resolved"] += "；健康SKU无清仓理由的降价已阻止"

            # ── 规则6: 高退货触发下架评估时，取消同 SKU 的定价/满减建议 ──
            if "high_return" in types:
                hr_severe = any(d.get("return_rate_pct", 0) >= 12 for d in decisions if d["type"] == "high_return")
                if hr_severe:
                    for d in decisions:
                        if d["type"] in ("reprice", "clearance"):
                            d["priority_override"] = "blocked_pending_diagnosis"
                            entry.setdefault("conflict_resolved", "")
                            if "待P0诊断完成" not in entry.get("conflict_resolved", ""):
                                entry["conflict_resolved"] += "；退货率≥12%待P0诊断，暂停定价/促销动作"

        return registry

    def _prioritize_actions(self, registry: Dict) -> List[Dict]:
        """基于数据计算优先级分数。被阻止的决策移入 blocked 列表不参与排序。"""
        scored: List[Dict] = []
        blocked: List[Dict] = []
        BLOCKED_OVERRIDES = ("superseded_by_clearance", "blocked_low_stock", "blocked_healthy", "blocked_pending_diagnosis")
        for sid, entry in registry.items():
            data = entry["data"]
            for d in entry["decisions"]:
                override = d.get("priority_override", "")
                if override in BLOCKED_OVERRIDES:
                    blocked.append({"sku_id": sid, "decision": d, "data": data, "block_reason": override})
                    continue
                score = 0.0
                if d["type"] == "high_return" and d.get("return_rate_pct", 0) >= 12:
                    score = 95
                elif d["type"] == "high_return":
                    score = 85
                elif d["type"] == "replenish" and d.get("priority_override") == "deferred":
                    score = 40
                elif d["type"] == "replenish" and d.get("urgency", 0) >= 80:
                    score = 90
                elif d["type"] == "replenish":
                    score = 70 + float(d.get("urgency", 0)) * 0.2
                elif d["type"] == "reprice":
                    score = 60
                elif d["type"] == "clearance":
                    score = 50 + float(d.get("pressure", 0)) * 0.3
                scored.append({
                    "sku_id": sid, "decision": d, "data": data,
                    "score": score, "conflict_note": entry.get("conflict_resolved"),
                })
        scored.sort(key=lambda x: -x["score"])
        # 将 blocked 决策从 registry 中移除，防止其他模块误读
        for item in blocked:
            sid = item["sku_id"]
            if sid in registry:
                registry[sid]["decisions"] = [
                    d for d in registry[sid]["decisions"]
                    if d.get("priority_override", "") not in BLOCKED_OVERRIDES
                ]
                registry[sid].setdefault("blocked_decisions", []).append(item["decision"])
        return scored

    def _generate_action_text(self, scored_actions: List[Dict]) -> List[str]:
        """从结构化决策生成 action 文本，含依赖关系标注。"""
        actions: List[str] = []

        # 建立 SKU→Action 类型索引，用于关联标注
        sku_types: Dict[str, List[str]] = {}
        for item in scored_actions:
            sid = item["sku_id"]
            sku_types.setdefault(sid, []).append(item["decision"]["type"])

        for item in scored_actions[:20]:
            d = item["decision"]
            data = item["data"]
            sid = item["sku_id"]
            label = f"{sid} {data['name']}"

            # 关联 Action 标注
            related = [t for t in sku_types.get(sid, []) if t != d["type"]]
            related_str = "、".join(f"{t}({sid})" for t in related[:3]) if related else "无"

            if d["type"] == "high_return":
                text = (
                    f"高退货处置：{label} · 退货率 {d['return_rate_pct']}%，"
                    f"日销 {data['daily_sales']} 件，库存 {data['stock']} 件 — 立即暂停推广，启动质检。"
                    f"\n【后置影响】若诊断结果=下架 → 取消该SKU所有后续Action"
                    f"\n【取消触发】诊断=材质问题且无法修复"
                    f"\n【关联】{related_str}"
                )
            elif d["type"] == "replenish":
                condition = d.get("condition", "库存低于补货点")
                text = f"补货：{label}，可售 {d['coverage_days']} 天，建议补 {d['qty']} 件。"
                text += f"\n【前置条件】{condition}"
                if data["trend"] == "declining":
                    text += f"\n【风险】近7天趋势下降{data['growth_7d_pct']:+.1f}%，需确认需求侧无问题"
                text += f"\n【取消触发】趋势持续declining超14天 / 高退货处置=下架"
                text += f"\n【关联】{related_str}"
            elif d["type"] == "reprice":
                cost = float(d.get("cost_price") or 0)
                to_price = float(d.get("to_price") or 0)
                from_price = float(d.get("from_price") or 0)
                margin = round((to_price - cost) / to_price * 100, 1) if to_price > 0 and cost > 0 else 0
                drop_pct = round(abs(to_price - from_price) / from_price * 100, 1) if from_price > 0 else 0
                text = (
                    f"定价建议：{label} ¥{int(from_price)} → ¥{int(to_price)}（{d.get('strategy', '')}），"
                    f"降幅 {drop_pct}%，调价后毛利率 {margin}%，成本 ¥{int(cost)}。"
                    f"\n【前置条件】高退货处置未触发或诊断≠下架；缺货已解除（coverage≥3天）"
                    f"\n【取消触发】高退货处置=下架 / 竞品降价致毛利低于底线"
                    f"\n【关联】{related_str}"
                )
            elif d["type"] == "clearance":
                text = (
                    f"去化：{label}，库存覆盖 {d.get('coverage_days', '?')} 天，建议 {d.get('strategy', '满减促销')}。"
                    f"\n【前置条件】库存覆盖>{self.overstock_days}天或转化率低于阈值"
                    f"\n【取消触发】销量突然提升 / 高退货处置=下架"
                    f"\n【关联】{related_str}"
                )
            else:
                continue

            if item.get("conflict_note"):
                text += f"\n【冲突解决】{item['conflict_note']}"
            actions.append(text)
        return actions

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
            intel = self._market_intel_for_new_product(pseudo, prices, products)
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

    def _market_intel_for_new_product(self, pseudo: Dict, prices: List[float], products: List[Dict]) -> Dict:
        """新品企划的市场情报（简化版，不走完整定价 Agent）。"""
        from .agents.pricing_tools import PricingToolExecutor
        executor = PricingToolExecutor(pseudo, prices, products)
        summary = executor.execute("get_competitor_summary", {"sku_id": pseudo.get("name", "")})
        margin = self._target_gross_margin or 0.45
        sweet = summary.get("sweet_spot")
        median = summary.get("median")
        reference = sweet or median
        implied_cost = round(reference * (1 - margin)) if reference else None
        return {
            "competitor_summary": summary,
            "market_intel": {
                "reference_band": f"¥{summary.get('p25', '?')}-¥{summary.get('p75', '?')}",
                "sweet_spot": sweet,
                "implied_cost_ceiling": implied_cost,
                "disclaimer": "企划参考价，非锁价",
            },
            "pricing_stage": "market_intel",
        }

    def _run_pricing_v2(self, sku_metrics: List[Dict], experiences: List[Dict]) -> Dict:
        """Tool-based 定价：LLM Agent 通过 function calling 逐 SKU 决策。"""
        from .agents.pricing_agent_v2 import PricingAgentV2

        agent = PricingAgentV2(self.llm_client, use_llm=True)
        results: List[Dict] = []
        total_skus = len(sku_metrics)

        for idx, sku in enumerate(sku_metrics):
            self._emit_progress(f"定价分析 ({idx+1}/{total_skus})", 4, 8)
            sku_id = str(sku.get("sku_id", "")).strip()

            # 获取竞品数据
            uploaded = self._uploaded_competitor_map.get(sku_id)
            if uploaded is None and sku.get("name"):
                uploaded = self._uploaded_competitor_map.get(str(sku.get("name", "")))

            if uploaded:
                competitor_prices = [float(p.get("price") or 0) for p in uploaded if float(p.get("price") or 0) > 0]
                competitor_products = uploaded
            else:
                competitor_prices = []
                competitor_products = []

            try:
                result = agent.analyze_sku(sku, competitor_prices, competitor_products, experiences)
            except Exception as e:
                print(f"[pricing_v2] SKU {sku_id} failed: {e}")
                result = {
                    "sku_id": sku_id,
                    "name": sku.get("name", ""),
                    "current_price": sku.get("price", 0),
                    "cost_price": sku.get("cost_price", 0),
                    "suggested_price": sku.get("price", 0),
                    "strategy": "hold",
                    "reasoning": f"Agent 调用失败: {e}",
                    "action": "hold",
                    "competitor_summary": {},
                }
            results.append(result)

        skus_with_data = [r for r in results if r.get("competitor_summary", {}).get("sample_count", 0) > 0]
        return {
            "pricing_suggestions": results,
            "summary": {
                "total_skus": len(results),
                "skus_with_competitor_data": len(skus_with_data),
                "data_source": "uploaded" if self._uploaded_competitor_map else "mock",
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
