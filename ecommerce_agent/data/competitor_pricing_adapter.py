
import json
from pathlib import Path
from typing import List, Dict, Any

class CompetitorPricingAPI:
    """
    一个模拟的API，用于从JSON文件中获取竞品价格。
    """

    def __init__(self, data_path: str = 'ecommerce_agent/data/mock_competitor_prices.json'):
        self.data_path = Path(data_path)
        self.pricing_data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        """从JSON文件加载数据。"""
        if not self.data_path.exists():
            return {}
        with open(self.data_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_competitor_prices(self, product_id: str) -> List[float]:
        """
        根据产品ID从加载的数据中获取竞品价格列表。
        """
        return self.pricing_data.get(product_id, {}).get("prices", [])
