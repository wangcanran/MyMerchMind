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

    @classmethod
    def from_env(cls) -> "LLMConfig":
        base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        path = os.environ.get("LLM_CHAT_PATH", "/chat/completions")
        if not path.startswith("/"):
            path = "/" + path
        key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        timeout = float(os.environ.get("LLM_TIMEOUT_S", "60"))
        return cls(
            base_url=base,
            chat_path=path,
            api_key=key,
            model=model,
            timeout_s=timeout,
        )

    def is_configured(self) -> bool:
        return bool(self.api_key.strip())


def load_llm_config() -> LLMConfig:
    return LLMConfig.from_env()
