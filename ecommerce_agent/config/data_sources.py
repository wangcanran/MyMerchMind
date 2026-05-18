"""数据接入配置：环境变量 + 可选 CLI 覆盖。

环境变量（均为可选）：
  ECOMMERCE_ERP_JSON          ERP SKU 数据 JSON 路径；设置则使用文件而非 mock
  ECOMMERCE_TRENDS_JSON       社媒趋势 JSON 路径
  ECOMMERCE_COMPETITORS_JSON  竞品对照 JSON 路径
  ECOMMERCE_TAGS_JSON         SKU 多维标签 JSON 路径
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _env_path(name: str) -> Optional[Path]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


@dataclass
class DataSourceSettings:
    """各数据源路径；未指定路径的组件仍使用 mock。"""

    erp_json: Optional[Path] = None
    trends_json: Optional[Path] = None
    competitors_json: Optional[Path] = None
    tags_json: Optional[Path] = None

    def describe(self) -> str:
        parts = []
        parts.append(f"erp={'file' if self.erp_json else 'mock'}")
        parts.append(f"trends={'file' if self.trends_json else 'mock'}")
        parts.append(f"competitors={'file' if self.competitors_json else 'mock'}")
        parts.append(f"tags={'file' if self.tags_json else 'mock'}")
        return ", ".join(parts)


def load_data_source_settings(
    *,
    erp_json: Optional[Path] = None,
    trends_json: Optional[Path] = None,
    competitors_json: Optional[Path] = None,
    tags_json: Optional[Path] = None,
) -> DataSourceSettings:
    """CLI 参数优先，否则读环境变量。"""
    return DataSourceSettings(
        erp_json=erp_json or _env_path("ECOMMERCE_ERP_JSON"),
        trends_json=trends_json or _env_path("ECOMMERCE_TRENDS_JSON"),
        competitors_json=competitors_json or _env_path("ECOMMERCE_COMPETITORS_JSON"),
        tags_json=tags_json or _env_path("ECOMMERCE_TAGS_JSON"),
    )
