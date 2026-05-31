"""Tool-based Inventory Agent: LLM 通过 function calling 自主编排库存决策。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .inventory_tools import INVENTORY_TOOLS, InventoryToolExecutor


INVENTORY_AGENT_SYSTEM = """你是电商库存决策 Agent。对每个 SKU，你需要通过调用工具来完成库存分析。

工作流程：
1. 调用 get_sku_inventory_status 了解库存状态
2. 根据状态决定下一步：
   - coverage_days < 5 → 调用 calculate_replenishment 计算补货量
   - total_coverage_days > overstock阈值 → 调用 assess_overstock_risk 评估去化
   - 5 ≤ coverage_days ≤ overstock阈值 → 库存健康，观察即可
3. 最后调用 decide_inventory_action 输出决策

决策规则：
- 缺货（coverage<3天）：紧急补货，urgency=critical
- 低库存（3-7天）：常规补货
- 健康（7-45天）：hold，不干预
- 高库存（>45天）：去化策略
- 高退货率（>10%）的SKU：即使缺货也暂缓补货，标注"待退货问题解决"
- 趋势declining的SKU：补货前需确认需求侧

以下是历史经验：
{experiences}

完成后输出最终决策（纯文本）：
格式：[ACTION] action=replenish/clearance/hold/freeze_po | qty=N | strategy=xxx | reasoning=原因
"""


class InventoryAgentV2:
    """Tool-based 库存 Agent。"""

    def __init__(self, llm_client, replenishment_cycle_days: int = 7, overstock_days: int = 45):
        self._llm = llm_client
        self.replenishment_cycle_days = replenishment_cycle_days
        self.overstock_days = overstock_days

    def analyze_sku(self, sku: Dict[str, Any], experiences: Optional[List[Dict]] = None) -> Dict[str, Any]:
        executor = InventoryToolExecutor(sku, self.replenishment_cycle_days, self.overstock_days)

        exp_text = "无"
        if experiences:
            lines = [f"- [{e.get('confidence','')}] {e.get('title','')}" for e in experiences[:3]]
            exp_text = "\n".join(lines) if lines else "无"

        system = INVENTORY_AGENT_SYSTEM.format(experiences=exp_text)
        ds = sku.get("daily_sales", 0)
        stock = sku.get("stock", 0)
        coverage = stock / ds if ds > 0 else 999

        user_msg = (
            f"请对以下 SKU 进行库存分析：\n"
            f"- SKU: {sku.get('sku_id', '')} {sku.get('name', '')}\n"
            f"- 日销: {ds} 件\n"
            f"- 库存: {stock} 件（估算覆盖 {coverage:.1f} 天）\n"
            f"- 在途: {sku.get('in_transit', 0)} 件\n"
            f"- 退货率: {float(sku.get('return_rate') or 0) * 100:.1f}%\n"
            f"- 库龄: {sku.get('stock_age_days', 0)} 天\n"
            f"- overstock阈值: {self.overstock_days} 天\n"
        )

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]

        for _ in range(5):
            response = self._llm.chat_with_tools(messages, tools=INVENTORY_TOOLS, temperature=0.0)

            if response.get("tool_calls"):
                for call in response["tool_calls"]:
                    fn_name = call["function"]["name"]
                    fn_args = json.loads(call["function"]["arguments"]) if isinstance(call["function"]["arguments"], str) else call["function"]["arguments"]
                    if "sku_id" not in fn_args:
                        fn_args["sku_id"] = sku.get("sku_id", "")
                    result = executor.execute(fn_name, fn_args)
                    messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
                    messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(result, ensure_ascii=False)})
            else:
                content = response.get("content", "")
                return self._parse_decision(content, sku, executor)

        return self._default_result(sku, "Agent 未在限定轮次内完成")

    def _parse_decision(self, content: str, sku: Dict, executor: InventoryToolExecutor) -> Dict[str, Any]:
        status = executor._status or executor._get_status()
        result = {
            "sku_id": sku.get("sku_id", ""),
            "name": sku.get("name", ""),
            "action": "hold",
            "qty": 0,
            "strategy": "",
            "reasoning": content[:200] if content else "",
            "coverage_days": status.get("coverage_days", 0),
            "total_coverage_days": status.get("total_coverage_days", 0),
            "avg_daily_7d": status.get("avg_daily_7d", 0),
            "sales_volatility": status.get("sales_volatility", 0),
        }

        if "action=replenish" in content:
            result["action"] = "replenish"
            qty_match = re.search(r"qty\s*=\s*(\d+)", content)
            if qty_match:
                result["qty"] = int(qty_match.group(1))
        elif "action=clearance" in content:
            result["action"] = "clearance"
        elif "action=freeze_po" in content:
            result["action"] = "freeze_po"

        strategy_match = re.search(r"strategy\s*=\s*(.+?)(?:\||$)", content)
        if strategy_match:
            result["strategy"] = strategy_match.group(1).strip()
        reasoning_match = re.search(r"reasoning\s*=\s*(.+?)(?:\||$)", content)
        if reasoning_match:
            result["reasoning"] = reasoning_match.group(1).strip()

        return result

    def _default_result(self, sku: Dict, reason: str) -> Dict[str, Any]:
        return {
            "sku_id": sku.get("sku_id", ""),
            "name": sku.get("name", ""),
            "action": "hold",
            "qty": 0,
            "strategy": "",
            "reasoning": reason,
            "coverage_days": 0,
            "total_coverage_days": 0,
            "avg_daily_7d": 0,
            "sales_volatility": 0,
        }
