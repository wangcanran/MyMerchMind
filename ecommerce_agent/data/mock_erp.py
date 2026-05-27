"""模拟 ERP/OMS 数据源"""
import random
from datetime import date, timedelta
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

    # 各品类的售价区间（元）与成本率区间
    _CATEGORY_PRICE = {
        "连衣裙": (99, 299),
        "衬衫":   (89, 199),
        "T恤":    (59, 139),
        "外套":   (199, 499),
        "裤子":   (99, 259),
    }
    _COST_RATIO = (0.30, 0.55)  # 成本 / 售价

    def _mock_price(self, style: str) -> int:
        lo, hi = self._CATEGORY_PRICE.get(style, (79, 299))
        raw = self._rng.randint(lo, hi)
        # 对齐到 9 结尾（更像真实定价，如 99/199/299）
        return max(lo, round(raw / 10) * 10 - 1)

    def _generate_mock_skus(self) -> Dict[str, Dict]:
        """生成模拟 SKU 数据"""
        colors = ["黑色", "白色", "米色", "咖啡色", "深棕色"]
        styles = ["连衣裙", "衬衫", "T恤", "外套", "裤子"]

        skus: Dict[str, Dict] = {}
        for i in range(20):
            sku_id = f"SKU{1001 + i}"
            style = self._rng.choice(styles)
            daily_sales = self._rng.randint(5, 50)
            channel = self._split_channel_daily(daily_sales)
            conversion = round(self._rng.uniform(0.003, 0.028), 4)
            stock_age = self._rng.randint(12, 95)
            prior_factor_w = round(self._rng.uniform(0.85, 1.12), 3)
            prior_factor_m = round(self._rng.uniform(0.9, 1.15), 3)
            week_units = int(daily_sales * 7 * prior_factor_w)
            month_units = int(daily_sales * 30 * prior_factor_m)
            price = self._mock_price(style)
            cost_ratio = round(self._rng.uniform(*self._COST_RATIO), 3)
            cost_price = max(1, round(price * cost_ratio))

            skus[sku_id] = {
                "name": f"{self._rng.choice(colors)}{style}",
                "price": price,
                "cost_price": cost_price,
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
                "price_history": self._generate_price_history(price, daily_sales),
            }
        return skus

    def _generate_price_history(
        self, current_price: int, base_daily_sales: int, days: int = 30
    ) -> List[Dict]:
        """生成近 N 天的价格-销量历史记录。

        模拟真实场景：价格偶尔调整，销量随价格变动有弹性反应。
        """
        history: List[Dict] = []
        today = date.today()
        price = current_price

        # 模拟 2-4 次调价事件
        change_days = sorted(self._rng.sample(range(5, days), k=min(3, days - 5)))

        for d in range(days, 0, -1):
            day_date = today - timedelta(days=d)

            # 在调价日变更价格（±5%~12%）
            if d in change_days:
                direction = self._rng.choice([-1, 1])
                pct = self._rng.uniform(0.05, 0.12)
                price = max(
                    int(current_price * 0.7),
                    min(int(current_price * 1.3), int(price * (1 + direction * pct))),
                )

            # 销量受价格弹性影响：价格越高于基准，销量越低
            price_ratio = price / current_price if current_price > 0 else 1.0
            elasticity_effect = max(0.3, min(2.0, 1.0 / (price_ratio ** 1.8)))
            noise = self._rng.uniform(0.7, 1.3)
            daily_sales = max(1, int(base_daily_sales * elasticity_effect * noise))

            history.append({
                "date": day_date.isoformat(),
                "price": price,
                "daily_sales": daily_sales,
            })

        # 最后一天回到当前价
        history.append({
            "date": today.isoformat(),
            "price": current_price,
            "daily_sales": base_daily_sales,
        })
        return history


class StaticERPData:
    """固定 SKU 表，供 benchmark 注入；字段与 `MockERPData.skus` 条目一致。"""

    def __init__(self, skus: Dict[str, Dict]):
        self.skus = {k: dict(v) for k, v in skus.items()}
