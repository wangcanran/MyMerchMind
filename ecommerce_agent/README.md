# 服装企业数字化大脑 Agent - 数据集成模块

## 项目结构

```
ecommerce_agent/
├── data/                  # 数据层
│   ├── mock_erp.py        # 模拟 ERP 数据源
│   ├── erp_adapter.py     # ERP 统一适配层
│   ├── mock_trends.py     # 模拟趋势数据源
│   └── trends_adapter.py  # 趋势统一适配层
├── tools/                 # Agent 工具层
│   ├── erp_tools.py       # ERP 查询工具
│   └── trends_tools.py    # 趋势查询工具
└── tests/                 # 测试
    ├── test_erp.py        # ERP 集成测试
    └── test_trends.py     # 趋势集成测试
```

## 已完成功能

### Issue 1.1：ERP/OMS 接口集成 ✅

实现了三个核心查询接口：

1. **销量查询** - `query_sales(sku_id, days)`
2. **库存查询** - `query_inventory(sku_id)`
3. **退货率查询** - `query_return_rate(sku_id)`

### Issue 1.2：外部趋势抓取 ✅

实现了社媒趋势查询接口：

1. **热门趋势查询** - `query_top_trends(limit)`
2. **增长趋势查询** - `query_growing_trends(limit)`

支持平台：小红书、抖音（模拟数据）

## 快速开始

### ERP 数据查询

```python
from ecommerce_agent.tools.erp_tools import ERPTools

tools = ERPTools(seed=42)

# 查询销量
print(tools.query_sales("SKU1001", 7))

# 查询库存
print(tools.query_inventory("SKU1001"))

# 查询退货率
print(tools.query_return_rate("SKU1001"))
```

### 趋势数据查询

```python
from ecommerce_agent.tools.trends_tools import TrendsTools

tools = TrendsTools(seed=42)

# 查询热门趋势
print(tools.query_top_trends(5))

# 查询增长趋势
print(tools.query_growing_trends(3))
```

### 一键运行 Baseline Demo

```bash
python -m ecommerce_agent.main --demo --seed 42 --top-n 5
```

### LLM 补充（可选）

使用 OpenAI 兼容的 `POST /chat/completions` 接口。默认**不**调用 LLM，以保证报告可复现。

环境变量（常用）：

- `LLM_API_KEY` 或 `OPENAI_API_KEY`：密钥
- `LLM_BASE_URL`：默认 `https://api.openai.com/v1`
- `LLM_CHAT_PATH`：默认 `/chat/completions`
- `LLM_MODEL`：默认 `gpt-4o-mini`
- `LLM_TIMEOUT_S`：超时秒数，默认 `60`

启用示例：

```bash
export LLM_API_KEY=your_key
python -m ecommerce_agent.main --demo --llm --llm-model gpt-4o-mini
```

默认会同时：
- 在终端打印结构化复盘结果
- 在项目根目录生成 `demo_report.md`

## 运行测试

```bash
# 测试 ERP 集成
python ecommerce_agent/tests/test_erp.py

# 测试趋势抓取
python ecommerce_agent/tests/test_trends.py

# Baseline Demo 冒烟测试
python ecommerce_agent/tests/test_demo_smoke.py
```
