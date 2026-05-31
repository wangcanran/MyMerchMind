"""库存预警 Agent（增强版：分层预警、优先级队列与协同摘要）。"""
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from ..config.return_rate_thresholds import high_return_fraction, high_return_rate_pct
from ..llm import prompts
from ..llm.client import LLMClientError, OpenAICompatChatClient
from ..llm.json_util import parse_json_object


def _safe_ratio(numerator: float, denominator: float, fallback: float = 0.0) -> float:
    if denominator <= 0:
        return fallback
    return numerator / denominator


class InventoryWarningAgent:
    """基于规则生成库存预警，并补充管理视角字段。"""

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
        replenishment_cycle_days: int = 7,
        overstock_days: int = 45,
        limit: int = 5,
    ) -> Dict:
        low_stock_all: List[Dict[str, Any]] = []
        overstock_all: List[Dict[str, Any]] = []
        current_coverages: List[float] = []
        total_coverages: List[float] = []
        stock_position_units = 0
        coverage_bands = {
            "critical_shortage": 0,
            "replenishment_watch": 0,
            "healthy": 0,
            "overstock": 0,
            "deadstock_like": 0,
        }

        for item in sku_metrics:
            daily_sales = int(item.get("daily_sales", 0))
            current_stock = int(item.get("stock", 0))
            in_transit = int(item.get("in_transit", 0))
            stock_position = current_stock + in_transit
            stock_position_units += stock_position

            # Use 7-day average from price_history if available (more stable than single-day snapshot)
            avg_daily_7d = daily_sales
            sales_volatility = 0.0
            history = item.get("price_history")
            if isinstance(history, list) and len(history) >= 7:
                recent_sales = [int(r.get("daily_sales") or 0) for r in history[-7:] if isinstance(r, dict)]
                if recent_sales:
                    avg_daily_7d = round(sum(recent_sales) / len(recent_sales), 1)
                    mean_val = sum(recent_sales) / len(recent_sales)
                    if mean_val > 0:
                        variance = sum((x - mean_val) ** 2 for x in recent_sales) / len(recent_sales)
                        sales_volatility = round((variance ** 0.5) / mean_val, 2)

            effective_daily = avg_daily_7d if avg_daily_7d > 0 else daily_sales

            channel_name, channel_share = self._get_channel_focus(item)
            return_rate = float(item.get("return_rate", 0.0))
            conversion_rate = float(item.get("conversion_rate", 0.0))
            stock_age_days = int(item.get("stock_age_days", 0))

            if effective_daily > 0:
                current_coverage_days = current_stock / effective_daily
                total_coverage_days = stock_position / effective_daily
                current_coverages.append(current_coverage_days)
                total_coverages.append(total_coverage_days)
            else:
                current_coverage_days = float("inf") if current_stock > 0 else 0.0
                total_coverage_days = float("inf") if stock_position > 0 else 0.0

            self._add_coverage_band(
                coverage_bands=coverage_bands,
                current_coverage_days=current_coverage_days,
                total_coverage_days=total_coverage_days,
                replenishment_cycle_days=replenishment_cycle_days,
                overstock_days=overstock_days,
                daily_sales=daily_sales,
                stock_position=stock_position,
            )

            if daily_sales > 0 and current_coverage_days < replenishment_cycle_days:
                safety_stock_days = self._estimate_safety_stock_days(
                    daily_sales=daily_sales,
                    channel_share=channel_share,
                    return_rate=return_rate,
                    conversion_rate=conversion_rate,
                )
                target_stock_days = round(
                    replenishment_cycle_days
                    + safety_stock_days
                    + (1.5 if daily_sales >= 25 else 0.5 if daily_sales >= 12 else 0.0),
                    1,
                )
                reorder_point_units = int(
                    math.ceil(daily_sales * (replenishment_cycle_days + safety_stock_days))
                )
                target_stock_units = int(math.ceil(daily_sales * target_stock_days))
                coverage_gap_days = round(max(target_stock_days - total_coverage_days, 0.0), 1)
                suggestion_qty = max(target_stock_units - stock_position, 0)
                urgency_score = self._compute_urgency_score(
                    current_coverage_days=current_coverage_days,
                    coverage_gap_days=coverage_gap_days,
                    daily_sales=daily_sales,
                    channel_share=channel_share,
                )
                urgency_level = self._score_to_level(
                    score=urgency_score,
                    severe_threshold=80,
                    high_threshold=62,
                    medium_threshold=40,
                )
                low_stock_all.append(
                    {
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "daily_sales": daily_sales,
                        "avg_daily_7d": avg_daily_7d,
                        "sales_volatility": sales_volatility,
                        "current_stock": current_stock,
                        "in_transit": in_transit,
                        "stock_position": stock_position,
                        "cost_price": float(item.get("cost_price") or 0),
                        "coverage_days": round(current_coverage_days, 1),
                        "total_coverage_days": round(total_coverage_days, 1),
                        "coverage_days_pessimistic": round(stock_position / (avg_daily_7d * (1 + sales_volatility)) if avg_daily_7d * (1 + sales_volatility) > 0 else 0, 1),
                        "coverage_gap_days": coverage_gap_days,
                        "safety_stock_days": safety_stock_days,
                        "target_stock_days": target_stock_days,
                        "reorder_point_units": reorder_point_units,
                        "target_stock_units": target_stock_units,
                        "suggest_replenish_qty": suggestion_qty,
                        "urgency_score": urgency_score,
                        "urgency_level": urgency_level,
                        "demand_band": self._classify_demand_band(daily_sales),
                        "channel_focus": channel_name,
                        "channel_focus_share_pct": round(channel_share * 100, 1),
                    }
                )

            if self._should_flag_overstock(
                daily_sales=daily_sales,
                total_coverage_days=total_coverage_days,
                overstock_days=overstock_days,
                stock_position=stock_position,
            ):
                pressure_score = self._compute_overstock_score(
                    total_coverage_days=total_coverage_days,
                    overstock_days=overstock_days,
                    stock_age_days=stock_age_days,
                    conversion_rate=conversion_rate,
                    return_rate=return_rate,
                    stock_position=stock_position,
                    daily_sales=daily_sales,
                )
                clearance_priority = self._score_to_level(
                    score=pressure_score,
                    severe_threshold=82,
                    high_threshold=62,
                    medium_threshold=40,
                )
                recommended_action, action_reason = self._pick_clearance_action(
                    item=item,
                    pressure_score=pressure_score,
                )
                total_coverage_value = 999.0 if math.isinf(total_coverage_days) else round(total_coverage_days, 1)
                overstock_all.append(
                    {
                        "sku_id": item["sku_id"],
                        "name": item["name"],
                        "daily_sales": daily_sales,
                        "avg_daily_7d": avg_daily_7d,
                        "sales_volatility": sales_volatility,
                        "current_stock": current_stock,
                        "in_transit": in_transit,
                        "stock_position": stock_position,
                        "total_coverage_days": total_coverage_value,
                        "stock_age_days": stock_age_days,
                        "conversion_rate": conversion_rate,
                        "return_rate_pct": round(return_rate * 100, 1),
                        "pressure_score": pressure_score,
                        "clearance_priority": clearance_priority,
                        "recommended_action": recommended_action,
                        "action_reason": action_reason,
                        "channel_focus": channel_name,
                    }
                )

        low_stock_alerts = sorted(
            low_stock_all,
            key=lambda row: (-float(row["urgency_score"]), float(row["coverage_days"]), str(row["sku_id"])),
        )[:limit]
        overstock_alerts = sorted(
            overstock_all,
            key=lambda row: (-float(row["pressure_score"]), -float(row["total_coverage_days"]), str(row["sku_id"])),
        )[:limit]

        inventory_health = {
            "sku_count": len(sku_metrics),
            "low_stock_skus": len(low_stock_all),
            "critical_low_stock_skus": sum(
                1
                for row in low_stock_all
                if str(row.get("urgency_level")) in {"critical", "high"}
            ),
            "overstock_skus": len(overstock_all),
            "severe_overstock_skus": sum(
                1
                for row in overstock_all
                if str(row.get("clearance_priority")) in {"critical", "high"}
            ),
            "healthy_skus": max(
                len(sku_metrics) - len(low_stock_all) - len(overstock_all),
                0,
            ),
            "avg_current_coverage_days": round(sum(current_coverages) / len(current_coverages), 1)
            if current_coverages
            else 0.0,
            "avg_total_coverage_days": round(sum(total_coverages) / len(total_coverages), 1)
            if total_coverages
            else 0.0,
            "stock_position_units": stock_position_units,
            "coverage_bands": coverage_bands,
        }
        action_queue = self._build_action_queue(low_stock_alerts, overstock_alerts)

        recommendations: List[str] = []
        if low_stock_alerts:
            first_low = low_stock_alerts[0]
            recommendations.append(
                f"补货优先级最高：{first_low['sku_id']}（{first_low['name']}），"
                f"当前仅可售 {first_low['coverage_days']} 天（7 天均销 {first_low.get('avg_daily_7d', first_low['daily_sales'])} 件），"
                f"建议补 {first_low['suggest_replenish_qty']} 件；"
                f"若供应商无法 3 天内发货，立即启动替代供应商或临时调拨。"
            )
        if overstock_alerts:
            first_over = overstock_alerts[0]
            recommendations.append(
                f"去化优先级最高：{first_over['sku_id']}（{first_over['name']}），"
                f"库存覆盖 {first_over['total_coverage_days']} 天，建议先做 {first_over['recommended_action']}；"
                f"执行后 7 天内日销未达 {max(first_over['daily_sales'] * 2, 10)} 件则升级为降价清仓。"
            )
        if not recommendations:
            recommendations.append("当前库存结构健康，无需额外干预。")
        if action_queue:
            first_action = action_queue[0]
            recommendations.append(
                f"跨团队先执行：{first_action['owner']} 在 {first_action['due_in_days']} 天内完成 {first_action['action_type']}（{first_action['sku_id']}）。"
            )

        data_source = "mock"
        llm_notes: Optional[Dict[str, Any]] = None
        llm_error: Optional[str] = None
        if self._use_llm and self._llm is not None:
            try:
                payload = {
                    "inventory_health": inventory_health,
                    "policy_snapshot": {
                        "replenishment_cycle_days": replenishment_cycle_days,
                        "overstock_days": overstock_days,
                    },
                    "top_low_stock_alerts": low_stock_alerts[:3],
                    "top_overstock_alerts": overstock_alerts[:3],
                    "action_queue": action_queue[:6],
                }
                llm_notes = self._build_llm_notes(payload)
                data_source = "hybrid"
            except (LLMClientError, ValueError, TypeError) as exc:
                llm_error = str(exc)

        return {
            "inventory_health": inventory_health,
            "policy_snapshot": {
                "replenishment_cycle_days": replenishment_cycle_days,
                "overstock_days": overstock_days,
            },
            "low_stock_alerts": low_stock_alerts,
            "overstock_alerts": overstock_alerts,
            "action_queue": action_queue,
            "recommendations": recommendations,
            "data_source": data_source,
            "llm_notes": llm_notes,
            "llm_error": llm_error,
        }

    def _get_channel_focus(self, item: Dict[str, Any]) -> Tuple[str, float]:
        channel_sales = item.get("channel_sales") or {}
        totals = {
            "live": int(channel_sales.get("live", 0)),
            "private": int(channel_sales.get("private", 0)),
            "shelf": int(channel_sales.get("shelf", 0)),
        }
        total_units = sum(totals.values())
        if total_units <= 0:
            return "mixed", 0.0
        name, units = max(totals.items(), key=lambda pair: (pair[1], pair[0]))
        return name, round(units / total_units, 4)

    def _estimate_safety_stock_days(
        self,
        *,
        daily_sales: int,
        channel_share: float,
        return_rate: float,
        conversion_rate: float,
    ) -> float:
        safety_days = 1.5
        if daily_sales >= 35:
            safety_days += 1.4
        elif daily_sales >= 20:
            safety_days += 1.0
        elif daily_sales >= 10:
            safety_days += 0.6
        else:
            safety_days += 0.2
        if channel_share >= 0.55:
            safety_days += 0.8
        if return_rate >= high_return_fraction():
            safety_days += 0.4
        if conversion_rate >= 0.02:
            safety_days += 0.3
        return round(min(max(safety_days, 1.5), 5.5), 1)

    def _compute_urgency_score(
        self,
        *,
        current_coverage_days: float,
        coverage_gap_days: float,
        daily_sales: int,
        channel_share: float,
    ) -> float:
        score = 0.0
        score += min(max(7.0 - current_coverage_days, 0.0) * 7.5, 42.0)
        score += min(coverage_gap_days * 4.5, 26.0)
        score += min(daily_sales * 0.9, 24.0)
        score += min(channel_share * 18.0, 8.0)
        if current_coverage_days <= 2.0:
            score += 10.0
        return round(min(score, 100.0), 1)

    def _compute_overstock_score(
        self,
        *,
        total_coverage_days: float,
        overstock_days: int,
        stock_age_days: int,
        conversion_rate: float,
        return_rate: float,
        stock_position: int,
        daily_sales: int,
    ) -> float:
        score = 0.0
        if math.isinf(total_coverage_days):
            score += 52.0
        else:
            score += min(max(total_coverage_days - overstock_days, 0.0) * 1.2, 42.0)
        score += min(max(stock_age_days - 45, 0) * 0.65, 24.0)
        score += min(max(0.012 - conversion_rate, 0.0) * 2200.0, 16.0)
        score += min(return_rate * 100.0, max(high_return_rate_pct(), 1.0))
        score += min(stock_position / 30.0, 8.0)
        if daily_sales <= 1 and stock_position > 0:
            score += 8.0
        return round(min(score, 100.0), 1)

    def _classify_demand_band(self, daily_sales: int) -> str:
        if daily_sales >= 30:
            return "high"
        if daily_sales >= 15:
            return "medium"
        return "low"

    def _score_to_level(
        self,
        *,
        score: float,
        severe_threshold: float,
        high_threshold: float,
        medium_threshold: float,
    ) -> str:
        if score >= severe_threshold:
            return "critical"
        if score >= high_threshold:
            return "high"
        if score >= medium_threshold:
            return "medium"
        return "low"

    def _should_flag_overstock(
        self,
        *,
        daily_sales: int,
        total_coverage_days: float,
        overstock_days: int,
        stock_position: int,
    ) -> bool:
        if stock_position <= 0:
            return False
        if daily_sales <= 0:
            return True
        return total_coverage_days > overstock_days

    def _pick_clearance_action(
        self,
        *,
        item: Dict[str, Any],
        pressure_score: float,
    ) -> Tuple[str, str]:
        stock = int(item.get("stock", 0))
        in_transit = int(item.get("in_transit", 0))
        daily_sales = int(item.get("daily_sales", 0))
        stock_age_days = int(item.get("stock_age_days", 0))
        conversion_rate = float(item.get("conversion_rate", 0.0))
        return_rate = float(item.get("return_rate", 0.0))

        if daily_sales <= 1:
            return "直播间秒杀", "几乎无自然动销，先用短促快速回笼库存"
        if in_transit > 0 and stock > 200:
            return "冻结补货并跨仓调拨", "在途与现货同时偏高，先停新增再平衡库位"
        if return_rate >= high_return_fraction():
            return "先做质检/详情页修正再去化", "高退货风险下直接放量促销会放大售后损失"
        if stock_age_days >= 75 or pressure_score >= 78:
            return "阶梯满减清仓", "库龄与库存压力都高，适合按节奏快速出清"
        if conversion_rate < 0.008:
            return "搭配套餐或券促转化", "转化偏弱，先改善成交效率再观察"
        return "满减促销", "先温和去化，避免一次性打穿价格带"

    def _add_coverage_band(
        self,
        *,
        coverage_bands: Dict[str, int],
        current_coverage_days: float,
        total_coverage_days: float,
        replenishment_cycle_days: int,
        overstock_days: int,
        daily_sales: int,
        stock_position: int,
    ) -> None:
        if daily_sales <= 0 and stock_position > 0:
            coverage_bands["deadstock_like"] += 1
            return
        if current_coverage_days < max(replenishment_cycle_days * 0.5, 2):
            coverage_bands["critical_shortage"] += 1
        elif current_coverage_days < replenishment_cycle_days:
            coverage_bands["replenishment_watch"] += 1
        elif total_coverage_days > overstock_days:
            coverage_bands["overstock"] += 1
        else:
            coverage_bands["healthy"] += 1

    def _build_action_queue(
        self,
        low_stock_alerts: List[Dict[str, Any]],
        overstock_alerts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        queue: List[Dict[str, Any]] = []
        for row in low_stock_alerts[:4]:
            if row.get("suggest_replenish_qty", 0) <= 0:
                continue
            due_in_days = 1 if row["urgency_level"] == "critical" else 2 if row["urgency_level"] == "high" else 4
            queue.append(
                {
                    "priority": row["urgency_level"],
                    "owner": "采购",
                    "action_type": "replenish_now",
                    "sku_id": row["sku_id"],
                    "name": row["name"],
                    "due_in_days": due_in_days,
                    "reason": (
                        f"库存位置 {row['stock_position']} 低于目标 {row['target_stock_units']}，"
                        f"当前仅可售 {row['coverage_days']} 天。"
                    ),
                    "recommended_qty": row["suggest_replenish_qty"],
                }
            )
        for row in overstock_alerts[:3]:
            queue.append(
                {
                    "priority": row["clearance_priority"],
                    "owner": "运营",
                    "action_type": "launch_clearance",
                    "sku_id": row["sku_id"],
                    "name": row["name"],
                    "due_in_days": 3 if row["clearance_priority"] in {"critical", "high"} else 5,
                    "reason": (
                        f"库存覆盖 {row['total_coverage_days']} 天，建议执行 {row['recommended_action']}。"
                    ),
                    "recommended_qty": 0,
                }
            )
            if row.get("in_transit", 0) > 0:
                queue.append(
                    {
                        "priority": row["clearance_priority"],
                        "owner": "采购",
                        "action_type": "freeze_or_trim_po",
                        "sku_id": row["sku_id"],
                        "name": row["name"],
                        "due_in_days": 2,
                        "reason": f"在途 {row['in_transit']} 件，需避免继续放大库存压力。",
                        "recommended_qty": 0,
                    }
                )

        order_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        queue.sort(
            key=lambda row: (
                order_rank.get(str(row.get("priority")), 9),
                int(row.get("due_in_days", 99)),
                str(row.get("sku_id", "")),
            )
        )
        deduped: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str, str]] = set()
        for row in queue:
            key = (str(row.get("owner")), str(row.get("action_type")), str(row.get("sku_id")))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped[:8]

    def _build_llm_notes(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        user_msg = prompts.INVENTORY_USER.format(
            payload=json.dumps(payload, ensure_ascii=False),
        )
        messages = [
            {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
            {"role": "user", "content": user_msg},
        ]
        raw: Optional[str] = None
        parsed: Optional[Dict[str, Any]] = None
        last_error: Optional[Exception] = None
        for attempt in range(2):
            try:
                try:
                    raw = self._llm.chat(
                        messages,
                        temperature=0.0,
                        response_format={"type": "json_object"},
                    )
                except TypeError:
                    raw = self._llm.chat(messages, temperature=0.0)
                parsed = parse_json_object(raw)
                break
            except (LLMClientError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt == 0:
                    messages = [
                        {"role": "system", "content": prompts.SYSTEM_ZH_BUSINESS},
                        {
                            "role": "user",
                            "content": (
                                "请严格只输出一个 JSON 对象，且必须包含：priorities_note / "
                                "replenishment_focus / clearance_focus / coordination_checklist。\n\n"
                                + user_msg
                            ),
                        },
                    ]
                    continue
                raise
        if parsed is None:
            raise last_error or ValueError("库存 LLM 摘要解析失败")

        priorities_note = str(parsed.get("priorities_note", "")).strip()
        replenishment_focus = str(parsed.get("replenishment_focus", "")).strip()
        clearance_focus = str(parsed.get("clearance_focus", "")).strip()
        checklist_raw = parsed.get("coordination_checklist")
        checklist: List[str] = []
        if isinstance(checklist_raw, list):
            for item in checklist_raw:
                text = str(item).strip()
                if text:
                    checklist.append(text)
        if not priorities_note:
            raise ValueError("缺少 priorities_note")
        if not replenishment_focus:
            replenishment_focus = "先处理高销量短覆盖 SKU 的补货单，确保采购与仓配确认交期与到仓节奏。"
        if not clearance_focus:
            clearance_focus = "对高覆盖或高库龄 SKU 先冻结新增补货，再按渠道区分去化动作与观察窗口。"
        if not checklist:
            checklist = [
                "采购确认高优先级 SKU 的交期、最小起订量与可拆单空间。",
                "运营为高库存 SKU 安排去化节奏，并同步价格与内容策略。",
                "仓配核对在途与现货可用量，避免重复下单。",
            ]
        return {
            "priorities_note": priorities_note,
            "replenishment_focus": replenishment_focus,
            "clearance_focus": clearance_focus,
            "coordination_checklist": checklist[:5],
        }
