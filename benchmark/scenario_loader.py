"""从 YAML 场景构建 ERP/Trends 与编排器参数。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from ecommerce_agent.data.erp_adapter import ERPAdapter
from ecommerce_agent.data.trends_adapter import TrendsAdapter
from ecommerce_agent.orchestrator import DemoOrchestrator


def _default_channel_split(daily_sales: int) -> Dict[str, int]:
    if daily_sales <= 0:
        return {"live": 0, "private": 0, "shelf": 0}
    third = max(1, daily_sales // 3)
    rest = daily_sales - third * 2
    return {"live": third, "private": third, "shelf": max(0, rest)}


def normalize_sku_row(sku_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """补全单条 SKU 字段，与 `MockERPData._generate_mock_skus` 条目对齐。"""
    daily = int(row.get("daily_sales", 10))
    channel = row.get("channel_sales")
    if not isinstance(channel, dict):
        channel = _default_channel_split(daily)
    snippets = row.get("review_snippets")
    if not isinstance(snippets, list):
        snippets = ["质量很好"]
    pw = row.get("prior_week_total_units")
    pm = row.get("prior_month_total_units")
    if pw is None:
        pw = int(daily * 7)
    if pm is None:
        pm = int(daily * 30)
    return {
        "name": str(row.get("name", sku_id)),
        "daily_sales": daily,
        "stock": int(row.get("stock", 100)),
        "in_transit": int(row.get("in_transit", 0)),
        "return_rate": float(row.get("return_rate", 0.05)),
        "channel_sales": {
            "live": int(channel.get("live", 0)),
            "private": int(channel.get("private", 0)),
            "shelf": int(channel.get("shelf", 0)),
        },
        "conversion_rate": float(row.get("conversion_rate", 0.02)),
        "stock_age_days": int(row.get("stock_age_days", 30)),
        "review_snippets": [str(s) for s in snippets],
        "prior_week_total_units": int(pw),
        "prior_month_total_units": int(pm),
    }


def load_scenario_yaml(path: Path) -> Dict[str, Any]:
    import yaml

    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_orchestrator_from_scenario(
    scenario: Dict[str, Any],
) -> Tuple[DemoOrchestrator, Dict[str, Any]]:
    """
    scenario 结构：
      orchestrator: { seed, top_n, replenishment_cycle_days, overstock_days, as_of, feedback_memory (optional str) }
      erp_skus: { SKUxxx: { ... partial fields } }
      trends: [ { keyword, platform, heat_score, growth_rate, timestamp? } ]
    """
    orch_cfg = scenario.get("orchestrator") or {}
    seed = int(orch_cfg.get("seed", 42))
    top_n = int(orch_cfg.get("top_n", 5))
    as_of = str(orch_cfg.get("as_of", ""))
    replenishment_cycle_days = int(orch_cfg.get("replenishment_cycle_days", 7))
    overstock_days = int(orch_cfg.get("overstock_days", 45))

    fb_raw = orch_cfg.get("feedback_memory")
    fb_path = Path(fb_raw) if fb_raw else None

    raw_skus = scenario.get("erp_skus") or {}
    sku_table: Dict[str, Dict] = {}
    for sku_id, row in raw_skus.items():
        sku_table[str(sku_id)] = normalize_sku_row(str(sku_id), row if isinstance(row, dict) else {})

    if sku_table:
        erp = ERPAdapter(seed=seed, sku_table=sku_table)
    else:
        erp = ERPAdapter(seed=seed)

    raw_trends = scenario.get("trends")
    if raw_trends:
        trends_ad = TrendsAdapter(seed=seed, trends=[dict(t) for t in raw_trends])
    else:
        trends_ad = TrendsAdapter(seed=seed)

    orch = DemoOrchestrator(
        seed=seed,
        top_n=top_n,
        as_of=as_of,
        replenishment_cycle_days=replenishment_cycle_days,
        overstock_days=overstock_days,
        feedback_memory_path=fb_path,
        erp_adapter=erp,
        trends_adapter=trends_ad,
    )
    return orch, scenario


def iter_scenario_files(fixtures_dir: Path) -> List[Path]:
    return sorted(fixtures_dir.glob("*.yaml"))


def load_all_scenarios(fixtures_dir: Path) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    for path in iter_scenario_files(fixtures_dir):
        data = load_scenario_yaml(path)
        sid = str(data.get("id", path.stem))
        out.append((sid, data))
    return out
