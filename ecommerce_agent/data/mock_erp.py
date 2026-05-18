"""模拟 ERP/OMS 数据源"""
import random
from typing import Dict, List, Optional

_REVIEW_POOL = [
    "尺码偏小，建议大一码",
    "颜色与图片有色差，实物偏暗",
    "面料容易皱，需要熨烫",
    "质量很好，版型显瘦",
    "物流快，包装不错",
    "袖口线头有点多",
]


class MockERPData:
    """模拟服装企业 ERP 数据"""

    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed)
        self.skus = self._generate_mock_skus()

    def _split_channel_daily(self, daily_sales: int) -> Dict[str, int]:
        if daily_sales <= 0:
            return {"live": 0, "private": 0, "shelf": 0}
        live = self._rng.randint(0, daily_sales)
        remain = daily_sales - live
        private = self._rng.randint(0, remain) if remain > 0 else 0
        shelf = remain - private
        return {"live": live, "private": private, "shelf": shelf}

    def _pick_reviews(self) -> List[str]:
        n = self._rng.randint(1, 2)
        return [self._rng.choice(_REVIEW_POOL) for _ in range(n)]

    def _generate_mock_skus(self) -> Dict[str, Dict]:
        """生成模拟 SKU 数据"""
        colors = ["黑色", "白色", "米色", "咖啡色", "深棕色"]
        styles = ["连衣裙", "衬衫", "T恤", "外套", "裤子"]

        skus: Dict[str, Dict] = {}
        for i in range(20):
            sku_id = f"SKU{1001 + i}"
            daily_sales = self._rng.randint(5, 50)
            channel = self._split_channel_daily(daily_sales)
            conversion = round(self._rng.uniform(0.003, 0.028), 4)
            stock_age = self._rng.randint(12, 95)
            prior_factor_w = round(self._rng.uniform(0.85, 1.12), 3)
            prior_factor_m = round(self._rng.uniform(0.9, 1.15), 3)
            week_units = int(daily_sales * 7 * prior_factor_w)
            month_units = int(daily_sales * 30 * prior_factor_m)

            skus[sku_id] = {
                "name": f"{self._rng.choice(colors)}{self._rng.choice(styles)}",
                "daily_sales": daily_sales,
                "stock": self._rng.randint(50, 500),
                "in_transit": self._rng.randint(0, 200),
                "return_rate": round(self._rng.uniform(0.01, 0.15), 3),
                "channel_sales": channel,
                "conversion_rate": conversion,
                "stock_age_days": stock_age,
                "review_snippets": self._pick_reviews(),
                "prior_week_total_units": week_units,
                "prior_month_total_units": month_units,
            }
        return skus


class StaticERPData:
    """固定 SKU 表，供 benchmark 注入；字段与 `MockERPData.skus` 条目一致。"""

    def __init__(self, skus: Dict[str, Dict]):
        self.skus = {k: dict(v) for k, v in skus.items()}
