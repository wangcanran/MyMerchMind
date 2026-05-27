"""全链路统一的「高退货」判定阈值。

ERP 与各 Agent 使用的小数口径 ``return_rate``（0.10 表示 10%）。

可通过环境变量 ``ECOMMERCE_HIGH_RETURN_RATE`` 覆盖默认值：

- 小数：``0.12`` 表示 12%；
- 大于 1 的数：``12`` 或 ``12.5`` 表示百分数。
"""
from __future__ import annotations

import os

_DEFAULT_HIGH_RETURN_FRACTION = 0.10


def high_return_fraction() -> float:
    """视为高退货的下限：``return_rate >=`` 该值则进入高退货列表、处置动作、定价压价等。"""
    raw = os.environ.get("ECOMMERCE_HIGH_RETURN_RATE", "").strip()
    if not raw:
        return _DEFAULT_HIGH_RETURN_FRACTION
    try:
        v = float(raw)
    except ValueError:
        return _DEFAULT_HIGH_RETURN_FRACTION
    if v > 1.0:
        v = v / 100.0
    if v <= 0.0 or v > 0.5:
        return _DEFAULT_HIGH_RETURN_FRACTION
    return v


def high_return_rate_pct() -> float:
    """与 ``high_return_fraction()`` 对应的百分数（如 0.10 -> 10.0），供品类 KPI 等字段对比。"""
    return round(high_return_fraction() * 100.0, 4)


def is_high_return(return_rate: object) -> bool:
    """是否达到高退货红线（含恰等于阈值）。"""
    try:
        rr = float(return_rate or 0.0)
    except (TypeError, ValueError):
        return False
    return rr >= high_return_fraction()
