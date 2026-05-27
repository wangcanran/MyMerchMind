"""数据接入配置：环境变量 + 可选 CLI 覆盖。

环境变量（均为可选）：
  ECOMMERCE_ERP_JSON              ERP SKU 数据 JSON 路径；设置则使用文件而非 mock
  ECOMMERCE_TRENDS_JSON           社媒趋势 JSON 路径
  ECOMMERCE_COMPETITORS_JSON      竞品对照 JSON 路径
  ECOMMERCE_TAGS_JSON             SKU 多维标签 JSON 路径
  ECOMMERCE_COMPETITORS_SOURCE    竞品数据源：``mock``（默认） | ``taobao``（现场爬虫）
  TAOBAO_COOKIE                   走 taobao 数据源时使用的登录 Cookie
  TAOBAO_COMPETITOR_MAX_ITEMS     每次搜索最多抓取条数（默认 30）
  TAOBAO_COMPETITOR_CACHE_TTL_SEC 缓存 TTL（秒，默认 21600 即 6 小时）
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_VALID_COMPETITORS_SOURCES = {"mock", "taobao"}


def _env_path(name: str) -> Optional[Path]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _normalize_competitors_source(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    if v not in _VALID_COMPETITORS_SOURCES:
        return "mock"
    return v


@dataclass
class DataSourceSettings:
    """各数据源路径；未指定路径的组件仍使用 mock。"""

    erp_json: Optional[Path] = None
    trends_json: Optional[Path] = None
    competitors_json: Optional[Path] = None
    tags_json: Optional[Path] = None
    # 竞品数据源开关：``mock``（默认）或 ``taobao``（现场爬虫）。
    competitors_source: str = "mock"
    # 走 taobao 时的可选参数；taobao_cookie 为空则会尝试匿名抓取，失败自动降级到 mock。
    taobao_cookie: str = ""
    taobao_max_items: int = 30
    taobao_cache_ttl_sec: int = 6 * 3600

    def describe(self) -> str:
        parts = []
        parts.append(f"erp={'file' if self.erp_json else 'mock'}")
        parts.append(f"trends={'file' if self.trends_json else 'mock'}")
        if self.competitors_source == "taobao":
            comp_label = "taobao_live"
        elif self.competitors_json:
            comp_label = "file"
        else:
            comp_label = "mock"
        parts.append(f"competitors={comp_label}")
        parts.append(f"tags={'file' if self.tags_json else 'mock'}")
        return ", ".join(parts)


def load_data_source_settings(
    *,
    erp_json: Optional[Path] = None,
    trends_json: Optional[Path] = None,
    competitors_json: Optional[Path] = None,
    tags_json: Optional[Path] = None,
    competitors_source: Optional[str] = None,
    taobao_cookie: Optional[str] = None,
    taobao_max_items: Optional[int] = None,
    taobao_cache_ttl_sec: Optional[int] = None,
) -> DataSourceSettings:
    """CLI 参数优先，否则读环境变量。"""
    return DataSourceSettings(
        erp_json=erp_json or _env_path("ECOMMERCE_ERP_JSON"),
        trends_json=trends_json or _env_path("ECOMMERCE_TRENDS_JSON"),
        competitors_json=competitors_json or _env_path("ECOMMERCE_COMPETITORS_JSON"),
        tags_json=tags_json or _env_path("ECOMMERCE_TAGS_JSON"),
        competitors_source=_normalize_competitors_source(
            competitors_source or os.environ.get("ECOMMERCE_COMPETITORS_SOURCE")
        ),
        taobao_cookie=(taobao_cookie if taobao_cookie is not None
                       else os.environ.get("TAOBAO_COOKIE", "")).strip(),
        taobao_max_items=(taobao_max_items if taobao_max_items is not None
                          else _env_int("TAOBAO_COMPETITOR_MAX_ITEMS", 30)),
        taobao_cache_ttl_sec=(taobao_cache_ttl_sec if taobao_cache_ttl_sec is not None
                              else _env_int("TAOBAO_COMPETITOR_CACHE_TTL_SEC", 6 * 3600)),
    )
