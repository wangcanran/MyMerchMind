"""采集结果默认输出目录。"""
from __future__ import annotations

from pathlib import Path


def package_data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def collected_dir() -> Path:
    d = package_data_dir() / "collected"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json(path: Path, payload: object) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
