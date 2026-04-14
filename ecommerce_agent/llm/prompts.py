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
