"""采集器 CSV 导入离线测试（不依赖网络）。"""
from pathlib import Path
import json
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = PROJECT_ROOT / "ecommerce_agent" / "collectors" / "samples"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_shop_csv_to_json_matches_loader() -> None:
    from ecommerce_agent.collectors.csv_imports import import_shop_skus_csv
    from ecommerce_agent.data.file_loaders import load_erp_skus_from_json

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "erp.json"
        import_shop_skus_csv(SAMPLES / "shop_sample.csv", out)
        skus = load_erp_skus_from_json(out)
        assert "SKU3001" in skus
        assert skus["SKU3001"]["daily_sales"] == 12


def test_trends_competitors_supply_triples_tags_csv() -> None:
    from ecommerce_agent.collectors.csv_imports import (
        import_competitors_csv,
        import_openkg_style_triples_csv,
        import_supply_chain_csv,
        import_tags_csv,
        import_trends_csv,
    )

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        import_trends_csv(SAMPLES / "trends_sample.csv", td_path / "t.json")
        troot = json.loads((td_path / "t.json").read_text(encoding="utf-8"))
        assert len(troot["trends"]) >= 1

        import_competitors_csv(SAMPLES / "competitors_sample.csv", td_path / "c.json")
        crows = json.loads((td_path / "c.json").read_text(encoding="utf-8"))["rows"]
        assert crows[0]["category_key"] == "连衣裙"

        import_supply_chain_csv(SAMPLES / "supply_sample.csv", td_path / "s.json")
        sup = json.loads((td_path / "s.json").read_text(encoding="utf-8"))["suppliers"]
        assert sup[0]["moq"] == 100

        import_openkg_style_triples_csv(SAMPLES / "triples_sample.csv", td_path / "k.json")
        tr = json.loads((td_path / "k.json").read_text(encoding="utf-8"))["triples"]
        assert any(x["subject"] == "新中式穿搭" for x in tr)

        import_tags_csv(SAMPLES / "tags_sample.csv", td_path / "g.json")
        tags = json.loads((td_path / "g.json").read_text(encoding="utf-8"))["tags"]
        assert tags["SKU3001"]["collar"] == "方领"


def test_federation_package() -> None:
    from ecommerce_agent.collectors.federated_package import package_for_federation

    with tempfile.TemporaryDirectory() as td:
        comp = Path(td) / "c.json"
        comp.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "category_key": "连衣裙",
                            "competitor_new_skus_30d": 10,
                            "price_band": "100-200",
                            "ours_new_skus_30d": 5,
                            "gap_note": "敏感文案不应出现在联邦包",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        out = Path(td) / "fed.json"
        package_for_federation(comp, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["format"] == "federation_aggregate_v1"
        assert "敏感" not in out.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_shop_csv_to_json_matches_loader()
    test_trends_competitors_supply_triples_tags_csv()
    test_federation_package()
    print("test_collectors_csv: ok")
