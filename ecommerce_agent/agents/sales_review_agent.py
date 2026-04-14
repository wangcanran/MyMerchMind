"""销量复盘 Agent（规则版 baseline + 渠道复盘 + 退货语义）。"""
from typing import Dict, List


_RETURN_KEYWORDS = [
    ("色差", "color_gap"),
    ("偏暗", "color_gap"),
    ("偏小", "sizing"),
    ("偏大", "sizing"),
    ("易皱", "wrinkle_care"),
    ("熨烫", "wrinkle_care"),
    ("线头", "quality_sewing"),
    ("起球", "pilling"),
]


class SalesReviewAgent:
    """基于规则生成销量复盘结论。"""

    def analyze(
        self,
        sku_metrics: List[Dict],
        top_trends: List[Dict],
        growing_trends: List[Dict],
        top_n: int = 5,
    ) -> Dict:
        data_source = "mock"
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
                "channel_dashboard": {},
                "return_semantics": {},
                "recommendations": ["暂无可分析数据"],
                "data_source": data_source,
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

        channel_dashboard = self._build_channel_dashboard(sku_metrics)
        return_semantics = self._aggregate_return_semantics(sku_metrics)

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

        ch = channel_dashboard.get("channels", {})
        if ch:
            top_ch = max(ch.items(), key=lambda kv: kv[1]["share_pct"])
            recommendations.append(
                f"渠道侧重：{top_ch[0]} 占比 {top_ch[1]['share_pct']:.1f}%，周环比约 {channel_dashboard.get('week_over_week_pct', 0):+.1f}%。"
            )

        if return_semantics.get("top_tags"):
            tag, cnt = return_semantics["top_tags"][0]
            recommendations.append(f"退货语义高频：{tag}（{cnt} 次），建议联动选品与质检。")

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
            "channel_dashboard": channel_dashboard,
            "return_semantics": return_semantics,
            "recommendations": recommendations,
            "data_source": data_source,
        }

    def _build_channel_dashboard(self, sku_metrics: List[Dict]) -> Dict:
        totals = {"live": 0, "private": 0, "shelf": 0}
        for item in sku_metrics:
            ch = item.get("channel_sales") or {}
            for k in totals:
                totals[k] += int(ch.get(k, 0))

        total_units = sum(totals.values()) or 1
        channels = {
            name: {
                "daily_units": totals[name],
                "share_pct": round(totals[name] / total_units * 100, 2),
            }
            for name in totals
        }

        current_week_units = sum(item["daily_sales"] for item in sku_metrics) * 7
        prior_week_units = sum(int(item.get("prior_week_total_units", 0)) for item in sku_metrics)
        wow = 0.0
        if prior_week_units > 0:
            wow = round((current_week_units - prior_week_units) / prior_week_units * 100, 2)

        prior_month = sum(int(item.get("prior_month_total_units", 0)) for item in sku_metrics)
        current_month_est = sum(item["daily_sales"] for item in sku_metrics) * 30
        mom = 0.0
        if prior_month > 0:
            mom = round((current_month_est - prior_month) / prior_month * 100, 2)

        return {
            "channels": channels,
            "week_over_week_pct": wow,
            "month_over_month_pct": mom,
            "current_week_est_units": int(current_week_units),
            "prior_week_total_units": int(prior_week_units),
            "current_month_est_units": int(current_month_est),
            "prior_month_total_units": int(prior_month),
        }

    def _aggregate_return_semantics(self, sku_metrics: List[Dict]) -> Dict:
        tag_counts: Dict[str, int] = {}
        per_sku: List[Dict] = []

        for item in sku_metrics:
            snippets = item.get("review_snippets") or []
            found: List[str] = []
            for text in snippets:
                for sub, tag in _RETURN_KEYWORDS:
                    if sub in text:
                        found.append(tag)
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1
            if found:
                per_sku.append(
                    {
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "tags": sorted(set(found)),
                    }
                )

        top_tags = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))
        return {
            "tag_counts": tag_counts,
            "top_tags": top_tags[:5],
            "sku_attributions": per_sku[:15],
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
