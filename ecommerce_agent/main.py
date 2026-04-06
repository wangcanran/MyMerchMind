"""Baseline demo CLI 入口。"""
import argparse
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

    lines: List[str] = []
    lines.append("# 电商运营 Agent Baseline Demo 报告")
    lines.append("")

    lines.append("## === DEMO CONTEXT ===")
    lines.append(f"- 日期：{context['as_of']}")
    lines.append(f"- 随机种子：{context['seed']}")
    lines.append(f"- SKU 数量：{context['sku_count']}")
    lines.append(f"- 趋势数量：{context['trend_count']}")
    lines.append("")

    lines.append("## === SALES REVIEW (P0) ===")
    lines.append(f"- 总日销量：{sales['summary']['total_daily_sales']} 件")
    lines.append(f"- 平均退货率：{sales['summary']['avg_return_rate_pct']:.2f}%")
    lines.append(f"- 当前最热趋势：{sales['summary']['top_trend']}")
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

    lines.append("## === INVENTORY WARNINGS (P1) ===")
    lines.append("### 低库存预警")
    low_lines = _format_inventory_lines(inventory["low_stock_alerts"], mode="low")
    lines.extend(low_lines if low_lines else ["- 暂无低库存预警"])
    lines.append("")

    lines.append("### 高库存预警")
    over_lines = _format_inventory_lines(inventory["overstock_alerts"], mode="over")
    lines.extend(over_lines if over_lines else ["- 暂无高库存预警"])
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
    parser.add_argument("--replenishment-cycle", type=int, default=7, help="补货周期（天）")
    parser.add_argument("--overstock-days", type=int, default=45, help="高库存阈值（总覆盖天数）")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[1] / "demo_report.md"),
        help="Markdown 报告输出路径",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    orchestrator = DemoOrchestrator(
        seed=args.seed,
        top_n=args.top_n,
        as_of=args.as_of,
        replenishment_cycle_days=args.replenishment_cycle,
        overstock_days=args.overstock_days,
    )
    report = orchestrator.run()
    markdown = build_markdown_report(report)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    print(markdown)
    print(f"报告已输出：{output_path}")
    if not args.demo:
        print("提示：你可以添加 --demo 参数作为统一演示命令。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
