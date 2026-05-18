"""避雷点长期记忆（Issue 4.3 Baseline：JSON 文件）。"""
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional


def _today_iso() -> str:
    return date.today().isoformat()


class FeedbackMemoryStore:
    """读写结构化避雷点；选品前可查询命中。"""

    def __init__(self, path: Optional[Path] = None):
        base = Path(__file__).resolve().parent
        self._path = path or (base / "default_feedback_memory.json")
        self._data: Dict[str, Any] = {"schema_version": 2, "items": [], "category_experiences": []}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
        else:
            self._data = {"schema_version": 2, "items": [], "category_experiences": []}
        if not isinstance(self._data, dict):
            self._data = {"schema_version": 2, "items": [], "category_experiences": []}
            return
        self._data.setdefault("schema_version", 2)
        self._data.setdefault("items", [])
        self._data.setdefault("category_experiences", [])

    def save(self) -> None:
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_active_items(self) -> List[Dict[str, Any]]:
        items = self._data.get("items", [])
        today = date.today()
        out: List[Dict[str, Any]] = []
        for it in items:
            if it.get("status") != "active":
                continue
            exp = it.get("expires_at")
            if exp:
                try:
                    if date.fromisoformat(exp) < today:
                        continue
                except ValueError:
                    continue
            out.append(dict(it))
        return out

    def find_hits_for_tags(self, tags: Dict[str, str]) -> List[Dict[str, Any]]:
        """根据商品标签匹配避雷点（子串规则）。"""
        hits: List[Dict[str, Any]] = []
        collar = tags.get("collar", "") or ""
        material = tags.get("material", "") or ""
        style = tags.get("style", "") or ""
        color = tags.get("color", "") or ""

        for it in self.list_active_items():
            m_sub = (it.get("material_substring") or "").strip()
            s_sub = (it.get("style_substring") or "").strip()
            c_sub = (it.get("collar_substring") or "").strip()
            matched = False
            if m_sub and m_sub in material:
                matched = True
            if s_sub and s_sub in style:
                matched = True
            if c_sub and c_sub in collar:
                matched = True
            if matched:
                hits.append(
                    {
                        "feedback_id": it.get("id"),
                        "summary": it.get("summary"),
                        "reason": it.get("reason"),
                        "matched_on": {
                            "collar": collar,
                            "material": material,
                            "style": style,
                            "color": color,
                        },
                    }
                )
        return hits

    def append_item(
        self,
        summary: str,
        reason: str,
        *,
        material_substring: str = "",
        style_substring: str = "",
        collar_substring: str = "",
        expires_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """人工或上游归因写入一条避雷点。"""
        new_id = f"fb-{len(self._data.get('items', [])) + 1}"
        item = {
            "id": new_id,
            "summary": summary,
            "material_substring": material_substring,
            "style_substring": style_substring,
            "collar_substring": collar_substring,
            "reason": reason,
            "status": "active",
            "created_at": _today_iso(),
            "expires_at": expires_at,
        }
        self._data.setdefault("items", []).append(item)
        return dict(item)

    def list_active_category_experiences(self) -> List[Dict[str, Any]]:
        items = self._data.get("category_experiences", [])
        today = date.today()
        out: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("status") != "active":
                continue
            exp = it.get("expires_at")
            if exp:
                try:
                    if date.fromisoformat(exp) < today:
                        continue
                except ValueError:
                    continue
            out.append(dict(it))
        return out

    def append_category_experience(self, candidate: Dict[str, Any], *, expires_at: Optional[str] = None) -> Dict[str, Any]:
        if not isinstance(candidate, dict):
            raise TypeError("candidate must be a dict")
        exp_id = str(candidate.get("experience_id", "")).strip()
        if not exp_id:
            exp_id = f"exp-{len(self._data.get('category_experiences', [])) + 1}"
        existing = self._data.get("category_experiences", [])
        if isinstance(existing, list):
            for it in existing:
                if isinstance(it, dict) and str(it.get("experience_id", "")).strip() == exp_id:
                    return dict(it)
        item = dict(candidate)
        item["experience_id"] = exp_id
        item.setdefault("status", "active")
        item.setdefault("created_at", _today_iso())
        item.setdefault("expires_at", expires_at)
        self._data.setdefault("category_experiences", []).append(item)
        return dict(item)
