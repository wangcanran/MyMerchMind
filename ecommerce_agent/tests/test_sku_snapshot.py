"""SKU 快照：编排内深拷贝，避免 Agent 串改同一 dict。"""
from ecommerce_agent.data.sku_snapshot import deep_copy_sku_metrics


def test_deep_copy_isolation() -> None:
    rows = [{"sku_id": "A", "price": 100, "nested": {"x": 1}}]
    c = deep_copy_sku_metrics(rows)
    assert c[0]["sku_id"] == "A"
    c[0]["price"] = 999
    c[0]["nested"]["x"] = 2
    assert rows[0]["price"] == 100
    assert rows[0]["nested"]["x"] == 1
