"""OpenAI 兼容 Chat API 的环境配置。"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    """从环境变量读取；未设置时使用安全默认值。"""

    base_url: str
    chat_path: str
    api_key: str
    model: str
    timeout_s: float
    max_output_tokens: int

    @classmethod
    def from_env(cls) -> "LLMConfig":
        # 与 kg_builder 降级路径对齐：优先 LLM_*，其次兼容 OPENAI_BASE_URL（常见于 pydantic Settings）
        base = (
            os.environ.get("LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        path = os.environ.get("LLM_CHAT_PATH", "/chat/completions")
        if not path.startswith("/"):
            path = "/" + path
        key = (os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        timeout = float(os.environ.get("LLM_TIMEOUT_S", "60"))
        # 部分网关（如 Gitee AI）要求：非流式请求 max_tokens 不得超过 4096，否则须 stream=true
        _raw_max = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "4096"))
        max_out = max(1, min(_raw_max, 4096))
        return cls(
            base_url=base,
            chat_path=path,
            api_key=key,
            model=model,
            timeout_s=timeout,
            max_output_tokens=max_out,
        )

    def is_configured(self) -> bool:
        return bool(self.api_key.strip())


def load_llm_config() -> LLMConfig:
    return LLMConfig.from_env()
