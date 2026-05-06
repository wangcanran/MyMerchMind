"""外部 JSON 数据接入测试。"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = PROJECT_ROOT / "ecommerce_agent" / "data" / "samples"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_load_erp_sample() -> None:
    from ecommerce_agent.data.file_loaders import load_erp_skus_from_json

    skus = load_erp_skus_from_json(SAMPLES / "erp_skus.sample.json")
    assert "SKU2001" in skus
    assert skus["SKU2001"]["daily_sales"] >= 0
    assert "channel_sales" in skus["SKU2001"]


def test_orchestrator_with_file_sources() -> None:
    from ecommerce_agent.config.data_sources import DataSourceSettings
    from ecommerce_agent.orchestrator import DemoOrchestrator

    ds = DataSourceSettings(
        erp_json=SAMPLES / "erp_skus.sample.json",
        trends_json=SAMPLES / "trends.sample.json",
        competitors_json=SAMPLES / "competitors.sample.json",
        tags_json=SAMPLES / "tags.sample.json",
    )
    report = DemoOrchestrator(seed=42, top_n=3, as_of="2026-04-12", data_sources=ds).run()
    ctx = report["context"]
    assert ctx["data_integration"]["erp"] == "file"
    assert ctx["data_integration"]["trends"] == "file"
    assert ctx["sku_count"] == 3
    assert "product_selection" in report


def test_get_rows_for_categories_uses_dynamic_rows() -> None:
    from ecommerce_agent.data.mock_competitors import get_rows_for_categories

    rows = [
        {"category_key": "连衣裙", "gap_note": "a"},
        {"category_key": "裤子", "gap_note": "b"},
    ]
    got = get_rows_for_categories(["连衣裙"], rows)
    assert len(got) == 1
    assert got[0]["category_key"] == "连衣裙"


if __name__ == "__main__":
    test_load_erp_sample()
    test_orchestrator_with_file_sources()
    test_get_rows_for_categories_uses_dynamic_rows()
    print("test_data_integration: ok")
