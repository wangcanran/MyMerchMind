"""OpenAI 兼容 Chat Completions HTTP 客户端（httpx）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .config import LLMConfig, load_llm_config


class LLMClientError(Exception):
    """LLM HTTP 调用或响应解析失败。"""


class OpenAICompatChatClient:
    """POST JSON 到 /v1/chat/completions 风格接口。"""

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self._config = config if config is not None else load_llm_config()
        self._transport = transport

    @property
    def config(self) -> LLMConfig:
        return self._config

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.0,
        response_format: Optional[Dict[str, str]] = None,
    ) -> str:
        """返回 assistant 的纯文本 content。"""
        if not self._config.is_configured():
            raise LLMClientError("LLM API key 未配置（LLM_API_KEY 或 OPENAI_API_KEY）")

        url = f"{self._config.base_url}{self._config.chat_path}"
        payload: Dict[str, Any] = {
            "model": model or self._config.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

        try:
            client_kw: Dict[str, Any] = {"timeout": self._config.timeout_s}
            if self._transport is not None:
                client_kw["transport"] = self._transport
            with httpx.Client(**client_kw) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise LLMClientError(f"HTTP 请求失败: {e}") from e
        except ValueError as e:
            raise LLMClientError(f"响应非 JSON: {e}") from e

        try:
            choices = data.get("choices") or []
            if not choices:
                raise LLMClientError("响应无 choices")
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if content is None or not isinstance(content, str):
                raise LLMClientError("响应缺少 message.content")
            return content.strip()
        except LLMClientError:
            raise
        except Exception as e:
            raise LLMClientError(f"解析响应失败: {e}") from e
