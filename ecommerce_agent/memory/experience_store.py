"""店铺经验积累机制 —— ExperienceStore。

设计原则
--------
1. 检索键（search_keys）全部来自系统可采集字段（ERP、趋势、选品 criteria、编排上下文），
   不依赖人工输入才能触发检索。
2. 经验正文（title / narrative）供人读 / 模型读，不参与硬过滤。
3. 所有自动产生的条目初始 status=draft，需人工或规则晋升到 active。
4. 经验定位为「参考」而非「硬约束」；调用方自行决定如何展示给模型。

数据文件格式（JSON）
--------------------
{
  "experiences": [
    {
      "experience_id": "exp-uuid",
      "status": "draft|active|archived",
      "title": "短标题（≤30字）",
      "narrative": "叙事正文；人工撰写或人审后编辑",
      "search_keys": {
        "season": ["spring"],           # 系统推导自 as_of 月份
        "category": ["连衣裙"],          # category_mapping 后类目
        "price_tier": "100-200",         # SKU price 分桶
        "channel_dominant": "live",      # channel_sales 最大渠道
        "return_signal": "high",         # return_rate 分级
        "inventory_signal": "overstocked",
        "conversion_signal": "low",
        "tags": {"material": "天丝", "style": "美拉德"},
        "trend_keywords": ["美拉德"],
        "criteria_style": "复古",        # 选品 criteria.target_style
        "criteria_audience": ""
      },
      "evidence": {
        "run_id": "run-20260501-seed42",
        "as_of": "2026-05-01",
        "sku_ids": ["SKU2002"],
        "kpi_snapshot": {
          "daily_sales": 9,
          "return_rate": 0.11,
          "conversion_rate": 0.009,
          "stock_age_days": 72
        }
      },
      "confidence": "low|medium|high",
      "source": "auto_draft|rule|human",
      "created_at": "2026-05-01",
      "valid_until": null,
      "archived_at": null
    }
  ]
}
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 辅助推导函数（全部使用系统字段，无需人工输入）
# ---------------------------------------------------------------------------

def _derive_season(as_of: str) -> str:
    """YYYY-MM-DD → 中国服装业习惯季节。"""
    try:
        month = int(as_of[5:7])
    except (IndexError, ValueError):
        return ""
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def _derive_price_tier(price: Optional[float]) -> str:
    """SKU price → 价位分桶。"""
    if price is None:
        return ""
    try:
        p = float(price)
    except (TypeError, ValueError):
        return ""
    if p < 100:
        return "0-100"
    if p < 200:
        return "100-200"
    if p < 500:
        return "200-500"
    return "500+"


def _derive_return_signal(return_rate: Optional[float]) -> str:
    """return_rate → 退货信号分级。"""
    if return_rate is None:
        return ""
    try:
        r = float(return_rate)
    except (TypeError, ValueError):
        return ""
    if r < 0.08:
        return "normal"
    if r < 0.15:
        return "elevated"
    return "high"


def _derive_inventory_signal(stock_age_days: Optional[float]) -> str:
    """stock_age_days → 库龄信号。"""
    if stock_age_days is None:
        return ""
    try:
        d = float(stock_age_days)
    except (TypeError, ValueError):
        return ""
    if d < 30:
        return "fresh"
    if d < 60:
        return "aging"
    return "overstocked"


def _derive_conversion_signal(conversion_rate: Optional[float]) -> str:
    """conversion_rate → 转化信号。"""
    if conversion_rate is None:
        return ""
    try:
        c = float(conversion_rate)
    except (TypeError, ValueError):
        return ""
    if c < 0.01:
        return "low"
    if c < 0.02:
        return "normal"
    return "high"


def _derive_channel_dominant(channel_sales: Optional[Dict]) -> str:
    """channel_sales dict → 销售额最大的渠道名。"""
    if not isinstance(channel_sales, dict) or not channel_sales:
        return ""
    try:
        return max(channel_sales, key=lambda k: float(channel_sales[k] or 0))
    except (TypeError, ValueError):
        return ""


def _today_iso() -> str:
    return date.today().isoformat()


def _make_run_id(as_of: str, seed: int) -> str:
    return f"run-{(as_of or _today_iso()).replace('-', '')}-seed{seed}"


# ---------------------------------------------------------------------------
# 检索键构建（外部调用）
# ---------------------------------------------------------------------------

def build_search_keys_from_sku(
    sku: Dict[str, Any],
    *,
    as_of: str = "",
    tags: Optional[Dict[str, str]] = None,
    category: str = "",
    trend_keywords: Optional[List[str]] = None,
    criteria: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """从单个 SKU 指标 + 上下文推导 search_keys。"""
    return {
        "season": _derive_season(as_of) if as_of else "",
        "category": [category] if category else [],
        "price_tier": _derive_price_tier(sku.get("price")),
        "channel_dominant": _derive_channel_dominant(sku.get("channel_sales")),
        "return_signal": _derive_return_signal(sku.get("return_rate")),
        "inventory_signal": _derive_inventory_signal(sku.get("stock_age_days")),
        "conversion_signal": _derive_conversion_signal(sku.get("conversion_rate")),
        "tags": dict(tags) if tags else {},
        "trend_keywords": list(trend_keywords or []),
        "criteria_style": str((criteria or {}).get("target_style") or "").strip(),
        "criteria_audience": str((criteria or {}).get("target_audience") or "").strip(),
    }


def build_query_keys_from_run(
    *,
    as_of: str = "",
    categories: Optional[List[str]] = None,
    price_tiers: Optional[List[str]] = None,
    channels: Optional[List[str]] = None,
    return_signals: Optional[List[str]] = None,
    inventory_signals: Optional[List[str]] = None,
    conversion_signals: Optional[List[str]] = None,
    tag_values: Optional[List[str]] = None,
    trend_keywords: Optional[List[str]] = None,
    criteria_style: str = "",
    criteria_audience: str = "",
) -> Dict[str, Any]:
    """从当次 run 聚合的多维字段构建「查询键集合」，供 retrieve() 匹配。"""
    return {
        "season": _derive_season(as_of) if as_of else "",
        "categories": list(categories or []),
        "price_tiers": list(price_tiers or []),
        "channels": list(channels or []),
        "return_signals": list(return_signals or []),
        "inventory_signals": list(inventory_signals or []),
        "conversion_signals": list(conversion_signals or []),
        "tag_values": list(tag_values or []),
        "trend_keywords": list(trend_keywords or []),
        "criteria_style": criteria_style.strip(),
        "criteria_audience": criteria_audience.strip(),
    }


# ---------------------------------------------------------------------------
# 相似度评分（key overlap，不依赖 embedding）
# ---------------------------------------------------------------------------

def _score_experience(exp_keys: Dict[str, Any], query: Dict[str, Any]) -> float:
    """计算经验的 search_keys 与本次 run 的 query_keys 重叠分。

    改进版：维度命中给基础分，集合交集越大加分越多（Jaccard 加权）。
    满分约 10 分；调用方取 Top-K 即可。
    """
    score = 0.0

    # 季节（精确匹配，权重高）
    if exp_keys.get("season") and exp_keys["season"] == query.get("season"):
        score += 1.5

    # 类目（集合交集，按 Jaccard 加权）
    exp_cats = set(exp_keys.get("category") or [])
    q_cats = set(query.get("categories") or [])
    if exp_cats and q_cats:
        intersection = exp_cats & q_cats
        if intersection:
            jaccard = len(intersection) / len(exp_cats | q_cats)
            score += 1.0 + jaccard  # 1.0~2.0

    # 价位带
    if exp_keys.get("price_tier") and exp_keys["price_tier"] in (query.get("price_tiers") or []):
        score += 1.0

    # 渠道
    if exp_keys.get("channel_dominant") and exp_keys["channel_dominant"] in (query.get("channels") or []):
        score += 0.5

    # 退货信号
    if exp_keys.get("return_signal") and exp_keys["return_signal"] in (query.get("return_signals") or []):
        score += 1.0

    # 库龄信号
    if exp_keys.get("inventory_signal") and exp_keys["inventory_signal"] in (query.get("inventory_signals") or []):
        score += 1.0

    # 转化信号
    if exp_keys.get("conversion_signal") and exp_keys["conversion_signal"] in (query.get("conversion_signals") or []):
        score += 0.5

    # 标签（材质/风格/领型/颜色）— 交集越多分越高
    exp_tag_vals = set(str(v).strip() for v in (exp_keys.get("tags") or {}).values() if v)
    q_tag_vals = set(str(v).strip() for v in (query.get("tag_values") or []) if v)
    if exp_tag_vals and q_tag_vals:
        tag_hits = len(exp_tag_vals & q_tag_vals)
        if tag_hits:
            score += min(2.0, 0.5 + tag_hits * 0.5)  # 0.5~2.0

    # 趋势词
    exp_trend = set(exp_keys.get("trend_keywords") or [])
    q_trend = set(query.get("trend_keywords") or [])
    if exp_trend and q_trend:
        trend_hits = len(exp_trend & q_trend)
        if trend_hits:
            score += min(1.5, 0.5 + trend_hits * 0.5)

    # criteria 风格
    es = (exp_keys.get("criteria_style") or "").strip()
    qs = (query.get("criteria_style") or "").strip()
    if es and qs and (es in qs or qs in es):
        score += 1.0

    return round(score, 2)


# ---------------------------------------------------------------------------
# ExperienceStore
# ---------------------------------------------------------------------------

class ExperienceStore:
    """读写店铺经验；全部经验默认为「参考」，不硬拦截任何自动决策。"""

    DEFAULT_FILENAME = "experience_store.json"

    def __init__(self, path: Optional[Path] = None):
        base = Path(__file__).resolve().parent
        self._path = path or (base / self.DEFAULT_FILENAME)
        self._data: Dict[str, Any] = {"experiences": []}
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._data = {"experiences": []}
        else:
            self._data = {"experiences": []}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # 基础读取
    # ------------------------------------------------------------------

    def list_all(self) -> List[Dict[str, Any]]:
        return [dict(e) for e in self._data.get("experiences", [])]

    def list_active(self) -> List[Dict[str, Any]]:
        today = date.today()
        out: List[Dict[str, Any]] = []
        for e in self._data.get("experiences", []):
            if e.get("status") != "active":
                continue
            vu = e.get("valid_until")
            if vu:
                try:
                    if date.fromisoformat(vu) < today:
                        continue
                except ValueError:
                    pass
            out.append(dict(e))
        return out

    def get_by_id(self, experience_id: str) -> Optional[Dict[str, Any]]:
        for e in self._data.get("experiences", []):
            if e.get("experience_id") == experience_id:
                return dict(e)
        return None

    # ------------------------------------------------------------------
    # 检索（两阶段：active 过滤 → key-overlap 排序）
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: Dict[str, Any],
        *,
        top_k: int = 5,
        min_score: float = 1.5,
    ) -> List[Dict[str, Any]]:
        """检索与当次 run 最相关的经验，按 key-overlap 分降序返回 top_k 条。

        query 由 build_query_keys_from_run() 构建；全部字段来自系统可采集数据。
        返回每条附带 _score 字段（仅供排序展示，不对外承诺稳定）。
        """
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for exp in self.list_active():
            s = _score_experience(exp.get("search_keys") or {}, query)
            if s >= min_score:
                hit = dict(exp)
                hit["_score"] = s
                scored.append((s, hit))
        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:top_k]]

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def append_draft(
        self,
        title: str,
        narrative: str,
        search_keys: Dict[str, Any],
        evidence: Dict[str, Any],
        *,
        source: str = "auto_draft",
        confidence: str = "low",
        valid_until: Optional[str] = None,
    ) -> Dict[str, Any]:
        """追加一条 draft 经验（需人工审核后才晋升为 active）。"""
        exp_id = f"exp-{uuid.uuid4().hex[:12]}"
        entry: Dict[str, Any] = {
            "experience_id": exp_id,
            "status": "draft",
            "title": title.strip(),
            "narrative": narrative.strip(),
            "search_keys": search_keys,
            "evidence": evidence,
            "confidence": confidence,
            "source": source,
            "created_at": _today_iso(),
            "valid_until": valid_until,
            "archived_at": None,
        }
        self._data.setdefault("experiences", []).append(entry)
        return dict(entry)

    def append_human(
        self,
        title: str,
        narrative: str,
        search_keys: Dict[str, Any],
        evidence: Optional[Dict[str, Any]] = None,
        *,
        confidence: str = "high",
        valid_until: Optional[str] = None,
    ) -> Dict[str, Any]:
        """人工录入一条经验（直接 active）。"""
        exp_id = f"exp-{uuid.uuid4().hex[:12]}"
        entry: Dict[str, Any] = {
            "experience_id": exp_id,
            "status": "active",
            "title": title.strip(),
            "narrative": narrative.strip(),
            "search_keys": search_keys,
            "evidence": evidence or {},
            "confidence": confidence,
            "source": "human",
            "created_at": _today_iso(),
            "valid_until": valid_until,
            "archived_at": None,
        }
        self._data.setdefault("experiences", []).append(entry)
        return dict(entry)

    # ------------------------------------------------------------------
    # 状态流转
    # ------------------------------------------------------------------

    def approve(self, experience_id: str, *, confidence: str = "medium") -> bool:
        """将 draft 晋升为 active。"""
        for e in self._data.get("experiences", []):
            if e.get("experience_id") == experience_id and e.get("status") == "draft":
                e["status"] = "active"
                e["confidence"] = confidence
                return True
        return False

    def archive(self, experience_id: str) -> bool:
        """归档经验（保留历史，不删除）。"""
        for e in self._data.get("experiences", []):
            if e.get("experience_id") == experience_id and e.get("status") != "archived":
                e["status"] = "archived"
                e["archived_at"] = _today_iso()
                return True
        return False

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, int]:
        counts: Dict[str, int] = {"draft": 0, "active": 0, "archived": 0}
        for e in self._data.get("experiences", []):
            s = e.get("status", "draft")
            counts[s] = counts.get(s, 0) + 1
        return counts
