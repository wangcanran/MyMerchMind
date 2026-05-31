"""Tool-based Sales Review Agent: LLM 通过 function calling 自主编排销售分析。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

SALES_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_sales_overview",
            "description": "获取全店销售概览：总日销、平均退货率、7天增长率、渠道分布",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_skus",
            "description": "获取畅销/滞销/高退货SKU排行",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["top", "lagging", "high_return"], "description": "排行类别"},
                    "limit": {"type": "integer", "description": "返回条数，默认5"},
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_channel_analysis",
            "description": "获取渠道详细分析：各渠道占比、环比、Top SKU贡献、风险诊断",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_return_semantics",
            "description": "获取退货语义分析：高频退货原因关键词",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_recommendations",
            "description": "基于分析结果生成经营建议",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus_areas": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "重点关注领域，如['high_return', 'channel_decline', 'top_sku_stockout']",
                    },
                },
                "required": ["focus_areas"],
            },
        },
    },
]


class SalesToolExecutor:
    """执行销售分析工具。"""

    def __init__(self, sku_metrics: List[Dict], top_trends: List[Dict], growing_trends: List[Dict]):
        self.sku_metrics = sku_metrics
        self.top_trends = top_trends
        self.growing_trends = growing_trends

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "get_sales_overview":
            return self._get_overview()
        elif tool_name == "get_top_skus":
            return self._get_top_skus(args["category"], args.get("limit", 5))
        elif tool_name == "get_channel_analysis":
            return self._get_channel_analysis()
        elif tool_name == "get_return_semantics":
            return self._get_return_semantics()
        elif tool_name == "generate_recommendations":
            return {"status": "ok", "note": "请基于以上数据直接输出建议"}
        return {"error": f"Unknown tool: {tool_name}"}

    def _get_overview(self) -> Dict[str, Any]:
        total_ds = sum(s.get("daily_sales", 0) for s in self.sku_metrics)
        avg_rr = sum(float(s.get("return_rate") or 0) for s in self.sku_metrics) / max(len(self.sku_metrics), 1)

        # 7天趋势
        from .sales_review_agent import SalesReviewAgent
        trend = SalesReviewAgent._compute_sales_trend(self.sku_metrics)

        return {
            "total_daily_sales": total_ds,
            "avg_return_rate_pct": round(avg_rr * 100, 2),
            "sku_count": len(self.sku_metrics),
            "sales_growth_7d_pct": trend.get("growth_7d_pct"),
            "avg_daily_7d": trend.get("avg_7d"),
            "top_trends": [t.get("keyword", "") for t in (self.top_trends or [])[:3]],
        }

    def _get_top_skus(self, category: str, limit: int) -> Dict[str, Any]:
        from .sales_review_agent import SalesReviewAgent
        sku_trends = SalesReviewAgent._compute_sku_trends(self.sku_metrics)

        if category == "top":
            ranked = sorted(self.sku_metrics, key=lambda x: -x.get("daily_sales", 0))[:limit]
        elif category == "lagging":
            ranked = sorted(self.sku_metrics, key=lambda x: x.get("daily_sales", 0))[:limit]
        elif category == "high_return":
            ranked = sorted(
                [s for s in self.sku_metrics if float(s.get("return_rate") or 0) >= 0.08],
                key=lambda x: -float(x.get("return_rate") or 0),
            )[:limit]
        else:
            ranked = []

        results = []
        for s in ranked:
            sid = s.get("sku_id", "")
            t = sku_trends.get(sid, {})
            results.append({
                "sku_id": sid,
                "name": s.get("name", ""),
                "daily_sales": s.get("daily_sales", 0),
                "stock": s.get("stock", 0),
                "return_rate_pct": round(float(s.get("return_rate") or 0) * 100, 1),
                "trend": t.get("trend", "unknown"),
                "growth_7d_pct": t.get("growth_7d_pct", 0),
                "price": s.get("price", 0),
            })
        return {"category": category, "skus": results}

    def _get_channel_analysis(self) -> Dict[str, Any]:
        totals = {"live": 0, "private": 0, "shelf": 0}
        for item in self.sku_metrics:
            ch = item.get("channel_sales") or {}
            for k in totals:
                totals[k] += int(ch.get(k, 0))
        total_units = sum(totals.values()) or 1
        channels = {name: {"daily_units": v, "share_pct": round(v / total_units * 100, 2)} for name, v in totals.items()}
        return {"channels": channels, "total_daily_units": total_units}

    def _get_return_semantics(self) -> Dict[str, Any]:
        keywords = [("色差", "color_gap"), ("偏小", "sizing"), ("偏大", "sizing"),
                    ("易皱", "wrinkle"), ("起球", "pilling"), ("线头", "quality")]
        tag_counts: Dict[str, int] = {}
        for item in self.sku_metrics:
            for snippet in (item.get("review_snippets") or []):
                for sub, tag in keywords:
                    if sub in str(snippet):
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:5]
        return {"top_tags": top_tags, "total_hits": sum(tag_counts.values())}


SALES_AGENT_SYSTEM = """你是电商销售分析 Agent。你需要通过工具获取数据，然后输出经营分析。

工作流程：
1. 调用 get_sales_overview 了解全店概况
2. 调用 get_top_skus 分别获取畅销、滞销、高退货SKU
3. 调用 get_channel_analysis 了解渠道状况
4. 调用 get_return_semantics 了解退货原因
5. 最后输出分析结论

以下是历史经验：
{experiences}

完成后输出分析结论（纯文本），包含：
1. 一段经营摘要（3-4句话）
2. 3-5条行动要点（每条一句话）
"""


class SalesAgentV2:
    """Tool-based 销售分析 Agent。"""

    def __init__(self, llm_client):
        self._llm = llm_client

    def analyze(self, sku_metrics: List[Dict], top_trends: List[Dict],
                growing_trends: List[Dict], experiences: Optional[List[Dict]] = None) -> Dict[str, Any]:
        executor = SalesToolExecutor(sku_metrics, top_trends, growing_trends)

        exp_text = "无"
        if experiences:
            lines = [f"- [{e.get('confidence','')}] {e.get('title','')}" for e in experiences[:3]]
            exp_text = "\n".join(lines) if lines else "无"

        system = SALES_AGENT_SYSTEM.format(experiences=exp_text)
        user_msg = f"请对当前店铺（{len(sku_metrics)}个SKU）进行销售分析。"

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]

        for _ in range(6):
            response = self._llm.chat_with_tools(messages, tools=SALES_TOOLS, temperature=0.0)
            if response.get("tool_calls"):
                for call in response["tool_calls"]:
                    fn_name = call["function"]["name"]
                    fn_args = json.loads(call["function"]["arguments"]) if isinstance(call["function"]["arguments"], str) else call["function"]["arguments"]
                    result = executor.execute(fn_name, fn_args)
                    messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
                    messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(result, ensure_ascii=False)})
            else:
                content = response.get("content", "")
                # 构建结构化输出
                overview = executor._get_overview()
                return {
                    "summary": overview,
                    "llm_executive_brief": {"executive_summary": content[:500], "action_bullets": self._extract_bullets(content)},
                    "top_skus": executor._get_top_skus("top", 5)["skus"],
                    "lagging_skus": executor._get_top_skus("lagging", 5)["skus"],
                    "high_return_skus": executor._get_top_skus("high_return", 5)["skus"],
                    "channel_dashboard": executor._get_channel_analysis(),
                    "return_semantics": executor._get_return_semantics(),
                    "trend_focus": [{"keyword": t.get("keyword", ""), "platform": t.get("platform", ""), "heat_score": t.get("heat_score", 0), "growth_rate_pct": t.get("growth_rate_pct", 0)} for t in (growing_trends or [])[:5]],
                }

        # Fallback
        overview = executor._get_overview()
        return {
            "summary": overview,
            "llm_executive_brief": None,
            "top_skus": executor._get_top_skus("top", 5)["skus"],
            "lagging_skus": executor._get_top_skus("lagging", 5)["skus"],
            "high_return_skus": executor._get_top_skus("high_return", 5)["skus"],
            "channel_dashboard": executor._get_channel_analysis(),
            "return_semantics": executor._get_return_semantics(),
            "trend_focus": [],
        }

    @staticmethod
    def _extract_bullets(content: str) -> List[str]:
        lines = content.split("\n")
        bullets = []
        for line in lines:
            line = line.strip()
            if re.match(r"^\d+[\.\、]", line):
                bullets.append(re.sub(r"^\d+[\.\、]\s*", "", line))
            elif line.startswith("- "):
                bullets.append(line[2:])
        return bullets[:5] if bullets else [content[:100]]
