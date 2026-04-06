"""Agent 可调用的趋势查询工具"""
from typing import Optional

from ..data.trends_adapter import TrendsAdapter


class TrendsTools:
    """封装为 Agent 可调用的趋势工具"""

    def __init__(self, seed: Optional[int] = None):
        self.adapter = TrendsAdapter(seed=seed)

    def query_top_trends(self, limit: int = 5) -> str:
        """查询当前最热门的趋势"""
        trends = self.adapter.get_top_trends(limit)
        result = f"当前最热门的 {limit} 个趋势：\n"
        for i, t in enumerate(trends, 1):
            result += f"{i}. {t['keyword']} ({t['platform']}) - 热度：{t['heat_score']}\n"
        return result

    def query_growing_trends(self, limit: int = 3) -> str:
        """查询增长最快的趋势"""
        trends = self.adapter.get_growing_trends(limit)
        if not trends:
            return "暂无快速增长的趋势"
        result = f"增长最快的 {len(trends)} 个趋势：\n"
        for i, t in enumerate(trends, 1):
            result += f"{i}. {t['keyword']} - 增长率：{t['growth_rate']*100:.0f}%\n"
        return result
