"""
基于 ``crawlers.taobao_search`` 的实时竞品数据适配器。

设计目标：
- 让 ``PricingAgent`` 与 ``DynamicPricingAgent`` 不再依赖 mock_competitor_prices.json
  / mock_competitors.py，而是按需现场抓取淘宝搜索结果再聚合。
- 与现有两个数据源接口签名保持一致，便于在 orchestrator 中直接替换：
  * ``list_competitor_benchmarks(category_keys)`` 与 ``mock_competitors.list_competitor_rows``
    输出结构兼容（含 ``category_key`` / ``price_band`` / ``gap_note`` 等字段）。
  * ``get_competitor_prices(query)`` 与 ``CompetitorPricingAPI.get_competitor_prices``
    输出结构兼容（返回 ``List[float]``）。
- 失败/超时/无 Cookie 等场景自动回退到注入的 fallback，编排不会中断。
- 内置内存 + 本地 JSON 双层缓存，避免一次编排重复爬同一关键词。
- 空结果（0 条）默认**短 TTL** 缓存（见 ``TAOBAO_EMPTY_CACHE_TTL_SEC``），且**不会从磁盘恢复**旧空条目，
  避免一次反爬/超时把「0 条」写进 6 小时缓存后长期不再重试。

注意：
- 默认不会真正访问淘宝。需要 orchestrator 显式开启
  （``DataSourceSettings.competitors_source == "taobao"``），并且
  ``crawlers.taobao_search.search_taobao_products`` 可用且 ``TAOBAO_COOKIE``
  存在时才会发起实时抓取，避免误触发反爬。
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


_DEFAULT_CACHE_FILENAME = "taobao_competitor_cache.json"

# 常见颜色前缀（长词在前，避免「棕」误切「棕色连衣裙」类边界问题）
_COLOR_PREFIXES: Tuple[str, ...] = (
    "深棕色",
    "咖啡色",
    "卡其色",
    "藏青色",
    "米白色",
    "浅灰色",
    "深灰色",
    "黑色",
    "白色",
    "米色",
    "灰色",
    "蓝色",
    "红色",
    "粉色",
    "黄色",
    "绿色",
    "紫色",
    "棕色",
    "杏色",
    "银色",
    "金色",
    "裸色",
    "橙色",
)


class TaobaoCompetitorAdapter:
    """以淘宝搜索结果为来源的竞品数据适配器。

    参数
    ----
    cookie_string:
        ``TAOBAO_COOKIE`` 字符串。为空时仍会尝试爬取，但失败概率高，会自动降级。
    max_items:
        每次搜索最多返回多少条商品（透传给 ``search_taobao_products``）。
    cache_ttl_sec:
        缓存有效期（秒），命中后不再重复发起抓取。
    cache_path:
        本地 JSON 缓存文件路径；为 ``None`` 时只用内存缓存。
    search_timeout_sec:
        单次 ``search_taobao_products`` 的硬超时（秒），用于防止编排被卡死。
    fallback_benchmarks:
        当淘宝抓取失败/为空时使用的兜底竞品行（与 mock_competitors 同结构）。
    fallback_prices_provider:
        当淘宝抓取失败/为空时按查询词回退的价格列表提供者
        （签名：``func(query: str) -> List[float]``）。
    debug:
        是否打印调试信息。
    """

    def __init__(
        self,
        *,
        cookie_string: str = "",
        max_items: int = 30,
        cache_ttl_sec: int = 6 * 3600,
        cache_path: Optional[Path] = None,
        search_timeout_sec: int = 20,
        fallback_benchmarks: Optional[List[Dict[str, Any]]] = None,
        fallback_prices_provider: Optional[Callable[[str], List[float]]] = None,
        debug: bool = False,
    ) -> None:
        self.cookie_string = (cookie_string or "").strip()
        self.max_items = max(int(max_items or 0), 10)
        self.cache_ttl_sec = max(int(cache_ttl_sec or 0), 0)
        self.search_timeout_sec = max(int(search_timeout_sec or 0), 5)
        self.cache_path = Path(cache_path) if cache_path else None
        self._fallback_benchmarks = list(fallback_benchmarks or [])
        self._fallback_prices_provider = fallback_prices_provider
        self._debug = bool(debug or os.getenv("TAOBAO_DEBUG", "").strip().lower()
                           in {"1", "true", "on", "yes"})

        # 缓存结构：{ keyword -> {"expires_at": float, "products": [...] } }
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock()
        self._load_disk_cache()

    def _empty_result_cache_ttl_sec(self) -> int:
        """空列表抓取结果的缓存秒数；0 表示不缓存空结果（每次都重新爬）。"""
        raw = (os.environ.get("TAOBAO_EMPTY_CACHE_TTL_SEC") or "").strip()
        if raw.isdigit():
            return max(0, int(raw))
        return 120

    # ------------------------------------------------------------------ public

    def list_competitor_benchmarks(
        self,
        category_keys: Optional[Iterable[str]] = None,
        search_context: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """按品类列表抓取淘宝竞品，聚合为与 mock_competitors 兼容的结构。

        - ``category_keys`` 为空时回退到 ``fallback_benchmarks`` 的 ``category_key``
          列表，保证至少能得到一份基线竞品基准。
        - ``search_context`` 可传入选品条件（如 ``target_style`` / ``target_audience`` /
          ``occasion``），这些字段会拼接在每个品类搜索词后面，使竞品定向更精准。
          例如：category_key="A字中长裙" + target_style="韩系休闲" + occasion="日常通勤"
          → 实际搜索词 "A字中长裙 韩系休闲 通勤"。
        """
        cats = [str(c).strip() for c in (category_keys or []) if str(c).strip()]
        if not cats:
            cats = [
                str(row.get("category_key", "")).strip()
                for row in self._fallback_benchmarks
                if isinstance(row, dict) and str(row.get("category_key", "")).strip()
            ]
        cats = list(dict.fromkeys(cats))  # 去重保序

        if not cats:
            self._log("竞品基准查询：未提供任何品类，直接回退 fallback")
            return [dict(r) for r in self._fallback_benchmarks]

        suffix = self._build_search_suffix(search_context or {})
        rows: List[Dict[str, Any]] = []
        for cat in cats:
            row = self._build_benchmark_row(cat, search_suffix=suffix)
            if row:
                rows.append(row)
        if rows:
            return rows

        self._log("所有品类抓取均失败，整体回退到 fallback_benchmarks")
        return [dict(r) for r in self._fallback_benchmarks]

    def get_competitor_prices(self, query: str) -> List[float]:
        """按查询词抓取淘宝竞品价格列表（清洗后）。

        - ``query`` 可以是 SKU 名称或品类关键词。
        - 抓取失败或没拿到合理价格时，回退到 ``fallback_prices_provider``（若提供）。
        """
        q = (query or "").strip()
        if not q:
            return []

        products = self._search_with_cache(q)
        prices = self._clean_prices([p.get("price") for p in products])
        prices = self._strip_outliers(prices)
        if prices:
            return prices

        if self._fallback_prices_provider is not None:
            try:
                fallback = self._fallback_prices_provider(q) or []
            except Exception:
                fallback = []
            fallback = self._clean_prices(fallback)
            self._log(f"价格查询 [{q}] 走 fallback，命中 {len(fallback)} 条")
            return fallback

        return []

    # ----------------------------------------------------------- benchmark row

    @staticmethod
    def _audience_to_search_token(audience: str) -> str:
        """把企划里的适用人群写成淘宝检索常用词。"""
        s = (audience or "").strip()
        if not s:
            return ""
        # 常见人群 → 检索侧常用词（与「年轻女性」不再跳过，避免竞品池过宽）
        mapped = {
            "年轻女性": "女装",
            "年轻男性": "男装",
            "女性": "女装",
            "男性": "男装",
            "女": "女装",
            "男": "男装",
            "大码": "大码",
            "孕妇": "孕妇",
            "儿童": "儿童",
            "中老年": "中老年",
            "学生": "学生",
        }
        if s in mapped:
            return mapped[s]
        skip = {"用户", "消费者", "大众", "所有人", ""}
        if s in skip:
            return ""
        return s

    @staticmethod
    def _build_search_suffix(context: Dict[str, str]) -> str:
        """从选品条件构造搜索词后缀。

        规则（与企划字段对齐，最多约 3 个修饰词，避免过长）：
        - ``target_style``：直接附加（韩系休闲、甜美等）。
        - ``target_audience``：映射为淘宝常用检索词（如「年轻女性」→「女装」）；其它细分人群原样附加。
        - ``occasion``：取前两字作场景锚点（「日常通勤」→「日常」）。
        - ``price_range``：若有「平价/中端」等档位词，附加以收窄价格带竞品。
        """
        parts: List[str] = []
        max_parts = 3

        style = context.get("target_style", "").strip()
        if style:
            parts.append(style)

        audience_raw = context.get("target_audience", "").strip()
        if audience_raw and len(parts) < max_parts:
            token = TaobaoCompetitorAdapter._audience_to_search_token(audience_raw)
            if token and token not in parts:
                parts.append(token)

        occasion = context.get("occasion", "").strip()
        if occasion and len(parts) < max_parts:
            occ_short = occasion[:2]
            if occ_short and occ_short not in parts:
                parts.append(occ_short)

        budget = context.get("price_range", "").strip()
        if budget and len(parts) < max_parts:
            # 只附加短档位词，避免整句塞进搜索框
            if len(budget) <= 6 and budget not in parts:
                parts.append(budget)

        return " ".join(parts)

    def _build_benchmark_row(
        self, category_key: str, search_suffix: str = ""
    ) -> Optional[Dict[str, Any]]:
        # 拼搜索词：「A字中长裙 韩系休闲 通勤」，以完整词为 cache key
        query = f"{category_key} {search_suffix}".strip() if search_suffix else category_key
        if search_suffix:
            self._log(f"品类 [{category_key}] 搜索词 → [{query}]")
        products = self._search_with_cache(query)
        prices = self._clean_prices([p.get("price") for p in products])
        prices = self._strip_outliers(prices)
        if not prices:
            # 单类目失败时优先用同类目 mock 行兜底
            fallback = self._find_fallback_row(category_key)
            if fallback:
                self._log(f"品类 [{category_key}] 抓取为空，使用 fallback 行")
                return dict(fallback)
            self._log(f"品类 [{category_key}] 抓取为空，且 fallback 缺失，跳过")
            return None

        low, high = self._price_band(prices)
        median = int(round(statistics.median(prices)))
        gap_note = (
            f"基于淘宝实时搜索「{query}」{len(products)} 条结果"
            f"（清洗后 {len(prices)} 个价格），"
            f"中位 ¥{median}；价格带按 P20–P80 估算。"
        )
        return {
            "category_key": category_key,
            "competitor_new_skus_30d": len(products),
            "ours_new_skus_30d": 0,  # 由 orchestrator 侧补齐，这里只反映淘宝侧
            "price_band": f"{low}-{high}",
            "gap_note": gap_note,
            "data_source": "taobao_live",
            "sample_size": len(products),
            "price_median": median,
            "search_query": query,
        }

    def _find_fallback_row(self, category_key: str) -> Optional[Dict[str, Any]]:
        for row in self._fallback_benchmarks:
            if not isinstance(row, dict):
                continue
            if str(row.get("category_key", "")).strip() == category_key:
                return row
        return None

    # ----------------------------------------------------------- price utils

    @staticmethod
    def _clean_prices(raw: Iterable[Any]) -> List[float]:
        out: List[float] = []
        for v in raw or []:
            if v is None:
                continue
            if isinstance(v, (int, float)):
                price = float(v)
            else:
                text = str(v).strip()
                if not text:
                    continue
                # 去掉「¥」「￥」「元」等非数字字符，保留小数点
                cleaned = re.sub(r"[^0-9.]", "", text)
                if not cleaned or cleaned == ".":
                    continue
                try:
                    price = float(cleaned)
                except ValueError:
                    continue
            # 过滤明显异常值：保留 1~99999 元区间
            if 1.0 <= price <= 99999.0:
                out.append(price)
        return out

    @staticmethod
    def _strip_outliers(prices: List[float]) -> List[float]:
        """剔除极端引流款/加价款（价格 < P5 或 > P95），样本太小时不剔除。"""
        if len(prices) < 8:
            return list(prices)
        ordered = sorted(prices)
        lo_idx = max(0, int(round(len(ordered) * 0.05)) - 1)
        hi_idx = min(len(ordered) - 1, int(round(len(ordered) * 0.95)) - 1)
        lo = ordered[lo_idx]
        hi = ordered[hi_idx]
        return [p for p in prices if lo <= p <= hi]

    @staticmethod
    def _price_band(prices: List[float]) -> Tuple[int, int]:
        """用 P20–P80 估算价格带，保证 low <= high 且都是整数。"""
        if not prices:
            return (0, 0)
        ordered = sorted(prices)
        if len(ordered) >= 5:
            lo_idx = max(0, int(round(len(ordered) * 0.20)) - 1)
            hi_idx = min(len(ordered) - 1, int(round(len(ordered) * 0.80)) - 1)
            low = ordered[lo_idx]
            high = ordered[hi_idx]
        else:
            low = ordered[0]
            high = ordered[-1]
        low_i = max(1, int(round(low)))
        high_i = max(low_i, int(round(high)))
        return (low_i, high_i)

    # ----------------------------------------------------------- search/cache

    def _search_with_cache(self, keyword: str) -> List[Dict[str, Any]]:
        key = keyword.strip()
        if not key:
            return []

        now = time.time()
        with self._lock:
            entry = self._memory_cache.get(key)
            if entry and float(entry.get("expires_at", 0)) > now:
                products = entry.get("products") or []
                if isinstance(products, list):
                    self._log(f"缓存命中 [{key}]：{len(products)} 条")
                    return products

        products = self._do_search(key)
        with self._lock:
            empty_ttl = self._empty_result_cache_ttl_sec()
            if products:
                ttl = self.cache_ttl_sec
            elif empty_ttl <= 0:
                # 不缓存空结果，避免「缓存命中 0 条」在整段 TTL 内挡掉重试
                return products
            else:
                ttl = min(empty_ttl, self.cache_ttl_sec) if self.cache_ttl_sec else empty_ttl
            self._memory_cache[key] = {
                "expires_at": now + ttl,
                "products": products,
            }
            self._dump_disk_cache_locked()
        return products

    @staticmethod
    def _search_query_variants(keyword: str) -> List[str]:
        """生成搜索词变体：先完整词，再去掉常见颜色前缀。

        淘宝对「颜色+品类」有时返回空页或反爬空白；用「连衣裙」「T恤」等
        更泛的词往往仍能拿到可用价格分布。
        """
        kw = (keyword or "").strip()
        if not kw:
            return []
        seen: set[str] = set()
        out: List[str] = []

        def push(s: str) -> None:
            s = s.strip()
            if len(s) < 2 or s in seen:
                return
            seen.add(s)
            out.append(s)

        push(kw)
        for pref in _COLOR_PREFIXES:
            if kw.startswith(pref):
                push(kw[len(pref) :])
        return out

    def _do_search(self, keyword: str) -> List[Dict[str, Any]]:
        try:
            from ..crawlers.taobao_search import search_taobao_products
        except Exception as exc:  # noqa: BLE001 - 任何导入异常都视为不可用
            self._log(f"crawlers.taobao_search 不可用：{exc}")
            return []

        variants = self._search_query_variants(keyword)
        last_empty_q = ""
        for i, q in enumerate(variants):
            if i > 0:
                time.sleep(0.7)
            try:
                self._log(f"开始抓取 [{q}]，max_items={self.max_items}")
                products = search_taobao_products(
                    q,
                    timeout=self.search_timeout_sec,
                    max_items=self.max_items,
                    cookie_string=self.cookie_string,
                    allow_manual_login=False,
                )
            except Exception as exc:  # noqa: BLE001 - 爬虫层任何异常都不应中断编排
                self._log(f"抓取 [{q}] 异常：{exc}")
                products = []

            if not isinstance(products, list):
                products = []
            n = len(products)
            self._log(f"抓取 [{q}] 完成：{n} 条")
            if n > 0:
                if q != (keyword or "").strip():
                    self._log(f"提示：原词 [{keyword}] 无结果，已用降级词 [{q}] 命中 {n} 条")
                return products
            last_empty_q = q

        if last_empty_q:
            self._log(f"全部搜索变体均无结果（最后尝试 [{last_empty_q}]）")
        return []

    # ----------------------------------------------------------- disk cache

    def _load_disk_cache(self) -> None:
        if not self.cache_path or not self.cache_path.is_file():
            return
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._log(f"加载缓存失败 ({self.cache_path}): {exc}")
            return
        if not isinstance(raw, dict):
            return

        now = time.time()
        cleaned: Dict[str, Dict[str, Any]] = {}
        for key, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            expires_at = float(entry.get("expires_at", 0) or 0)
            products = entry.get("products")
            if expires_at <= now or not isinstance(products, list):
                continue
            # 磁盘里历史「0 条」长 TTL 会导致进程重启后仍长期不重爬；空列表不预加载进内存
            if len(products) == 0:
                continue
            cleaned[str(key)] = {"expires_at": expires_at, "products": products}
        with self._lock:
            self._memory_cache.update(cleaned)
        self._log(f"加载缓存 {self.cache_path} 完成：{len(cleaned)} 条有效")

    def _dump_disk_cache_locked(self) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                k: {
                    "expires_at": float(v.get("expires_at", 0)),
                    "products": v.get("products") or [],
                }
                for k, v in self._memory_cache.items()
            }
            self.cache_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"写入缓存失败 ({self.cache_path}): {exc}")

    # ----------------------------------------------------------- misc

    def _log(self, message: str) -> None:
        if self._debug:
            print(f"[taobao-adapter] {message}")


def build_default_cache_path() -> Path:
    """默认缓存文件位置：``ecommerce_agent/data/taobao_competitor_cache.json``。"""
    return Path(__file__).resolve().parent / _DEFAULT_CACHE_FILENAME
