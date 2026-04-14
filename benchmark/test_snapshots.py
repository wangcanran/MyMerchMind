"""L3：默认 Mock 编排器摘要回归（固定 seed）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.report_digest import digest_report
from ecommerce_agent.orchestrator import DemoOrchestrator

SNAPSHOT_PATH = ROOT / "benchmark" / "snapshots" / "orchestrator_seed_42_digest.json"


def test_orchestrator_digest_matches_snapshot() -> None:
    report = DemoOrchestrator(seed=42, top_n=5, as_of="2026-04-14").run()
    digest = digest_report(report)

    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(
            json.dumps(digest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        pytest.skip("已更新快照（UPDATE_SNAPSHOTS=1）")

    assert SNAPSHOT_PATH.is_file(), f"缺少快照文件：{SNAPSHOT_PATH}（可设 UPDATE_SNAPSHOTS=1 生成）"
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert digest == expected
