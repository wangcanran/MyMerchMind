"""OpenAI 兼容 Chat API 的环境配置。"""
import json
import os
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class LLMConfig:
    """从环境变量读取；未设置时使用安全默认值。"""

    base_url: str
    chat_path: str
    api_key: str
    model: str
    timeout_s: float
    max_output_tokens: int = 4096
    extra_headers: Dict[str, str] = field(default_factory=dict)
    extra_body: Dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "LLMConfig":
        base_raw = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
        base = _normalize_base_url(base_raw)

        path_raw = os.environ.get("LLM_CHAT_PATH", "/chat/completions")
        path = _clean_env_string(path_raw) or "/chat/completions"
        if not path.startswith("/"):
            path = "/" + path

        key = _clean_env_string(
            os.environ.get("MOARK_API_KEY")
            or os.environ.get("LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        model = _clean_env_string(os.environ.get("LLM_MODEL", "gpt-4o-mini")) or "gpt-4o-mini"
        timeout = float(_clean_env_string(os.environ.get("LLM_TIMEOUT_S", "60")) or "60")

        raw_max = _clean_env_string(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "4096")) or "4096"
        try:
            max_out = int(raw_max)
        except ValueError:
            max_out = 4096
        max_out = max(1, min(max_out, 4096))

        extra_headers = _load_json_dict(os.environ.get("LLM_EXTRA_HEADERS_JSON"))
        extra_body = _load_json_dict(os.environ.get("LLM_EXTRA_BODY_JSON"))

        return cls(
            base_url=base,
            chat_path=path,
            api_key=key,
            model=model,
            timeout_s=timeout,
            max_output_tokens=max_out,
            extra_headers={k: str(v) for k, v in (extra_headers or {}).items()},
            extra_body=extra_body or {},
        )

    def is_configured(self) -> bool:
        return bool(self.api_key.strip())


def load_llm_config() -> LLMConfig:
    return LLMConfig.from_env()


def _load_json_dict(s: Optional[str]) -> Optional[Dict[str, object]]:
    raw = (s or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def _clean_env_string(s: Optional[str]) -> str:
    raw = (s or "").strip()
    if not raw:
        return ""
    for _ in range(3):
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"`", '"', "'"}:
            raw = raw[1:-1].strip()
            continue
        if raw.startswith("`") and raw.endswith("`") and len(raw) >= 2:
            raw = raw[1:-1].strip()
            continue
        break
    return raw


def _normalize_base_url(s: Optional[str]) -> str:
    raw = _clean_env_string(s) or "https://api.openai.com/v1"
    return raw.rstrip("/")
