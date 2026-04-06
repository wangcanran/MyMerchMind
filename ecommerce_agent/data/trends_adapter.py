"""趋势数据适配层"""
from typing import Dict, List, Optional
from .mock_trends import MockTrendsData


class TrendsAdapter:
    """统一的趋势数据访问接口"""

    def __init__(self, seed: Optional[int] = None):
        self.data_source = MockTrendsData(seed=seed)

    def get_top_trends(self, limit: int = 10) -> List[Dict]:
        """获取热度最高的趋势"""
        return self.data_source.trends[:limit]

    def get_growing_trends(self, limit: int = 5) -> List[Dict]:
        """获取增长最快的趋势"""
        growing = [t for t in self.data_source.trends if t["growth_rate"] > 0.2]
        return sorted(growing, key=lambda x: x["growth_rate"], reverse=True)[:limit]
