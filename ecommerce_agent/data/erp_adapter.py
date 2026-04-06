"""ERP/OMS 统一适配层"""
from typing import Dict, List, Optional
from .mock_erp import MockERPData


class ERPAdapter:
    """统一的 ERP 数据访问接口"""

    def __init__(self, seed: Optional[int] = None):
        self.data_source = MockERPData(seed=seed)

    def get_all_skus(self) -> List[Dict]:
        """获取全部 SKU 原始指标（用于复盘与预警）"""
        items: List[Dict] = []
        for sku_id in sorted(self.data_source.skus.keys()):
            sku = self.data_source.skus[sku_id]
            items.append({
                "sku_id": sku_id,
                "name": sku["name"],
                "daily_sales": sku["daily_sales"],
                "stock": sku["stock"],
                "in_transit": sku["in_transit"],
                "return_rate": sku["return_rate"],
            })
        return items

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
            "status": "正常" if sku["return_rate"] < 0.1 else "偏高",
        }
