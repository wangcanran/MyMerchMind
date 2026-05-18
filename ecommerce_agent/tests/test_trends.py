"""测试趋势抓取功能"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecommerce_agent.tools.trends_tools import TrendsTools


def test_trends():
    """测试趋势查询工具"""
    tools = TrendsTools(seed=42)

    print("=== 测试趋势抓取功能 ===\n")

    # 测试热门趋势
    print(tools.query_top_trends(5))
    print()

    # 测试增长趋势
    print(tools.query_growing_trends(3))


if __name__ == "__main__":
    test_trends()
