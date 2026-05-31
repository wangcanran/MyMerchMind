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

        # ── 历史趋势分析 ──────────────────────────────────────────────────
        sales_trend = self._compute_sales_trend(sku_metrics)
        sku_trends = self._compute_sku_trends(sku_metrics)

        trend_focus = self._build_trend_focus(top_trends, growing_trends)
        top_trend_label = "未接入"
        if trend_focus:
            top_trend_label = str(trend_focus[0].get("keyword") or "").strip() or "未接入"

        channel_dashboard = self._build_channel_dashboard(sku_metrics)
        return_semantics = self._aggregate_return_semantics(sku_metrics)

        recommendations: List[str] = []
        best = ranked_sales[0]
        best_trend = sku_trends.get(best['sku_id'], {})
        best_trend_label = best_trend.get('trend', 'stable')
        best_growth = best_trend.get('growth_7d_pct', 0)
        if best_trend_label == "declining":
            recommendations.append(
                f"{best['sku_id']}（{best['name']}）日销 {best['daily_sales']} 件为全店最高，但近7天趋势下降（{best_growth:+.1f}%）；"
                f"优先排查原因（库存不足限制排品？渠道流量下降？竞品分流？），确认供给侧无问题后再考虑加大曝光。"
            )
        else:
            trend_note = f"（近7天趋势：{best_trend_label}，增长{best_growth:+.1f}%）" if best_trend else ""
            recommendations.append(
                f"加大 {best['sku_id']}（{best['name']}）的曝光与备货，当前日均销量 {best['daily_sales']} 件{trend_note}；"
                f"目标：7 天内日销提升至 {int(best['daily_sales'] * 1.2)} 件，若未达标则复盘流量分配。"
            )

        if high_return:
            risk = high_return[0]
            recommendations.append(
                f"优先处理 {risk['sku_id']}（{risk['name']}）退货问题，当前退货率 {risk['return_rate'] * 100:.1f}%；"
                f"48h 内完成评价分析+详情页复核，若退货集中在尺码问题则更新尺码表，若为材质问题则考虑下架。"
            )

        ch = channel_dashboard.get("channels", {})
        if ch:
            top_ch = max(ch.items(), key=lambda kv: kv[1]["share_pct"])
            wow = channel_dashboard.get('week_over_week_pct')
            wow_str = f"周环比{wow:+.1f}%" if wow is not None else "周环比数据不足"
            recommendations.append(
                f"渠道侧重：{top_ch[0]} 占比 {top_ch[1]['share_pct']:.1f}%，{wow_str}。"
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
                "sales_growth_7d_pct": sales_trend.get("growth_7d_pct"),
                "avg_daily_7d": sales_trend.get("avg_7d"),
                "avg_daily_prev_7d": sales_trend.get("avg_prev_7d"),
            },
            "top_skus": [self._to_view(item, sku_trends) for item in ranked_sales[:top_n]],
            "lagging_skus": [self._to_view(item, sku_trends) for item in lagging_sales[:top_n]],
            "high_return_skus": [self._to_view(item, sku_trends) for item in high_return[:top_n]],
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

        # 用 price_history 最近 7 天实际销量（如果有），否则用快照估算
        actual_week_sales = 0
        has_history = False
        for item in sku_metrics:
            history = item.get("price_history")
            if isinstance(history, list) and len(history) >= 7:
                has_history = True
                recent_7 = [int(r.get("daily_sales") or 0) for r in history[-7:] if isinstance(r, dict)]
                actual_week_sales += sum(recent_7)
        current_week_units = actual_week_sales if has_history else sum(item["daily_sales"] for item in sku_metrics) * 7
        prior_week_units = sum(int(item.get("prior_week_total_units", 0)) for item in sku_metrics)
        wow = None
        if prior_week_units > 0:
            wow = round((current_week_units - prior_week_units) / prior_week_units * 100, 2)

        prior_month = sum(int(item.get("prior_month_total_units", 0)) for item in sku_metrics)
        # 用 price_history 最近 30 天实际销量（如果有）
        actual_month_sales = 0
        for item in sku_metrics:
            history = item.get("price_history")
            if isinstance(history, list) and len(history) >= 7:
                actual_month_sales += sum(int(r.get("daily_sales") or 0) for r in history if isinstance(r, dict))
        current_month_est = actual_month_sales if has_history else sum(item["daily_sales"] for item in sku_metrics) * 30
        mom = None
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
            "channel_sku_breakdown": self._build_channel_sku_breakdown(sku_metrics),
            "channel_risk_diagnosis": self._diagnose_channel_risks(sku_metrics),
        }

    def _aggregate_return_semantics(self, sku_metrics: List[Dict]) -> Dict:
        """退货语义分析。"""
        """按渠道拆解 Top SKU 贡献，识别渠道集中度风险。"""
        channel_skus: Dict[str, List[Dict]] = {"live": [], "private": [], "shelf": []}
        for item in sku_metrics:
            ch = item.get("channel_sales") or {}
            for ch_name in channel_skus:
                units = int(ch.get(ch_name, 0))
                if units > 0:
                    channel_skus[ch_name].append({
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "channel_units": units,
                        "daily_sales": item["daily_sales"],
                        "stock": item.get("stock", 0),
                        "in_transit": item.get("in_transit", 0),
                    })
        # 每个渠道按贡献排序取 Top 3
        result = {}
        for ch_name, skus in channel_skus.items():
            sorted_skus = sorted(skus, key=lambda x: -x["channel_units"])[:3]
            total_ch = sum(s["channel_units"] for s in skus) or 1
            for s in sorted_skus:
                s["channel_share_pct"] = round(s["channel_units"] / total_ch * 100, 1)
                coverage = s["stock"] / s["daily_sales"] if s["daily_sales"] > 0 else 999
                s["coverage_days"] = round(coverage, 1)
            result[ch_name] = sorted_skus
        return result

    @staticmethod
    def _diagnose_channel_risks(sku_metrics: List[Dict]) -> List[Dict]:
        """诊断渠道下降的可能原因：库存不足限制排品、高退货率拖累等。"""
        risks = []
        for item in sku_metrics:
            ch = item.get("channel_sales") or {}
            ds = item.get("daily_sales", 0)
            stock = item.get("stock", 0)
            in_transit = item.get("in_transit", 0)
            coverage = (stock + in_transit) / ds if ds > 0 else 999
            rr = float(item.get("return_rate") or 0)

            # 高渠道贡献 + 低库存 = 可能限制排品
            for ch_name, ch_units in ch.items():
                if ch_units > 0 and coverage < 5:
                    risks.append({
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "channel": ch_name,
                        "channel_units": ch_units,
                        "coverage_days": round(coverage, 1),
                        "risk_type": "low_stock_limits_channel",
                        "diagnosis": f"{item['name']}在{ch_name}渠道贡献{ch_units}件/天，但库存仅覆盖{coverage:.1f}天，可能限制排品频次",
                    })
            # 高退货率 + 高渠道占比 = 渠道质量风险
            if rr >= 0.08:
                dominant_ch = max(ch.items(), key=lambda x: x[1]) if ch else ("", 0)
                if dominant_ch[1] > 0:
                    risks.append({
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "channel": dominant_ch[0],
                        "return_rate_pct": round(rr * 100, 1),
                        "risk_type": "high_return_drags_channel",
                        "diagnosis": f"{item['name']}退货率{rr*100:.1f}%，主要在{dominant_ch[0]}渠道销售，可能拖累渠道整体转化",
                    })
        return risks[:5]  # 最多返回 5 条风险


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

    @staticmethod
    def _build_channel_sku_breakdown(sku_metrics: List[Dict]) -> Dict:
        """按渠道拆解 Top SKU 贡献，识别渠道集中度风险。"""
        channel_skus: Dict[str, List[Dict]] = {"live": [], "private": [], "shelf": []}
        for item in sku_metrics:
            ch = item.get("channel_sales") or {}
            for ch_name in channel_skus:
                units = int(ch.get(ch_name, 0))
                if units > 0:
                    channel_skus[ch_name].append({
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "channel_units": units,
                        "daily_sales": item["daily_sales"],
                        "stock": item.get("stock", 0),
                        "in_transit": item.get("in_transit", 0),
                    })
        result = {}
        for ch_name, skus in channel_skus.items():
            sorted_skus = sorted(skus, key=lambda x: -x["channel_units"])[:3]
            total_ch = sum(s["channel_units"] for s in skus) or 1
            for s in sorted_skus:
                s["channel_share_pct"] = round(s["channel_units"] / total_ch * 100, 1)
                coverage = s["stock"] / s["daily_sales"] if s["daily_sales"] > 0 else 999
                s["coverage_days"] = round(coverage, 1)
            result[ch_name] = sorted_skus
        return result

    @staticmethod
    def _diagnose_channel_risks(sku_metrics: List[Dict]) -> List[Dict]:
        """诊断渠道下降的可能原因：库存不足限制排品、高退货率拖累等。"""
        risks = []
        for item in sku_metrics:
            ch = item.get("channel_sales") or {}
            ds = item.get("daily_sales", 0)
            stock = item.get("stock", 0)
            in_transit = item.get("in_transit", 0)
            coverage = (stock + in_transit) / ds if ds > 0 else 999
            rr = float(item.get("return_rate") or 0)
            for ch_name, ch_units in ch.items():
                if ch_units > 0 and coverage < 5:
                    risks.append({
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "channel": ch_name,
                        "channel_units": ch_units,
                        "coverage_days": round(coverage, 1),
                        "risk_type": "low_stock_limits_channel",
                        "diagnosis": f"{item['name']}在{ch_name}渠道贡献{ch_units}件/天，但库存仅覆盖{coverage:.1f}天，可能限制排品频次",
                    })
            if rr >= 0.08:
                dominant_ch = max(ch.items(), key=lambda x: x[1]) if ch else ("", 0)
                if dominant_ch[1] > 0:
                    risks.append({
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "channel": dominant_ch[0],
                        "return_rate_pct": round(rr * 100, 1),
                        "risk_type": "high_return_drags_channel",
                        "diagnosis": f"{item['name']}退货率{rr*100:.1f}%，主要在{dominant_ch[0]}渠道销售，可能拖累渠道整体转化",
                    })
        return risks[:5]

    def _to_view(self, item: Dict, sku_trends: Optional[Dict] = None) -> Dict:
        raw_p = item.get("price")
        list_price = None
        if raw_p is not None:
            try:
                list_price = int(round(float(raw_p)))
            except (TypeError, ValueError):
                list_price = None
        view = {
            "sku_id": item["sku_id"],
            "name": item["name"],
            "daily_sales": item["daily_sales"],
            "stock": item["stock"],
            "in_transit": item["in_transit"],
            "return_rate_pct": round(item["return_rate"] * 100, 1),
            "list_price": list_price,
        }
        if sku_trends and item["sku_id"] in sku_trends:
            t = sku_trends[item["sku_id"]]
            view["trend"] = t["trend"]
            view["growth_7d_pct"] = t["growth_7d_pct"]
        # Return rate signal
        rr = item["return_rate"]
        view["return_rate_signal"] = "high" if rr >= 0.08 else "elevated" if rr >= 0.05 else "normal"
        return view

    @staticmethod
    def _compute_sales_trend(sku_metrics: List[Dict]) -> Dict:
        """从全店 price_history 计算 7 天 vs 前 7 天销量增长率。"""
        from collections import defaultdict
        daily_totals: defaultdict = defaultdict(int)
        for sku in sku_metrics:
            history = sku.get("price_history")
            if not isinstance(history, list):
                continue
            for rec in history:
                if isinstance(rec, dict) and rec.get("date"):
                    daily_totals[rec["date"]] += int(rec.get("daily_sales") or 0)
        if not daily_totals:
            return {}
        sorted_dates = sorted(daily_totals.keys())
        recent_7 = sorted_dates[-7:]
        prev_7 = sorted_dates[-14:-7] if len(sorted_dates) >= 14 else sorted_dates[max(0, len(sorted_dates) - 14):max(0, len(sorted_dates) - 7)]
        if not prev_7:
            return {}
        avg_7d = sum(daily_totals[d] for d in recent_7) / max(len(recent_7), 1)
        avg_prev_7d = sum(daily_totals[d] for d in prev_7) / max(len(prev_7), 1)
        growth = round((avg_7d - avg_prev_7d) / avg_prev_7d * 100, 1) if avg_prev_7d > 0 else 0.0
        return {"growth_7d_pct": growth, "avg_7d": round(avg_7d, 1), "avg_prev_7d": round(avg_prev_7d, 1)}

    @staticmethod
    def _compute_sku_trends(sku_metrics: List[Dict]) -> Dict[str, Dict]:
        """为每个 SKU 计算近 7 天 vs 前 7 天增长率和趋势标签。"""
        result = {}
        for sku in sku_metrics:
            history = sku.get("price_history")
            if not isinstance(history, list) or len(history) < 7:
                continue
            sales = [int(r.get("daily_sales") or 0) for r in history if isinstance(r, dict)]
            if len(sales) < 7:
                continue
            recent = sales[-7:]
            prev = sales[-14:-7] if len(sales) >= 14 else sales[max(0, len(sales) - 14):max(0, len(sales) - 7)]
            if not prev:
                continue
            avg_recent = sum(recent) / len(recent)
            avg_prev = sum(prev) / max(len(prev), 1)
            growth = round((avg_recent - avg_prev) / avg_prev * 100, 1) if avg_prev > 0 else 0.0
            if growth > 20:
                trend = "accelerating"
            elif growth < -10:
                trend = "declining"
            else:
                trend = "stable"
            result[sku["sku_id"]] = {"growth_7d_pct": growth, "trend": trend}
        return result
