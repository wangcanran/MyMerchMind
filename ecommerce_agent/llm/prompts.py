"""各 Agent 的 LLM 提示模板（与业务逻辑分离）。"""

SYSTEM_ZH_BUSINESS = (
    "你是服装电商运营分析助手，输出简洁、可执行的中文结论。"
    "用户数据为演示/脱敏数据，不要编造不存在的 SKU 名称以外的字段。"
)

PRODUCT_SELECTION_SYSTEM = """你是一个专业的服装选品专家。
你的任务是基于市场数据和知识图谱分析，为电商平台推荐最佳选品策略。

你需要考虑：
- 当前流行趋势和热门品类（图谱侧重品类与搭配语境；仅当用户提示中显式提供原帖赞/藏时才可作该帖热度参考，勿臆造互动数据）
- 季节性因素和天气适配
- 目标用户群体的风格偏好
- 市场竞争与需求判断

注意：知识图谱入库正文**不含**电商定价字段；**不要在输出 JSON 中编造定价或价格带策略**。
若用户条件里写了预算档位，仅作文字理解即可，勿输出独立「定价方案」结构。

提供具体的选品建议，包括：
1. 推荐的服装品类和具体款式
2. 建议的风格方向
3. 颜色和材质选择
4. 预期的市场表现（需求与竞争，非定价）

一体化原则（极其重要）：
- 当用户同时给出「季节 / 气温 / 地域气候」与「目标风格」时，**禁止**把「春末夏初该卖的品类」与「复古风常见品类」分成两套各写一套、彼此不解释如何统一。
- 每一条品类建议必须在**同一条叙事**里说明：该品类如何**同时**满足当季（含温差、叠穿若适用）与目标风格；若图谱里季节块与风格块信息不一致，你要在结论里**取舍并说明理由**，而不是并排堆砌。

输出格式（必须遵守）：
- 每一轮最终回复**只输出一个 JSON 对象**：从第一个字符「{」到最后一个字符「}」，中间为合法 JSON。
- **不要**使用 markdown 代码围栏（不要 ```json）；**不要**在 JSON 前写开场白、**不要**在 JSON 后写总结段落。
- 字段须符合用户消息末尾给出的 Schema（含 recommended_categories、style_direction 等）。"""

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

REQUIREMENTS_CRITERIA_SYSTEM = (
    "你是电商服装企划助手。用户提交「选品需求文档」全文，请把其中的选品意图抽取为一个 JSON 对象。"
    "只输出 JSON，不要 markdown 代码围栏，不要任何解释性前后文。"
)

REQUIREMENTS_CRITERIA_USER = """从下列需求文档中提取选品条件（文档没有的键可省略或设为 null；constraints 为字符串数组）：

键说明：
- season, target_style, temperature_range, occasion, price_range, target_audience
- source_post（可选）, constraints, notes
- include_engagement: 可选；省略时由环境或 config 中的 product_selection_include_engagement 决定

需求文档：
---
{body}
---
"""
