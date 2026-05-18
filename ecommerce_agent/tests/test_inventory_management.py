"""库存管理增强逻辑测试。"""
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _sample_rows():
    return [
        {
            "sku_id": "SKU-L1",
            "name": "爆款夹克",
            "daily_sales": 38,
            "stock": 28,
            "in_transit": 12,
            "return_rate": 0.04,
            "channel_sales": {"live": 22, "private": 8, "shelf": 8},
            "conversion_rate": 0.024,
            "stock_age_days": 18,
            "review_snippets": [],
            "prior_week_total_units": 240,
            "prior_month_total_units": 980,
        },
        {
            "sku_id": "SKU-O1",
            "name": "慢销衬衫",
            "daily_sales": 2,
            "stock": 320,
            "in_transit": 60,
            "return_rate": 0.09,
            "channel_sales": {"live": 0, "private": 1, "shelf": 1},
            "conversion_rate": 0.004,
            "stock_age_days": 88,
            "review_snippets": [],
            "prior_week_total_units": 18,
            "prior_month_total_units": 90,
        },
        {
            "sku_id": "SKU-H1",
            "name": "健康T恤",
            "daily_sales": 16,
            "stock": 240,
            "in_transit": 20,
            "return_rate": 0.03,
            "channel_sales": {"live": 5, "private": 5, "shelf": 6},
            "conversion_rate": 0.017,
            "stock_age_days": 26,
            "review_snippets": [],
            "prior_week_total_units": 120,
            "prior_month_total_units": 430,
        },
    ]


def test_inventory_warning_agent_outputs_management_fields() -> None:
    from ecommerce_agent.agents.inventory_warning_agent import InventoryWarningAgent

    report = InventoryWarningAgent().analyze(
        _sample_rows(),
        replenishment_cycle_days=7,
        overstock_days=45,
        limit=5,
    )
    assert report["inventory_health"]["low_stock_skus"] >= 1
    assert report["inventory_health"]["overstock_skus"] >= 1
    assert report["action_queue"], "应生成动作队列"
    first_low = report["low_stock_alerts"][0]
    assert "urgency_score" in first_low
    assert "target_stock_units" in first_low
    first_over = report["overstock_alerts"][0]
    assert "pressure_score" in first_over
    assert "recommended_action" in first_over


def test_inventory_management_agent_builds_summary() -> None:
    from ecommerce_agent.agents.inventory_management_agent import InventoryManagementAgent

    bundle = InventoryManagementAgent().analyze(
        _sample_rows(),
        replenishment_cycle_days=7,
        overstock_days=45,
        limit=5,
    )
    assert bundle["inventory_review"]["inventory_health"]["sku_count"] == 3
    summary = bundle["management_summary"]
    assert summary["action_board"], "应汇总到总控动作板"
    assert "采购" in summary["owner_lane_summary"] or "运营" in summary["owner_lane_summary"]


def test_replenishment_skips_new_po_when_in_transit_covers_target() -> None:
    from ecommerce_agent.agents.replenishment_calculator import ReplenishmentCalculator

    rows = [
        {
            "sku_id": "SKU-X1",
            "name": "测试外套",
            "daily_sales": 12,
            "stock_position": 235,
            "target_stock_units": 134,
            "reorder_point_units": 128,
            "coverage_gap_days": 0.0,
            "urgency_level": "low",
            "suggest_replenish_qty": 0,
        }
    ]
    report = ReplenishmentCalculator().suggest_for_low_stock(rows, limit=3)
    assert report["replenishment_rows"][0]["suggested_order_qty"] == 0
    assert "无需新增采购" in report["replenishment_rows"][0]["order_trigger"]
