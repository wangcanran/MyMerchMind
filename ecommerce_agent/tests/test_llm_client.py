"""LLM 客户端与 Agent 可选 LLM 路径的单元测试。"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecommerce_agent.llm.client import LLMClientError, OpenAICompatChatClient
from ecommerce_agent.llm.config import LLMConfig
from ecommerce_agent.llm.json_util import parse_json_object
from ecommerce_agent.agents.sales_review_agent import SalesReviewAgent


def _cfg() -> LLMConfig:
    return LLMConfig(
        base_url="https://example.com/v1",
        chat_path="/chat/completions",
        api_key="test-key",
        model="dummy-model",
        timeout_s=10.0,
    )


def test_openai_compat_chat_parses_message_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content.decode())
        assert body["model"] == "dummy-model"
        assert body["messages"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "  hello world  "}}]},
        )

    transport = httpx.MockTransport(handler)
    client = OpenAICompatChatClient(_cfg(), transport=transport)
    assert client.chat([{"role": "user", "content": "hi"}]) == "hello world"


def test_openai_compat_raises_on_missing_choices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = OpenAICompatChatClient(_cfg(), transport=transport)
    try:
        client.chat([{"role": "user", "content": "x"}])
        assert False, "expected LLMClientError"
    except LLMClientError:
        pass


def test_parse_json_object_strips_fence() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert parse_json_object(raw)["a"] == 1


def test_sales_review_agent_llm_appends_brief() -> None:
    payload = {
        "executive_summary": "摘要",
        "action_bullets": ["行动一", "行动二"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    llm = OpenAICompatChatClient(_cfg(), transport=transport)
    agent = SalesReviewAgent(llm_client=llm, use_llm=True)

    sku_metrics = [
        {
            "sku_id": "A1",
            "name": "测试裙",
            "daily_sales": 10,
            "stock": 5,
            "in_transit": 0,
            "return_rate": 0.05,
            "channel_sales": {"live": 5, "private": 3, "shelf": 2},
            "prior_week_total_units": 60,
            "prior_month_total_units": 200,
            "review_snippets": [],
        }
    ]
    top_trends = [{"keyword": "美拉德", "platform": "x", "heat_score": 100, "growth_rate": 0.1}]
    growing = [{"keyword": "牛仔", "growth_rate": 0.2}]

    out = agent.analyze(sku_metrics, top_trends, growing, top_n=3)
    assert out["data_source"] == "hybrid"
    assert out["llm_executive_brief"]["executive_summary"] == "摘要"
    assert any("【LLM】行动一" in r for r in out["recommendations"])
