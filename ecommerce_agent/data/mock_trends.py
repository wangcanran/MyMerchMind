"""模拟社媒趋势数据源"""
from datetime import datetime, timedelta
import random
from typing import Dict, List, Optional


class MockTrendsData:
    """模拟小红书/抖音热门标签数据"""

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
                "platform": self._rng.choice(["小红书", "抖音"]),
                "heat_score": self._rng.randint(5000, 50000),
                "growth_rate": round(self._rng.uniform(-0.1, 0.5), 2),
                "timestamp": (base_time - timedelta(hours=i)).isoformat(),
            })

        return sorted(trends, key=lambda x: x["heat_score"], reverse=True)
