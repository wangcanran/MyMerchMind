"""L1：YAML 场景 + 期望集合断言。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.scenario_loader import build_orchestrator_from_scenario, load_scenario_yaml


FIXTURES = ROOT / "benchmark" / "fixtures" / "scenarios"


def _ids_in_low_stock(report: dict) -> set:
    rows = report.get("inventory_review", {}).get("low_stock_alerts") or []
    return {r["sku_id"] for r in rows}


def _ids_in_overstock(report: dict) -> set:
    rows = report.get("inventory_review", {}).get("overstock_alerts") or []
    return {r["sku_id"] for r in rows}


def _ids_in_slow_moving(report: dict) -> set:
    rows = report.get("slow_moving", {}).get("slow_moving_skus") or []
    return {r["sku_id"] for r in rows}


def _ids_in_high_return(report: dict) -> set:
    rows = report.get("sales_review", {}).get("high_return_skus") or []
    return {r["sku_id"] for r in rows}


def _apply_expect(name: str, expect: dict, report: dict) -> None:
    for key, must in (expect or {}).items():
        if key == "low_stock_must_include":
            got = _ids_in_low_stock(report)
            for sku in must:
                assert sku in got, f"[{name}] low_stock 缺少期望 SKU {sku}，当前 {got}"
        elif key == "overstock_must_include":
            got = _ids_in_overstock(report)
            for sku in must:
                assert sku in got, f"[{name}] overstock 缺少期望 SKU {sku}，当前 {got}"
        elif key == "slow_moving_must_include":
            got = _ids_in_slow_moving(report)
            for sku in must:
                assert sku in got, f"[{name}] slow_moving 缺少期望 SKU {sku}，当前 {got}"
        elif key == "high_return_must_include":
            got = _ids_in_high_return(report)
            for sku in must:
                assert sku in got, f"[{name}] high_return 缺少期望 SKU {sku}，当前 {got}"
        elif key == "actions_should_contain_substr":
            actions = report.get("actions") or []
            blob = "\n".join(actions)
            for sub in must:
                assert sub in blob, f"[{name}] actions 未包含子串 {sub!r}"


@pytest.mark.parametrize(
    "yaml_name",
    [p.name for p in sorted(FIXTURES.glob("*.yaml"))],
)
def test_scenario_yaml_matches_expect(yaml_name: str) -> None:
    path = FIXTURES / yaml_name
    scenario = load_scenario_yaml(path)
    name = str(scenario.get("id", path.stem))
    orch, _ = build_orchestrator_from_scenario(scenario)
    report = orch.run()
    _apply_expect(name, scenario.get("expect") or {}, report)
