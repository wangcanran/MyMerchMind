"""本店经营 / 趋势 / 竞品 / 供应链：从平台导出 CSV 归一化为项目 JSON（无爬虫，合规）。"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .paths import write_json


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    return [dict(row) for row in reader]


def _norm_key(name: str) -> str:
    return re.sub(r"\s+", "", name.strip().lower())


def _pick(row: Dict[str, str], aliases: Tuple[str, ...]) -> str:
    inv = {_norm_key(k): v for k, v in row.items() if k}
    for a in aliases:
        key = _norm_key(a)
        if key in inv and inv[key] != "":
            return str(inv[key]).strip()
    return ""


# --- 本店 SKU（淘宝/千牛/ERP 导出列名可不一致，尽量兼容）---
_SHOP_ALIASES = {
    "sku_id": ("sku_id", "sku", "商品id", "商品编码", "货号", "商家编码"),
    "name": ("name", "商品名称", "标题", "title"),
    "daily_sales": ("daily_sales", "日销量", "日均销量", "预估日销"),
    "stock": ("stock", "库存", "可售库存", "现货"),
    "in_transit": ("in_transit", "在途", "采购在途"),
    "return_rate": ("return_rate", "退货率", "退款率"),
    "conversion_rate": ("conversion_rate", "转化率"),
    "stock_age_days": ("stock_age_days", "库龄", "库龄天数"),
    "prior_week_total_units": ("prior_week_total_units", "近7天销量", "周销量"),
    "prior_month_total_units": ("prior_month_total_units", "近30天销量", "月销量"),
    "live_sales": ("live_sales", "直播销量", "直播间"),
    "private_sales": ("private_sales", "私域", "私域销量"),
    "shelf_sales": ("shelf_sales", "货架", "搜索货架"),
}


def import_shop_skus_csv(csv_path: Path, out_json: Path) -> Path:
    """本店历史经营数据：CSV → `erp_skus` 兼容 JSON。"""
    rows = _read_csv_rows(csv_path)
    skus_list: List[Dict[str, Any]] = []
    for row in rows:
        sku_id = _pick(row, _SHOP_ALIASES["sku_id"])
        if not sku_id:
            continue
        def num(key: str, default: float = 0.0) -> float:
            s = _pick(row, _SHOP_ALIASES[key])  # type: ignore[index]
            if not s:
                return default
            try:
                return float(s.replace("%", "").strip())
            except ValueError:
                return default

        daily = int(num("daily_sales", 0))
        live = int(num("live_sales", 0))
        priv = int(num("private_sales", 0))
        shelf = int(num("shelf_sales", 0))
        if live + priv + shelf == 0 and daily > 0:
            third = daily // 3
            channel_sales = {"live": third, "private": third, "shelf": daily - 2 * third}
        else:
            channel_sales = {"live": live, "private": priv, "shelf": shelf}

        rr = num("return_rate", 0.05)
        if rr > 1.0:
            rr = rr / 100.0

        cv = num("conversion_rate", 0.01)
        if cv > 1.0:
            cv = cv / 100.0

        item: Dict[str, Any] = {
            "sku_id": sku_id,
            "name": _pick(row, _SHOP_ALIASES["name"]) or sku_id,
            "daily_sales": daily,
            "stock": int(num("stock", 0)),
            "in_transit": int(num("in_transit", 0)),
            "return_rate": rr,
            "channel_sales": channel_sales,
            "conversion_rate": cv,
            "stock_age_days": int(num("stock_age_days", 30)),
            "review_snippets": [],
        }
        pw = _pick(row, _SHOP_ALIASES["prior_week_total_units"])
        pm = _pick(row, _SHOP_ALIASES["prior_month_total_units"])
        if pw:
            item["prior_week_total_units"] = int(float(pw))
        if pm:
            item["prior_month_total_units"] = int(float(pm))
        skus_list.append(item)

    root = {"skus": skus_list}
    write_json(out_json, root)
    return out_json


_TREND_ALIASES = {
    "keyword": ("keyword", "关键词", "话题", "标签"),
    "platform": ("platform", "平台", "来源"),
    "heat_score": ("heat_score", "热度", "热度分", "指数"),
    "growth_rate": ("growth_rate", "增长率", "环比", "增速"),
    "timestamp": ("timestamp", "时间", "日期"),
}


def import_trends_csv(csv_path: Path, out_json: Path) -> Path:
    """社交媒体趋势：第三方榜单/人工整理 CSV → trends JSON。小红书/抖音官方 API 需企业授权，此处不接爬虫。"""
    rows = _read_csv_rows(csv_path)
    trends: List[Dict[str, Any]] = []
    for row in rows:
        kw = _pick(row, _TREND_ALIASES["keyword"])
        if not kw:
            continue
        heat_s = _pick(row, _TREND_ALIASES["heat_score"])
        growth_s = _pick(row, _TREND_ALIASES["growth_rate"])
        try:
            heat = float(heat_s) if heat_s else 0.0
        except ValueError:
            heat = 0.0
        try:
            gr = float(growth_s) if growth_s else 0.0
        except ValueError:
            gr = 0.0
        if gr > 1.0:
            gr = gr / 100.0
        trends.append(
            {
                "keyword": kw,
                "platform": _pick(row, _TREND_ALIASES["platform"]) or "导入",
                "heat_score": heat,
                "growth_rate": gr,
                "timestamp": _pick(row, _TREND_ALIASES["timestamp"]) or "",
            }
        )
    write_json(out_json, {"trends": trends})
    return out_json


_COMP_ALIASES = {
    "category_key": ("category_key", "类目", "品类"),
    "competitor_new_skus_30d": ("competitor_new_skus_30d", "竞品上新", "竞品30天上新"),
    "price_band": ("price_band", "价格带", "竞品价格带"),
    "ours_new_skus_30d": ("ours_new_skus_30d", "我方上新", "本店上新"),
    "gap_note": ("gap_note", "备注", "说明"),
}


def import_competitors_csv(csv_path: Path, out_json: Path) -> Path:
    """竞品销售/上新：手工或爬虫导出后的脱敏 CSV → competitors JSON。"""
    rows = _read_csv_rows(csv_path)
    out_rows: List[Dict[str, Any]] = []
    for row in rows:
        ck = _pick(row, _COMP_ALIASES["category_key"])
        if not ck:
            continue
        def ikey(k: str) -> str:
            return _pick(row, _COMP_ALIASES[k])  # type: ignore[index]

        out_rows.append(
            {
                "category_key": ck,
                "competitor_new_skus_30d": int(float(ikey("competitor_new_skus_30d") or 0)),
                "price_band": ikey("price_band") or "-",
                "ours_new_skus_30d": int(float(ikey("ours_new_skus_30d") or 0)),
                "gap_note": ikey("gap_note") or "",
            }
        )
    write_json(out_json, {"rows": out_rows})
    return out_json


_SUPPLY_ALIASES = {
    "sku_id": ("sku_id", "sku", "商品编码", "货号"),
    "supplier_id": ("supplier_id", "供应商", "供应商id", "工厂"),
    "moq": ("moq", "起订量", "最小起订"),
    "lead_time_days": ("lead_time_days", "交期", "交期天", "生产周期"),
    "unit_cost_yuan": ("unit_cost_yuan", "单价", "采购价", "成本", "含税价"),
}


def import_supply_chain_csv(csv_path: Path, out_json: Path) -> Path:
    """供应链：1688/供应商表导出 → supply_chain.json（可与 ERP 按 sku_id 关联）。"""
    rows = _read_csv_rows(csv_path)
    suppliers: List[Dict[str, Any]] = []
    for row in rows:
        sku = _pick(row, _SUPPLY_ALIASES["sku_id"])
        if not sku:
            continue
        moq_s = _pick(row, _SUPPLY_ALIASES["moq"])
        lt_s = _pick(row, _SUPPLY_ALIASES["lead_time_days"])
        cost_s = _pick(row, _SUPPLY_ALIASES["unit_cost_yuan"])
        suppliers.append(
            {
                "sku_id": sku,
                "supplier_id": _pick(row, _SUPPLY_ALIASES["supplier_id"]) or "unknown",
                "moq": int(float(moq_s)) if moq_s else 0,
                "lead_time_days": int(float(lt_s)) if lt_s else 0,
                "unit_cost_yuan": float(cost_s) if cost_s else 0.0,
            }
        )
    write_json(out_json, {"suppliers": suppliers, "source": "csv_import"})
    return out_json


_KG_ALIASES = {
    "subject": ("subject", "主语", "概念", "主题"),
    "predicate": ("predicate", "关系", "谓词"),
    "object": ("object", "宾语", "值", "属性值"),
}


def import_openkg_style_triples_csv(csv_path: Path, out_json: Path) -> Path:
    """知识图谱：OpenKG/自建三元组 CSV → triples JSON（用于趋势→属性扩展，可接图数据库）。"""
    rows = _read_csv_rows(csv_path)
    triples: List[Dict[str, str]] = []
    for row in rows:
        s = _pick(row, _KG_ALIASES["subject"])
        p = _pick(row, _KG_ALIASES["predicate"])
        o = _pick(row, _KG_ALIASES["object"])
        if s and p and o:
            triples.append({"subject": s, "predicate": p, "object": o})
    write_json(out_json, {"triples": triples, "source": "csv_import"})
    return out_json


_TAG_ALIASES = {
    "sku_id": ("sku_id", "sku", "商品编码", "货号"),
    "collar": ("collar", "领型"),
    "material": ("material", "材质", "面料"),
    "style": ("style", "风格"),
    "color": ("color", "颜色", "色系"),
}


def import_tags_csv(csv_path: Path, out_json: Path) -> Path:
    """商品多维标签：Excel 另存 CSV → tags JSON。"""
    rows = _read_csv_rows(csv_path)
    tags: Dict[str, Dict[str, str]] = {}
    for row in rows:
        sid = _pick(row, _TAG_ALIASES["sku_id"])
        if not sid:
            continue
        tags[sid] = {
            "collar": _pick(row, _TAG_ALIASES["collar"]),
            "material": _pick(row, _TAG_ALIASES["material"]),
            "style": _pick(row, _TAG_ALIASES["style"]),
            "color": _pick(row, _TAG_ALIASES["color"]),
        }
    write_json(out_json, {"tags": tags})
    return out_json
