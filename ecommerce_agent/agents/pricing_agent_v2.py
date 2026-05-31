"""Tool-based Pricing Agent: LLM 通过 function calling 自主编排定价决策。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .pricing_tools import PRICING_TOOLS, PricingToolExecutor


PRICING_AGENT_SYSTEM = """你是电商定价决策 Agent。对每个 SKU，你需要通过调用工具来完成定价分析。

工作流程：
1. 调用 get_competitor_summary 了解市场价格
2. 调用 estimate_elasticity 了解价格敏感度
3. 根据 SKU 状态决定策略：
   - 缺货（coverage<5天）→ 调用 decide_no_action（不调价，保供给优先）
   - 高退货率（>10%）→ 调用 decide_no_action（待诊断）或 clearance 策略
   - 高库存（coverage>45天）→ clearance 策略加速去化
   - 健康且趋势稳定 → 调用 decide_no_action（维持现价）
   - 竞品价格显著低于当前价且趋势下降 → traffic 或 profit 策略
4. 确定策略后调用 calculate_price 计算建议价
5. 最后调用 apply_guardrail 确保不违反硬约束

硬规则（不可违反）：
- 缺货 SKU（coverage<5天）绝对不降价，也不涨价
- 健康 SKU（coverage 7-45天，趋势非declining，退货率<8%）无外部驱动不调价
- 所有最终价格必须经过 apply_guardrail
- 高退货率（≥12%）的 SKU 暂停定价，等待诊断

以下是历史经验（请参考并影响你的决策）：
{experiences}

完成所有工具调用后，输出最终决策（纯文本，不要 JSON）：
格式：[ACTION] action=reprice/hold | price=N | strategy=xxx | reasoning=一句话原因
"""


class PricingAgentV2:
    """Tool-based 定价 Agent：LLM 通过 function calling 编排定价流程。"""

    def __init__(self, llm_client, use_llm: bool = True):
        self._llm = llm_client
        self._use_llm = use_llm

    def analyze_sku(
        self,
        sku: Dict[str, Any],
        competitor_prices: List[float],
        competitor_products: Optional[List[Dict]] = None,
        experiences: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """对单个 SKU 执行 Tool-based 定价分析。"""
        executor = PricingToolExecutor(sku, competitor_prices, competitor_products)

        # 构建经验文本
        exp_text = "无"
        if experiences:
            lines = []
            for exp in experiences[:5]:
                title = exp.get("title", "")
                narrative = exp.get("narrative", "")
                if len(narrative) > 100:
                    narrative = narrative[:100] + "..."
                lines.append(f"- [{exp.get('confidence', '')}] {title}: {narrative}")
            if lines:
                exp_text = "\n".join(lines)

        system = PRICING_AGENT_SYSTEM.format(experiences=exp_text)

        # 构建 SKU 数据摘要
        ds = sku.get("daily_sales", 0)
        stock = sku.get("stock", 0)
        coverage = stock / ds if ds > 0 else 999
        user_msg = (
            f"请对以下 SKU 进行定价分析：\n"
            f"- SKU: {sku.get('sku_id', '')} {sku.get('name', '')}\n"
            f"- 当前价: ¥{sku.get('price', 0)}\n"
            f"- 成本: ¥{sku.get('cost_price', 0)}\n"
            f"- 日销: {ds} 件\n"
            f"- 库存: {stock} 件（覆盖 {coverage:.1f} 天）\n"
            f"- 在途: {sku.get('in_transit', 0)} 件\n"
            f"- 退货率: {float(sku.get('return_rate') or 0) * 100:.1f}%\n"
            f"- 转化率: {float(sku.get('conversion_rate') or 0) * 100:.2f}%\n"
            f"- 渠道: {json.dumps(sku.get('channel_sales', {}))}\n"
            f"- 库龄: {sku.get('stock_age_days', 0)} 天\n"
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

        # 多轮 function calling
        max_rounds = 6
        for _ in range(max_rounds):
            response = self._llm.chat_with_tools(
                messages, tools=PRICING_TOOLS, temperature=0.0
            )

            if response.get("tool_calls"):
                # 执行工具调用
                for call in response["tool_calls"]:
                    fn_name = call["function"]["name"]
                    fn_args = json.loads(call["function"]["arguments"]) if isinstance(call["function"]["arguments"], str) else call["function"]["arguments"]
                    # 注入 sku_id（工具需要但 Agent 可能省略）
                    if "sku_id" not in fn_args:
                        fn_args["sku_id"] = sku.get("sku_id", "")
                    result = executor.execute(fn_name, fn_args)
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [call],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            else:
                # Agent 完成，解析最终决策
                content = response.get("content", "")
                return self._parse_final_decision(content, sku, executor)

        # 超过最大轮次
        return self._fallback_result(sku, "Agent 未在限定轮次内完成决策")

    def _parse_final_decision(
        self, content: str, sku: Dict, executor: PricingToolExecutor
    ) -> Dict[str, Any]:
        """解析 Agent 的最终文本输出为结构化结果。"""
        sid = sku.get("sku_id", "")
        current_price = sku.get("price", 0)
        cost = sku.get("cost_price", 0)

        # 尝试解析 [ACTION] 格式
        result = {
            "sku_id": sid,
            "name": sku.get("name", ""),
            "current_price": current_price,
            "cost_price": cost,
            "suggested_price": current_price,
            "strategy": "hold",
            "reasoning": content[:200] if content else "无决策输出",
            "action": "hold",
            "competitor_summary": executor._competitor_summary or {},
            "elasticity_detail": executor._elasticity,
        }

        if "action=reprice" in content or "action = reprice" in content:
            result["action"] = "reprice"
            # 提取 price
            price_match = re.search(r"price\s*=\s*(\d+)", content)
            if price_match:
                result["suggested_price"] = int(price_match.group(1))
            strategy_match = re.search(r"strategy\s*=\s*(\w+)", content)
            if strategy_match:
                result["strategy"] = strategy_match.group(1)
            reasoning_match = re.search(r"reasoning\s*=\s*(.+?)(?:\||$)", content)
            if reasoning_match:
                result["reasoning"] = reasoning_match.group(1).strip()
        elif "action=hold" in content or "action = hold" in content:
            result["action"] = "hold"
            reasoning_match = re.search(r"reasoning\s*=\s*(.+?)(?:\||$)", content)
            if reasoning_match:
                result["reasoning"] = reasoning_match.group(1).strip()

        return result

    def _fallback_result(self, sku: Dict, reason: str) -> Dict[str, Any]:
        return {
            "sku_id": sku.get("sku_id", ""),
            "name": sku.get("name", ""),
            "current_price": sku.get("price", 0),
            "cost_price": sku.get("cost_price", 0),
            "suggested_price": sku.get("price", 0),
            "strategy": "hold",
            "reasoning": reason,
            "action": "hold",
            "competitor_summary": {},
            "elasticity_detail": None,
        }
