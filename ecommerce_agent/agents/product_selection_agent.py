"""选品 Agent（M2 Baseline：规则映射 + 竞品 Gap + 首单 MOQ）。"""
from typing import Dict, List, Tuple

from ..memory.feedback_store import FeedbackMemoryStore
from ..data.mock_competitors import get_rows_for_categories


def map_trend_to_merch_rules(keyword: str) -> Dict:
    """从趋势关键词推导商品需求（可替换为 LLM）。"""
    kw = keyword.lower()
    rules: List[Tuple[List[str], Dict]] = [
        (["美拉德", "棕色", "咖啡"], {
            "suggested_categories": ["连衣裙", "外套", "裤子"],
            "color_focus": ["咖啡色", "深棕色", "卡其"],
            "material_focus": ["羊毛混纺", "牛仔"],
            "story": "美拉德色系可补裙装与外套，强调棕色梯度搭配",
        }),
        (["多巴胺", "亮色"], {
            "suggested_categories": ["T恤", "连衣裙"],
            "color_focus": ["白色", "米色"],
            "material_focus": ["棉", "涤纶"],
            "story": "多巴胺/亮色趋势下，基础款 T 恤与裙装可做流量款",
        }),
        (["静奢", "极简"], {
            "suggested_categories": ["衬衫", "外套"],
            "color_focus": ["米色", "白色", "黑色"],
            "material_focus": ["天丝", "羊毛混纺"],
            "story": "静奢风侧重衬衫与外套的质感与剪裁",
        }),
        (["牛仔"], {
            "suggested_categories": ["外套", "裤子"],
            "color_focus": ["黑色", "深棕色"],
            "material_focus": ["牛仔"],
            "story": "牛仔元素可在外套与裤装加深布局",
        }),
    ]
    for keys, payload in rules:
        for k in keys:
            if k.lower() in kw or k in keyword:
                return dict(payload, matched_keyword=k)
    return {
        "suggested_categories": ["连衣裙", "衬衫", "T恤"],
        "color_focus": ["黑色", "白色", "米色"],
        "material_focus": ["棉", "涤纶"],
        "story": "未命中专项规则，按通用女装品类做宽覆盖",
        "matched_keyword": "",
    }


def _moq_for_risk(heat_score: float, growth_rate: float) -> Tuple[str, int, int]:
    """风险分级与首单件数区间（规则版）。heat_score 为社媒原始热度，先归一化到 0–100。"""
    norm = min(100.0, max(0.0, heat_score / 500.0))
    risk_score = norm * (1 + max(growth_rate, 0))
    if risk_score >= 55:
        level = "中风险"
        low, high = 80, 150
    elif risk_score >= 35:
        level = "中低风险"
        low, high = 120, 220
    else:
        level = "偏高风险"
        low, high = 40, 90
    return level, low, high


class ProductSelectionAgent:
    """基于规则与标签匹配的选品建议。"""

    def analyze(
        self,
        top_trends: List[Dict],
        growing_trends: List[Dict],
        sku_metrics: List[Dict],
        all_sku_tags: Dict[str, Dict[str, str]],
        competitor_rows: List[Dict],
        memory: FeedbackMemoryStore,
        top_n: int = 5,
    ) -> Dict:
        data_source = "mock"
        trend_picks: List[Dict] = []
        primary = top_trends[0] if top_trends else {"keyword": "通用", "heat_score": 50, "growth_rate": 0.0}
        merch = map_trend_to_merch_rules(primary.get("keyword", ""))
        cats = merch.get("suggested_categories", [])
        gap_rows = get_rows_for_categories(cats) if cats else competitor_rows[:3]

        heat = float(primary.get("heat_score", 50))
        growth = float(primary.get("growth_rate", 0.0))
        risk_level, moq_lo, moq_hi = _moq_for_risk(heat, growth)

        memory_hits_summary: List[Dict] = []
        for sku in sku_metrics[: top_n * 2]:
            sid = sku["sku_id"]
            tags = all_sku_tags.get(sid, {})
            hits = memory.find_hits_for_tags(tags)
            if hits:
                memory_hits_summary.append({"sku_id": sid, "name": sku["name"], "hits": hits})

        tag_overlap: List[Dict] = []
        for sku in sku_metrics[:top_n]:
            sid = sku["sku_id"]
            tags = all_sku_tags.get(sid, {})
            color = tags.get("color", "")
            style = tags.get("style", "")
            overlap = color in merch.get("color_focus", []) or style in str(merch.get("material_focus", []))
            tag_overlap.append(
                {
                    "sku_id": sid,
                    "name": sku["name"],
                    "tags": tags,
                    "aligns_with_trend_merch": bool(overlap),
                }
            )

        trend_picks.append(
            {
                "keyword": primary.get("keyword"),
                "merch_mapping": merch,
                "competitor_gaps": gap_rows,
                "moq": {
                    "risk_level": risk_level,
                    "suggested_range_pcs": [moq_lo, moq_hi],
                    "note": "首单量结合趋势热度与增长率分级，偏高风险收窄试单量",
                },
                "data_source": data_source,
            }
        )

        recommendations: List[str] = []
        recommendations.append(
            f"围绕「{primary.get('keyword', '当季')}」：{merch.get('story', '')}"
        )
        if gap_rows:
            g0 = gap_rows[0]
            recommendations.append(
                f"竞品缺口参考：{g0.get('category_key')} 类目 — {g0.get('gap_note', '')}"
            )
        recommendations.append(
            f"首单建议区间 {moq_lo}-{moq_hi} 件（{risk_level}），需结合供应链 MOQ 复核。"
        )
        if memory_hits_summary:
            recommendations.append(
                f"避雷记忆命中 {len(memory_hits_summary)} 个 SKU，选品时需标注风险或拦截相似材质/风格。"
            )

        return {
            "trend_picks": trend_picks,
            "tag_overlap_sample": tag_overlap,
            "memory_hits": memory_hits_summary,
            "recommendations": recommendations,
            "data_source": data_source,
        }
