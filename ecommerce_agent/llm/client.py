"""OpenAI 兼容 Chat Completions HTTP 客户端（httpx）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    import httpx
except ImportError:
    httpx = None

from .config import LLMConfig, load_llm_config


class LLMClientError(Exception):
    """LLM HTTP 调用或响应解析失败。"""


class OpenAICompatChatClient:
    """POST JSON 到 /v1/chat/completions 风格接口。"""

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        transport: Optional[Any] = None,
    ):
        self._config = config if config is not None else load_llm_config()
        self._transport = transport

    @property
    def config(self) -> LLMConfig:
        return self._config

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.0,
        response_format: Optional[Dict[str, str]] = None,
    ) -> str:
        """返回 assistant 的纯文本 content。"""
        if httpx is None:
            raise LLMClientError("缺少依赖 httpx，无法启用 LLM 模式；请安装 requirements-dev.txt 或单独安装 httpx")
        if not self._config.is_configured():
            raise LLMClientError("LLM API key 未配置（MOARK_API_KEY / LLM_API_KEY / OPENAI_API_KEY）")

        url = f"{self._config.base_url}{self._config.chat_path}"
        payload: Dict[str, Any] = {
            "model": model or self._config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": int(getattr(self._config, "max_output_tokens", 4096)),
        }
        if response_format is not None:
            payload["response_format"] = response_format
        extra_body = getattr(self._config, "extra_body", None)
        if isinstance(extra_body, dict) and extra_body:
            for k, v in extra_body.items():
                if k in payload:
                    continue
                payload[k] = v

        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        extra_headers = getattr(self._config, "extra_headers", None)
        if isinstance(extra_headers, dict) and extra_headers:
            for k, v in extra_headers.items():
                if k in headers:
                    continue
                headers[k] = str(v)

        try:
            client_kw: Dict[str, Any] = {"timeout": self._config.timeout_s}
            if self._transport is not None:
                client_kw["transport"] = self._transport
            with httpx.Client(**client_kw) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except ValueError as e:
            raise LLMClientError(f"响应非 JSON: {e}") from e
        except httpx.HTTPError as e:
            raise LLMClientError(f"HTTP 请求失败: {e}") from e

        try:
            choices = data.get("choices") or []
            if not choices:
                raise LLMClientError("响应无 choices")
            choice0 = choices[0] if isinstance(choices[0], dict) else {}

            msg = choice0.get("message") if isinstance(choice0, dict) else None
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    s = content.strip()
                    if s:
                        return s
                if isinstance(content, list):
                    parts: List[str] = []
                    for part in content:
                        if isinstance(part, str):
                            parts.append(part)
                            continue
                        if isinstance(part, dict):
                            text = part.get("text")
                            if isinstance(text, str):
                                parts.append(text)
                                continue
                            alt = part.get("content")
                            if isinstance(alt, str):
                                parts.append(alt)
                    joined = "".join(parts).strip()
                    if joined:
                        return joined

            legacy_text = choice0.get("text") if isinstance(choice0, dict) else None
            if isinstance(legacy_text, str) and legacy_text.strip():
                return legacy_text.strip()

            output_text = data.get("output_text") if isinstance(data, dict) else None
            if isinstance(output_text, str) and output_text.strip():
                return output_text.strip()

            reasoning = msg.get("reasoning_content") or msg.get("reasoning") if isinstance(msg, dict) else None
            if isinstance(reasoning, str) and reasoning.strip():
                return reasoning.strip()

            msg_keys = list(msg.keys()) if isinstance(msg, dict) else []
            choice_keys = list(choice0.keys()) if isinstance(choice0, dict) else []
            raise LLMClientError(
                "响应缺少可解析的内容（期望 choices[0].message.content 为 str 或 list）。"
                f" message keys={msg_keys}, choice keys={choice_keys}"
            )
        except LLMClientError:
            raise
        except Exception as e:
            raise LLMClientError(f"解析响应失败: {e}") from e
