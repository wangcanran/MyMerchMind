"""
选品 Agent（独立运行）：输入店铺语境条件 ``criteria``（风格、季节、地点、价位等，可由需求文档解析），
经知识图谱检索 + 本仓库 LLM 输出结构化品类建议；可与 ERP/竞品价格在编排层对比后再接库存模块。

环境变量见 ``ecommerce_agent/llm/config.py``（``LLM_BASE_URL``、``LLM_API_KEY``、``LLM_MODEL`` 等）。
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from ..llm import load_llm_config, prompts
from ..llm.client import LLMClientError, OpenAICompatChatClient
from ..llm.json_util import parse_json_object

from .kg_engagement_lookup import (
    collect_file_paths_from_query_data,
    format_engagement_for_prompt,
)

_ROOT = Path(__file__).resolve().parent.parent

try:
    from config import settings as _RUNTIME_SETTINGS
except ImportError:
    _RUNTIME_SETTINGS = SimpleNamespace(
        product_selection_include_engagement=os.environ.get(
            "PRODUCT_SELECTION_INCLUDE_ENGAGEMENT", ""
        ).strip().lower()
        in ("1", "true", "yes"),
        max_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "4096")),
    )


class ProductSelectionAgent:
    """用 ``criteria``（风格、季节、地点、需求文档解析结果等）查询知识图谱并由 LLM 生成选品 JSON。
    与历史销售/竞品/定价/库存的对比与补货，由上层编排（或后续 pipeline）组合其他 Agent 完成。
    """

    @staticmethod
    def _source_post_context_lines(criteria: dict) -> List[str]:
        lines: List[str] = []
        sp = criteria.get("source_post")
        if isinstance(sp, dict):
            if sp.get("source_post_id"):
                lines.append(f"原帖 ID: {sp['source_post_id']}")
            if sp.get("title"):
                lines.append(f"标题: {sp['title']}")
            if sp.get("url"):
                lines.append(f"链接: {sp['url']}")
            lk, cl = sp.get("liked_count"), sp.get("collected_count")
            if lk is not None or cl is not None:
                lines.append(
                    f"点赞: {lk if lk is not None else '（未提供）'}；"
                    f"收藏: {cl if cl is not None else '（未提供）'}"
                )
            if sp.get("search_keyword"):
                lines.append(f"检索词: {sp['search_keyword']}")
            return lines

        lk, cl = criteria.get("liked_count"), criteria.get("collected_count")
        if lk is not None or cl is not None:
            lines.append(
                f"原帖互动（溯源传入）点赞: {lk if lk is not None else '（未提供）'}；"
                f"收藏: {cl if cl is not None else '（未提供）'}"
            )
        if criteria.get("source_post_id"):
            lines.append(f"原帖 ID: {criteria['source_post_id']}")
        if criteria.get("source_post_url"):
            lines.append(f"原帖链接: {criteria['source_post_url']}")
        if criteria.get("search_keyword"):
            lines.append(f"检索词: {criteria['search_keyword']}")
        return lines

    @staticmethod
    def _criteria_has_traced_engagement_counts(criteria: dict) -> bool:
        sp = criteria.get("source_post")
        if isinstance(sp, dict) and ("liked_count" in sp or "collected_count" in sp):
            return True
        return "liked_count" in criteria or "collected_count" in criteria

    @staticmethod
    def _skip_global_trending_query(criteria: dict, auto_engagement_text: str) -> bool:
        if ProductSelectionAgent._criteria_has_traced_engagement_counts(criteria):
            return True
        return bool((auto_engagement_text or "").strip())

    @staticmethod
    def _extract_balanced_json_object(s: str) -> Optional[str]:
        start = s.find("{")
        if start < 0:
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(s)):
            c = s[i]
            if in_string:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_string = False
            else:
                if c == '"':
                    in_string = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return s[start : i + 1]
        return None

    @staticmethod
    def _parse_llm_json(text: str) -> dict:
        raw = (text or "").strip()
        candidates: List[str] = []

        def _push(x: Optional[str]) -> None:
            if x and x.strip():
                candidates.append(x.strip())

        _push(raw)
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            while lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            _push("\n".join(lines).strip())

        extracted = ProductSelectionAgent._extract_balanced_json_object(raw)
        _push(extracted)

        seen: set[str] = set()
        last_err: Optional[Exception] = None
        for cand in candidates:
            if cand in seen:
                continue
            seen.add(cand)
            try:
                data = json.loads(cand)
                if isinstance(data, dict):
                    return data
                last_err = ValueError("JSON 根节点必须是对象")
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                last_err = e
                continue
        if last_err:
            raise last_err
        raise ValueError("无法从模型输出中解析 JSON 对象")

    @staticmethod
    def _parse_llm_response(text: str) -> dict:
        try:
            return parse_json_object(text)
        except (ValueError, TypeError, json.JSONDecodeError):
            return ProductSelectionAgent._parse_llm_json(text)

    def __init__(
        self,
        kg_working_dir: str = "ecommerce_agent/kg_storage_v2",
        *,
        include_engagement: Optional[bool] = None,
        llm_client: Optional[OpenAICompatChatClient] = None,
    ):
        """
        Args:
            kg_working_dir: LightRAG 工作目录
            include_engagement: 是否使用赞藏回溯；None 时用 ``config`` 或环境变量
            llm_client: 可选；不传则在图谱选品调用时按 ``load_llm_config()`` 自动构造
        """
        self.kg_working_dir = kg_working_dir
        if include_engagement is not None:
            self._include_engagement_default = bool(include_engagement)
        else:
            self._include_engagement_default = bool(
                getattr(_RUNTIME_SETTINGS, "product_selection_include_engagement", False)
            )
        self._llm = llm_client
        self.kg: Any = None

    def _get_llm(self) -> OpenAICompatChatClient:
        if self._llm is not None:
            return self._llm
        cfg = load_llm_config()
        if not cfg.is_configured():
            raise LLMClientError(
                "未配置 LLM：请设置 LLM_API_KEY 或 OPENAI_API_KEY（可选 LLM_BASE_URL、LLM_MODEL），"
                "参见 ecommerce_agent/llm/config.py"
            )
        self._llm = OpenAICompatChatClient(cfg)
        return self._llm

    def _chat_selection(self, user_content: str) -> str:
        client = self._get_llm()
        return client.chat(
            [
                {"role": "system", "content": prompts.PRODUCT_SELECTION_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
        )

    @staticmethod
    def _criteria_include_engagement_flag(criteria: dict) -> Optional[bool]:
        if "include_engagement" not in criteria:
            return None
        v = criteria["include_engagement"]
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            low = v.strip().lower()
            if low in ("1", "true", "yes", "on"):
                return True
            if low in ("0", "false", "no", "off"):
                return False
        return bool(v)

    def _use_engagement_for_query(self, criteria: dict) -> bool:
        o = ProductSelectionAgent._criteria_include_engagement_flag(criteria)
        if o is not None:
            return o
        return self._include_engagement_default

    async def _ensure_kg_initialized(self) -> None:
        if self.kg is None:
            from ..kg_builder import ClothingKnowledgeGraph

            self.kg = ClothingKnowledgeGraph(working_dir=self.kg_working_dir)
            await self.kg.initialize()

    def analyze_sync(self, criteria: dict) -> dict:
        """同步：给定选品条件，跑图谱 + 本仓库 LLM。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.analyze_async(criteria))
        finally:
            loop.close()

    async def analyze_async(self, criteria: dict) -> dict:
        await self._ensure_kg_initialized()
        kg_insights = await self._query_knowledge_graph(criteria)
        user_prompt = self._build_analysis_prompt(criteria, kg_insights)

        try:
            raw = self._chat_selection(user_prompt)
        except LLMClientError as e:
            return {
                "criteria": criteria,
                "error": str(e),
                "kg_insights": kg_insights,
                "timestamp": datetime.now().isoformat(),
                "llm_error": str(e),
            }

        try:
            recommendation = self._parse_llm_response(raw)
            return {
                "criteria": criteria,
                "recommendation": recommendation,
                "kg_insights": kg_insights,
                "timestamp": datetime.now().isoformat(),
                "llm_error": None,
            }
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            return {
                "criteria": criteria,
                "error": "Failed to parse recommendation",
                "raw_response": raw,
                "kg_insights": kg_insights,
                "timestamp": datetime.now().isoformat(),
                "llm_error": str(e),
            }

    async def _query_knowledge_graph(self, criteria: dict) -> dict:
        insights: Dict[str, Any] = {}
        auto_engagement = ""
        use_eng = self._use_engagement_for_query(criteria)

        if use_eng and (criteria.get("season") or criteria.get("target_style")):
            q_sel = self.kg.build_selection_question(criteria)
            raw = await self.kg.query_data(q_sel, mode="hybrid", top_k=30)
            paths = collect_file_paths_from_query_data(raw)
            auto_engagement = format_engagement_for_prompt(_ROOT, paths)
            if auto_engagement:
                insights["retrieved_source_engagement"] = auto_engagement

        skip_trending = not use_eng or self._skip_global_trending_query(
            criteria, auto_engagement
        )

        if criteria.get("season"):
            result = await self.kg.get_seasonal_trends(criteria["season"])
            insights["seasonal_trends"] = result.get("answer", "")

        if criteria.get("target_style"):
            result = await self.kg.get_style_recommendations(criteria["target_style"])
            insights["style_recommendations"] = result.get("answer", "")

        if criteria.get("temperature_range"):
            result = await self.kg.analyze_temperature_range(criteria["temperature_range"])
            insights["temperature_recommendations"] = result.get("answer", "")

        if skip_trending:
            if use_eng:
                insights["trending_categories"] = (
                    "已跳过图谱侧「按点赞/收藏列全局热门品类」查询（语料入库不含互动统计，或已从 JSON 回溯到赞藏）。"
                    "热度请结合主提示词中的「溯源原帖补充」「检索命中记录的原帖互动」及下方图谱摘录中的品类与搭配。"
                )
        else:
            result = await self.kg.get_trending_categories()
            insights["trending_categories"] = result.get("answer", "")

        if criteria.get("season") or criteria.get("target_style"):
            result = await self.kg.query_for_selection(criteria)
            insights["comprehensive_analysis"] = result.get("answer", "")

        return insights

    def _build_analysis_prompt(self, criteria: dict, kg_insights: dict) -> str:
        prompt = f"""基于以下选品条件和市场数据，提供详细的选品建议：

## 选品条件
"""
        if criteria.get("season"):
            prompt += f"- 季节: {criteria['season']}\n"
        if criteria.get("target_style"):
            prompt += f"- 目标风格: {criteria['target_style']}\n"
        if criteria.get("temperature_range"):
            prompt += f"- 温度范围: {criteria['temperature_range']}\n"
        if criteria.get("occasion"):
            prompt += f"- 使用场景: {criteria['occasion']}\n"
        if criteria.get("price_range"):
            prompt += f"- 预算档位（用户填写，非图谱数据）: {criteria['price_range']}\n"
        if criteria.get("target_audience"):
            prompt += f"- 目标用户: {criteria['target_audience']}\n"

        if criteria.get("notes"):
            prompt += f"\n## 需求文档要点\n{criteria['notes']}\n"
        cons = criteria.get("constraints")
        if isinstance(cons, list) and cons:
            prompt += "\n## 需求文档中的其他约束\n"
            for c in cons:
                s = str(c).strip()
                if s:
                    prompt += f"- {s}\n"

        sp_lines = self._source_post_context_lines(criteria)
        if sp_lines:
            prompt += "\n## 溯源原帖补充（未写入知识图谱，可作该帖/同款热度参考）\n"
            for line in sp_lines:
                prompt += f"- {line}\n"

        if kg_insights.get("retrieved_source_engagement"):
            prompt += (
                "\n## 检索命中记录的原帖互动（由 file_path 回溯 JSON，非图谱字段）\n"
                f"{kg_insights['retrieved_source_engagement'][:4500]}\n"
            )

        prompt += (
            "\n## 市场数据分析\n"
            "（说明：下列小节来自分列检索，信息可能片段化；**禁止**在最终 JSON 里机械照搬成"
            "「季节一套 + 风格一套」两套品类；须按上文「一体化选品」交叉整合。）\n"
        )

        if kg_insights.get("seasonal_trends"):
            prompt += f"\n### 季节趋势\n{kg_insights['seasonal_trends'][:500]}\n"

        if kg_insights.get("style_recommendations"):
            prompt += f"\n### 风格建议\n{kg_insights['style_recommendations'][:500]}\n"

        if kg_insights.get("temperature_recommendations"):
            prompt += f"\n### 温度适配\n{kg_insights['temperature_recommendations'][:500]}\n"

        if kg_insights.get("trending_categories"):
            prompt += f"\n### 热门品类\n{kg_insights['trending_categories'][:500]}\n"

        if kg_insights.get("comprehensive_analysis"):
            prompt += f"\n### 综合分析\n{kg_insights['comprehensive_analysis'][:500]}\n"

        prompt += """

## 一体化选品（输出前必读）
下方「市场数据分析」中，季节趋势、温度适配、风格建议等小节可能分别来自不同检索片段，**不代表**你要分开展示三套品类清单。
在最终 JSON 中你必须：
1. 填写 `cross_dimension_summary`：用 3～6 句话概括「季节/气温语境 + 目标风格」如何共同决定本盘货的主线与补充线，明确若存在冲突时以谁优先（例如：复古叙事优先于泛季节爆款）。
2. `recommended_categories` 中**每一条**的 `reason` 必须**同段文字内**同时包含：①当季/气温下的实穿与结构（如叠穿、厚薄）；②如何体现目标风格；缺一不可。禁止只写「适合春季」或只写「符合复古」这类单侧理由。
3. `style_direction` 不得与 `recommended_categories` 脱节：`style_mix_suggestions` 应直接服务上述品类组合（可点名品类），而非泛泛而谈复古定义。

## 请提供 JSON 格式的选品建议

```json
{
  "cross_dimension_summary": "季节/气温与目标风格如何拧成一盘货的概括，含取舍原则",
  "recommended_categories": [
    {
      "category": "品类名称",
      "priority": "high/medium/low",
      "reason": "须同时写清：当季实穿（含温差/叠穿若适用）+ 如何体现目标风格",
      "specific_items": ["具体款式1", "具体款式2"],
      "colors": ["推荐颜色1", "推荐颜色2"],
      "materials": ["推荐材质1", "推荐材质2"],
      "expected_demand": "预期需求 (high/medium/low)",
      "market_competition": "市场竞争程度 (high/medium/low)"
    }
  ],
  "style_direction": {
    "primary_style": "主要风格",
    "secondary_styles": ["辅助风格1", "辅助风格2"],
    "style_mix_suggestions": "风格混搭建议"
  },
  "inventory_allocation": {
    "high_priority_ratio": 0.5,
    "medium_priority_ratio": 0.3,
    "low_priority_ratio": 0.2,
    "reasoning": "配比理由"
  },
  "marketing_suggestions": [
    "营销建议1",
    "营销建议2"
  ],
  "risk_assessment": {
    "seasonal_risk": "季节性风险评估",
    "competition_risk": "竞争风险评估",
    "inventory_risk": "库存风险评估"
  },
  "confidence_score": 0.85
}
```

请基于市场数据提供具体、可执行的选品建议。

【再次强调】你的**全部**回复内容只能是上述 Schema 的一个 JSON 对象，不要有任何其它字符。"""
        return prompt

    async def get_quick_recommendations(self, season: str, budget: str = "medium") -> dict:
        criteria = {
            "season": season,
            "price_range": budget,
            "target_audience": "年轻女性",
        }
        return await self.analyze_async(criteria)

    async def compare_styles(self, styles: List[str]) -> dict:
        await self._ensure_kg_initialized()
        comparisons: Dict[str, str] = {}
        for style in styles:
            result = await self.kg.get_style_recommendations(style)
            ans = result.get("answer") if isinstance(result, dict) else None
            if ans is None:
                comparisons[style] = ""
            elif isinstance(ans, str):
                comparisons[style] = ans
            else:
                comparisons[style] = str(ans)

        prompt = "比较以下服装风格的市场表现和选品价值：\n\n"
        for style, analysis in comparisons.items():
            snippet = (analysis or "")[:300]
            prompt += f"\n## {style}风格\n{snippet}\n"

        prompt += """

请以 JSON 格式提供比较分析：

```json
{
  "style_rankings": [
    {
      "style": "风格名称",
      "market_potential": "high/medium/low",
      "competition_level": "high/medium/low",
      "recommendation": "是否推荐",
      "reason": "理由"
    }
  ],
  "best_combination": "最佳风格组合建议",
  "market_gaps": ["市场空白1", "市场空白2"]
}
```
"""
        raw = ""
        try:
            raw = self._chat_selection(prompt)
            comparison_result = self._parse_llm_response(raw)
            return {
                "styles": styles,
                "comparison": comparison_result,
                "timestamp": datetime.now().isoformat(),
                "llm_error": None,
            }
        except LLMClientError as e:
            return {
                "styles": styles,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                "llm_error": str(e),
            }
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            return {
                "styles": styles,
                "error": "Failed to parse comparison",
                "raw_response": raw,
                "llm_error": str(e),
            }

    async def analyze_from_requirements_text(
        self,
        document_text: str,
        *,
        source_path: Optional[str] = None,
    ) -> dict:
        criteria = parse_selection_criteria_from_requirements_text(
            document_text,
            llm_client=self._llm,
        )
        result = await self.analyze_async(criteria)
        if source_path:
            result["requirements_file"] = source_path
        result["requirements_preview"] = (document_text or "")[:4000]
        result["parsed_criteria"] = {
            k: v for k, v in criteria.items() if not str(k).startswith("_")
        }
        return result

    async def analyze_from_requirements_path(self, path: str | Path) -> dict:
        p = Path(path)
        text = p.read_text(encoding="utf-8-sig")
        return await self.analyze_from_requirements_text(
            text, source_path=str(p.resolve())
        )

    async def finalize(self) -> None:
        if self.kg is not None:
            await self.kg.finalize()
            self.kg = None


def parse_selection_criteria_from_requirements_text(
    document_text: str,
    *,
    llm_client: Optional[OpenAICompatChatClient] = None,
) -> dict:
    """用本仓库 LLM 将需求文档抽成 criteria（需已配置 API Key）。"""
    body = (document_text or "").strip()
    if not body:
        raise ValueError("需求文档为空")

    client = llm_client
    if client is None:
        cfg = load_llm_config()
        if not cfg.is_configured():
            raise LLMClientError("需求解析需要已配置的 LLM（LLM_API_KEY / OPENAI_API_KEY）")
        client = OpenAICompatChatClient(cfg)

    human = prompts.REQUIREMENTS_CRITERIA_USER.format(body=body[:14000])
    raw = client.chat(
        [
            {"role": "system", "content": prompts.REQUIREMENTS_CRITERIA_SYSTEM},
            {"role": "user", "content": human},
        ],
        temperature=0.0,
    )
    data = ProductSelectionAgent._parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("需求解析结果不是 JSON 对象")
    return data


def write_selection_report_to_txt(
    selection_result: dict,
    *,
    comparison_result: Optional[dict] = None,
    output_path: Optional[str | Path] = None,
    kg_insights_max_chars: int = 520,
) -> Path:
    root = _ROOT
    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = root / f"selection_recommendation_{stamp}.txt"
    else:
        path = Path(output_path)
        if not path.is_absolute():
            path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    lines.append("服装选品建议报告")
    lines.append("=" * 60)
    lines.append(f"生成时间: {selection_result.get('timestamp', datetime.now().isoformat())}")
    rf = selection_result.get("requirements_file")
    if rf:
        lines.append(f"需求文档: {rf}")
    lines.append("")
    lines.append(
        "说明：下文「结构化选品建议」为结论主体；「附录」为图谱检索原文摘录，可能与结论重复，仅供核对。"
    )
    lines.append("")

    lines.append("## 结构化选品建议")
    if selection_result.get("recommendation") is not None:
        lines.append(json.dumps(selection_result["recommendation"], ensure_ascii=False, indent=2))
    else:
        lines.append(f"解析失败或未返回 recommendation: {selection_result.get('error', '')}")
        raw = selection_result.get("raw_response")
        if raw:
            lines.append("")
            lines.append("### 原始模型输出（节选，可据此人工整理）")
            lines.append(str(raw)[:4500])
    lines.append("")

    parsed = selection_result.get("parsed_criteria")
    crit = selection_result.get("criteria")
    if parsed:
        lines.append("## 选品条件（自需求文档解析）")
        lines.append(json.dumps(parsed, ensure_ascii=False, indent=2))
        lines.append("")
    elif crit:
        lines.append("## 选品条件（传入图谱/Agent）")
        lines.append(json.dumps(crit, ensure_ascii=False, indent=2))
        lines.append("")

    insights = selection_result.get("kg_insights")
    if insights:
        lines.append("## 附录：知识图谱检索摘录（节选）")
        cap = max(200, int(kg_insights_max_chars))
        for key, text in insights.items():
            lines.append(f"### {key}")
            body = (text or "").strip()
            if len(body) > cap:
                body = body[:cap] + "…"
            lines.append(body if body else "（空）")
            lines.append("")

    if comparison_result:
        lines.append("## 风格比较")
        if comparison_result.get("comparison") is not None:
            lines.append(json.dumps(comparison_result["comparison"], ensure_ascii=False, indent=2))
        else:
            lines.append(str(comparison_result.get("error", "")))
            raw = comparison_result.get("raw_response")
            if raw:
                lines.append("")
                lines.append(str(raw)[:4000])

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def get_selection_recommendation(criteria: dict) -> dict:
    agent = ProductSelectionAgent()
    return agent.analyze_sync(criteria)


async def get_selection_recommendation_async(criteria: dict) -> dict:
    agent = ProductSelectionAgent()
    try:
        return await agent.analyze_async(criteria)
    finally:
        await agent.finalize()


async def get_selection_from_requirements_async(document_text: str) -> dict:
    agent = ProductSelectionAgent()
    try:
        return await agent.analyze_from_requirements_text(document_text)
    finally:
        await agent.finalize()


if __name__ == "__main__":
    import argparse

    _repo_root = Path(__file__).resolve().parent.parent.parent

    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None  # type: ignore[assignment, misc]
    if load_dotenv is not None:
        load_dotenv(_repo_root / ".env", override=False)

    _sample_req = _repo_root / "ecommerce_agent" / "data" / "samples" / "selection_requirements_sample.md"
    _default_report = (
        _repo_root / "ecommerce_agent" / "data" / "samples" / "selection_report_sample.txt"
    )

    parser = argparse.ArgumentParser(description="服装选品 Agent（独立运行，使用本仓库 LLM 环境变量）")
    parser.add_argument(
        "--requirements",
        metavar="FILE",
        help="从需求文档（UTF-8 txt/md）解析条件并生成选品报告",
    )
    parser.add_argument("--out", metavar="FILE", help="报告输出路径（默认见 --sample）")
    parser.add_argument(
        "--sample",
        action="store_true",
        help=f"使用内置示例需求文档并生成报告（{_sample_req.name}）",
    )
    parser.add_argument("--demo", action="store_true", help="内置结构化条件演示")
    parser.add_argument(
        "--llm-smoke",
        action="store_true",
        help="仅测选品 LLM 连通与 PRODUCT_SELECTION_SYSTEM（不加载知识图谱）",
    )
    args = parser.parse_args()

    req_path: Optional[Path] = None
    report_out: Optional[str] = args.out
    if args.sample:
        req_path = _sample_req
        if report_out is None:
            report_out = str(_default_report)
    elif args.requirements:
        req_path = Path(args.requirements)

    async def demo_from_criteria():
        print("=" * 60)
        print("选品 Agent 测试（结构化条件）")
        print("=" * 60)

        agent = ProductSelectionAgent()
        try:
            print("\n春季选品建议…", flush=True)
            criteria = {
                "season": "春季",
                "temperature_range": "15-20度",
                "target_style": "甜美",
                "occasion": "日常通勤",
                "price_range": "平价",
                "target_audience": "年轻女性",
            }

            result = await agent.analyze_async(criteria)
            print(json.dumps(result.get("recommendation", {}), ensure_ascii=False, indent=2))

            print("\n风格比较…", flush=True)
            styles = ["甜美", "休闲", "韩系"]
            comparison = await agent.compare_styles(styles)
            print(json.dumps(comparison.get("comparison", {}), ensure_ascii=False, indent=2))

            out = write_selection_report_to_txt(
                result,
                comparison_result=comparison,
                output_path=args.out,
            )
            print(f"\n选品报告已写入: {out}")

        finally:
            await agent.finalize()

    async def run_from_requirements_file():
        assert req_path is not None
        if not req_path.is_file():
            raise SystemExit(f"找不到需求文件: {req_path.resolve()}")

        agent = ProductSelectionAgent()
        try:
            result = await agent.analyze_from_requirements_path(req_path)
            out = write_selection_report_to_txt(result, output_path=report_out)
            print(f"\n选品报告已写入: {out}", flush=True)
        finally:
            await agent.finalize()

    def run_llm_smoke() -> None:
        """不初始化图谱，只验证 OpenAI 兼容接口 + 选品 system 提示词。"""
        agent = ProductSelectionAgent()
        user = (
            "场景：春季、华东、日常通勤；店铺风格：韩系休闲；价位：平价。\n"
            "请严格按系统提示只输出一个 JSON 对象（可精简字段但须合法 JSON）。"
        )
        print("调用选品 LLM（无图谱）…", flush=True)
        raw = agent._chat_selection(user)
        print(raw[:8000] if len(raw) > 8000 else raw, flush=True)
        try:
            obj = agent._parse_llm_response(raw)
            print("\n[JSON 解析成功] 顶层键:", list(obj.keys())[:20], flush=True)
        except Exception as e:
            print("\n[JSON 解析未通过]", e, flush=True)

    if args.llm_smoke:
        run_llm_smoke()
    elif req_path is not None:
        asyncio.run(run_from_requirements_file())
    elif args.demo:
        asyncio.run(demo_from_criteria())
    else:
        parser.print_help()
        print(
            "\n单独输出选品报告（示例需求文档）:\n"
            "  python -m ecommerce_agent.agents.product_selection_agent --sample\n"
            "\n其它:\n"
            "  python -m ecommerce_agent.agents.product_selection_agent --demo\n"
            "  python -m ecommerce_agent.agents.product_selection_agent --llm-smoke\n"
            "  python -m ecommerce_agent.agents.product_selection_agent "
            "--requirements ecommerce_agent/data/samples/selection_requirements_sample.md\n",
            flush=True,
        )
