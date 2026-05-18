"""模拟竞品类目数据，用于 Gap Analysis（Issue 2.2）。"""
from typing import Dict, List, Optional

# category_key 与商品名称中的款式词对齐（规则匹配用）
COMPETITOR_BY_CATEGORY: List[Dict] = [
    {
        "category_key": "连衣裙",
        "competitor_new_skus_30d": 48,
        "price_band": "199-399",
        "ours_new_skus_30d": 14,
        "gap_note": "竞品连衣裙上新更快，价格带略低于我方主力款",
    },
    {
        "category_key": "衬衫",
        "competitor_new_skus_30d": 32,
        "price_band": "129-259",
        "ours_new_skus_30d": 18,
        "gap_note": "上新节奏接近，缺「静奢风」浅色系衬衫",
    },
    {
        "category_key": "T恤",
        "competitor_new_skus_30d": 60,
        "price_band": "79-159",
        "ours_new_skus_30d": 35,
        "gap_note": "竞品低价引流款多，我方可补多巴胺色系基础款",
    },
    {
        "category_key": "外套",
        "competitor_new_skus_30d": 22,
        "price_band": "299-699",
        "ours_new_skus_30d": 9,
        "gap_note": "外套类目竞品上新优势明显，建议加大美拉德/棕色系补位",
    },
    {
        "category_key": "裤子",
        "competitor_new_skus_30d": 28,
        "price_band": "159-329",
        "ours_new_skus_30d": 15,
        "gap_note": "裤装价格带重叠，差异化在版型与面料故事",
    },
]


def list_competitor_rows() -> List[Dict]:
    """返回竞品对照行（结构化）。"""
    return [dict(row) for row in COMPETITOR_BY_CATEGORY]


def get_rows_for_categories(category_keys: List[str], rows: Optional[List[Dict]] = None) -> List[Dict]:
    """按类目关键字筛选竞品行。"""
    keys = set(category_keys)
    source = rows if rows is not None else COMPETITOR_BY_CATEGORY
    return [row for row in source if row.get("category_key") in keys]
