"""销量复盘 Agent（规则版 baseline + 渠道复盘 + 退货语义）。"""
import json
from typing import Dict, List, Optional

from ..config.return_rate_thresholds import high_return_rate_pct, is_high_return
from ..llm import prompts
from ..llm.client import LLMClientError, OpenAICompatChatClient
from ..llm.json_util import parse_json_object
from ..report_formatting import normalize_trend_growth_in_text


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

    def __init__(
        self,
        llm_client: Optional[OpenAICompatChatClient] = None,
        use_llm: bool = False,
    ):
        self._llm = llm_client
        self._use_llm = bool(use_llm and llm_client is not None)

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
                    "top_trend": "未接入",
                },
                "top_skus": [],
                "lagging_skus": [],
                "high_return_skus": [],
                "trend_focus": [],
                "channel_dashboard": {},
                "return_semantics": {},
                "recommendations": ["暂无可分析数据"],
                "segmentation_glossary": {},
                "data_source": data_source,
                "llm_executive_brief": None,
                "llm_error": None,
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
            [item for item in sku_metrics if is_high_return(item.get("return_rate"))],
            key=lambda x: (-x["return_rate"], x["sku_id"]),
        )

        total_daily_sales = sum(item["daily_sales"] for item in sku_metrics)
        avg_return_rate = sum(item["return_rate"] for item in sku_metrics) / len(sku_metrics)

        trend_focus = self._build_trend_focus(top_trends, growing_trends)
        top_trend_label = "未接入"
        if trend_focus:
            top_trend_label = str(trend_focus[0].get("keyword") or "").strip() or "未接入"

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

        ch = channel_dashboard.get("channels", {})
        if ch:
            top_ch = max(ch.items(), key=lambda kv: kv[1]["share_pct"])
            recommendations.append(
                f"渠道侧重：{top_ch[0]} 占比 {top_ch[1]['share_pct']:.1f}%，周环比约 {channel_dashboard.get('week_over_week_pct', 0):+.1f}%。"
            )

        if return_semantics.get("top_tags"):
            tag, cnt = return_semantics["top_tags"][0]
            recommendations.append(f"退货语义高频：{tag}（{cnt} 次），建议联动选品与质检。")

        llm_executive_brief: Optional[Dict] = None
        llm_error: Optional[str] = None
        if self._use_llm and self._llm is not None:
            try:
                brief_payload = {
                    "summary": {
                        "total_daily_sales": total_daily_sales,
                        "avg_return_rate_pct": round(avg_return_rate * 100, 2),
                    },
                    "top_skus": [self._to_view(item) for item in ranked_sales[:top_n]],
                    "high_return_skus": [self._to_view(item) for item in high_return[:3]],
                    "channel_dashboard": channel_dashboard,
                    "return_semantics": return_semantics,
                }
                user_msg = prompts.SALES_REVIEW_USER.format(
                    payload=json.dumps(brief_payload, ensure_ascii=False),
                )
                raw = self._llm.chat(
                    [
                        {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.0,
                )
                parsed = parse_json_object(raw)
                es = parsed.get("executive_summary")
                bullets = parsed.get("action_bullets")
                if not isinstance(es, str) or not isinstance(bullets, list):
                    raise ValueError("LLM 返回结构无效")
                llm_executive_brief = {
                    "executive_summary": normalize_trend_growth_in_text(es.strip()),
                    "action_bullets": [
                        normalize_trend_growth_in_text(str(b).strip())
                        for b in bullets
                        if str(b).strip()
                    ],
                }
                for b in llm_executive_brief["action_bullets"]:
                    recommendations.append(f"【LLM】{b}")
                data_source = "hybrid"
            except (LLMClientError, ValueError, TypeError) as e:
                llm_error = str(e)

        return {
            "summary": {
                "total_daily_sales": total_daily_sales,
                "avg_return_rate_pct": round(avg_return_rate * 100, 2),
            },
            "top_skus": [self._to_view(item) for item in ranked_sales[:top_n]],
            "lagging_skus": [self._to_view(item) for item in lagging_sales[:top_n]],
            "high_return_skus": [self._to_view(item) for item in high_return[:top_n]],
            "channel_dashboard": channel_dashboard,
            "return_semantics": return_semantics,
            "recommendations": recommendations,
            "segmentation_glossary": {
                "top_skus": "按日销量全店降序取 Top N；与 ERP 现价同快照，展示为 sku_id + 品名。",
                "lagging_skus": "按日销量升序取 Top N（弱动销观察），不排除高库龄；清滞见库存模块。",
                "high_return_skus": (
                    f"退货率≥{high_return_rate_pct():g}% 降序；行动清单中为达到该阈值的每个 SKU "
                    "生成「高退货处置」闭环（阈值见 config.return_rate_thresholds）。"
                ),
                "slow_moving_coordination": "滞销清理池排除日销 Top5（与 orchestrator.reporting_rules 一致），避免与高销 SKU 标签冲突。",
            },
            "data_source": data_source,
            "llm_executive_brief": llm_executive_brief,
            "llm_error": llm_error,
        }

    @staticmethod
    def _build_trend_focus(
        top_trends: List[Dict],
        growing_trends: List[Dict],
    ) -> List[Dict]:
        """合并热度 Top 与增长趋势，供复盘与 LLM 摘要使用（字段与 ``mock_trends`` 对齐）。"""
        out: List[Dict] = []
        seen: set[str] = set()

        def _push(row: Dict, source: str) -> None:
            if not isinstance(row, dict):
                return
            kw = str(row.get("keyword", "")).strip()
            if not kw or kw in seen:
                return
            seen.add(kw)
            out.append(
                {
                    "keyword": kw,
                    "heat_score": row.get("heat_score"),
                    "growth_rate": row.get("growth_rate"),
                    "platform": row.get("platform"),
                    "source": source,
                }
            )

        for t in top_trends or []:
            _push(t, "heat_top")
        for t in growing_trends or []:
            _push(t, "growth")
        return out

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
        raw_p = item.get("price")
        list_price = None
        if raw_p is not None:
            try:
                list_price = int(round(float(raw_p)))
            except (TypeError, ValueError):
                list_price = None
        return {
            "sku_id": item["sku_id"],
            "name": item["name"],
            "daily_sales": item["daily_sales"],
            "stock": item["stock"],
            "in_transit": item["in_transit"],
            "return_rate_pct": round(item["return_rate"] * 100, 1),
            "list_price": list_price,
        }
