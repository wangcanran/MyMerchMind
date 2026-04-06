"""模拟 ERP/OMS 数据源"""
import random
from typing import Dict, Optional


class MockERPData:
    """模拟服装企业 ERP 数据"""

    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed)
        self.skus = self._generate_mock_skus()

    def _generate_mock_skus(self) -> Dict[str, Dict]:
        """生成模拟 SKU 数据"""
        colors = ["黑色", "白色", "米色", "咖啡色", "深棕色"]
        styles = ["连衣裙", "衬衫", "T恤", "外套", "裤子"]

        skus: Dict[str, Dict] = {}
        for i in range(20):
            sku_id = f"SKU{1001 + i}"
            skus[sku_id] = {
                "name": f"{self._rng.choice(colors)}{self._rng.choice(styles)}",
                "daily_sales": self._rng.randint(5, 50),
                "stock": self._rng.randint(50, 500),
                "in_transit": self._rng.randint(0, 200),
                "return_rate": round(self._rng.uniform(0.01, 0.15), 3),
            }
        return skus
