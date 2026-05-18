from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def load_category_mapping(path: Path) -> Dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json(path)
    if suffix == ".csv":
        return _load_csv(path)
    raise ValueError(f"不支持的映射文件类型：{path.suffix}（仅支持 .json/.csv）")


def _load_json(path: Path) -> Dict[str, str]:
    text = path.read_text(encoding="utf-8")
    root = json.loads(text)
    if isinstance(root, dict):
        mapping: Dict[str, str] = {}
        for k, v in root.items():
            kk = str(k).strip()
            vv = str(v).strip()
            if kk and vv:
                mapping[kk] = vv
        return mapping
    if isinstance(root, list):
        mapping = {}
        for row in root:
            if not isinstance(row, dict):
                continue
            sku_id = _pick(row, ("sku_id", "sku", "SKU", "skuId", "skuID"))
            category = _pick(row, ("category", "category_name", "cate", "cat", "class", "类目", "品类"))
            if sku_id and category:
                mapping[sku_id] = category
        return mapping
    raise ValueError(f"{path}: JSON 根对象需为 dict 或 list")


def _load_csv(path: Path) -> Dict[str, str]:
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    sku_key = _match_header(reader.fieldnames or [], ("sku_id", "sku", "skuid", "sku id", "sku编号", "sku编码"))
    cat_key = _match_header(reader.fieldnames or [], ("category", "cate", "cat", "class", "类目", "品类", "品类名称"))
    if not sku_key or not cat_key:
        raise ValueError(f"{path}: CSV 需包含 SKU 与品类列")

    mapping: Dict[str, str] = {}
    for row in reader:
        sku_id = str(row.get(sku_key, "")).strip()
        category = str(row.get(cat_key, "")).strip()
        if sku_id and category:
            mapping[sku_id] = category
    return mapping


def _pick(row: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for k in keys:
        if k in row and row[k] is not None:
            s = str(row[k]).strip()
            if s:
                return s
    return None


def _match_header(headers: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    normalized = {str(h).strip().lower(): str(h) for h in headers if h is not None}
    for c in candidates:
        key = str(c).strip().lower()
        if key in normalized:
            return normalized[key]
    return None

