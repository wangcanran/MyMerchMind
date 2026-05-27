"""SKU 级动态定价智能体。

定价逻辑分三层：
1. 竞品锚点：从竞品价格列表算出市场甜点（销量密度最高的价格区间中位）。
2. 成本底线：建议价不得低于 cost_price * MIN_MARGIN_FACTOR。
3. 策略调整：结合 SKU 的库存健康度 / 退货率 / 季节系数做 ±15% 幅度的微调。

开启 LLM（--llm）时，规则结果作为"基准价"输入给模型，由模型给出最终建议价和分析摘要；
LLM 失败则静默回退到规则结果，不中断编排。

输出字段：
- pricing_stage         ``executable``（在营、可当作调价参考）或 ``market_intel``（新品类情报，非锁价）
- binding_suggested_price  是否将 ``suggested_price`` 视为可执行锁价
- suggested_price       规则锚点后的数值（情报模式下仍为内部参考，报告侧重价带/成本上限）
- market_intel            仅 ``market_intel`` 时有值：参考价带、示意成本上限、假设毛利率说明
- price_position_pct    我们现售价在竞品中的百分位（0–100）
- strategy              定价策略名称
- competitor_summary    竞品价格概要（样本数 / 中位 / P25-P75 / 甜点价）
- reasoning             文字说明
- llm_analysis          LLM 给出的分析摘要（仅 use_llm=True 且成功时有值）
- llm_error             LLM 调用失败原因（失败时有值）
- pricing_exceptions    规则识别的定价例外场景（bool 标记）
- exception_explanation_rule  规则层例外说明（中文短句拼接）
- llm_exception_explanation  启用 LLM 时对例外的运营向解读（不改变建议价）
- llm_operator_cautions / llm_human_review_triggers  LLM 给出的注意点与人工复核触发
- llm_exception_error   例外解读 LLM 调用失败原因（若有）
"""
from __future__ import annotations

import json
import statistics
from typing import Any, Dict, List, Optional, Tuple

from ..config.return_rate_thresholds import high_return_fraction
from ..llm.json_util import parse_json_object

MIN_MARGIN_FACTOR = 1.15   # 成本保护：建议价 >= 成本 × 1.15
SWEET_BUCKET_WIDTH = 30    # 价格桶宽度（元），用于找销量密度最高的区间
DEFAULT_TARGET_GROSS_MARGIN = 0.45  # 企划 market_intel：示意成本上限 = 甜点价 × (1−毛利率)
MAX_STEP_PCT = 0.15        # 单次调价最大幅度 ±15%
CLEARANCE_STOCK_AGE_DAYS = 45  # 库龄超过此值视为清仓候选
CLEARANCE_TARGET_DAYS = 30     # 清仓目标天数


def normalize_target_gross_margin(raw: Optional[float]) -> float:
    """企划情报用目标毛利率：默认 0.45；>1 视为百分数（如 40 → 0.40）；夹紧到 [0.05, 0.85]。"""
    if raw is None:
        return DEFAULT_TARGET_GROSS_MARGIN
    try:
        m = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TARGET_GROSS_MARGIN
    if m > 1.0:
        m = m / 100.0
    if m != m:  # NaN
        return DEFAULT_TARGET_GROSS_MARGIN
    return max(0.05, min(0.85, m))


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _parse_sales_num(text: Any) -> Optional[float]:
    """把淘宝销量文本转成数字，无法解析返回 None。
    支持：「3000人付款」「1.2万+人付款」「已售5000+」「2.5万」
    不接受：「人看过」（浏览量，不代表销量）
    """
    if isinstance(text, (int, float)):
        return float(text) if text > 0 else None
    s = str(text or "").strip()
    if not s or "看过" in s:
        return None
    import re
    m = re.search(r"([\d.]+)\s*万", s)
    if m:
        return float(m.group(1)) * 10000
    m = re.search(r"([\d]+)\+?", s)
    if m:
        return float(m.group(1))
    return None


def _clean_prices(raw: List[Any]) -> List[float]:
    out: List[float] = []
    for v in raw or []:
        if v is None:
            continue
        try:
            p = float(v)
        except (TypeError, ValueError):
            continue
        if 1.0 <= p <= 99999.0:
            out.append(p)
    return out


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(len(sorted_vals) * pct / 100)))
    return sorted_vals[idx]


def _price_position(price: float, sorted_prices: List[float]) -> float:
    """price 在 sorted_prices 中的百分位（0–100）。"""
    if not sorted_prices:
        return 50.0
    below = sum(1 for p in sorted_prices if p < price)
    return round(below / len(sorted_prices) * 100, 1)


def _sweet_spot(prices: List[float], bucket_width: int = SWEET_BUCKET_WIDTH) -> Optional[float]:
    """找价格密度最高的桶，返回桶中位数。"""
    if not prices:
        return None
    lo = min(prices)
    buckets: Dict[int, List[float]] = {}
    for p in prices:
        key = int((p - lo) / bucket_width)
        buckets.setdefault(key, []).append(p)
    best_key = max(buckets, key=lambda k: len(buckets[k]))
    return round(statistics.median(buckets[best_key]))


def _sweet_spot_with_sales(
    products: List[Dict[str, Any]],
    bucket_width: int = SWEET_BUCKET_WIDTH,
) -> Optional[float]:
    """按价格桶聚合销量，找销量最集中的桶，返回桶中位价。

    products 是 taobao_search 返回的原始列表（含 price / sales 字段）。
    如果没有足够的销量数据，降级到纯价格密度。
    """
    priced = []
    for p in products or []:
        price = None
        try:
            price = float(p.get("price") or 0)
        except (TypeError, ValueError):
            pass
        if not price or price < 1:
            continue
        sales = _parse_sales_num(p.get("sales"))
        priced.append((price, sales or 0.0))

    if not priced:
        return None

    has_sales = any(s > 0 for _, s in priced)
    if not has_sales:
        return _sweet_spot([pr for pr, _ in priced], bucket_width)

    lo = min(pr for pr, _ in priced)
    buckets: Dict[int, Tuple[List[float], float]] = {}
    for price, sales in priced:
        key = int((price - lo) / bucket_width)
        plist, stot = buckets.get(key, ([], 0.0))
        plist.append(price)
        buckets[key] = (plist, stot + sales)

    best_key = max(buckets, key=lambda k: buckets[k][1])
    return round(statistics.median(buckets[best_key][0]))


# ---------------------------------------------------------------------------
# SKU 角色判定 & 弹性估算
# ---------------------------------------------------------------------------

def _determine_role(
    product_info: Dict[str, Any],
    daily_sales_percentile: float,
) -> str:
    """根据 SKU 状态判定定价角色。

    返回: traffic / profit / image / clearance
    """
    stock_age = int(product_info.get("stock_age_days") or 0)
    return_rate = float(product_info.get("return_rate") or 0)
    conversion = float(product_info.get("conversion_rate") or 0)
    daily_sales = int(product_info.get("daily_sales") or 0)
    price = float(product_info.get("price") or 0)

    # 清仓款：库龄高 或 高退货+低转化
    if stock_age >= CLEARANCE_STOCK_AGE_DAYS:
        return "clearance"
    if return_rate >= high_return_fraction() and conversion < 0.015:
        return "clearance"

    # 引流款：日销 Top 20% 且转化率高
    if daily_sales_percentile >= 0.80 and conversion >= 0.025:
        return "traffic"

    # 形象款：高客单 + 低销量
    if price >= 300 and daily_sales_percentile < 0.40:
        return "image"

    # 其余为利润款
    return "profit"


def _estimate_elasticity(
    price_history: Optional[List[Dict[str, Any]]],
    competitor_products: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """用价格-销量历史拟合对数线性弹性系数。

    模型: ln(Q) = a - ε × ln(P)
    返回 {value, confidence, sample_count, r_squared, data_source} 或 None。
    """
    import math

    own_points = []
    for rec in (price_history or []):
        p = float(rec.get("price") or 0)
        q = float(rec.get("daily_sales") or 0)
        if p > 0 and q > 0:
            own_points.append((math.log(p), math.log(q)))

    points = list(own_points)
    data_source = "price_history"

    if len(points) < 3:
        # 尝试用竞品数据近似
        if competitor_products:
            for cp in competitor_products:
                p = float(cp.get("price") or 0)
                q = _parse_sales_num(cp.get("sales"))
                if p > 0 and q and q > 0:
                    points.append((math.log(p), math.log(q)))
            if len(points) >= 3 and len(own_points) < 3:
                data_source = "competitor_proxy"

    if len(points) < 3:
        return None

    # 最小二乘法: ε = -Σ((x-x̄)(y-ȳ)) / Σ((x-x̄)²)
    n = len(points)
    x_vals = [p[0] for p in points]
    y_vals = [p[1] for p in points]
    x_mean = sum(x_vals) / n
    y_mean = sum(y_vals) / n

    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
    denominator = sum((x - x_mean) ** 2 for x in x_vals)

    if abs(denominator) < 1e-10:
        return None

    slope = numerator / denominator  # 应为负数（价格涨→销量跌）
    elasticity = -slope  # 取正

    # 合理范围约束
    if elasticity < 0.5 or elasticity > 8.0:
        return None

    # 计算 R²（拟合优度）
    ss_res = sum((y - (y_mean + slope * (x - x_mean))) ** 2 for x, y in zip(x_vals, y_vals))
    ss_tot = sum((y - y_mean) ** 2 for y in y_vals)
    r_squared = round(1.0 - ss_res / ss_tot, 3) if ss_tot > 1e-10 else 0.0

    # 置信度评估：基于样本数 + R² + 数据来源
    confidence = 0.0
    # 样本数贡献（3→0.3, 5→0.4, 10+→0.5）
    confidence += min(0.5, 0.2 + n * 0.03)
    # R² 贡献（0→0, 0.8→0.32, 1.0→0.4）
    confidence += max(0.0, r_squared) * 0.4
    # 自有数据加分
    if data_source == "price_history":
        confidence += 0.1
    confidence = round(min(1.0, confidence), 2)

    return {
        "value": round(elasticity, 2),
        "confidence": confidence,
        "sample_count": n,
        "r_squared": r_squared,
        "data_source": data_source,
    }


def _optimal_price_profit(cost: float, elasticity: float) -> float:
    """利润最大化公式: P* = cost × ε / (ε - 1)"""
    if elasticity <= 1.0:
        # 弹性≤1 时公式不适用（需求不够弹性），回退到成本加成
        return cost * 2.2
    return cost * elasticity / (elasticity - 1.0)


def _clearance_price(
    current_price: float,
    cost: float,
    stock: int,
    daily_sales: int,
    target_days: int = CLEARANCE_TARGET_DAYS,
) -> float:
    """清仓定价：根据库存压力倒推降价幅度。"""
    floor = cost * 1.05  # 清仓底线：微利
    if daily_sales <= 0:
        return floor

    remaining_days = stock / daily_sales
    if remaining_days <= target_days:
        # 库存不多，小幅降价即可
        ratio = 0.90
    elif remaining_days <= target_days * 2:
        ratio = 0.80
    else:
        ratio = 0.70

    price = current_price * ratio
    return max(price, floor)


def _apply_step_constraint(
    suggested: float,
    current_price: float,
    role: str,
) -> Dict[str, Any]:
    """调幅约束：单次不超过 ±15%（清仓款放宽到 ±25%）。"""
    max_pct = 0.25 if role == "clearance" else MAX_STEP_PCT

    if current_price <= 0:
        return {"final_price": round(suggested), "step_plan": None, "capped": False}

    max_price = current_price * (1 + max_pct)
    min_price = current_price * (1 - max_pct)

    if min_price <= suggested <= max_price:
        return {"final_price": round(suggested), "step_plan": None, "capped": False}

    # 需要分步调价
    target = suggested
    capped = round(max(min_price, min(max_price, suggested)))
    diff = abs(target - current_price)
    step_size = current_price * max_pct
    steps = max(1, int(diff / step_size + 0.5)) if step_size > 0 else 1

    return {
        "final_price": capped,
        "step_plan": {
            "target_price": round(target),
            "steps_needed": steps,
            "per_step_pct": round(max_pct * 100),
            "note": f"目标价 ¥{round(target)}，建议分 {steps} 步调整，每步≤{round(max_pct*100)}%",
        },
        "capped": True,
    }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class DynamicPricingAgent:
    """SKU 级动态定价智能体。"""

    def __init__(self, llm_client: Optional[Any] = None, use_llm: bool = False):
        self._llm = llm_client
        self._use_llm = bool(use_llm and llm_client is not None)

    def analyze(
        self,
        product_info: Dict[str, Any],
        competitor_prices: List[float],
        store_cost_price: float,
        seasonal_factor: float = 1.0,
        competitor_products: Optional[List[Dict[str, Any]]] = None,
        *,
        pricing_mode: str = "executable",
        target_gross_margin: Optional[float] = None,
        daily_sales_percentile: float = 0.5,
        relevant_experiences: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        参数
        ----
        product_info        SKU 字典，含 name / price / cost_price / daily_sales /
                            stock / return_rate 等字段。
        competitor_prices   竞品价格列表（已清洗的 float 列表）。
        store_cost_price    SKU 成本价；为 0 时不做成本约束。
        seasonal_factor     季节系数：>1 旺季可适当提价，<1 淡季压价。
        competitor_products 原始竞品列表（含 price + sales 字段），有则用于
                            计算销量加权甜点价，比纯价格密度更准确。
        pricing_mode        ``executable``：按成本底线输出可执行建议价；``market_intel``：
                            企划/新品类情报，输出市场参考价带与**示意**成本上限（假设毛利率），
                            不作为锁价；此时不调用 LLM 覆盖以免误锁价。
        target_gross_margin 可选；企划 ``market_intel`` 下用于 ``implied_cost_ceiling`` 计算
                            （售价侧毛利率，甜点价 × (1−该值)）。缺省见 ``DEFAULT_TARGET_GROSS_MARGIN``。
        """
        prices = sorted(_clean_prices(competitor_prices))
        cost = float(store_cost_price or 0)
        current_price = float(product_info.get("price") or 0)
        return_rate = float(product_info.get("return_rate") or 0)
        daily_sales = int(product_info.get("daily_sales") or 0)
        stock = int(product_info.get("stock") or 0)

        # ── 1. 竞品价格概要 ──────────────────────────────────────────────────
        if prices:
            comp_median = statistics.median(prices)
            comp_p25 = _percentile(prices, 25)
            comp_p75 = _percentile(prices, 75)
            if competitor_products:
                sweet = _sweet_spot_with_sales(competitor_products)
            else:
                sweet = _sweet_spot(prices)
            sweet = sweet or comp_median
            comp_summary = {
                "sample_count": len(prices),
                "median": round(comp_median),
                "p25": round(comp_p25),
                "p75": round(comp_p75),
                "sweet_spot": round(sweet),
            }
        else:
            comp_median = comp_p25 = comp_p75 = sweet = None
            comp_summary = {"sample_count": 0}

        # ── 2. 判定 SKU 角色 ─────────────────────────────────────────────────
        role = _determine_role(product_info, daily_sales_percentile)

        # ── 3. 估算价格弹性 ─────────────────────────────────────────────────
        price_history = product_info.get("price_history")
        elasticity_result = _estimate_elasticity(price_history, competitor_products)
        elasticity = elasticity_result["value"] if elasticity_result else None
        elasticity_confidence = elasticity_result["confidence"] if elasticity_result else None

        # ── 4. 按角色计算最优价 ──────────────────────────────────────────────
        if role == "traffic":
            # 引流款：卡竞品低位
            if sweet is not None:
                raw_price = sweet * 0.85
            elif comp_p25 is not None:
                raw_price = comp_p25
            else:
                raw_price = current_price * 0.90
            strategy = "引流款·竞品低位卡位"
            anchor_source = "竞品P25附近"

        elif role == "profit":
            # 利润款：弹性模型利润最大化
            if elasticity and cost > 0:
                raw_price = _optimal_price_profit(cost, elasticity)
                strategy = f"利润款·弹性定价(ε={elasticity})"
                anchor_source = "利润最大化公式"
            elif sweet is not None:
                raw_price = sweet
                strategy = "利润款·跟随甜点价"
                anchor_source = "竞品销量甜点价"
            else:
                raw_price = cost * 2.2 if cost > 0 else current_price
                strategy = "利润款·成本加成"
                anchor_source = "成本×2.2"
            # 约束在竞品 P25-P75 区间
            if comp_p25 is not None and comp_p75 is not None:
                raw_price = max(comp_p25, min(comp_p75, raw_price))

        elif role == "image":
            # 形象款：维持高位，不主动降价
            if comp_p75 is not None:
                raw_price = max(current_price, comp_p75)
            else:
                raw_price = current_price
            strategy = "形象款·维持品牌溢价"
            anchor_source = "现售价/竞品P75"

        else:  # clearance
            raw_price = _clearance_price(
                current_price, cost,
                int(product_info.get("stock") or 0),
                daily_sales,
            )
            strategy = "清仓款·限期出清"
            anchor_source = "库存压力倒推"

        # 旺/淡季微调（非清仓款）
        if role != "clearance":
            if seasonal_factor < 0.85:
                raw_price *= 0.97
                strategy += "+淡季"
            elif seasonal_factor > 1.10:
                raw_price *= 1.03
                strategy += "+旺季"

        # ── 5. 成本底线保护 ──────────────────────────────────────────────────
        cost_floor = round(cost * MIN_MARGIN_FACTOR) if cost > 0 else 0
        if cost_floor > 0 and raw_price < cost_floor:
            raw_price = cost_floor
            strategy += "（已触成本底线）"

        # ── 6. 调幅约束 ─────────────────────────────────────────────────────
        step_result = _apply_step_constraint(raw_price, current_price, role)
        suggested = step_result["final_price"]
        step_plan = step_result["step_plan"]

        # ── 7. 百分位定位 ────────────────────────────────────────────────────
        position_pct: Optional[float] = None
        if prices and suggested > 0:
            position_pct = _price_position(float(suggested), prices)

        # ── 8. 文字说明 ──────────────────────────────────────────────────────
        parts = []
        parts.append(f"角色：{role}。")
        if elasticity:
            conf_label = "高" if (elasticity_confidence or 0) >= 0.7 else "中" if (elasticity_confidence or 0) >= 0.45 else "低"
            parts.append(f"价格弹性 ε={elasticity}（置信度{conf_label} {elasticity_confidence}）。")
        if sweet is not None:
            parts.append(
                f"竞品样本 {len(prices)} 条，甜点价 ¥{round(sweet)}，"
                f"P25–P75 ¥{round(comp_p25)}–¥{round(comp_p75)}。"
            )
        if cost > 0:
            parts.append(f"成本 ¥{round(cost)}，底线 ¥{cost_floor}。")
        if step_plan:
            parts.append(step_plan["note"])
        if position_pct is not None:
            parts.append(f"建议价位于竞品第 {position_pct:.0f} 百分位。")
        reasoning = " ".join(parts)

        mode = (pricing_mode or "executable").strip().lower()
        if mode not in {"executable", "market_intel"}:
            mode = "executable"

        assumed_margin = normalize_target_gross_margin(target_gross_margin)

        result: Dict[str, Any] = {
            "sku_id": product_info.get("sku_id", ""),
            "name": product_info.get("name", ""),
            "current_price": round(current_price) if current_price else None,
            "cost_price": round(cost) if cost else None,
            "suggested_price": suggested,
            "role": role,
            "elasticity": elasticity,
            "elasticity_confidence": elasticity_confidence,
            "elasticity_detail": elasticity_result,
            "optimal_price": round(raw_price) if raw_price else None,
            "step_plan": step_plan,
            "price_position_pct": position_pct,
            "strategy": strategy,
            "competitor_summary": comp_summary,
            "reasoning": reasoning,
            "anchor_source": anchor_source,
            "llm_analysis": None,
            "llm_error": None,
            "pricing_stage": mode,
            "binding_suggested_price": mode == "executable",
            "market_intel": None,
            "pricing_exceptions": {},
            "exception_explanation_rule": "",
            "llm_exception_explanation": None,
            "llm_operator_cautions": None,
            "llm_human_review_triggers": None,
            "llm_exception_error": None,
        }

        exc_flags, exc_lines = self._collect_pricing_exceptions(
            prices=prices,
            comp_median=comp_median,
            comp_p25=comp_p25,
            comp_p75=comp_p75,
            current_price=current_price,
            suggested=suggested,
            strategy=strategy,
            return_rate=return_rate,
            daily_sales=daily_sales,
            stock=stock,
        )
        result["pricing_exceptions"] = exc_flags
        result["exception_explanation_rule"] = " ".join(exc_lines).strip()

        if mode == "market_intel" and prices and sweet is not None and comp_p25 is not None and comp_p75 is not None:
            # 企划阶段：用 P25–P75 作「市场可卖区间」，甜点作锚点；示意成本上限 = 甜点价 × (1−目标毛利率)
            implied_ceiling = max(1, int(round(float(sweet) * (1.0 - assumed_margin))))
            pct = int(round(assumed_margin * 100))
            mi_dict: Dict[str, Any] = {
                "reference_band": f"{round(comp_p25)}-{round(comp_p75)}",
                "sweet_spot": round(sweet),
                "median": round(comp_median) if comp_median is not None else None,
                "assumed_target_gross_margin": assumed_margin,
                "implied_cost_ceiling": implied_ceiling,
                "disclaimer": (
                    f"企划/新品类情报：区间为竞品 P25–P75，成本上限按甜点价与目标毛利率 {pct}% 示意，"
                    "待真实 BOM/报价后再定正式标价。"
                ),
            }
            if float(sweet) + 1e-6 < float(comp_p25):
                mi_dict["anchor_band_tension"] = "sweet_below_p25"
                mi_dict["sweet_vs_band_note"] = (
                    "注：甜点锚点可能低于 P25 下沿，并非「P25 与甜点」的算术矛盾："
                    "甜点价为按销量加权的价格桶中位，低价段竞品成交密集时会拉低锚点；"
                    "价带仍以 P25–P75 表征稳健成交区间，请结合链接样本复核。"
                )
            elif float(sweet) > float(comp_p75) + 1e-6:
                mi_dict["anchor_band_tension"] = "sweet_above_p75"
                mi_dict["sweet_vs_band_note"] = (
                    "注：甜点锚点高于 P75 上沿时，多为头部爆款或样本偏差；"
                    "建议抽样核对高价链接是否可比（套装/多件/品牌溢价）。"
                )
            result["market_intel"] = mi_dict
            result["reasoning"] = (
                f"{result['market_intel']['disclaimer']} {reasoning}".strip()
            )
        elif mode == "market_intel":
            pct = int(round(assumed_margin * 100))
            result["market_intel"] = {
                "reference_band": None,
                "sweet_spot": None,
                "median": None,
                "assumed_target_gross_margin": assumed_margin,
                "implied_cost_ceiling": None,
                "disclaimer": (
                    f"企划/新品类情报：暂无有效竞品价样本，未完成市场区间与示意成本上限（目标毛利率 {pct}%）；"
                    "请补爬或人工估价后再议。"
                ),
            }
            result["reasoning"] = (
                f"{result['market_intel']['disclaimer']} {reasoning}".strip()
            )

        if self._use_llm and self._llm is not None:
            exf = result.get("pricing_exceptions") or {}
            if result.get("exception_explanation_rule") or any(
                bool(exf.get(k))
                for k in (
                    "no_competitors",
                    "high_price_jump_vs_current",
                    "wide_competitor_spread",
                    "touched_cost_floor",
                    "high_return_discount",
                    "high_inventory_discount",
                    "deep_coverage_without_promo_flag",
                )
            ):
                self._llm_pricing_exception_brief(result, product_info, seasonal_factor)

        # ── LLM 增强（可选）：仅可执行模式，避免情报价被模型锁成「正式价」────────
        if self._use_llm and self._llm is not None and mode == "executable":
            result = self._enrich_with_llm(result, product_info, seasonal_factor, relevant_experiences)

        return result

    @staticmethod
    def _collect_pricing_exceptions(
        *,
        prices: List[float],
        comp_median: Optional[float],
        comp_p25: Optional[float],
        comp_p75: Optional[float],
        current_price: float,
        suggested: int,
        strategy: str,
        return_rate: float,
        daily_sales: int,
        stock: int,
    ) -> Tuple[Dict[str, Any], List[str]]:
        flags: Dict[str, Any] = {
            "no_competitors": len(prices) == 0,
            "high_price_jump_vs_current": False,
            "wide_competitor_spread": False,
            "touched_cost_floor": "成本底线" in strategy,
            "high_return_discount": ("高退货" in strategy) or (
                return_rate >= high_return_fraction() and "压价" in strategy
            ),
            "high_inventory_discount": "高库存促销" in strategy,
            "deep_coverage_without_promo_flag": False,
        }
        lines: List[str] = []
        if flags["no_competitors"]:
            lines.append("【例外】无有效竞品样本，锚点依赖成本或现售；建议补数据后再调价。")
        if current_price > 0 and suggested > 0:
            rel = abs(float(suggested) - float(current_price)) / float(current_price)
            if rel >= 0.25:
                flags["high_price_jump_vs_current"] = True
                lines.append(
                    f"【例外】建议价相对现价变动约 {rel*100:.0f}%，属大幅调整，需活动/权限与供应链确认。"
                )
        if (
            comp_median is not None
            and comp_p25 is not None
            and comp_p75 is not None
            and float(comp_median) > 0
        ):
            spread = float(comp_p75) - float(comp_p25)
            if spread > float(comp_median) * 1.25:
                flags["wide_competitor_spread"] = True
                lines.append("【例外】竞品价差带宽偏大，甜点价代表性下降，建议分层对标或人工抽样。")
        if flags["touched_cost_floor"]:
            lines.append("【例外】建议价已顶到成本毛利底线，继续下探需特批或改成本结构。")
        if flags["high_return_discount"]:
            lines.append("【例外】高退货触发压价；需同步排查质量/尺码/描述，避免单纯降价放大亏损。")
        if flags["high_inventory_discount"]:
            lines.append("【例外】高库存覆盖触发促销性降价；注意与渠道价盘、清仓节奏协调。")
        if daily_sales > 0 and stock / max(daily_sales, 1) > 60 and "高库存促销" not in strategy:
            flags["deep_coverage_without_promo_flag"] = True
            lines.append("【提示】库存覆盖仍偏高但未命中促销规则阈值，可关注是否需调参。")
        return flags, lines

    def _llm_pricing_exception_brief(
        self,
        result: Dict[str, Any],
        product_info: Dict[str, Any],
        seasonal_factor: float,
    ) -> None:
        from ..llm import prompts

        if not self._llm:
            return
        payload = {
            "sku_id": product_info.get("sku_id", ""),
            "name": product_info.get("name", ""),
            "pricing_stage": result.get("pricing_stage"),
            "strategy": result.get("strategy"),
            "suggested_price": result.get("suggested_price"),
            "current_price": result.get("current_price"),
            "seasonal_factor": round(float(seasonal_factor), 3),
            "pricing_exceptions": result.get("pricing_exceptions"),
            "exception_explanation_rule": result.get("exception_explanation_rule"),
            "competitor_summary": result.get("competitor_summary"),
            "market_intel": result.get("market_intel"),
        }
        user_msg = prompts.DYNAMIC_PRICING_EXCEPTION_USER.format(
            payload=json.dumps(payload, ensure_ascii=False),
        )
        try:
            raw = self._llm.chat(
                [
                    {"role": "system", "content": prompts.DYNAMIC_PRICING_EXCEPTION_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
            )
            parsed = parse_json_object(raw)
            ex = str(parsed.get("exception_explanation", "") or "").strip()
            if ex:
                result["llm_exception_explanation"] = ex
            cautions = parsed.get("operator_cautions")
            if isinstance(cautions, list):
                result["llm_operator_cautions"] = [
                    str(x).strip() for x in cautions if str(x).strip()
                ][:8]
            triggers = parsed.get("human_review_triggers")
            if isinstance(triggers, list):
                result["llm_human_review_triggers"] = [
                    str(x).strip() for x in triggers if str(x).strip()
                ][:5]
        except Exception:  # noqa: BLE001
            result["llm_exception_error"] = None
            if not (result.get("llm_exception_explanation") or "").strip():
                result["llm_exception_explanation"] = (
                    "（LLM 定价例外解读生成失败，已忽略；请以上方规则层「定价例外」与 exception_explanation_rule 为准。）"
                )

    def _enrich_with_llm(
        self,
        rule_result: Dict[str, Any],
        product_info: Dict[str, Any],
        seasonal_factor: float,
        relevant_experiences: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        from ..llm.prompts import DYNAMIC_PRICING_SYSTEM, DYNAMIC_PRICING_USER

        # 构建完整上下文：SKU 信息 + 规则分析结果
        product_summary = {
            "sku_id": product_info.get("sku_id", ""),
            "name": product_info.get("name", ""),
            "current_price": product_info.get("price"),
            "daily_sales": product_info.get("daily_sales"),
            "return_rate": product_info.get("return_rate"),
            "stock": product_info.get("stock"),
            "stock_age_days": product_info.get("stock_age_days"),
            "conversion_rate": product_info.get("conversion_rate"),
        }

        # 规则层分析结果——让 LLM 看到完整推理过程
        rule_analysis = {
            "role": rule_result.get("role"),
            "elasticity": rule_result.get("elasticity"),
            "rule_suggested_price": rule_result.get("suggested_price"),
            "strategy": rule_result.get("strategy"),
            "anchor_source": rule_result.get("anchor_source"),
            "step_plan": rule_result.get("step_plan"),
            "price_position_pct": rule_result.get("price_position_pct"),
            "pricing_exceptions": rule_result.get("pricing_exceptions"),
            "exception_explanation_rule": rule_result.get("exception_explanation_rule"),
        }

        # 价格历史（截取最近 10 条避免 token 过长）
        price_history = product_info.get("price_history") or []
        if len(price_history) > 10:
            price_history = price_history[-10:]

        # 相关历史经验
        experience_text = ""
        if relevant_experiences:
            exp_lines = []
            for exp in relevant_experiences[:3]:  # 最多 3 条避免 token 过长
                ref_idx = exp.get("_ref_index", "?")
                conf = exp.get("confidence", "")
                title = exp.get("title", "")
                narrative = exp.get("narrative", "")
                if narrative and len(narrative) > 120:
                    narrative = narrative[:120] + "…"
                exp_lines.append(f"[{ref_idx}] [{conf}] {title}：{narrative}")
            if exp_lines:
                experience_text = "\n".join(exp_lines)

        user_msg = DYNAMIC_PRICING_USER.format(
            product_info=json.dumps(product_summary, ensure_ascii=False),
            rule_analysis=json.dumps(rule_analysis, ensure_ascii=False),
            price_history=json.dumps(price_history, ensure_ascii=False) if price_history else "无",
            competitor_summary=json.dumps(rule_result["competitor_summary"], ensure_ascii=False),
            store_cost_price=rule_result.get("cost_price") or 0,
            seasonal_factor=round(seasonal_factor, 2),
            experience_context=experience_text or "无",
        )
        try:
            raw = self._llm.chat(
                [
                    {"role": "system", "content": DYNAMIC_PRICING_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
            )
            clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            parsed = json.loads(clean)
            if isinstance(parsed.get("suggested_price"), (int, float)):
                llm_raw_price = int(round(float(parsed["suggested_price"])))
                llm_price = llm_raw_price
                guardrails_applied: List[str] = []

                # 成本底线保护：LLM 也不能低于底线
                cost_floor = rule_result.get("cost_price") or 0
                if cost_floor:
                    min_floor = int(round(cost_floor * MIN_MARGIN_FACTOR))
                    if llm_price < min_floor:
                        guardrails_applied.append(f"成本底线（¥{min_floor}）")
                        llm_price = min_floor

                # 调幅护栏：LLM 也受单次调幅约束
                current_price = rule_result.get("current_price") or 0
                if current_price and current_price > 0:
                    role = rule_result.get("role", "profit")
                    max_pct = 0.25 if role == "clearance" else MAX_STEP_PCT
                    upper = int(current_price * (1 + max_pct))
                    lower = int(current_price * (1 - max_pct))
                    if llm_price > upper:
                        guardrails_applied.append(f"单次涨幅上限（+{int(max_pct*100)}%=¥{upper}）")
                        llm_price = upper
                    elif llm_price < lower:
                        guardrails_applied.append(f"单次降幅上限（-{int(max_pct*100)}%=¥{lower}）")
                        llm_price = lower

                rule_result["suggested_price"] = llm_price
                rule_result["llm_raw_price"] = llm_raw_price
                if guardrails_applied:
                    rule_result["guardrail_applied"] = guardrails_applied
                    rule_result["guardrail_note"] = (
                        f"LLM 原始建议 ¥{llm_raw_price}，被护栏调整为 ¥{llm_price}（{'; '.join(guardrails_applied)}）"
                    )
                strategy_name = parsed.get("strategy_name") or "LLM智能定价"
                rule_result["strategy"] = str(strategy_name)
            if parsed.get("analysis_summary"):
                rule_result["llm_analysis"] = str(parsed["analysis_summary"])
            if parsed.get("reasoning"):
                rule_result["reasoning"] = str(parsed["reasoning"])
            if parsed.get("risk_notes"):
                rule_result["llm_risk_notes"] = str(parsed["risk_notes"])
        except Exception as exc:  # noqa: BLE001
            rule_result["llm_error"] = str(exc)

        return rule_result
