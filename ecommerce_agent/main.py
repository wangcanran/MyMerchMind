"""Baseline demo CLI 入口。"""
import argparse
import os
from datetime import date
from pathlib import Path
from typing import Dict, List

from .orchestrator import DemoOrchestrator


def _format_sku_lines(items: List[Dict]) -> List[str]:
    lines: List[str] = []
    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. {item['sku_id']} {item['name']} | 日销 {item['daily_sales']} | "
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
    category_mgmt = report.get("category_management", {})
    slow = report.get("slow_moving", {})
    replen = report.get("replenishment", {})
    memory_snap = report.get("memory_snapshot", {})

    lines: List[str] = []
    lines.append("# 电商运营 Agent Baseline Demo 报告")
    lines.append("")

    lines.append("## === DEMO CONTEXT ===")
    lines.append(f"- 日期：{context['as_of']}")
    lines.append(f"- 随机种子：{context['seed']}")
    lines.append(f"- SKU 数量：{context['sku_count']}")
    lines.append(f"- 趋势数量：{context['trend_count']}")
    if context.get("sku_scenario"):
        lines.append(f"- SKU 场景：{context.get('sku_scenario')}")
    lines.append(f"- LLM 补充：{'开启' if context.get('llm_enabled') else '关闭'}")
    if context.get("llm_scope") and context.get("llm_enabled"):
        lines.append(f"- LLM 范围：{context.get('llm_scope')}")
    if context.get("llm_notice"):
        lines.append(f"- LLM 提示：{context['llm_notice']}")
    if context.get("category_mapping_notice"):
        lines.append(f"- 类目映射提示：{context['category_mapping_notice']}")
    if context.get("experience_memory_notice"):
        lines.append(f"- 经验库提示：{context['experience_memory_notice']}")
    lines.append("")

    lines.append("## === PRODUCT SELECTION (M2) ===")
    if selection.get("trend_picks"):
        pick = selection["trend_picks"][0]
        mm = pick.get("merch_mapping", {})
        lines.append(f"- 主趋势：{pick.get('keyword', 'N/A')}")
        lines.append(f"- 映射说明：{mm.get('story', '')}")
        moq = pick.get("moq", {})
        lines.append(
            f"- 首单区间：{moq.get('suggested_range_pcs', [])} | 风险：{moq.get('risk_level', '')}"
        )
        gaps = pick.get("competitor_gaps") or []
        if gaps:
            lines.append("- 竞品缺口：")
            for g in gaps[:3]:
                lines.append(
                    f"  - {g.get('category_key')}：竞品上新 {g.get('competitor_new_skus_30d')} vs 我方 {g.get('ours_new_skus_30d')} | {g.get('gap_note', '')}"
                )
    else:
        lines.append("- 暂无选品输出")
    if selection.get("llm_error"):
        lines.append(f"- LLM 补充失败：{selection['llm_error']}")
    lines.append("")

    lines.append("## === CATEGORY MANAGEMENT (M2.0) ===")
    cs = category_mgmt.get("category_summary") or {}
    if cs:
        lines.append(f"- 品类数：{cs.get('category_count', 0)}")
        lines.append(f"- 销量贡献 Top 品类：{cs.get('top_category_by_sales', '')}")
        if cs.get("mapping_enabled"):
            lines.append(
                f"- 类目映射命中：{cs.get('mapping_hit_skus', 0)}/{cs.get('sku_total', 0)} "
                f"({cs.get('mapping_hit_rate_pct', 0)}%)"
            )
    ck = category_mgmt.get("category_kpis") or []
    if ck:
        lines.append("")
        lines.append("### 品类 KPI（Top）")
        for i, row in enumerate(ck[:3], 1):
            lines.append(
                f"{i}. {row.get('category', '')} | SKU {row.get('sku_count', 0)} | "
                f"日销 {row.get('total_daily_sales', 0)} | 覆盖 {row.get('est_stock_coverage_days', 0)} 天 | "
                f"退货 {row.get('avg_return_rate_pct', 0)}%"
            )
    ca = category_mgmt.get("category_actions") or []
    if ca:
        lines.append("")
        lines.append("### 品类动作")
        for i, a in enumerate(ca[:3], 1):
            lines.append(f"{i}. {a.get('category', '')} — {a.get('action_type', '')}：{a.get('reason', '')}")
    decisions = category_mgmt.get("decisions") or {}
    if isinstance(decisions, dict) and decisions:
        lines.append("")
        lines.append("### 决策卡片")
        for key in ("audit_existing", "retire", "evaluate_new"):
            card = decisions.get(key)
            if not isinstance(card, dict):
                continue
            lines.append(f"- {card.get('decision_type', key)}：{card.get('description', '')}")
            note = card.get("llm_note")
            if isinstance(note, str) and note.strip():
                lines.append(f"  提示：{note.strip()}")
            if key == "audit_existing":
                results = card.get("results")
                if isinstance(results, list) and results:
                    for j, r in enumerate(results[:2], 1):
                        if not isinstance(r, dict):
                            continue
                        eg = r.get("experience_guardrail") if isinstance(r.get("experience_guardrail"), dict) else {}
                        hit = int(eg.get("hit_count", 0)) if isinstance(eg, dict) else 0
                        rc = eg.get("root_causes", []) if isinstance(eg, dict) else []
                        rc_s = " / ".join([str(x) for x in rc[:2] if str(x).strip()]) if isinstance(rc, list) else ""
                        suffix = f" | 经验命中 {hit}" + (f"（{rc_s}）" if rc_s else "") if hit else ""
                        lines.append(f"  {j}. {r.get('category', '')} | 状态 {r.get('status', '')}{suffix}")
                        if hit:
                            acts = eg.get("guardrail_actions", []) if isinstance(eg, dict) else []
                            if isinstance(acts, list) and acts:
                                top_act = acts[0] if isinstance(acts[0], dict) else {}
                                if isinstance(top_act, dict) and str(top_act.get("action", "")).strip():
                                    lines.append(
                                        f"     - 经验动作：{top_act.get('action')}（{top_act.get('owner', '')}）"
                                    )
            cands = card.get("candidates")
            if isinstance(cands, list) and cands:
                for j, c in enumerate(cands[:2], 1):
                    if not isinstance(c, dict):
                        continue
                    if key == "evaluate_new":
                        m = c.get("match") if isinstance(c.get("match"), dict) else {}
                        mt = m.get("match_type", "")
                        dec = c.get("decision", "")
                        lines.append(
                            f"  {j}. {c.get('category', '')} | 决策 {dec} | 匹配 {mt} | "
                            f"预算建议 {c.get('proposed_budget_share_pct', '')}%"
                        )
                    elif key == "retire":
                        reason = str(c.get("reason", "")).strip()
                        impacted = c.get("impacted_skus_count", "")
                        eg = c.get("experience_guardrail") if isinstance(c.get("experience_guardrail"), dict) else {}
                        hit = int(eg.get("hit_count", 0)) if isinstance(eg, dict) else 0
                        suffix = f" | 经验命中 {hit}" if hit else ""
                        lines.append(
                            f"  {j}. {c.get('category', '')} | 影响 SKU {impacted}{suffix} | {reason}"
                        )
                        if hit:
                            checks = eg.get("guardrail_checks", []) if isinstance(eg, dict) else []
                            if isinstance(checks, list) and checks:
                                lines.append(f"     - 经验检查：{str(checks[0]).strip()}")
            ec = card.get("experience_candidates")
            if isinstance(ec, list) and ec:
                lines.append(f"  - 负样本候选：{len(ec)} 条")
    ln = category_mgmt.get("llm_notes") or {}
    if isinstance(ln, dict):
        checklist = ln.get("execution_checklist")
        if isinstance(checklist, list) and checklist:
            lines.append("")
            lines.append("### LLM 执行清单")
            for i, it in enumerate(checklist[:6], 1):
                s = str(it).strip()
                if s:
                    lines.append(f"{i}. {s}")
    if category_mgmt.get("llm_error"):
        lines.append(f"- LLM 补充失败：{category_mgmt['llm_error']}")
    scenarios = category_mgmt.get("strategy_scenarios") or []
    if isinstance(scenarios, list) and scenarios:
        lines.append("")
        lines.append("### 受约束策略方案（LLM）")
        for i, s in enumerate(scenarios[:3], 1):
            if not isinstance(s, dict):
                continue
            lines.append(f"{i}. {s.get('title', f'方案{i}')}: {s.get('summary', '')}")
            impacts = s.get("expected_impact") if isinstance(s.get("expected_impact"), list) else []
            risks = s.get("risks") if isinstance(s.get("risks"), list) else []
            m7 = s.get("monitor_7d") if isinstance(s.get("monitor_7d"), list) else []
            m30 = s.get("monitor_30d") if isinstance(s.get("monitor_30d"), list) else []
            if impacts:
                lines.append(f"   - 预期影响：{'；'.join([str(x) for x in impacts[:3]])}")
            if risks:
                lines.append(f"   - 主要风险：{'；'.join([str(x) for x in risks[:3]])}")
            if m7:
                lines.append(f"   - 7天监控：{'；'.join([str(x) for x in m7[:3]])}")
            if m30:
                lines.append(f"   - 30天监控：{'；'.join([str(x) for x in m30[:3]])}")
    lines.append("")

    lines.append("## === SALES REVIEW (P0) ===")
    lines.append(f"- 总日销量：{sales['summary']['total_daily_sales']} 件")
    lines.append(f"- 平均退货率：{sales['summary']['avg_return_rate_pct']:.2f}%")
    lines.append(f"- 当前最热趋势：{sales['summary']['top_trend']}")
    brief = sales.get("llm_executive_brief")
    if brief and isinstance(brief, dict):
        lines.append("")
        lines.append("### LLM 经营摘要")
        lines.append(brief.get("executive_summary", "").strip() or "-")
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
    if sales["high_return_skus"]:
        for i, item in enumerate(sales["high_return_skus"], 1):
            lines.append(
                f"{i}. {item['sku_id']} {item['name']} | 日销 {item['daily_sales']} | "
                f"库存 {item['stock']} | 退货率 {item['return_rate_pct']:.1f}%"
            )
    else:
        lines.append("- 暂无高风险 SKU")
    lines.append("")

    lines.append("### 趋势关注")
    if sales["trend_focus"]:
        for i, t in enumerate(sales["trend_focus"], 1):
            lines.append(
                f"{i}. {t['keyword']} ({t['platform']}) | 热度 {t['heat_score']} | 增长 {t['growth_rate_pct']}%"
            )
    else:
        lines.append("- 暂无趋势数据")
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
    lines.append("### 低库存预警")
    low_lines = _format_inventory_lines(inventory["low_stock_alerts"], mode="low")
    lines.extend(low_lines if low_lines else ["- 暂无低库存预警"])
    lines.append("")

    lines.append("### 高库存预警")
    over_lines = _format_inventory_lines(inventory["overstock_alerts"], mode="over")
    lines.extend(over_lines if over_lines else ["- 暂无高库存预警"])
    inv_notes = inventory.get("llm_notes") or {}
    if inv_notes.get("priorities_note"):
        lines.append("")
        lines.append("### LLM 优先级与协作")
        lines.append(inv_notes["priorities_note"])
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
    if replen.get("llm_error"):
        lines.append(f"- LLM 补充失败：{replen['llm_error']}")
    lines.append("")

    lines.append("## === MEMORY (M4.3) ===")
    lines.append(f"- 活跃避雷条数：{memory_snap.get('active_feedback_count', 0)}")
    lines.append(f"- 选品命中 SKU 数：{memory_snap.get('product_selection_hits', 0)}")
    lines.append("")

    lines.append("## === ACTIONS ===")
    if report["actions"]:
        for i, action in enumerate(report["actions"], 1):
            lines.append(f"{i}. {action}")
    else:
        lines.append("- 暂无行动建议")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行电商运营 Agent baseline demo")
    parser.add_argument("--demo", action="store_true", help="运行 demo 模式")
    parser.add_argument("--seed", type=int, default=42, help="随机种子，保证输出可复现")
    parser.add_argument("--top-n", type=int, default=5, help="榜单展示数量")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="报告日期")
    parser.add_argument(
        "--sku-scenario",
        default="default",
        choices=["default", "class_demo"],
        help="SKU 数据场景：default=随机生成；class_demo=课堂演示用固定 SKU 集",
    )
    parser.add_argument("--replenishment-cycle", type=int, default=7, help="补货周期（天）")
    parser.add_argument("--overstock-days", type=int, default=45, help="高库存阈值（总覆盖天数）")
    parser.add_argument(
        "--category-mapping",
        default="",
        help="SKU→品类映射表路径（.json/.csv）；提供后优先按映射归类，未命中再回退关键词规则",
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
        "--llm-scope",
        default="all",
        choices=["all", "category"],
        help="LLM 启用范围：all=所有智能体；category=仅品类管理智能体",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    fb_path = Path(args.feedback_memory) if args.feedback_memory else None
    category_mapping_path = (
        Path(args.category_mapping) if getattr(args, "category_mapping", "").strip() else None
    )

    if getattr(args, "llm_model", "") and args.llm_model.strip():
        os.environ["LLM_MODEL"] = args.llm_model.strip()

    orchestrator = DemoOrchestrator(
        seed=args.seed,
        top_n=args.top_n,
        as_of=args.as_of,
        sku_scenario=args.sku_scenario,
        replenishment_cycle_days=args.replenishment_cycle,
        overstock_days=args.overstock_days,
        feedback_memory_path=fb_path,
        category_mapping_path=category_mapping_path,
        use_llm=args.llm,
        llm_scope=args.llm_scope,
    )
    report = orchestrator.run()
    markdown = build_markdown_report(report)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    print(markdown)
    print(f"报告已输出：{output_path}")
    ctx = report.get("context") or {}
    if ctx.get("llm_notice"):
        print(f"提示：{ctx['llm_notice']}")
    if not args.demo:
        print("提示：你可以添加 --demo 参数作为统一演示命令。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
