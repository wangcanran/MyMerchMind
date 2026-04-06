"""销量复盘 Agent（规则版 baseline）。"""
from typing import Dict, List


class SalesReviewAgent:
    """基于规则生成销量复盘结论。"""

    def analyze(
        self,
        sku_metrics: List[Dict],
        top_trends: List[Dict],
        growing_trends: List[Dict],
        top_n: int = 5,
    ) -> Dict:
        if not sku_metrics:
            return {
                "summary": {
                    "total_daily_sales": 0,
                    "avg_return_rate_pct": 0.0,
                    "top_trend": "暂无",
                },
                "top_skus": [],
                "lagging_skus": [],
                "high_return_skus": [],
                "trend_focus": [],
                "recommendations": ["暂无可分析数据"],
            }

        ranked_sales = sorted(
            sku_metrics,
            key=lambda x: (-x["daily_sales"], x["sku_id"]),
        )
        lagging_sales = sorted(
            sku_metrics,
            key=lambda x: (x["daily_sales"], x["sku_id"]),
        )
        high_return = sorted(
            [item for item in sku_metrics if item["return_rate"] >= 0.1],
            key=lambda x: (-x["return_rate"], x["sku_id"]),
        )

        total_daily_sales = sum(item["daily_sales"] for item in sku_metrics)
        avg_return_rate = sum(item["return_rate"] for item in sku_metrics) / len(sku_metrics)

        trend_focus = [
            {
                "keyword": t["keyword"],
                "platform": t["platform"],
                "heat_score": t["heat_score"],
                "growth_rate_pct": round(t["growth_rate"] * 100, 1),
            }
            for t in top_trends[:top_n]
        ]

        recommendations: List[str] = []
        best = ranked_sales[0]
        recommendations.append(
            f"加大 {best['sku_id']}（{best['name']}）的曝光与备货，当前日均销量 {best['daily_sales']} 件。"
        )

        if high_return:
            risk = high_return[0]
            recommendations.append(
                f"优先处理 {risk['sku_id']}（{risk['name']}）退货问题，当前退货率 {risk['return_rate'] * 100:.1f}%。"
            )

        if growing_trends:
            growth = growing_trends[0]
            recommendations.append(
                f"关注“{growth['keyword']}”相关款式，上升趋势明显（增长率 {growth['growth_rate'] * 100:.0f}%）。"
            )
        elif top_trends:
            hottest = top_trends[0]
            recommendations.append(
                f"围绕当前热度最高的“{hottest['keyword']}”准备下周选品素材。"
            )

        return {
            "summary": {
                "total_daily_sales": total_daily_sales,
                "avg_return_rate_pct": round(avg_return_rate * 100, 2),
                "top_trend": top_trends[0]["keyword"] if top_trends else "暂无",
            },
            "top_skus": [self._to_view(item) for item in ranked_sales[:top_n]],
            "lagging_skus": [self._to_view(item) for item in lagging_sales[:top_n]],
            "high_return_skus": [self._to_view(item) for item in high_return[:top_n]],
            "trend_focus": trend_focus,
            "recommendations": recommendations,
        }

    def _to_view(self, item: Dict) -> Dict:
        return {
            "sku_id": item["sku_id"],
            "name": item["name"],
            "daily_sales": item["daily_sales"],
            "stock": item["stock"],
            "in_transit": item["in_transit"],
            "return_rate_pct": round(item["return_rate"] * 100, 1),
        }
