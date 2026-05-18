"""模拟商品多维标签（Issue 1.3 Baseline：确定性生成，非多模态）。"""
import random
from typing import Dict, List, Optional


_COLLAR = ["圆领", "V领", "翻领", "方领"]
_MATERIAL = ["棉", "涤纶", "羊毛混纺", "天丝", "牛仔"]
_STYLE = ["休闲", "通勤", "静奢", "多巴胺", "美拉德"]
_COLOR = ["黑色", "白色", "米色", "咖啡色", "深棕色", "卡其"]


class ProductTagStore:
    """按 SKU 列表生成稳定可复现的结构化标签。"""

    def __init__(self, seed: Optional[int], sku_ids: List[str]):
        self._rng = random.Random(seed)
        self._tags: Dict[str, Dict[str, str]] = {}
        for sku_id in sorted(sku_ids):
            self._rng.seed(seed + sum(ord(c) for c in sku_id))
            self._tags[sku_id] = {
                "collar": self._rng.choice(_COLLAR),
                "material": self._rng.choice(_MATERIAL),
                "style": self._rng.choice(_STYLE),
                "color": self._rng.choice(_COLOR),
            }
        self._rng.seed(seed)

    def get_sku_tags(self, sku_id: str) -> Dict[str, str]:
        return dict(self._tags.get(sku_id, {}))

    def all_tags(self) -> Dict[str, Dict[str, str]]:
        return {k: dict(v) for k, v in self._tags.items()}
