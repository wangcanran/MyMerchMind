# MerchMind

> Multi-agent e-commerce merchandising platform powered by LLM function calling.

MerchMind 是一个多智能体电商运营决策平台。它通过 LLM Tool Calling 驱动定价、库存、销售分析等核心模块，将经验库作为 Agent 的长期记忆注入决策过程，实现"数据 → 决策 → 执行 → 反馈 → 学习"的完整闭环。

## Why MerchMind

传统电商运营决策系统的问题：
- **规则引擎** — 规则越加越多，互相冲突，维护困难
- **LLM 直接生成** — 幻觉严重，数字不可信，无法追溯
- **各模块独立** — 定价不知道库存状态，库存不知道退货率

MerchMind 的解法：
- **LLM 做决策编排，工具做精确计算** — Agent 决定"用什么策略"，工具保证"数字正确"
- **跨模块冲突自动解决** — 缺货 SKU 不会被建议降价，高退货 SKU 自动暂停促销
- **经验驱动决策** — 历史反馈沉淀为经验，下次决策时 Agent 自动参考

## Features

- **Tool-based Agents** — 定价/库存/销售分析通过 LLM function calling 自主编排
- **冲突解决引擎** — 6 条硬约束规则，按 SKU 聚合决策并自动仲裁
- **经验库闭环** — 策略执行 → 反馈 → 经验生成 → 注入下次决策
- **实时进度推送** — SSE 流式报告生成，前端实时显示当前步骤
- **可视化报告** — Sparkline 图表、环形图、StatChip 指标卡片
- **HTML/Markdown 导出** — 带排版的报告文件下载

## Architecture

```
┌──────────────────────────────────────────────┐
│              React Frontend                    │
└─────────────────────┬────────────────────────┘
                      │ SSE / REST
┌─────────────────────┴────────────────────────┐
│              FastAPI Backend                   │
└─────────────────────┬────────────────────────┘
                      │
┌─────────────────────┴────────────────────────┐
│               Orchestrator                    │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│  │Pricing  │ │Inventory│ │ Sales   │        │
│  │Agent    │ │Agent    │ │ Agent   │  ...   │
│  │(5 tools)│ │(4 tools)│ │(5 tools)│        │
│  └────┬────┘ └────┬────┘ └────┬────┘        │
│       └────────────┼──────────┘              │
│                    │                          │
│  ┌─────────────────┴──────────────────────┐  │
│  │  Conflict Resolution + Action Registry  │  │
│  └─────────────────────────────────────────┘  │
│                    │                          │
│  ┌─────────────────┴──────────────────────┐  │
│  │         Experience Store (Memory)       │  │
│  └─────────────────────────────────────────┘  │
└───────────────────────────────────────────────┘
         │
         ▼ LLM Function Calling
   ┌───────────┐
   │ Any OpenAI│
   │ Compatible│
   │ LLM API   │
   └───────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- An OpenAI-compatible LLM API key (e.g., OpenAI, Anthropic, Deepseek, Kimi)

### Installation

```bash
git clone https://github.com/your-org/MerchMind.git
cd MerchMind

# Backend dependencies
pip install fastapi uvicorn httpx bcrypt

# Frontend dependencies
cd web && npm install && cd ..
```

### Configuration

Create a `.env` file or set environment variables:

```bash
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1      # or any compatible endpoint
LLM_MODEL=gpt-4o                             # model that supports function calling
LLM_TIMEOUT_S=120
```

### Run

```bash
# Terminal 1: Backend
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

# Terminal 2: Frontend
cd web && npm run dev
```

Open `http://localhost:5173`, register an account, upload data, and generate a report.

## Data Format

Upload a single JSON file containing all SKU data:

```json
[
  {
    "sku_id": "SKU001",
    "name": "Product Name",
    "current_price": 259,
    "cost_price": 108,
    "daily_sales": 38,
    "stock": 420,
    "in_transit": 150,
    "return_rate": 0.04,
    "channel_sales": { "live": 18, "private": 8, "shelf": 12 },
    "conversion_rate": 0.022,
    "stock_age_days": 20,
    "review_snippets": ["Great fabric", "True to size"],
    "price_history": [
      { "date": "2026-05-24", "price": 259, "daily_sales": 38 }
    ]
  }
]
```

A demo dataset is included at `web/public/demo_price_history.json`.

## How It Works

### 1. Agent Decision Making

Each Agent receives SKU data + historical experiences, then autonomously calls tools:

```
Agent sees: SKU2002, return_rate=14%, experience="涤纶降价无效"
Agent decides: call decide_no_action(reason="高退货待诊断")
Result: No price change (instead of blindly suggesting a discount)
```

### 2. Conflict Resolution

After all Agents output decisions, the orchestrator resolves conflicts:

```
SKU2006: PricingAgent says "lower price" + InventoryAgent says "out of stock"
→ Rule 4: coverage < 3 days, block price reduction
→ Final: replenish only, no price change
```

### 3. Experience Loop

```
Report → Strategy tracked → Operator executes → Feedback submitted
→ Experience generated → Injected into next report's Agent prompts
```

## Project Structure

```
├── api/                        # FastAPI backend
├── ecommerce_agent/
│   ├── orchestrator.py         # Agent orchestration + conflict resolution
│   ├── agents/
│   │   ├── pricing_agent_v2.py     # Tool-based pricing
│   │   ├── pricing_tools.py        # Pricing tool definitions
│   │   ├── inventory_agent_v2.py   # Tool-based inventory
│   │   ├── inventory_tools.py      # Inventory tool definitions
│   │   ├── sales_agent_v2.py       # Tool-based sales analysis
│   │   ├── category_management_agent.py
│   │   └── product_selection_agent.py
│   ├── memory/                 # Experience & strategy stores
│   ├── data/                   # Data adapters
│   └── llm/                    # LLM client (function calling support)
├── web/                        # React frontend
└── demo_erp_data.json          # Demo dataset
```

## Extending

### Add a New Tool

1. Define the tool schema in `*_tools.py`:
```python
{
    "type": "function",
    "function": {
        "name": "your_tool",
        "description": "What it does",
        "parameters": { ... }
    }
}
```

2. Implement the executor method in the `ToolExecutor` class.

3. The Agent will automatically discover and use it via function calling.

### Add a New Agent

1. Create `agents/your_agent_v2.py` with a system prompt and tool list.
2. Create `agents/your_tools.py` with tool definitions and executor.
3. Wire it into `orchestrator.py`.

## Roadmap

- [ ] Multi-agent consensus algorithm (replace hard-coded conflict rules)
- [ ] CSIO constraint satisfaction optimization
- [ ] Async parallel SKU processing
- [ ] Migrate category/selection agents to Tool-based architecture
- [ ] Real-time data connectors (ERP API, marketplace API)

## License

MIT

## Contributing

Issues and PRs welcome. Please read the architecture section before contributing.

```
                    ┌─────────────────────────────────────────────────────────┐
                    │              服装企业数字化大脑 Agent                     │
                    └─────────────────────────────────────────────────────────┘
                                          │
          ┌───────────────────────────────┼───────────────────────────────┐
          ▼                               ▼                               ▼
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│  选品 Agent     │           │  库存管理 Agent  │           │  销量回顾 Agent  │
│  趋势→爆款预测   │           │  预警/补货/清滞   │           │  周报/归因/记忆   │
└────────┬────────┘           └────────┬────────┘           └────────┬────────┘
         │                             │                             │
         └─────────────────────────────┼─────────────────────────────┘
                                       ▼
                    ┌─────────────────────────────────────────────────────────┐
                    │  数据层：ERP/OMS 实时数据 │ 社媒趋势 │ 商品标签库 │ Memory  │
                    └─────────────────────────────────────────────────────────┘
```

## 四大里程碑

| 里程碑 | 目标 | 文档 |
|--------|------|------|
| **M1** | 基础设施与数据「血液」打通 | [docs/milestones/M1-基础设施与数据打通.md](docs/milestones/M1-基础设施与数据打通.md) |
| **M2** | 选品 Agent：从直觉到预测 | [docs/milestones/M2-选品Agent.md](docs/milestones/M2-选品Agent.md) |
| **M3** | 库存管理 Agent：效率与流转 | [docs/milestones/M3-库存管理Agent.md](docs/milestones/M3-库存管理Agent.md) |
| **M4** | 销量回顾 Agent：闭环归因与策略进化 | [docs/milestones/M4-销量回顾Agent.md](docs/milestones/M4-销量回顾Agent.md) |

## 执行优先级建议

| 优先级 | 任务模块 | 核心价值 | 建议周期 |
|--------|----------|----------|----------|
| **P0（必做）** | 内部数据集成 + 销量回顾 | 替代人工周报，看清生意现状 | Week 1–2 |
| **P1（提效）** | 库存预警 + 动态补货 | 直接降低断货损失 | Week 3–4 |
| **P2（进阶）** | 趋势选品 + 竞品监控 | 提高爆款概率，解决卖什么 | Week 5–8 |

## 避坑指南

1. **数据干净度**：服装 SKU 多，ERP 标签混乱（如「咖啡」/「深棕」）会导致 Agent 出错，建议先做**标签归一化**预处理。
2. **不仅是 Chat**：Agent 必须具备 **Tool Use（函数调用）** 能力，能生成 **Excel 采购单** 等可执行产出，而非仅提示「库存不够」。

## 仓库结构

```
├── README.md                 # 本文件
├── web/                      # 前端看板（Vite + React），API 见 web 内说明
├── ecommerce_agent/          # Python 包与编排 CLI
├── docs/
│   ├── ROADMAP.md            # 完整路线图（含所有 Milestone 与 Issue）
│   ├── milestones/           # 各里程碑详细说明
│   └── issues/               # 各 Issue 的详细描述与验收标准
└── .gitignore
```

## 前端看板（`web/`）

在仓库根目录执行（会先使用根目录 `package.json` 转发到 `web`）：

```bash
npm run install:web   # 首次或依赖变更时安装 web 依赖
npm run dev           # 开发服务器
```

也可直接进入子目录：

```bash
cd web
npm install
npm run dev
```

## 如何开始

- 路线图与所有 Issues：见 [docs/ROADMAP.md](docs/ROADMAP.md)。
- 按优先级可从 **P0：内部数据集成 + 销量回顾** 起步；若需「用 Python Interpreter 自动生成周报」的具体流程，可基于 M4 与 Issue 4.1 展开设计。
