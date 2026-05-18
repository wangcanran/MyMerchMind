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

    def __init__(self, seed: Optional[int] = None, scenario: str = "default"):
        self._rng = random.Random(seed)
        self._scenario = (scenario or "default").strip().lower()
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
        if self._scenario in {"class_demo", "demo"}:
            return self._generate_class_demo_skus()
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

    def _generate_class_demo_skus(self) -> Dict[str, Dict]:
        rows = [
            {
                "sku_id": "SKU2001",
                "name": "深棕色连衣裙",
                "daily_sales": 45,
                "stock": 120,
                "in_transit": 80,
                "return_rate": 0.045,
                "conversion_rate": 0.024,
                "stock_age_days": 18,
                "review_snippets": ["质量很好，版型显瘦", "物流快，包装不错"],
                "channel_sales": {"live": 25, "private": 10, "shelf": 10},
            },
            {
                "sku_id": "SKU2002",
                "name": "米色衬衫",
                "daily_sales": 6,
                "stock": 520,
                "in_transit": 120,
                "return_rate": 0.062,
                "conversion_rate": 0.011,
                "stock_age_days": 78,
                "review_snippets": ["面料容易皱，需要熨烫"],
                "channel_sales": {"live": 1, "private": 1, "shelf": 4},
            },
            {
                "sku_id": "SKU2003",
                "name": "黑色外套",
                "daily_sales": 20,
                "stock": 35,
                "in_transit": 0,
                "return_rate": 0.11,
                "conversion_rate": 0.016,
                "stock_age_days": 35,
                "review_snippets": ["袖口线头有点多"],
                "channel_sales": {"live": 10, "private": 6, "shelf": 4},
            },
            {
                "sku_id": "SKU2004",
                "name": "白色裤子",
                "daily_sales": 16,
                "stock": 280,
                "in_transit": 50,
                "return_rate": 0.145,
                "conversion_rate": 0.009,
                "stock_age_days": 62,
                "review_snippets": ["尺码偏小，建议大一码"],
                "channel_sales": {"live": 8, "private": 2, "shelf": 6},
            },
            {
                "sku_id": "SKU2005",
                "name": "咖啡色T恤",
                "daily_sales": 8,
                "stock": 410,
                "in_transit": 90,
                "return_rate": 0.05,
                "conversion_rate": 0.006,
                "stock_age_days": 92,
                "review_snippets": ["颜色与图片有色差，实物偏暗"],
                "channel_sales": {"live": 2, "private": 1, "shelf": 5},
            },
            {
                "sku_id": "SKU2006",
                "name": "白色连衣裙",
                "daily_sales": 28,
                "stock": 180,
                "in_transit": 40,
                "return_rate": 0.038,
                "conversion_rate": 0.021,
                "stock_age_days": 26,
                "review_snippets": ["质量很好，版型显瘦"],
                "channel_sales": {"live": 18, "private": 3, "shelf": 7},
            },
            {
                "sku_id": "SKU2007",
                "name": "黑色衬衫",
                "daily_sales": 10,
                "stock": 140,
                "in_transit": 20,
                "return_rate": 0.072,
                "conversion_rate": 0.013,
                "stock_age_days": 48,
                "review_snippets": ["面料容易皱，需要熨烫", "物流快，包装不错"],
                "channel_sales": {"live": 5, "private": 2, "shelf": 3},
            },
            {
                "sku_id": "SKU2008",
                "name": "米色外套",
                "daily_sales": 12,
                "stock": 260,
                "in_transit": 0,
                "return_rate": 0.098,
                "conversion_rate": 0.012,
                "stock_age_days": 70,
                "review_snippets": ["颜色与图片有色差，实物偏暗"],
                "channel_sales": {"live": 4, "private": 3, "shelf": 5},
            },
        ]

        skus: Dict[str, Dict] = {}
        for r in rows:
            daily_sales = int(r["daily_sales"])
            prior_factor_w = 0.96
            prior_factor_m = 1.02
            skus[str(r["sku_id"])] = {
                "name": str(r["name"]),
                "daily_sales": daily_sales,
                "stock": int(r["stock"]),
                "in_transit": int(r["in_transit"]),
                "return_rate": float(r["return_rate"]),
                "channel_sales": dict(r["channel_sales"]),
                "conversion_rate": float(r["conversion_rate"]),
                "stock_age_days": int(r["stock_age_days"]),
                "review_snippets": list(r["review_snippets"]),
                "prior_week_total_units": int(daily_sales * 7 * prior_factor_w),
                "prior_month_total_units": int(daily_sales * 30 * prior_factor_m),
            }
        return skus


class StaticERPData:
    """固定 SKU 表，供 benchmark 注入；字段与 `MockERPData.skus` 条目一致。"""

    def __init__(self, skus: Dict[str, Dict]):
        self.skus = {k: dict(v) for k, v in skus.items()}
