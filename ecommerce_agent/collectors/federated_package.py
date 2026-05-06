"""联邦学习侧：仅导出类目级聚合数值 + 哈希键，不输出原始竞品文案（可对接 FATE 前的数据准备）。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from .paths import write_json


def _salt() -> str:
    return os.environ.get("ECOMMERCE_FEDERATION_SALT", "ecommerce-agent-demo-salt")


def package_for_federation(competitors_json: Path, out_json: Path) -> Path:
    """读取 competitors JSON，生成脱敏聚合包。"""
    root = json.loads(competitors_json.read_text(encoding="utf-8"))
    rows: List[Dict[str, Any]] = list(root.get("rows") or [])
    salt = _salt()
    nodes: List[Dict[str, Any]] = []
    for row in rows:
        ck = str(row.get("category_key", ""))
        h = hashlib.sha256(f"{salt}:{ck}".encode("utf-8")).hexdigest()
        nodes.append(
            {
                "category_key_hmac": h[:24],
                "competitor_new_skus_30d": int(row.get("competitor_new_skus_30d", 0) or 0),
                "ours_new_skus_30d": int(row.get("ours_new_skus_30d", 0) or 0),
                "price_band_present": bool(row.get("price_band")),
            }
        )
    payload = {
        "format": "federation_aggregate_v1",
        "note": "不含类目明文与 gap 文本；真实联邦训练请接入 FATE / 隐私计算平台",
        "nodes": nodes,
    }
    write_json(out_json, payload)
    return out_json
