"""SKU 指标快照：编排内各模块共享同一份深拷贝，避免串改导致报告现价不一致。"""
from __future__ import annotations

import copy
from typing import Any, Dict, List


def deep_copy_sku_metrics(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """返回 ERP 行的深拷贝列表；各 Agent 只读自己的副本逻辑，不污染他处。"""
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, dict):
            out.append(copy.deepcopy(row))
    return out
