"""测试 ERP 数据集成功能"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecommerce_agent.tools.erp_tools import ERPTools


def test_erp_integration():
    """测试 ERP 工具调用"""
    tools = ERPTools(seed=42)

    print("=== 测试 ERP 数据集成 ===\n")

    # 测试销量查询
    print("1. 查询销量：")
    print(tools.query_sales("SKU1001", 7))
    print()

    # 测试库存查询
    print("2. 查询库存：")
    print(tools.query_inventory("SKU1001"))
    print()

    # 测试退货率查询
    print("3. 查询退货率：")
    print(tools.query_return_rate("SKU1001"))
    print()


if __name__ == "__main__":
    test_erp_integration()
