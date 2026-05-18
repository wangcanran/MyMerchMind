"""L2：仿真 KPI 冒烟（周期策略不应劣于 noop 的填充率）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.scenario_loader import build_orchestrator_from_scenario, load_scenario_yaml
from benchmark.simulation.inventory_env import compare_policies


def test_compare_policies_periodic_improves_fill_rate() -> None:
    path = ROOT / "benchmark" / "fixtures" / "scenarios" / "minimal_rules.yaml"
    scenario = load_scenario_yaml(path)
    orch, _ = build_orchestrator_from_scenario(scenario)
    template = orch.erp_adapter.get_all_skus()
    orch_cfg = scenario.get("orchestrator") or {}
    kpis = compare_policies(
        template,
        num_days=60,
        decision_interval=7,
        lead_time_days=3,
        replenishment_cycle_days=int(orch_cfg.get("replenishment_cycle_days", 7)),
        overstock_days=int(orch_cfg.get("overstock_days", 45)),
    )
    assert kpis["periodic_agent"]["fill_rate"] >= kpis["noop"]["fill_rate"]
