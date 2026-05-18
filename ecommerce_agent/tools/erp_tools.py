"""Agent 可调用的 ERP 工具"""
from typing import Optional

from ..data.erp_adapter import ERPAdapter


class ERPTools:
    """封装为 Agent 可调用的工具函数"""

    def __init__(self, seed: Optional[int] = None):
        self.adapter = ERPAdapter(seed=seed)

    def query_sales(self, sku_id: str, days: int = 7) -> str:
        """查询 SKU 销量

        Args:
            sku_id: 商品 SKU 编号
            days: 查询天数，默认 7 天
        """
        result = self.adapter.get_sales(sku_id, days)
        if "error" in result:
            return result["error"]

        return f"{result['name']} 近 {days} 天销量：{result['total_sales']} 件，日均 {result['daily_avg']} 件"

    def query_inventory(self, sku_id: str) -> str:
        """查询库存和在途"""
        result = self.adapter.get_inventory(sku_id)
        if "error" in result:
            return result["error"]

        return f"{result['name']} 当前库存：{result['current_stock']} 件，在途：{result['in_transit']} 件，总可用：{result['total_available']} 件"

    def query_return_rate(self, sku_id: str) -> str:
        """查询退货率"""
        result = self.adapter.get_return_rate(sku_id)
        if "error" in result:
            return result["error"]

        return f"{result['name']} 退货率：{result['return_rate']*100:.1f}%，状态：{result['status']}"
