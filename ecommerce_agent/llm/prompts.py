"""各 Agent 的 LLM 提示模板（与业务逻辑分离）。"""

SYSTEM_ZH_BUSINESS = (
    "你是服装电商运营分析助手，输出简洁、可执行的中文结论。"
    "用户数据为演示/脱敏数据，不要编造不存在的 SKU 名称以外的字段。"
)

SALES_REVIEW_USER = """根据以下已计算的 JSON 摘要，输出两段内容：
1) executive_summary：2-4 句经营摘要（中文）。
2) action_bullets：3-5 条可执行建议（字符串数组，中文）。

只输出一个 JSON 对象，键为 executive_summary（字符串）和 action_bullets（字符串数组），不要 markdown 代码围栏。

数据：
{payload}
"""

PRODUCT_SELECTION_USER = """根据以下趋势与规则映射结果，输出一个 JSON 对象，键为：
- story: 字符串，1-3 句中文，补充或润色选品叙事（不要否定已有 MOQ 数字）。
- color_focus: 字符串数组，可选的补充色系关键词（若无需补充可为空数组）。
- material_focus: 字符串数组，可选的补充材质关键词（若无需补充可为空数组）。

只输出 JSON，不要其他文字。

趋势关键词: {keyword}
规则映射（基准）:
{merch_json}
竞品缺口摘要（前 3 条内任选关键信息）:
{gaps_summary}
"""

INVENTORY_USER = """根据以下库存预警 JSON，用中文写一段 priorities_note（80-180 字）：说明优先处理顺序、与采购/运营的协作要点。只输出 JSON：{{"priorities_note": "..."}}。

数据:
{payload}
"""

SLOW_MOVING_USER = """根据以下滞销 SKU 候选 JSON，用中文写一段 coordination_note（80-200 字）：说明清货优先级、渠道分工与风险。只输出 JSON：{{"coordination_note": "..."}}。

数据:
{payload}
"""

REPLENISHMENT_USER = """根据以下补货/EOQ 行数据，用中文写一段 business_comment（60-150 字）：解释为何取较大订货量、需与供应链确认的点。只输出 JSON：{{"business_comment": "..."}}。

数据:
{payload}
"""

CATEGORY_MANAGEMENT_USER = """你将收到“品类管理智能体”的结构化决策 JSON（包含品类 KPI、阈值、以及三张决策卡片：audit_existing/retire/evaluate_new）。
请在不改变任何数值与字段含义的前提下，用中文补充更可执行的说明，输出一个 JSON 对象，键为：
- card_notes: 对象，键为 audit_existing/retire/evaluate_new，值为字符串（每段 60-160 字），强调执行要点与风险
- execution_checklist: 字符串数组，3-6 条（面向团队协作的下一步动作）
- strategy_scenarios: 数组，必须包含 3 个对象，且 title 必须分别为“方案A 保守去化”“方案B 结构优化”“方案C 延后上新观察”。
  每个对象必须包含：
  - title: 字符串
  - summary: 字符串（40-120 字）
  - expected_impact: 字符串数组（2-4 条）
  - risks: 字符串数组（2-4 条）
  - monitor_7d: 字符串数组（2-4 条，7天观察指标）
  - monitor_30d: 字符串数组（2-4 条，30天观察指标）
  注意：必须严格遵守输入里的 hard_constraints，不能提出违反约束的方案（例如被标记 stop_replenishment 的品类不能补货）。

输出必须是严格 JSON：你的回复中第一个非空白字符必须为 {{，最后一个非空白字符必须为 }}。
除 JSON 外不要输出任何解释文字、标题、编号、Markdown。

数据:
{payload}
"""
