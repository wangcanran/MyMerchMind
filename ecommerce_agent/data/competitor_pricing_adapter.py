
from typing import List

class CompetitorPricingAPI:
    """
    一个模拟的API，用于获取竞品价格。
    """

    def get_competitor_prices(self, product_id: str) -> List[float]:
        """
        根据产品ID获取竞品价格列表。
        在实际应用中，这里会调用外部API。
        """
        # 基于product_id的哈希生成可复现的随机价格
        seed = hash(product_id)
        num_competitors = (seed % 5) + 3  # 3 to 7 competitors
        base_price = (seed % 100) + 50  # 50 to 149

        prices = []
        for i in range(num_competitors):
            price = base_price + ((seed * i) % 20) - 10
            prices.append(round(price, 2))

        return prices
