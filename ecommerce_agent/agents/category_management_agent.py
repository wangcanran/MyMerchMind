import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..llm import prompts
from ..llm.client import LLMClientError, OpenAICompatChatClient
from ..llm.json_util import parse_json_object


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff\-_]+", "", s)
    return s[:80] or "unknown"


def _is_placeholder_text(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return True
    if t.lower() == "ellipsis":
        return True
    if all(ch in {".", "…"} for ch in t):
        return True
    if "ellipsis" in t.lower():
        return True
    return False


def _clean_text_list(values: object, *, min_items: int = 1) -> List[str]:
    if not isinstance(values, list):
        return []
    out: List[str] = []
    for x in values:
        s = str(x).strip()
        if not s or _is_placeholder_text(s):
            continue
        out.append(s)
    return out if len(out) >= min_items else []


class CategoryManagementAgent:
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
        product_selection: Optional[Dict] = None,
        category_mapping: Optional[Dict[str, str]] = None,
        category_experiences: Optional[List[Dict[str, Any]]] = None,
        top_n: int = 5,
    ) -> Dict:
        category_rows: Dict[str, Dict[str, object]] = {}
        source_totals = {"mapping": 0, "keyword": 0, "unknown": 0}
        exp_counts: Dict[str, int] = {}
        exp_by_category: Dict[str, List[Dict[str, Any]]] = {}
        if isinstance(category_experiences, list) and category_experiences:
            for it in category_experiences:
                if not isinstance(it, dict):
                    continue
                if it.get("status") != "active":
                    continue
                cat = str(it.get("category", "")).strip()
                if not cat:
                    continue
                exp_counts[cat] = exp_counts.get(cat, 0) + 1
                exp_by_category.setdefault(cat, []).append(
                    {
                        "experience_id": str(it.get("experience_id", "")),
                        "type": str(it.get("type", "")),
                        "decision": str(it.get("decision", "")),
                        "root_cause": str(it.get("root_cause", "")),
                        "revisit_conditions": it.get("revisit_conditions", []),
                    }
                )

        total_daily_sales_all = 0
        for item in sku_metrics:
            name = str(item.get("name", ""))
            raw_category, source = self._resolve_category_with_source(item, name, category_mapping)
            category = (raw_category or "").strip() or "其他"
            if source not in source_totals:
                source = "unknown"
            source_totals[source] += 1
            row = category_rows.get(category)
            if row is None:
                row = {
                    "category": category,
                    "sku_count": 0,
                    "total_daily_sales": 0,
                    "total_stock": 0,
                    "total_in_transit": 0,
                    "weighted_return_rate_sum": 0.0,
                    "weighted_conversion_sum": 0.0,
                    "stock_age_sum": 0.0,
                    "weight_sum": 0.0,
                    "sku_ids": [],
                    "source_counts": {},
                    "experience_hit_count": int(exp_counts.get(category, 0)),
                }
                category_rows[category] = row

            daily_sales = int(item.get("daily_sales", 0))
            stock = int(item.get("stock", 0))
            in_transit = int(item.get("in_transit", 0))
            rr = float(item.get("return_rate", 0.0))
            conv = float(item.get("conversion_rate", 0.0))
            stock_age = float(item.get("stock_age_days", 0.0))

            row["sku_count"] = int(row["sku_count"]) + 1
            row["total_daily_sales"] = int(row["total_daily_sales"]) + daily_sales
            row["total_stock"] = int(row["total_stock"]) + stock
            row["total_in_transit"] = int(row["total_in_transit"]) + in_transit
            total_daily_sales_all += daily_sales

            weight = float(max(daily_sales, 1))
            row["weighted_return_rate_sum"] = float(row["weighted_return_rate_sum"]) + rr * weight
            row["weighted_conversion_sum"] = float(row["weighted_conversion_sum"]) + conv * weight
            row["stock_age_sum"] = float(row["stock_age_sum"]) + stock_age * weight
            row["weight_sum"] = float(row["weight_sum"]) + weight

            sku_ids = row["sku_ids"]
            if isinstance(sku_ids, list):
                sku_ids.append(str(item.get("sku_id", "")))
            source_counts = row.get("source_counts")
            if not isinstance(source_counts, dict):
                source_counts = {}
                row["source_counts"] = source_counts
            source_counts[source] = int(source_counts.get(source, 0)) + 1

        kpis: List[Dict[str, object]] = []
        for category, row in category_rows.items():
            total_daily_sales = int(row["total_daily_sales"])
            total_available = int(row["total_stock"]) + int(row["total_in_transit"])
            coverage = total_available / max(total_daily_sales, 1)
            wsum = float(row["weight_sum"]) or 1.0
            avg_rr = float(row["weighted_return_rate_sum"]) / wsum
            avg_conv = float(row["weighted_conversion_sum"]) / wsum
            avg_age = float(row["stock_age_sum"]) / wsum
            share = total_daily_sales / max(total_daily_sales_all, 1)
            kpis.append(
                {
                    "category": category,
                    "sku_count": int(row["sku_count"]),
                    "total_daily_sales": total_daily_sales,
                    "sales_share_pct": round(share * 100, 2),
                    "total_available": total_available,
                    "est_stock_coverage_days": round(coverage, 1),
                    "avg_return_rate_pct": round(avg_rr * 100, 2),
                    "avg_conversion_rate_pct": round(avg_conv * 100, 3),
                    "avg_stock_age_days": round(avg_age, 1),
                    "sku_source_counts": row.get("source_counts") if isinstance(row.get("source_counts"), dict) else {},
                    "experience_hit_count": int(row.get("experience_hit_count", 0)),
                }
            )

        kpis_sorted = sorted(kpis, key=lambda x: (-int(x.get("total_daily_sales", 0)), str(x.get("category", ""))))
        top_kpis = kpis_sorted[: max(1, int(top_n))]

        category_summary = {
            "category_count": len(kpis_sorted),
            "top_category_by_sales": str(top_kpis[0]["category"]) if top_kpis else "",
            "sku_total": len(sku_metrics),
            "mapping_enabled": bool(isinstance(category_mapping, dict) and category_mapping),
            "sku_source_totals": source_totals,
            "mapping_hit_skus": int(source_totals.get("mapping", 0)),
            "mapping_hit_rate_pct": round(
                (float(source_totals.get("mapping", 0)) / max(len(sku_metrics), 1)) * 100.0,
                2,
            ),
            "active_category_experiences": int(sum(exp_counts.values())),
        }

        decision_thresholds = {
            "high_coverage_days": 45.0,
            "medium_coverage_days": 30.0,
            "low_sales_share_pct": 10.0,
            "high_return_rate_pct": 12.0,
            "keep_sales_share_pct": 10.0,
        }

        portfolio_decisions: List[Dict[str, object]] = []
        for row in kpis_sorted:
            cat = str(row.get("category", ""))
            cov = float(row.get("est_stock_coverage_days", 0.0))
            share_pct = float(row.get("sales_share_pct", 0.0))
            rr_pct = float(row.get("avg_return_rate_pct", 0.0))
            status = "maintain"
            if cov >= float(decision_thresholds["high_coverage_days"]):
                status = "reduce"
            if share_pct <= float(decision_thresholds["low_sales_share_pct"]) and cov >= float(
                decision_thresholds["medium_coverage_days"]
            ):
                status = "retire_candidate"
            if share_pct >= 25.0 and cov < float(decision_thresholds["medium_coverage_days"]) and rr_pct < float(
                decision_thresholds["high_return_rate_pct"]
            ):
                status = "invest"
            exp_hits = exp_by_category.get(cat, [])
            exp_root_causes = [
                str(x.get("root_cause", "")).strip()
                for x in exp_hits
                if isinstance(x, dict) and str(x.get("root_cause", "")).strip()
            ]
            exp_revisit = []
            for x in exp_hits:
                if not isinstance(x, dict):
                    continue
                rcs = x.get("revisit_conditions")
                if not isinstance(rcs, list):
                    continue
                for rc in rcs:
                    if not isinstance(rc, dict):
                        continue
                    d = str(rc.get("description", "")).strip()
                    if d:
                        exp_revisit.append(d)
            exp_revisit = list(dict.fromkeys(exp_revisit))[:3]
            exp_guardrail = None
            if exp_hits:
                exp_guardrail = {
                    "hit_count": len(exp_hits),
                    "root_causes": list(dict.fromkeys(exp_root_causes))[:3],
                    "revisit_conditions": exp_revisit,
                    "note": "命中过往负样本经验，建议优先按经验约束执行复核/去化/延后引入。",
                }
                playbook = self._derive_guardrail_playbook(
                    category=cat,
                    kpis=row,
                    thresholds=decision_thresholds,
                    guardrail=exp_guardrail,
                )
                if playbook:
                    exp_guardrail.update(playbook)
                if status == "maintain":
                    share_gate = float(decision_thresholds["keep_sales_share_pct"])
                    if cov >= float(decision_thresholds["medium_coverage_days"]) and share_pct <= share_gate:
                        status = "retire_candidate"
            portfolio_decisions.append(
                {
                    "category": cat,
                    "status": status,
                    "kpis": row,
                    "impacted_skus": list(category_rows.get(cat, {}).get("sku_ids", [])),
                    "experience_guardrail": exp_guardrail,
                    "experience_hits": exp_hits[:3],
                }
            )

        retire_candidates = [d for d in portfolio_decisions if d.get("status") == "retire_candidate"]
        retire_candidates = sorted(
            retire_candidates,
            key=lambda d: (
                -int(((d.get("experience_guardrail") or {}) if isinstance(d.get("experience_guardrail"), dict) else {}).get("hit_count", 0)),
                -float((((d.get("kpis") or {}) if isinstance(d.get("kpis"), dict) else {}).get("est_stock_coverage_days", 0.0))),
            ),
        )

        def _top_by(key: str, reverse: bool) -> Optional[Dict[str, object]]:
            if not kpis_sorted:
                return None
            return sorted(kpis_sorted, key=lambda x: float(x.get(key, 0.0)), reverse=reverse)[0]

        actions: List[Dict[str, object]] = []
        worst_cov = _top_by("est_stock_coverage_days", reverse=True)
        worst_rr = _top_by("avg_return_rate_pct", reverse=True)
        top_sales = _top_by("total_daily_sales", reverse=True)
        if worst_cov is not None:
            cat = str(worst_cov.get("category", ""))
            actions.append(
                {
                    "category": cat,
                    "action_type": "reduce_stock_risk",
                    "reason": "覆盖天数偏高，建议结合促销/调价/渠道分配做去化并暂停补货。",
                    "impacted_skus": list(category_rows.get(cat, {}).get("sku_ids", [])),
                }
            )
        if worst_rr is not None:
            cat = str(worst_rr.get("category", ""))
            actions.append(
                {
                    "category": cat,
                    "action_type": "investigate_returns",
                    "reason": "退货率偏高，建议核查尺码/面料/描述与质检，并针对性优化详情页与售后。",
                    "impacted_skus": list(category_rows.get(cat, {}).get("sku_ids", [])),
                }
            )
        if retire_candidates:
            first = retire_candidates[0]
            actions.append(
                {
                    "category": str(first.get("category", "")),
                    "action_type": "deprioritize",
                    "reason": "销量占比偏低且库存覆盖偏高，建议收紧上新与资源投入，优先消化库存并评估下架清退。",
                    "impacted_skus": list(first.get("impacted_skus", [])),
                }
            )
        if top_sales is not None:
            cat = str(top_sales.get("category", ""))
            actions.append(
                {
                    "category": cat,
                    "action_type": "keep_and_invest",
                    "reason": "销量贡献最高，建议优先补位上新、加大投放与库存保障。",
                    "impacted_skus": list(category_rows.get(cat, {}).get("sku_ids", [])),
                }
            )

        new_product_decisions: List[Dict[str, object]] = []
        suggested_categories = self._collect_suggested_categories(product_selection)
        overstock_cats = [
            r
            for r in kpis_sorted
            if float(r.get("est_stock_coverage_days", 0.0)) >= float(decision_thresholds["high_coverage_days"])
        ]
        conservative = bool(len(overstock_cats) >= 2 or len(retire_candidates) >= 1)
        try:
            picks = product_selection.get("trend_picks") if isinstance(product_selection, dict) else None
            if isinstance(picks, list) and picks:
                moq = picks[0].get("moq") if isinstance(picks[0], dict) else None
                risk_level = moq.get("risk_level") if isinstance(moq, dict) else ""
                if isinstance(risk_level, str) and ("高" in risk_level or "high" in risk_level.lower()):
                    conservative = True
        except Exception:
            pass

        experience_candidates: List[Dict[str, object]] = []
        for cat in sorted(suggested_categories):
            base = self._find_kpi_row(kpis_sorted, cat)
            match_type = "strict" if base else "none"
            current_share = float(base.get("sales_share_pct", 0.0)) if base else 0.0
            keep_share = float(decision_thresholds["keep_sales_share_pct"])
            total_daily_sales = float(base.get("total_daily_sales", 0.0)) if base else 0.0
            meets_sales = bool(current_share >= keep_share or total_daily_sales >= 30.0)

            decision = "approve_new"
            reason = "来自选品智能体的趋势/竞品缺口映射建议，优先在该品类上新补位。"
            if match_type == "strict" and meets_sales:
                decision = "keep_selling"
                reason = "店铺内已有相似品类且销售达标，建议继续售卖并可做小幅结构与资源微调。"
            elif match_type == "strict" and not meets_sales:
                decision = "adjust_or_retire"
                reason = "店铺内已有相似品类但销售未达标，建议先做优化或清退验证，再决定是否上新扩充。"
            elif match_type == "none" and conservative:
                decision = "defer_new"
                reason = "当前库存/结构压力偏高，建议延后引入新类目，优先消化库存并观察信号变化。"

            target_share = min(max(current_share + 5.0, 10.0), 35.0)
            new_product_decisions.append(
                {
                    "category": cat,
                    "match": {
                        "match_type": match_type,
                        "meets_sales": meets_sales,
                        "current_sales_share_pct": round(current_share, 2),
                        "current_total_daily_sales": int(total_daily_sales),
                    },
                    "decision": decision,
                    "reason": reason,
                    "proposed_budget_share_pct": round(target_share, 1),
                    "validation": {
                        "next_7d_sales_uplift_pct_target": 5.0,
                        "next_30d_return_rate_pct_cap": 12.0,
                    },
                }
            )
            if decision in {"defer_new", "adjust_or_retire"}:
                experience_candidates.append(
                    {
                        "experience_id": f"exp_{_slug(cat)}_{decision}",
                        "type": "negative",
                        "category": cat,
                        "trigger_conditions": {
                            "store_match_type": match_type,
                            "conservative_mode": conservative,
                            "sales_share_pct": round(current_share, 2),
                            "coverage_pressure": len(overstock_cats),
                        },
                        "decision": "不选品" if decision == "defer_new" else "谨慎上新",
                        "root_cause": "库存压力/结构风险" if decision == "defer_new" else "同类目未达标",
                        "revisit_conditions": [
                            {
                                "description": "库存覆盖天数回落或清退完成",
                                "trigger_signals": ["高库存品类数量下降", "清退候选品类执行完成"],
                                "suggested_strategy": "再评估该品类上新节奏与预算",
                            }
                        ],
                        "status": "active",
                    }
                )

        recommendations: List[str] = []
        if top_kpis:
            top = top_kpis[0]
            recommendations.append(
                f"品类优先级：{top['category']} 贡献最高日销（{top['total_daily_sales']}），建议优先补位上新与资源投入。"
            )
        if actions:
            first = actions[0]
            recommendations.append(f"品类动作建议：对 {first['category']} 启动 {first['action_type']}，原因：{first['reason']}")
        if not recommendations:
            recommendations.append("当前品类结构无明显异常，可保持现有节奏并持续监控。")

        decisions = self._build_decision_cards(
            portfolio_decisions=portfolio_decisions,
            retire_candidates=retire_candidates,
            new_product_decisions=new_product_decisions,
            experience_candidates=experience_candidates,
            thresholds=decision_thresholds,
            top_n=top_n,
        )

        data_source = "mock"
        llm_notes: Optional[Dict[str, object]] = None
        strategy_scenarios: List[Dict[str, object]] = []
        llm_error: Optional[str] = None
        if self._use_llm and self._llm is not None:
            try:
                hard_constraints = self._build_hard_constraints(
                    thresholds=decision_thresholds,
                    decisions=decisions,
                    top_kpis=top_kpis,
                )
                payload = {
                    "category_summary": category_summary,
                    "category_kpis": top_kpis,
                    "thresholds": decision_thresholds,
                    "decisions": decisions,
                    "experience_candidates": experience_candidates,
                    "hard_constraints": hard_constraints,
                }
                user_msg = prompts.CATEGORY_MANAGEMENT_USER.format(
                    payload=json.dumps(payload, ensure_ascii=False),
                )
                messages = [
                    {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
                    {"role": "user", "content": user_msg},
                ]
                raw: Optional[str] = None
                parsed: Optional[Dict[str, Any]] = None
                last_err: Optional[Exception] = None
                for attempt in range(3):
                    try:
                        try:
                            raw = self._llm.chat(
                                messages,
                                temperature=0.0,
                                response_format={"type": "json_object"},
                            )
                        except TypeError:
                            raw = self._llm.chat(
                                messages,
                                temperature=0.0,
                            )
                        parsed = parse_json_object(raw)
                        break
                    except (LLMClientError, ValueError, TypeError) as e:
                        last_err = e
                        if attempt == 0:
                            messages = [
                                {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
                                {
                                    "role": "user",
                                    "content": (
                                        "请严格只输出一个 JSON 对象（必须以 { 开头，以 } 结尾），"
                                        "不要包含任何解释文字、编号、Markdown。字段必须包含："
                                        "card_notes / execution_checklist / strategy_scenarios。\n\n"
                                        + user_msg
                                    ),
                                },
                            ]
                            continue
                        if attempt == 1:
                            skeleton = (
                                '{"card_notes":{"audit_existing":"","retire":"","evaluate_new":""},'
                                '"execution_checklist":[""],'
                                '"strategy_scenarios":['
                                '{"title":"方案A 保守去化","summary":"","expected_impact":[""],"risks":[""],"monitor_7d":[""],"monitor_30d":[""]},'
                                '{"title":"方案B 结构优化","summary":"","expected_impact":[""],"risks":[""],"monitor_7d":[""],"monitor_30d":[""]},'
                                '{"title":"方案C 延后上新观察","summary":"","expected_impact":[""],"risks":[""],"monitor_7d":[""],"monitor_30d":[""]}'
                                "]}"
                            )
                            messages = [
                                {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
                                {
                                    "role": "user",
                                    "content": (
                                        "请直接输出严格 JSON（第一个字符为 {，最后一个字符为 }），不要输出任何解释/编号/Markdown。\n"
                                        "必须遵守 hard_constraints（stop_replenishment 的品类不能补货）。\n"
                                        "按下方 JSON 模板填充内容（保留键名与结构不变，只替换值；中文；card_notes 每段 60-160 字）：\n"
                                        f"{skeleton}\n\n"
                                        "参考数据：\n"
                                        + json.dumps(payload, ensure_ascii=False)
                                    ),
                                },
                            ]
                            continue
                        raise
                if parsed is None:
                    raise last_err or ValueError("LLM 输出解析失败")
                card_notes = parsed.get("card_notes")
                checklist = parsed.get("execution_checklist")
                strategy_raw = parsed.get("strategy_scenarios")
                if not isinstance(card_notes, dict):
                    raise ValueError("缺少 card_notes")
                if not isinstance(checklist, list):
                    checklist = []

                default_card_notes = {
                    "audit_existing": (
                        "按销量占比、库存覆盖与退货率盘点：高贡献且覆盖低的品类优先加码备货；"
                        "覆盖偏高或退货偏高的品类优先去化与质检复核，避免新增库存风险。"
                    ),
                    "retire": (
                        "对清退候选先冻结补货并制定去化节奏（折扣/调拨/下架），7天看动销与覆盖回落，"
                        "30天看周转与退货是否回到阈值内，再决定是否继续清退。"
                    ),
                    "evaluate_new": (
                        "新品在预算范围内小步验证，优先投向已有达标品类；若触发库存压力或退货上限则延后上新，"
                        "以7天/30天指标复盘后再放量。"
                    ),
                }

                cleaned_card_notes: Dict[str, str] = {}
                for k in ("audit_existing", "retire", "evaluate_new"):
                    v = card_notes.get(k)
                    s = v.strip() if isinstance(v, str) else ""
                    cleaned_card_notes[k] = (
                        default_card_notes[k] if not s or _is_placeholder_text(s) else s
                    )

                cleaned_checklist = _clean_text_list(checklist, min_items=1)
                if not cleaned_checklist:
                    cleaned_checklist = [
                        "确认 stop_replenishment 品类并冻结补货（避免越界）。",
                        "为高覆盖/低贡献品类制定去化节奏（折扣/调拨/下架），明确负责人。",
                        "7天复盘：动销率、库存覆盖天数、退货率是否改善。",
                        "30天复盘：库存周转、GMV贡献与毛利影响，决定继续/收缩/清退。",
                    ]

                strategy_scenarios = self._normalize_strategy_scenarios(strategy_raw, hard_constraints=hard_constraints)
                llm_notes = {
                    "card_notes": cleaned_card_notes,
                    "execution_checklist": cleaned_checklist,
                }
                for k in ("audit_existing", "retire", "evaluate_new"):
                    note = cleaned_card_notes.get(k)
                    if isinstance(note, str) and note.strip() and not _is_placeholder_text(note) and isinstance(decisions.get(k), dict):
                        decisions[k]["llm_note"] = note.strip()
                data_source = "hybrid"
            except (LLMClientError, ValueError, TypeError) as e:
                llm_error = str(e)
                if isinstance(raw, str) and raw.strip():
                    preview = raw.strip().replace("\n", " ")
                    llm_error = f"{llm_error} | raw_preview={preview[:160]}"

        return {
            "category_summary": category_summary,
            "category_kpis": top_kpis,
            "category_actions": actions[: max(1, int(top_n))],
            "decisions": decisions,
            "thresholds": decision_thresholds,
            "experience_candidates": experience_candidates[: max(1, int(top_n))] if experience_candidates else [],
            "experience_candidates_all": experience_candidates,
            "recommendations": recommendations,
            "data_source": data_source,
            "llm_notes": llm_notes,
            "strategy_scenarios": strategy_scenarios,
            "llm_error": llm_error,
        }

    def _build_hard_constraints(
        self,
        *,
        thresholds: Dict[str, float],
        decisions: Dict[str, object],
        top_kpis: List[Dict[str, object]],
    ) -> Dict[str, object]:
        stop_replenish_categories: List[str] = []
        try:
            retire = decisions.get("retire") if isinstance(decisions, dict) else None
            cands = retire.get("candidates") if isinstance(retire, dict) else None
            if isinstance(cands, list):
                for c in cands:
                    if not isinstance(c, dict):
                        continue
                    cat = str(c.get("category", "")).strip()
                    if cat:
                        stop_replenish_categories.append(cat)
        except Exception:
            pass
        budget = []
        for row in top_kpis[:3]:
            if not isinstance(row, dict):
                continue
            budget.append(
                {
                    "category": str(row.get("category", "")).strip(),
                    "suggest_budget_share_pct_range": [10, 35],
                }
            )
        return {
            "budget_share_pct_range": [10, 35],
            "inventory_pressure_threshold_days": float(thresholds.get("medium_coverage_days", 30.0)),
            "return_rate_cap_pct": float(thresholds.get("high_return_rate_pct", 12.0)),
            "stop_replenishment_categories": list(dict.fromkeys(stop_replenish_categories)),
            "category_budget_ranges": budget,
        }

    def _normalize_strategy_scenarios(
        self,
        value: object,
        *,
        hard_constraints: Dict[str, object],
    ) -> List[Dict[str, object]]:
        desired = ["方案A 保守去化", "方案B 结构优化", "方案C 延后上新观察"]
        stop_cats = hard_constraints.get("stop_replenishment_categories")
        forbidden = "、".join([str(x) for x in stop_cats if str(x).strip()]) if isinstance(stop_cats, list) else ""
        base_default = {
            "方案A 保守去化": {
                "summary": "在库存与退货约束下优先去化，避免新增补货压力。",
                "expected_impact": ["库存覆盖天数下降", "现金回收速度提升"],
                "risks": ["毛利率短期承压", "促销节奏不当会影响品牌感知"],
                "monitor_7d": ["去化SKU动销率", "折扣活动转化率"],
                "monitor_30d": ["库存周转天数", "清退品类GMV贡献"],
            },
            "方案B 结构优化": {
                "summary": "在不突破退货与库存阈值前提下优化SKU结构与内容质量。",
                "expected_impact": ["高退货SKU占比下降", "转化漏斗效率改善"],
                "risks": ["改版成本增加", "结构调整周期较长"],
                "monitor_7d": ["详情页点击到加购转化", "负反馈标签占比"],
                "monitor_30d": ["品类退货率", "SKU层级转化率"],
            },
            "方案C 延后上新观察": {
                "summary": "对高压品类先延后上新，通过观察窗口确认信号后再决策。",
                "expected_impact": ["避免新增库存风险", "集中资源处理存量问题"],
                "risks": ["错失短期趋势窗口", "竞争对手上新速度更快"],
                "monitor_7d": ["高库存品类数量", "清退动作完成率"],
                "monitor_30d": ["库存覆盖是否回落到阈值内", "核心品类销量稳定性"],
            },
        }
        out: List[Dict[str, object]] = []
        rows = value if isinstance(value, list) else []
        by_title: Dict[str, Dict[str, object]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            t = str(row.get("title", "")).strip()
            if t in desired and t not in by_title:
                by_title[t] = row
        for t in desired:
            src = by_title.get(t, {})
            defaults = base_default[t]
            summary = str(src.get("summary", "")).strip() if isinstance(src, dict) else ""
            if not summary or _is_placeholder_text(summary):
                summary = defaults["summary"]
            if forbidden and "补货" in summary:
                summary += f"（约束：{forbidden} 不补货）"

            def _as_list(key: str) -> List[str]:
                raw = src.get(key) if isinstance(src, dict) else None
                if not isinstance(raw, list):
                    return list(defaults[key])
                cleaned = [str(x).strip() for x in raw if str(x).strip() and not _is_placeholder_text(str(x))]
                return cleaned[:4] if cleaned else list(defaults[key])

            out.append(
                {
                    "title": t,
                    "summary": summary,
                    "expected_impact": _as_list("expected_impact"),
                    "risks": _as_list("risks"),
                    "monitor_7d": _as_list("monitor_7d"),
                    "monitor_30d": _as_list("monitor_30d"),
                }
            )
        return out

    def _derive_guardrail_playbook(
        self,
        *,
        category: str,
        kpis: Dict[str, Any],
        thresholds: Dict[str, float],
        guardrail: Dict[str, Any],
    ) -> Dict[str, Any]:
        root_causes = guardrail.get("root_causes")
        if not isinstance(root_causes, list) or not root_causes:
            return {}
        cov = float(kpis.get("est_stock_coverage_days", 0.0))
        share_pct = float(kpis.get("sales_share_pct", 0.0))
        rr_pct = float(kpis.get("avg_return_rate_pct", 0.0))

        actions: List[Dict[str, str]] = []
        checks: List[str] = []

        rc_text = " ".join([str(x) for x in root_causes if str(x).strip()])
        inv_pressure = ("库存" in rc_text) or ("结构" in rc_text) or cov >= float(thresholds.get("medium_coverage_days", 30.0))
        perf_under = share_pct <= float(thresholds.get("keep_sales_share_pct", 10.0))
        return_risk = rr_pct >= float(thresholds.get("high_return_rate_pct", 12.0)) or ("退货" in rc_text) or ("尺码" in rc_text) or ("质检" in rc_text)
        underperform = ("未达标" in rc_text) or ("同类目" in rc_text) or ("转化" in rc_text) or ("低转化" in rc_text)

        if inv_pressure and perf_under:
            actions.extend(
                [
                    {"action": "stop_replenishment", "owner": "供应链/采购"},
                    {"action": "markdown_or_promo", "owner": "运营"},
                    {"action": "consider_delist", "owner": "店铺运营"},
                ]
            )
            checks.extend(
                [
                    f"{category} 覆盖天数回落至 < {int(thresholds.get('medium_coverage_days', 30.0))} 天",
                    "清退/去化动作在 7 天内落地",
                ]
            )
        if return_risk:
            actions.extend(
                [
                    {"action": "return_reason_deep_dive", "owner": "品控/运营"},
                    {"action": "size_chart_and_material_audit", "owner": "运营/质检"},
                ]
            )
            checks.extend(
                [
                    f"30 天退货率 ≤ {float(thresholds.get('high_return_rate_pct', 12.0))}%",
                    "退货语义高频标签下降",
                ]
            )
        if underperform:
            actions.extend(
                [
                    {"action": "conversion_funnel_review", "owner": "运营"},
                    {"action": "price_and_content_test", "owner": "运营/定价"},
                ]
            )
            checks.extend(
                [
                    "转化率 7 天环比提升",
                    "点击-加购-下单漏斗异常点定位完成",
                ]
            )

        revisit = guardrail.get("revisit_conditions")
        if isinstance(revisit, list) and revisit:
            for d in revisit:
                s = str(d).strip()
                if s:
                    checks.append(s)

        dedup_actions: List[Dict[str, str]] = []
        seen = set()
        for a in actions:
            if not isinstance(a, dict):
                continue
            k = str(a.get("action", "")).strip()
            if not k or k in seen:
                continue
            seen.add(k)
            dedup_actions.append({"action": k, "owner": str(a.get("owner", "")).strip()})

        dedup_checks = [s for s in list(dict.fromkeys([str(x).strip() for x in checks])) if s]
        return {"guardrail_actions": dedup_actions[:6], "guardrail_checks": dedup_checks[:8]}

    def _resolve_category_with_source(
        self,
        item: Dict,
        name: str,
        category_mapping: Optional[Dict[str, str]],
    ) -> Tuple[str, str]:
        if isinstance(category_mapping, dict) and category_mapping:
            sku_id = str(item.get("sku_id", "")).strip()
            if sku_id:
                mapped = category_mapping.get(sku_id)
                if isinstance(mapped, str) and mapped.strip():
                    return mapped.strip(), "mapping"
            nm = (name or "").strip()
            if nm:
                mapped = category_mapping.get(nm)
                if isinstance(mapped, str) and mapped.strip():
                    return mapped.strip(), "mapping"
                mapped = category_mapping.get(_slug(nm))
                if isinstance(mapped, str) and mapped.strip():
                    return mapped.strip(), "mapping"
        extracted = self._extract_category(name) or ""
        if extracted:
            return extracted, "keyword"
        return "", "unknown"

    def _resolve_category(
        self,
        item: Dict,
        name: str,
        category_mapping: Optional[Dict[str, str]],
    ) -> str:
        if isinstance(category_mapping, dict) and category_mapping:
            sku_id = str(item.get("sku_id", "")).strip()
            if sku_id:
                mapped = category_mapping.get(sku_id)
                if isinstance(mapped, str) and mapped.strip():
                    return mapped.strip()
            nm = (name or "").strip()
            if nm:
                mapped = category_mapping.get(nm)
                if isinstance(mapped, str) and mapped.strip():
                    return mapped.strip()
                mapped = category_mapping.get(_slug(nm))
                if isinstance(mapped, str) and mapped.strip():
                    return mapped.strip()
        return self._extract_category(name) or ""

    def _extract_category(self, name: str) -> str:
        s = (name or "").strip()
        if not s:
            return ""
        if "连衣裙" in s or ("裙" in s and "半身" not in s):
            return "连衣裙"
        if "衬衫" in s:
            return "衬衫"
        if "T恤" in s or "短袖" in s:
            return "T恤"
        if "外套" in s or "夹克" in s or "风衣" in s or "大衣" in s:
            return "外套"
        if "裤" in s:
            return "裤子"
        return ""

    def _collect_suggested_categories(self, product_selection: Optional[Dict]) -> Set[str]:
        out: Set[str] = set()
        if not isinstance(product_selection, dict):
            return out
        picks = product_selection.get("trend_picks")
        if not isinstance(picks, list):
            return out
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            mm = pick.get("merch_mapping") or {}
            if not isinstance(mm, dict):
                continue
            cats = mm.get("suggested_categories")
            if not isinstance(cats, list):
                continue
            for c in cats:
                raw = str(c).strip()
                if not raw:
                    continue
                norm = self._extract_category(raw) or raw
                out.add(norm)
        return out

    def _find_kpi_row(self, rows: List[Dict[str, object]], category: str) -> Optional[Dict[str, object]]:
        for r in rows:
            if str(r.get("category", "")) == category:
                return r
        return None

    def _build_decision_cards(
        self,
        *,
        portfolio_decisions: List[Dict[str, object]],
        retire_candidates: List[Dict[str, object]],
        new_product_decisions: List[Dict[str, object]],
        experience_candidates: List[Dict[str, object]],
        thresholds: Dict[str, float],
        top_n: int,
    ) -> Dict[str, object]:
        def short_portfolio(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
            out: List[Dict[str, object]] = []
            for r in rows[: max(1, int(top_n))]:
                guard = r.get("experience_guardrail") if isinstance(r.get("experience_guardrail"), dict) else None
                out.append(
                    {
                        "category": r.get("category", ""),
                        "status": r.get("status", ""),
                        "kpis": r.get("kpis", {}),
                        "impacted_skus_count": len(r.get("impacted_skus", []) or []),
                        "experience_guardrail": guard,
                    }
                )
            return out

        audit_existing = {
            "decision_type": "audit_existing",
            "description": "盘点现有品类：按销量占比、库存覆盖、退货率与转化表现给出加码/维持/收缩/清退候选。",
            "thresholds": thresholds,
            "results": short_portfolio(portfolio_decisions),
            "execution_actions": [
                {"action": "adjust_budget", "owner": "品类负责人"},
                {"action": "adjust_listing_plan", "owner": "运营/选品"},
            ],
            "validation_metrics": [
                {"metric": "next_7d_sales_uplift_pct", "direction": "up"},
                {"metric": "inventory_coverage_days", "direction": "down"},
                {"metric": "return_rate_pct", "direction": "down"},
            ],
        }

        retire_rows = retire_candidates[: max(1, int(top_n))]
        retire = {
            "decision_type": "retire",
            "description": "触发淘汰：识别销量占比偏低且覆盖天数偏高的品类/款式，给出清退候选与去化动作。",
            "trigger": {
                "sales_share_pct_le": thresholds.get("low_sales_share_pct", 10.0),
                "coverage_days_ge": thresholds.get("medium_coverage_days", 30.0),
            },
            "candidates": [
                {
                    "category": r.get("category", ""),
                    "reason": (
                        "销量占比偏低且覆盖天数偏高"
                        + (
                            "；经验约束："
                            + " / ".join(
                                [
                                    str(x)
                                    for x in (
                                        (r.get("experience_guardrail") or {})
                                        if isinstance(r.get("experience_guardrail"), dict)
                                        else {}
                                    ).get("root_causes", [])
                                    if str(x).strip()
                                ][:2]
                            )
                            if (
                                isinstance(r.get("experience_guardrail"), dict)
                                and (r.get("experience_guardrail") or {}).get("root_causes")
                            )
                            else ""
                        )
                    ),
                    "impacted_skus_count": len(r.get("impacted_skus", []) or []),
                    "experience_guardrail": r.get("experience_guardrail", None),
                }
                for r in retire_rows
            ],
            "execution_actions": [
                {"action": "stop_replenishment", "owner": "供应链/采购"},
                {"action": "markdown_or_promo", "owner": "运营"},
                {"action": "consider_delist", "owner": "店铺运营"},
            ],
            "validation_metrics": [
                {"metric": "inventory_turnover_improve", "direction": "up"},
                {"metric": "aged_stock_ratio", "direction": "down"},
                {"metric": "cash_recovered", "direction": "up"},
            ],
        }

        evaluate_new = {
            "decision_type": "evaluate_new",
            "description": "评估新品：对比“建议品类”与店铺现有品类表现，按分支决策给出继续售卖/优化清退/延后引入/批准上新的建议。",
            "candidates": new_product_decisions[: max(1, int(top_n))],
            "experience_candidates": experience_candidates[: max(1, int(top_n))] if experience_candidates else [],
            "execution_actions": [
                {"action": "approve_listing", "owner": "品类负责人"},
                {"action": "set_initial_budget", "owner": "品类负责人"},
                {"action": "handoff_to_pricing", "owner": "定价智能体/运营"},
            ],
            "validation_metrics": [
                {"metric": "new_listing_7d_gmv", "direction": "up"},
                {"metric": "new_listing_7d_conversion", "direction": "up"},
                {"metric": "new_listing_30d_return_rate_pct", "direction": "down"},
            ],
        }

        return {
            "audit_existing": audit_existing,
            "retire": retire,
            "evaluate_new": evaluate_new,
        }
