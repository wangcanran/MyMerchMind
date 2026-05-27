# Web 看板实现说明（FastAPI + Vite/React）

当前仓库 Agent 核心为 [`ecommerce_agent/orchestrator.py`](../ecommerce_agent/orchestrator.py) 与 [`ecommerce_agent/main.py`](../ecommerce_agent/main.py) 的 Markdown 报告。本说明给出**可直接落地的文件清单、接口契约与前端结构**；在 **Agent 模式**下可让助手自动创建这些文件。

## 1. 依赖

新增 `requirements-api.txt`（与仅标准库的 core 分离）：

```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
```

安装（在仓库根目录 `ECommerceAgent/`）：

```bash
pip install -r requirements-api.txt
```

## 2. 后端：`api/main.py`

从仓库根目录启动时需将根目录加入 `PYTHONPATH`，或使用 `uvicorn api.main:app` 且工作目录为根目录。

职责：

- `GET /api/health` → `{"status":"ok"}`
- `GET /api/report` → 与 `DemoOrchestrator(..., use_llm=True).run()` 对齐的 JSON（查询参数含 `seed`、`top_n`、`as_of`、`replenishment_cycle`、`overstock_days`、`feedback_memory`、`target_gross_margin`、`use_llm`）。**默认 `use_llm=true`**（前端全链路大模型）；传 `use_llm=false` 可强制纯规则。未配置 `LLM_API_KEY`/`OPENAI_API_KEY` 时仍回退规则，见响应 `context.llm_notice`。**不含**选品正文；长需求请用 `POST /api/report`。
- `POST /api/report` → JSON 体字段与上相同，另可含 `selection_requirements`（自然语言或 Markdown 字符串）；非空时先 LLM 需求理解再跑图谱选品。体字段 **`use_llm` 默认 `true`**。响应同 GET，并含 `markdown`。
- `GET /api/report/markdown` → `{"markdown": "<与 build_markdown_report 相同>"}`（无选品正文；支持查询参数 **`use_llm`，默认 true**）
- `POST /api/report/markdown` → 同上，体与 `POST /api/report` 一致，仅返回 `markdown`

**实现要点**：复用 [`build_markdown_report`](../ecommerce_agent/main.py) 与 [`DemoOrchestrator`](../ecommerce_agent/orchestrator.py)；`as_of` 为空时用 `date.today().isoformat()`；`feedback_memory` 非空时校验文件存在否则 400。

启动命令（示例）：

```bash
cd /path/to/ECommerceAgent
export PYTHONPATH="$PWD"
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

## 3. 前端：`web/`（Vite + React + TypeScript）

### 3.1 脚手架

```bash
cd /path/to/ECommerceAgent
npm create vite@latest web -- --template react-ts
cd web && npm install
```

### 3.2 `vite.config.ts` 开发代理

将 `/api` 代理到 `http://127.0.0.1:8000`，避免 CORS 与手写完整 URL。

### 3.3 类型 `src/types/report.ts`

根据 orchestrator 输出定义（关键字段）：

- `context`: `as_of`, `seed`, `sku_count`, `trend_count`, `top_n`
- `product_selection`: `trend_picks`, `recommendations`, `memory_hits`, …
- `sales_review`: `summary`, `top_skus`, `lagging_skus`, `high_return_skus`, `trend_focus`, `channel_dashboard`, `return_semantics`, `llm_executive_brief`
- `inventory_review`: `low_stock_alerts`, `overstock_alerts`, …
- `slow_moving`: `slow_moving_skus`, …
- `replenishment`: `replenishment_rows`, …
- `memory_snapshot`, `actions`

SKU 行视图字段见 [`SalesReviewAgent._to_view`](../ecommerce_agent/agents/sales_review_agent.py)（`return_rate_pct` 等）。

### 3.4 页面结构（与运营心智一致）

1. **顶栏**：参数表单（seed、as-of、top-n、补货周期、高库存阈值）+「生成报告」按钮。
2. **行动区**：`actions` 编号列表，浅底强调（语义色见下）。
3. **KPI 行**：`sales_review.summary`（总日销、平均退货率、最热趋势）。
4. **模块卡片**（顺序建议）：选品 → 渠道 → 退货语义 → 库存低/高 → 滞销 → EOQ → 记忆。

### 3.5 设计令牌（CSS 变量）

| 语义 | 用途 | 建议色 |
|------|------|--------|
| `--color-growth` | 畅销、正向环比、机会 | `#0d9488` |
| `--color-risk` | 高退货、滞销、偏高风险 MOQ | `#ea580c` |
| `--color-urgent` | 低库存断货 | `#dc2626` |
| `--color-structure` | 库存覆盖、EOQ、渠道结构 | `#4f46e5` |
| `--surface-bg` / `--surface-card` / `--text` | 中性面与正文 | `#f8f7f4` / `#fff` / `#1c1917` |

表格数字使用 `font-variant-numeric: tabular-nums`。

### 3.6 `src/api/client.ts`

`fetch('/api/report?' + params)` 与可选 `fetch('/api/report/markdown?...')` 下载展示。

## 4. 验收

- 同参数下，UI 各区块与 [`build_markdown_report`](../ecommerce_agent/main.py) 章节一一对应。
- `actions` 顺序与条数与后端 `_merge_actions` 结果一致。

## 5. 下一步（可选）

- 避雷记忆：生产环境勿用任意服务器路径；改为上传 JSON 或专用配置目录。
- LLM 开启后，在 `sales_review` / `product_selection` 展示 `llm_executive_brief` 折叠块。

---

若需助手**自动创建上述全部源文件**，请在 Cursor 中切换到 **Agent 模式** 并说明「按 `docs/web-dashboard-setup.md` 实现」。

---

## 已实现（仓库内）

- 后端：[`requirements-api.txt`](../requirements-api.txt)、[`api/main.py`](../api/main.py)
- 前端：[`web/`](../web/)（Vite + React + TS，开发代理 `/api` → `http://127.0.0.1:8000`）

**终端 1（API）**（在 `ECommerceAgent` 根目录）：

```bash
export PYTHONPATH="$PWD"
python3 -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

**终端 2（前端）**：

```bash
cd web && npm install && npm run dev
```

浏览器打开 Vite 提示的本地地址即可；需先启动 API，否则「生成报告」会失败。

**依赖**：`pip3 install -r requirements-api.txt`（与 Agent 核心标准库分离）。
