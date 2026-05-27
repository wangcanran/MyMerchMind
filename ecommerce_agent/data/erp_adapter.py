"""ERP/OMS 统一适配层"""
from typing import Dict, List, Optional

from ..config.return_rate_thresholds import high_return_fraction

from .mock_competitors import list_competitor_rows
from .mock_erp import MockERPData, StaticERPData
from .mock_product_tags import ProductTagStore


class ERPAdapter:
    """统一的 ERP 数据访问接口"""

    def __init__(
        self,
        seed: Optional[int] = None,
        sku_table: Optional[Dict[str, Dict]] = None,
        tags_table: Optional[Dict[str, Dict[str, str]]] = None,
        competitor_rows: Optional[List[Dict]] = None,
    ):
        if sku_table is not None:
            self.data_source = StaticERPData(sku_table)
        else:
            self.data_source = MockERPData(seed=seed)
        sku_ids = sorted(self.data_source.skus.keys())
        self._tags_table = tags_table
        self._tag_store = None if tags_table is not None else ProductTagStore(seed=seed, sku_ids=sku_ids)
        self._competitor_rows = competitor_rows

    def get_all_skus(self) -> List[Dict]:
        """获取全部 SKU 原始指标（用于复盘与预警）"""
        items: List[Dict] = []
        for sku_id in sorted(self.data_source.skus.keys()):
            sku = self.data_source.skus[sku_id]
            items.append({
                "sku_id": sku_id,
                "name": sku["name"],
                "price": sku.get("price"),
                "cost_price": sku.get("cost_price"),
                "daily_sales": sku["daily_sales"],
                "stock": sku["stock"],
                "in_transit": sku["in_transit"],
                "return_rate": sku["return_rate"],
                "channel_sales": sku["channel_sales"],
                "conversion_rate": sku["conversion_rate"],
                "stock_age_days": sku["stock_age_days"],
                "review_snippets": sku["review_snippets"],
                "prior_week_total_units": sku["prior_week_total_units"],
                "prior_month_total_units": sku["prior_month_total_units"],
                "price_history": sku.get("price_history"),
            })
        return items

    def get_sku_tags(self, sku_id: str) -> Dict[str, str]:
        """多维标签（领型/材质/风格/颜色）。"""
        if self._tags_table is not None:
            return dict(self._tags_table.get(sku_id, {}))
        assert self._tag_store is not None
        return self._tag_store.get_sku_tags(sku_id)

    def get_all_sku_tags(self) -> Dict[str, Dict[str, str]]:
        if self._tags_table is not None:
            return {k: dict(v) for k, v in self._tags_table.items()}
        assert self._tag_store is not None
        return self._tag_store.all_tags()

    def list_competitor_benchmarks(self) -> List[Dict]:
        """竞品类目对照（Gap Analysis 数据源）。"""
        if self._competitor_rows is not None:
            return [dict(r) for r in self._competitor_rows]
        return list_competitor_rows()

    def get_sales(self, sku_id: str, days: int = 7) -> Dict:
        """查询 SKU 销量"""
        if sku_id not in self.data_source.skus:
            return {"error": f"SKU {sku_id} 不存在"}

        sku = self.data_source.skus[sku_id]
        total_sales = sku["daily_sales"] * days

        return {
            "sku_id": sku_id,
            "name": sku["name"],
            "period_days": days,
            "total_sales": total_sales,
            "daily_avg": sku["daily_sales"],
        }

    def get_inventory(self, sku_id: str) -> Dict:
        """查询在途库存"""
        if sku_id not in self.data_source.skus:
            return {"error": f"SKU {sku_id} 不存在"}

        sku = self.data_source.skus[sku_id]
        return {
            "sku_id": sku_id,
            "name": sku["name"],
            "current_stock": sku["stock"],
            "in_transit": sku["in_transit"],
            "total_available": sku["stock"] + sku["in_transit"],
        }

    def get_return_rate(self, sku_id: str) -> Dict:
        """查询退货率"""
        if sku_id not in self.data_source.skus:
            return {"error": f"SKU {sku_id} 不存在"}

        sku = self.data_source.skus[sku_id]
        return {
            "sku_id": sku_id,
            "name": sku["name"],
            "return_rate": sku["return_rate"],
            "status": "正常" if sku["return_rate"] < high_return_fraction() else "偏高",
        }

    def get_price_history(self, sku_id: str, days: int = 30) -> Dict:
        """查询 SKU 价格-销量历史。

        返回近 N 天的每日记录，含 date / price / daily_sales 字段。
        用于定价弹性分析和 LLM 智能定价上下文。
        """
        if sku_id not in self.data_source.skus:
            return {"error": f"SKU {sku_id} 不存在"}

        sku = self.data_source.skus[sku_id]
        history = sku.get("price_history") or []

        # 按请求天数截取
        if days and len(history) > days:
            history = history[-days:]

        return {
            "sku_id": sku_id,
            "name": sku["name"],
            "days": len(history),
            "records": history,
        }
