"""运行时配置（数据接入等）。"""
from .data_sources import DataSourceSettings, load_data_source_settings
from .return_rate_thresholds import (
    high_return_fraction,
    high_return_rate_pct,
    is_high_return,
)

__all__ = [
    "DataSourceSettings",
    "load_data_source_settings",
    "high_return_fraction",
    "high_return_rate_pct",
    "is_high_return",
]
