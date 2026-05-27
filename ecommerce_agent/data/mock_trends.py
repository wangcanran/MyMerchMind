"""演示用趋势词数据源（仅供选品降级等内部逻辑，不作为真实社媒展示）。"""
from datetime import datetime, timedelta
import random
from typing import Dict, List, Optional


class MockTrendsData:
    """演示用随机趋势词（仅内部/选品降级；不当作真实社媒数据展示）。"""

    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed)
        self.trends = self._generate_mock_trends()

    def _generate_mock_trends(self) -> List[Dict]:
        """生成模拟趋势数据"""
        trend_keywords = [
            "多巴胺穿搭", "静奢风", "美拉德风格", "老钱风",
            "法式优雅", "Y2K复古", "山系穿搭", "通勤风",
            "奶油风", "辣妹风", "学院风", "慵懒风"
        ]

        trends: List[Dict] = []
        base_time = datetime.now()

        for i, keyword in enumerate(trend_keywords):
            trends.append({
                "keyword": keyword,
                "platform": "mock",
                "heat_score": self._rng.randint(5000, 50000),
                "growth_rate": round(self._rng.uniform(-0.1, 0.5), 2),
                "timestamp": (base_time - timedelta(hours=i)).isoformat(),
            })

        return sorted(trends, key=lambda x: x["heat_score"], reverse=True)


class StaticTrendsData:
    """固定趋势列表，供 benchmark 注入；元素字段与 `MockTrendsData.trends` 一致。"""

    def __init__(self, trends: List[Dict]):
        self.trends = [dict(t) for t in trends]
