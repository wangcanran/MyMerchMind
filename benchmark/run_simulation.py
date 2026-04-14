"""L2：对比 NoOp 与周期 Agent 补货策略，输出 JSON。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.scenario_loader import build_orchestrator_from_scenario, load_scenario_yaml
from benchmark.simulation.inventory_env import compare_policies


def main() -> int:
    parser = argparse.ArgumentParser(description="库存策略仿真实验（noop vs periodic_agent）")
    parser.add_argument(
        "--scenario",
        type=str,
        default=str(ROOT / "benchmark" / "fixtures" / "scenarios" / "minimal_rules.yaml"),
        help="场景 YAML（需含 erp_skus）",
    )
    parser.add_argument("--days", type=int, default=90, help="仿真天数")
    parser.add_argument("--decision-interval", type=int, default=7, help="Agent 决策间隔（天）")
    parser.add_argument("--lead-time", type=int, default=3, help="补货提前期（天）")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="结果 JSON 路径（默认 benchmark/results/sim_comparison.json）",
    )
    args = parser.parse_args()

    scenario_path = Path(args.scenario)
    scenario = load_scenario_yaml(scenario_path)
    orch, _ = build_orchestrator_from_scenario(scenario)
    template = orch.erp_adapter.get_all_skus()

    orch_cfg = scenario.get("orchestrator") or {}
    replenishment_cycle_days = int(orch_cfg.get("replenishment_cycle_days", 7))
    overstock_days = int(orch_cfg.get("overstock_days", 45))

    result = {
        "scenario_id": scenario.get("id", scenario_path.stem),
        "params": {
            "num_days": args.days,
            "decision_interval": args.decision_interval,
            "lead_time_days": args.lead_time,
            "replenishment_cycle_days": replenishment_cycle_days,
            "overstock_days": overstock_days,
        },
        "kpis": compare_policies(
            template,
            num_days=args.days,
            decision_interval=args.decision_interval,
            lead_time_days=args.lead_time,
            replenishment_cycle_days=replenishment_cycle_days,
            overstock_days=overstock_days,
        ),
    }

    out_path = Path(args.output) if args.output else ROOT / "benchmark" / "results" / "sim_comparison.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"已写入：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
