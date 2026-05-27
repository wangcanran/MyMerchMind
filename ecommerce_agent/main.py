"""Baseline demo CLI 入口。"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List

from .orchestrator import DemoOrchestrator
from .report_formatting import (
    build_actions_display,
    dedupe_pricing_llm_exception_lines,
    m2_m3_structure_bridge_note,
    normalize_trend_growth_in_text,
)


def _append_new_product_planning_markdown(lines: List[str], selection: Dict) -> None:
    """新品企划块：放在品类管理（M3）之后，与编排顺序一致。"""
    npp = selection.get("new_product_planning")
    if not isinstance(npp, dict):
        return
    note = str(npp.get("note") or "").strip()
    entries = npp.get("entries")
    if isinstance(entries, list) and entries:
        lines.append("")
        lines.append("## === 新品企划（M3 · approve_new） ===")
        if note:
            lines.append(f"- {note}")
        for i, ent in enumerate(entries, 1):
            if not isinstance(ent, dict):
                continue
            title = str(ent.get("title") or "").strip()
            if not title:
                continue
            q = str(ent.get("competitor_search_query") or "").strip()
            inf = ent.get("intel") if isinstance(ent.get("intel"), dict) else {}
            mi = inf.get("market_intel") if isinstance(inf.get("market_intel"), dict) else {}
            band = mi.get("reference_band")
            sweet = mi.get("sweet_spot")
            ceiling = mi.get("implied_cost_ceiling")
            marg = mi.get("assumed_target_gross_margin")
            parts: List[str] = []
            if band:
                parts.append(f"参考价带 ¥{band}")
            if sweet is not None:
                parts.append(f"甜点锚点约 ¥{sweet}")
            if ceiling is not None:
                try:
                    mstr = f"{float(marg) * 100:.0f}%"
                except (TypeError, ValueError):
                    mstr = "45%"
                parts.append(f"示意成本上限 ¥{ceiling}（目标毛利率 {mstr}）")
            body = " | ".join(parts) if parts else "（暂无有效竞品价样本）"
            lines.append(f"  {i}. {title}：{body}")
            if q:
                lines.append(f"      检索：{q}")
            disc = str(mi.get("disclaimer") or "").strip()
            note_sweet = str(mi.get("sweet_vs_band_note") or "").strip()
            if disc:
                lines.append(f"      （{disc}）")
            if note_sweet:
                lines.append(f"      （{note_sweet}）")
    else:
        items = [str(x).strip() for x in (npp.get("items") or []) if str(x).strip()]
        if items:
            lines.append("")
            lines.append("## === 新品企划（M3 · approve_new） ===")
            if note:
                lines.append(f"- {note}")
            for i, it in enumerate(items, 1):
                lines.append(f"  {i}. {it}")


def _format_sku_lines(items: List[Dict]) -> List[str]:
    lines: List[str] = []
    for i, item in enumerate(items, 1):
        lp = item.get("list_price")
        price_seg = ""
        if isinstance(lp, (int, float)) and not isinstance(lp, bool):
            price_seg = f" | ERP现价 ¥{int(lp)}"
        lines.append(
            f"{i}. {item['sku_id']} {item['name']}{price_seg} | 日销 {item['daily_sales']} | "
            f"库存 {item['stock']} | 退货率 {item['return_rate_pct']:.1f}%"
        )
    return lines


def _format_inventory_lines(items: List[Dict], mode: str) -> List[str]:
    lines: List[str] = []
    for i, item in enumerate(items, 1):
        if mode == "low":
            lines.append(
                f"{i}. {item['sku_id']} {item['name']} | 可售 {item['coverage_days']} 天 | "
                f"建议补货 {item['suggest_replenish_qty']} 件"
            )
        else:
            lines.append(
                f"{i}. {item['sku_id']} {item['name']} | 总覆盖 {item['total_coverage_days']} 天 | "
                f"当前库存 {item['current_stock']} + 在途 {item['in_transit']}"
            )
    return lines


def build_markdown_report(report: Dict) -> str:
    context = report["context"]
    sales = report["sales_review"]
    inventory = report["inventory_review"]
    selection = report.get("product_selection", {})
    slow = report.get("slow_moving", {})
    replen = report.get("replenishment", {})
    inventory_management = report.get("inventory_management", {})
    memory_snap = report.get("memory_snapshot", {})
    top_n_disp = int(context.get("top_n") or 5)
    actions_cap = min(40, max(12, top_n_disp * 4))
    inv_digest = str(inventory_management.get("llm_digest") or "").strip()

    lines: List[str] = []
    lines.append("# 电商运营 Agent Baseline Demo 报告")
    lines.append("")

    lines.append("## === 决策与口径（必读）===")
    lines.append(
        "- **可执行基线**：M3.1「与现售偏差 Top N」、P1 低/高库存、M3.3 补货与 EOQ、各模块规则数值为系统口径，可作为执行起点。"
    )
    lines.append(
        "- **LLM 解读**：经营摘要、行动要点、协同话术等为辅助；若与上项数字或策略冲突，**以规则为准**，"
        "LLM 建议须经业务复核后再执行。"
    )
    lines.append("")

    lines.append("## === DEMO CONTEXT ===")
    lines.append(f"- 日期：{context['as_of']}")
    lines.append(f"- 随机种子：{context['seed']}")
    lines.append(f"- SKU 数量：{context['sku_count']}")
    lines.append(f"- LLM 补充：{'开启' if context.get('llm_enabled') else '关闭'}")
    if context.get("llm_notice"):
        lines.append(f"- LLM 提示：{context['llm_notice']}")
    rules = context.get("reporting_rules")
    if isinstance(rules, dict) and rules:
        lines.append("- 数据一致性口径：")
        for rk, rv in rules.items():
            if isinstance(rv, str) and rv.strip():
                lines.append(f"  - {rk}：{rv.strip()}")
    lines.append("")

    lines.append("## === PRODUCT SELECTION (M2) ===")
    if selection.get("skipped"):
        lines.append("- 未启用选品智能体（使用 --full 启用选品→品类管理联动）。")
    else:
        crit = selection.get("criteria")
        if isinstance(crit, dict) and crit:
            lines.append(f"- 条件：{json.dumps(crit, ensure_ascii=False)}")
        cats = selection.get("suggested_categories")
        if isinstance(cats, list) and cats:
            # 与前端 ReportSections 一致：展示全部建议品类（不再截断为 8 条）
            preview = "、".join([str(x) for x in cats if str(x).strip()])
            lines.append(f"- 建议品类（Top）：{preview}")
        rec = selection.get("recommendation")
        if isinstance(rec, dict):
            cs = rec.get("cross_dimension_summary")
            if isinstance(cs, str) and cs.strip():
                lines.append(f"- 结论摘要：{cs.strip()}")
            conf = rec.get("confidence_score")
            ds = selection.get("data_source")
            if isinstance(conf, (int, float)):
                if isinstance(ds, str) and ds.strip():
                    lines.append(f"- 置信度：{conf} · 数据源：{ds.strip()}")
                else:
                    lines.append(f"- 置信度：{conf}")
        if selection.get("selection_note"):
            lines.append(f"- 说明：{selection['selection_note']}")
        if selection.get("llm_error") and selection.get("data_source") == "llm_parse_fallback":
            detail = str(selection["llm_error"]).strip()
            if len(detail) > 220:
                detail = detail[:220] + "…"
            lines.append(f"- JSON 解析细节：{detail}")
        if selection.get("error"):
            if selection.get("data_source") == "rules_fallback":
                lines.append(f"- 选品降级：{selection.get('error')}")
            else:
                lines.append(f"- 选品失败：{selection.get('error')}")
        if selection.get("llm_error") and selection.get("data_source") not in (
            "rules_fallback",
            "llm_parse_fallback",
        ):
            lines.append(f"- LLM 错误：{selection.get('llm_error')}")
    lines.append("")

    category = report.get("category_management") or {}
    lines.append("## === CATEGORY MANAGEMENT (M3) ===")
    if isinstance(category, dict) and category and not category.get("skipped"):
        bridge = str(category.get("m2_m3_bridge_note") or "").strip()
        if not bridge:
            bridge = m2_m3_structure_bridge_note(selection, category) or ""
        summ = category.get("category_summary") or {}
        if isinstance(summ, dict) and summ:
            lines.append(
                f"- 品类数：{summ.get('category_count', 0)} | SKU 总数：{summ.get('sku_total', 0)} | "
                f"Top 品类：{summ.get('top_category_by_sales', 'N/A')}"
            )
        if bridge:
            lines.append(f"- {bridge}")
        eval_new = ((category.get("decisions") or {}) if isinstance(category.get("decisions"), dict) else {}).get(
            "evaluate_new"
        )
        cand = None
        if isinstance(eval_new, dict):
            cand = eval_new.get("candidates")
        if isinstance(cand, list) and cand:
            lines.append("- 新品评估（示例）：")
            for row in cand[:3]:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    f"  - {row.get('category', 'N/A')}：{row.get('decision', 'N/A')}（{row.get('reason', '')}）"
                )
                br = str(row.get("boundary_rule_hint") or "").strip()
                if br:
                    if len(br) > 180:
                        br = br[:180] + "…"
                    lines.append(f"      边界（规则）：{br}")
                blm = row.get("boundary_llm") if isinstance(row.get("boundary_llm"), dict) else {}
                if blm:
                    bs = str(blm.get("boundary_summary") or "").strip()
                    ac = str(blm.get("alignment_comment") or "").strip()
                    if bs or ac:
                        seg = " ".join(x for x in [bs, ac] if x)
                        if len(seg) > 200:
                            seg = seg[:200] + "…"
                        lines.append(f"      边界（LLM）：{seg}")
        if category.get("boundary_llm_error"):
            lines.append(f"- 品类边界 LLM 错误：{category.get('boundary_llm_error')}")
        if category.get("llm_error"):
            lines.append(f"- LLM 错误：{category.get('llm_error')}")
    else:
        lines.append("- 未启用品类管理联动（使用 --full 启用选品→品类管理联动）。")
    lines.append("")

    _append_new_product_planning_markdown(lines, selection)

    pricing = report.get("pricing") or {}
    lines.append("## === SKU PRICING (M3.1) ===")
    if isinstance(pricing, dict) and not pricing.get("skipped"):
        lines.append("- 在架 SKU：可执行价微调；M3 approve_new 企划向市场情报见上文「新品企划」。")
        summ = pricing.get("summary") or {}
        total = summ.get("total_skus", 0)
        with_data = summ.get("skus_with_competitor_data", 0)
        src = summ.get("data_source", "mock")
        lines.append(f"- SKU 总数：{total} | 有竞品数据：{with_data} | 数据源：{src}")
        sfx = summ.get("competitor_search_suffix")
        if sfx:
            lines.append(
                f"- 企划检索后缀（选品上下文；当前仅对在架 SKU 裸词检索，未附加）：{sfx}"
            )
        suggestions = pricing.get("pricing_suggestions") or []
        if suggestions:
            rows = [r for r in suggestions if isinstance(r, dict)]

            def _price_gap(r: Dict) -> float:
                cur = float(r.get("current_price") or 0)
                sug = float(r.get("suggested_price") or 0)
                if not cur or not sug:
                    return 0.0
                return abs(sug - cur) / cur

            ranked = sorted(rows, key=_price_gap, reverse=True)
            top_slice = ranked[:top_n_disp]
            lines.append(
                f"- 可执行调价（与现售偏差 Top {top_n_disp}；与「ACTIONS」中定价句范围一致；"
                "完整算价见 JSON `pricing.pricing_suggestions`）："
            )
            common_llm, per_llm = dedupe_pricing_llm_exception_lines(top_slice)
            if common_llm:
                lines.append(f"- **定价例外解读（LLM）共性**：{common_llm}")
                lines.append("- **SKU 差异化（LLM）**：")
            for idx, r in enumerate(top_slice):
                sid = str(r.get("sku_id") or "").strip()
                name = str(r.get("name", "N/A")).strip()
                label = f"{sid} {name}".strip() if sid else name
                cur = r.get("current_price")
                sug = r.get("suggested_price")
                pos = r.get("price_position_pct")
                strategy = str(r.get("strategy", ""))
                comp = r.get("competitor_summary") or {}
                sweet = comp.get("sweet_spot")
                cur_s = f"¥{cur}" if cur else "未知"
                sug_s = f"¥{sug}" if sug else "未知"
                sweet_s = f"甜点¥{sweet}" if sweet else ""
                pos_s = f"竞品P{pos:.0f}" if pos is not None else ""
                meta = " | ".join(x for x in [sweet_s, pos_s, strategy] if x)
                lines.append(f"  - {label}：{cur_s} → {sug_s}（{meta}）")
                # LLM 定价理由
                reasoning = str(r.get("reasoning") or "").strip()
                if reasoning:
                    if len(reasoning) > 200:
                        reasoning = reasoning[:200] + "…"
                    lines.append(f"      定价理由：{reasoning}")
                # LLM 分析摘要
                llm_analysis = str(r.get("llm_analysis") or "").strip()
                if llm_analysis:
                    if len(llm_analysis) > 200:
                        llm_analysis = llm_analysis[:200] + "…"
                    lines.append(f"      LLM 分析：{llm_analysis}")
                # LLM 风险提示
                risk_notes = str(r.get("llm_risk_notes") or "").strip()
                if risk_notes:
                    if len(risk_notes) > 160:
                        risk_notes = risk_notes[:160] + "…"
                    lines.append(f"      风险提示：{risk_notes}")
                # 护栏透明度
                guardrail_note = str(r.get("guardrail_note") or "").strip()
                if guardrail_note:
                    lines.append(f"      护栏调整：{guardrail_note}")
                erule = str(r.get("exception_explanation_rule") or "").strip()
                if erule:
                    if len(erule) > 160:
                        erule = erule[:160] + "…"
                    lines.append(f"      定价例外（规则）：{erule}")
                llex_raw = str(r.get("llm_exception_explanation") or "").strip()
                llex = per_llm[idx] if idx < len(per_llm) else llex_raw
                if llex:
                    if len(llex) > 160:
                        llex = llex[:160] + "…"
                    if common_llm:
                        lines.append(f"      - {label}：{llex}")
                    else:
                        lines.append(f"      定价例外解读（LLM）：{llex}")
    else:
        lines.append("- 未启用定价智能体（使用 --full 启用）。")
    lines.append("")

    lines.append("## === SALES REVIEW (P0) ===")
    lines.append(f"- 总日销量：{sales['summary']['total_daily_sales']} 件")
    lines.append(f"- 平均退货率：{sales['summary']['avg_return_rate_pct']:.2f}%")
    gloss = sales.get("segmentation_glossary")
    if isinstance(gloss, dict) and gloss:
        lines.append("- 分段口径（避免畅销/滞销标签打架）：")
        for k, v in gloss.items():
            if isinstance(v, str) and v.strip():
                lines.append(f"  - {k}：{v.strip()}")
    brief = sales.get("llm_executive_brief")
    if brief and isinstance(brief, dict):
        lines.append("")
        lines.append("### LLM 经营摘要")
        lines.append(
            normalize_trend_growth_in_text(brief.get("executive_summary", "").strip()) or "-"
        )
        bullets = brief.get("action_bullets") or []
        if bullets:
            lines.append("")
            lines.append("### LLM 行动要点")
            for i, b in enumerate(bullets, 1):
                lines.append(f"{i}. {b}")
    if sales.get("llm_error"):
        lines.append(f"- LLM 补充失败：{sales['llm_error']}")
    lines.append("")

    lines.append("### 畅销 SKU")
    top_skus = _format_sku_lines(sales["top_skus"])
    lines.extend(top_skus if top_skus else ["- 暂无数据"])
    lines.append("")

    lines.append("### 滞销 SKU")
    lagging_skus = _format_sku_lines(sales["lagging_skus"])
    lines.extend(lagging_skus if lagging_skus else ["- 暂无数据"])
    lines.append("")

    lines.append("### 高退货风险 SKU")
    hr = sales.get("high_return_skus") or []
    hr_lines = _format_sku_lines(hr) if hr else []
    if hr_lines:
        lines.extend(hr_lines)
    else:
        lines.append("- 暂无高风险 SKU")
    lines.append("")

    ch = sales.get("channel_dashboard") or {}
    lines.append("## === CHANNEL REVIEW (M4.1) ===")
    if ch.get("channels"):
        for name, payload in ch["channels"].items():
            lines.append(
                f"- {name}：日均 {payload.get('daily_units', 0)} 件，占比 {payload.get('share_pct', 0)}%"
            )
        lines.append(
            f"- 周预估销量：{ch.get('current_week_est_units', 0)}，上周合计：{ch.get('prior_week_total_units', 0)}，周环比约 {ch.get('week_over_week_pct', 0):+.2f}%"
        )
        lines.append(
            f"- 月预估销量：{ch.get('current_month_est_units', 0)}，上月合计：{ch.get('prior_month_total_units', 0)}，月环比约 {ch.get('month_over_month_pct', 0):+.2f}%"
        )
    else:
        lines.append("- 暂无渠道数据")
    lines.append("")

    rs = sales.get("return_semantics") or {}
    lines.append("## === RETURN SEMANTICS (M4.2) ===")
    if rs.get("top_tags"):
        for tag, cnt in rs["top_tags"]:
            lines.append(f"- {tag}：{cnt} 次")
    else:
        lines.append("- 未命中关键词规则")
    lines.append("")

    lines.append("## === INVENTORY WARNINGS (P1) ===")
    inv_health = inventory.get("inventory_health") or {}
    if inv_health:
        lines.append(
            f"- 库存健康：低库存 {inv_health.get('low_stock_skus', 0)} 个，高库存 {inv_health.get('overstock_skus', 0)} 个，健康 SKU {inv_health.get('healthy_skus', 0)} 个"
        )
        lines.append(
            f"- 覆盖天数：当前均值 {inv_health.get('avg_current_coverage_days', 0)} 天，总库存均值 {inv_health.get('avg_total_coverage_days', 0)} 天"
        )
    lines.append("")
    lines.append("### 低库存预警")
    low_lines = _format_inventory_lines(inventory["low_stock_alerts"], mode="low")
    lines.extend(low_lines if low_lines else ["- 暂无低库存预警"])
    lines.append("")

    lines.append("### 高库存预警")
    over_lines = _format_inventory_lines(inventory["overstock_alerts"], mode="over")
    lines.extend(over_lines if over_lines else ["- 暂无高库存预警"])
    inv_notes = inventory.get("llm_notes") or {}
    if inv_digest:
        lines.append("")
        lines.append(
            "- **LLM 库存协同**：已与「INVENTORY CONTROL BOARD → 管理摘要」合并展示，"
            "此处不再重复 P1 下的「LLM 优先级/补货/去化」分块（避免与看板摘要撞车）。"
        )
    elif inv_notes.get("priorities_note"):
        lines.append("")
        lines.append("### LLM 优先级与协作")
        lines.append(inv_notes["priorities_note"])
    if not inv_digest and inv_notes.get("replenishment_focus"):
        lines.append("")
        lines.append("### LLM 补货关注点")
        lines.append(inv_notes["replenishment_focus"])
    if not inv_digest and inv_notes.get("clearance_focus"):
        lines.append("")
        lines.append("### LLM 去化关注点")
        lines.append(inv_notes["clearance_focus"])
    checklist = inv_notes.get("coordination_checklist") or []
    if not inv_digest and checklist:
        lines.append("")
        lines.append("### 协同清单")
        for i, item in enumerate(checklist, 1):
            lines.append(f"{i}. {item}")
    if inventory.get("llm_error"):
        lines.append(f"- LLM 补充失败：{inventory['llm_error']}")
    lines.append("")

    lines.append("## === SLOW MOVING (M3.2) ===")
    sms = slow.get("slow_moving_skus") or []
    if sms:
        for i, row in enumerate(sms, 1):
            lines.append(
                f"{i}. {row['sku_id']} {row['name']} | 库龄 {row['stock_age_days']} 天 | "
                f"转化 {row['conversion_rate']*100:.2f}% | 策略：{row['strategy']} — {row['reason']}"
            )
    else:
        lines.append("- 暂无滞销命中")
    sm_notes = slow.get("llm_notes") or {}
    if sm_notes.get("coordination_note"):
        lines.append("")
        lines.append("### LLM 清货协同")
        lines.append(sm_notes["coordination_note"])
    if slow.get("llm_error"):
        lines.append(f"- LLM 补充失败：{slow['llm_error']}")
    lines.append("")

    lines.append("## === REPLENISHMENT EOQ (M3.3) ===")
    rlg = ""
    rules = context.get("reporting_rules") if isinstance(context.get("reporting_rules"), dict) else {}
    if isinstance(rules.get("replenishment_qty_legend"), str):
        rlg = str(rules["replenishment_qty_legend"]).strip()
    if rlg:
        lines.append(f"- {rlg}")
    rrows = replen.get("replenishment_rows") or []
    if rrows:
        for i, row in enumerate(rrows, 1):
            eoq = row.get("eoq") or {}
            lines.append(
                f"{i}. {row['sku_id']} {row['name']} | 建议订货 {row.get('suggested_order_qty')} 件 "
                f"(EOQ {eoq.get('eoq_units', 0)})"
            )
    else:
        lines.append("- 暂无低库存可计算 EOQ")
    if replen.get("llm_replenishment_comment"):
        lines.append("")
        lines.append("### LLM 业务解读")
        lines.append(replen["llm_replenishment_comment"])
    repl_notes = replen.get("llm_notes") or {}
    repl_watchouts = repl_notes.get("procurement_watchouts") or []
    if repl_watchouts:
        lines.append("")
        lines.append("### 采购确认点")
        for i, item in enumerate(repl_watchouts, 1):
            lines.append(f"{i}. {item}")
    if replen.get("llm_error"):
        lines.append(f"- LLM 补充失败：{replen['llm_error']}")
    lines.append("")

    lines.append("## === INVENTORY CONTROL BOARD ===")
    board = inventory_management.get("action_board") or []
    if board:
        for i, item in enumerate(board, 1):
            lines.append(
                f"{i}. [{item.get('owner', '未指定')}] {item.get('title', '')} — {item.get('reason', '')}"
            )
    else:
        lines.append("- 暂无管理动作队列")
    if inventory_management.get("llm_digest"):
        lines.append("")
        lines.append("### 管理摘要")
        lines.append(inventory_management["llm_digest"])
    lines.append("")

    lines.append("## === MEMORY (M4.3) ===")
    retrieved_exps = memory_snap.get("retrieved_experiences") or []
    if retrieved_exps:
        lines.append(f"### 本次命中的经验（{len(retrieved_exps)} 条）")
        for idx, exp in enumerate(retrieved_exps, 1):
            title = exp.get("title", "")
            confidence = exp.get("confidence", "")
            score = exp.get("_score", "")
            narrative = exp.get("narrative", "")
            lines.append(f"- [{idx}] [{confidence}] {title}（匹配度 {score}/10）")
            if narrative:
                lines.append(f"  {narrative}")
    else:
        lines.append("- 本次未命中任何经验。积累更多策略反馈后，经验会自动参与决策。")
    exp_store = memory_snap.get("experience_store")
    meta_parts = []
    if exp_store:
        meta_parts.append(f"经验库 {exp_store.get('active', 0)} 条生效")
    if memory_snap.get("active_feedback_count", 0) > 0:
        meta_parts.append(f"避雷记忆 {memory_snap['active_feedback_count']} 条")
    if memory_snap.get("product_selection_hits", 0) > 0:
        meta_parts.append(f"选品命中 {memory_snap['product_selection_hits']} SKU")
    if meta_parts:
        lines.append(f"- {' · '.join(meta_parts)}")
    lines.append("")

    lines.append("## === ACTIONS ===")
    all_actions = report.get("actions") or []
    ad = report.get("actions_display") if isinstance(report.get("actions_display"), dict) else {}
    if not isinstance(ad, dict) or not ad.get("rows"):
        ad = build_actions_display(all_actions, as_of_iso=str(context.get("as_of") or ""))
    if all_actions:
        note = str(ad.get("note") or "").strip()
        if note:
            lines.append(f"- {note}")
        lines.append(
            f"- 矩阵含前 {min(actions_cap, len(all_actions))} 条（共 {len(all_actions)} 条）；"
            "同一优先级内为启发式归类，执行顺序请结合业务日历。"
        )
        lines.append("")
        lines.append("| 优先级 | 负责 | 动作（原文节选） | 建议完成 |")
        lines.append("| --- | --- | --- | --- |")
        rows = ad.get("rows") or []
        shown = 0
        for row in rows:
            if shown >= actions_cap:
                break
            act = str(row.get("action") or "").strip()
            if not act:
                continue
            cell = act.replace("|", "\\|")
            if len(cell) > 120:
                cell = cell[:120] + "…"
            lines.append(
                f"| {row.get('tier', '')} | {row.get('owner', '')} | {cell} | {row.get('due', '')} |"
            )
            shown += 1
        lines.append("")
        lines.append("- 完整原文见 JSON ``actions``（与矩阵逐条对应，按优先级重排）。")
    else:
        lines.append("- 暂无行动建议")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行电商运营 Agent baseline demo")
    parser.add_argument("--demo", action="store_true", help="运行 demo 模式")
    parser.add_argument(
        "--full",
        action="store_true",
        help="启用选品→品类管理→定价联动（默认跳过选品/品类管理/定价，以保证 baseline 可离线运行）",
    )
    parser.add_argument("--seed", type=int, default=42, help="随机种子，保证输出可复现")
    parser.add_argument("--top-n", type=int, default=5, help="榜单展示数量")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="报告日期")
    parser.add_argument("--replenishment-cycle", type=int, default=7, help="补货周期（天）")
    parser.add_argument("--overstock-days", type=int, default=45, help="高库存阈值（总覆盖天数）")
    parser.add_argument(
        "--selection-requirements",
        default="",
        help="选品需求文档路径（md/txt）；为空则使用内置 demo 条件",
    )
    parser.add_argument(
        "--category-mapping",
        default="",
        help="SKU→品类映射文件（.json/.csv），为空则用内置规则抽取",
    )
    parser.add_argument(
        "--feedback-memory",
        default="",
        help="避雷记忆 JSON 路径（默认使用包内 default_feedback_memory.json）",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[1] / "demo_report.md"),
        help="Markdown 报告输出路径",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="启用 LLM 叙事补充（需环境变量 LLM_API_KEY 或 OPENAI_API_KEY；默认关闭以保证输出可复现）",
    )
    parser.add_argument(
        "--llm-model",
        default="",
        help="覆盖 LLM_MODEL 环境变量（仅在与 --llm 同用时生效）",
    )
    parser.add_argument(
        "--target-gross-margin",
        type=float,
        default=None,
        help="企划 market_intel 用目标毛利率：0~1 小数（如 0.45），或 >1 表示百分数（如 40）；缺省 0.45",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    fb_path = Path(args.feedback_memory) if args.feedback_memory else None
    cat_map = Path(args.category_mapping) if args.category_mapping else None
    sel_req = Path(args.selection_requirements) if args.selection_requirements else None

    if getattr(args, "llm_model", "") and args.llm_model.strip():
        os.environ["LLM_MODEL"] = args.llm_model.strip()

    orchestrator = DemoOrchestrator(
        seed=args.seed,
        top_n=args.top_n,
        as_of=args.as_of,
        replenishment_cycle_days=args.replenishment_cycle,
        overstock_days=args.overstock_days,
        feedback_memory_path=fb_path,
        category_mapping_path=cat_map,
        selection_requirements_path=sel_req,
        enable_selection=bool(args.full),
        enable_category_management=bool(args.full),
        enable_pricing=bool(args.full),
        use_llm=args.llm,
        target_gross_margin=args.target_gross_margin,
    )
    report = orchestrator.run()
    markdown = build_markdown_report(report)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    sys.stdout.buffer.write((markdown + "\n").encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()
    print(f"报告已输出：{output_path}")
    ctx = report.get("context") or {}
    if ctx.get("llm_notice"):
        print(f"提示：{ctx['llm_notice']}")
    if not args.demo:
        print("提示：你可以添加 --demo 参数作为统一演示命令。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
