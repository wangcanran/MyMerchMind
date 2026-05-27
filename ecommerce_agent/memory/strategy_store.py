"""
策略追踪存储。

将报告中的 action 建议持久化为可追踪的策略条目，
支持商家 Accept/Reject 和月末反馈闭环。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


_MODULE_KEYWORDS: Dict[str, List[str]] = {
    "selection": ["选品", "上新", "品类优先", "新品企划"],
    "pricing": ["定价", "调价", "调至", "现售"],
    "inventory": ["库存", "预警", "去化", "覆盖"],
    "replenishment": ["补货", "EOQ", "订货"],
    "slow_moving": ["滞销", "清仓", "促销", "调拨"],
    "category": ["品类动作", "退货", "渠道"],
}


def _classify_module(text: str) -> str:
    """根据关键词将 action 文本分类到模块。"""
    for module, keywords in _MODULE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return module
    return "other"


def _gen_id() -> str:
    return f"strat-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class StrategyStore:
    """策略追踪存储，JSON 文件持久化。"""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or Path(__file__).parent / "strategy_store.json"
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {"strategies": []}

    def save(self) -> None:
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @property
    def strategies(self) -> List[Dict[str, Any]]:
        return self._data.setdefault("strategies", [])

    def get_by_id(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        for s in self.strategies:
            if s.get("strategy_id") == strategy_id:
                return s
        return None

    def ingest_from_run(
        self,
        actions: List[str],
        run_id: str,
        as_of: str,
    ) -> List[Dict[str, Any]]:
        """从报告 actions 列表提取策略条目。去重：同 run_id 不重复入库。"""
        existing_run_ids = {s.get("run_id") for s in self.strategies}
        if run_id in existing_run_ids:
            return []

        new_entries: List[Dict[str, Any]] = []
        now = _now_iso()
        for action_text in actions:
            if not action_text or not isinstance(action_text, str):
                continue
            entry = {
                "strategy_id": _gen_id(),
                "run_id": run_id,
                "as_of": as_of,
                "module": _classify_module(action_text),
                "description": action_text.strip(),
                "status": "pending",
                "status_history": [{"status": "pending", "at": now}],
                "created_at": as_of,
                "feedback": None,
            }
            new_entries.append(entry)

        self.strategies.extend(new_entries)
        self.save()
        return new_entries

    def list_by_month(self, year_month: str) -> List[Dict[str, Any]]:
        """按月份筛选，year_month 格式 '2026-05'。"""
        return [
            s for s in self.strategies
            if (s.get("as_of") or "").startswith(year_month)
        ]

    def list_filtered(
        self,
        month: Optional[str] = None,
        status: Optional[str] = None,
        module: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results = self.strategies
        if month:
            results = [s for s in results if (s.get("as_of") or "").startswith(month)]
        if status:
            results = [s for s in results if s.get("status") == status]
        if module:
            results = [s for s in results if s.get("module") == module]
        return results

    def _transition(self, strategy_id: str, new_status: str) -> Optional[Dict[str, Any]]:
        entry = self.get_by_id(strategy_id)
        if entry is None:
            return None
        entry["status"] = new_status
        entry.setdefault("status_history", []).append(
            {"status": new_status, "at": _now_iso()}
        )
        self.save()
        return entry

    def accept(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        return self._transition(strategy_id, "accepted")

    def reject(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        return self._transition(strategy_id, "rejected")

    def mark_awaiting_feedback(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        return self._transition(strategy_id, "awaiting_feedback")

    def submit_feedback(
        self,
        strategy_id: str,
        outcome: str,
        reason: str,
        kpi_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """提交反馈，状态转为 feedback_received。"""
        entry = self.get_by_id(strategy_id)
        if entry is None:
            return None
        feedback = {
            "feedback_id": f"fb-{uuid.uuid4().hex[:12]}",
            "outcome": outcome,
            "reason": reason,
            "kpi_data": kpi_data or {},
            "submitted_at": _now_iso(),
        }
        entry["feedback"] = feedback
        entry["status"] = "feedback_received"
        entry.setdefault("status_history", []).append(
            {"status": "feedback_received", "at": _now_iso()}
        )
        self.save()
        return entry

    def stats(self, month: Optional[str] = None) -> Dict[str, Any]:
        """模块级统计。"""
        items = self.list_by_month(month) if month else self.strategies
        from collections import Counter
        by_module: Dict[str, Dict[str, int]] = {}
        for s in items:
            mod = s.get("module", "other")
            if mod not in by_module:
                by_module[mod] = Counter()
            by_module[mod][s.get("status", "pending")] += 1

        total = len(items)
        accepted = sum(1 for s in items if s.get("status") in ("accepted", "awaiting_feedback", "feedback_received"))
        feedback_done = sum(1 for s in items if s.get("status") == "feedback_received")

        return {
            "total": total,
            "accepted": accepted,
            "rejected": sum(1 for s in items if s.get("status") == "rejected"),
            "feedback_received": feedback_done,
            "execution_rate": round(accepted / total, 2) if total else 0,
            "by_module": {k: dict(v) for k, v in by_module.items()},
        }
