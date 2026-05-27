"""报告展示层：行动优先级分组、定价 LLM 共性抽取等（不改变规则算价，仅影响叙事结构）。"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple


def parse_report_date(as_of_iso: str) -> date:
    raw = (as_of_iso or "").strip()
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return date.today()


def _due_mmdd(base: date, days: int) -> str:
    d = base + timedelta(days=max(0, int(days)))
    return f"{d.month}/{d.day}"


_TIER_ORDER = {
    "P0-24h": 0,
    "P0-48h": 1,
    "P0-72h": 2,
    "P1-72h": 3,
    "P1-本周": 4,
    "P2-辅助": 5,
    "P2-两周内": 6,
    "P2-跟进": 7,
}


def classify_demo_action(text: str, as_of: date) -> Dict[str, str]:
    """按中文行动句做演示级优先级/负责人/建议完成日（启发式，可执行 Demo 用）。"""
    t = (text or "").strip()
    if not t:
        return {
            "tier": "P2-跟进",
            "owner": "综合",
            "action": "",
            "due": _due_mmdd(as_of, 14),
        }

    if "高退货处置" in t:
        return {
            "tier": "P0-48h",
            "owner": "品控/运营",
            "action": t,
            "due": _due_mmdd(as_of, 2),
        }
    if "补货优先级最高" in t:
        return {
            "tier": "P0-24h",
            "owner": "采购/供应链",
            "action": t,
            "due": _due_mmdd(as_of, 1),
        }
    if t.startswith("跨团队先执行"):
        m = re.search(r"在\s*(\d+)\s*天内", t)
        due_days = min(int(m.group(1)), 7) if m else 2
        if "采购" in t or "供应链" in t:
            owner_g = "采购/供应链"
        elif "运营" in t:
            owner_g = "运营"
        else:
            owner_g = "跨团队"
        tier = "P0-24h" if due_days <= 1 else ("P0-48h" if due_days <= 2 else "P0-72h")
        return {
            "tier": tier,
            "owner": owner_g,
            "action": t,
            "due": _due_mmdd(as_of, max(1, due_days)),
        }
    if "优先处理" in t and "退货" in t:
        return {
            "tier": "P0-72h",
            "owner": "品控/运营",
            "action": t,
            "due": _due_mmdd(as_of, 3),
        }
    if "定价建议" in t:
        return {
            "tier": "P1-72h",
            "owner": "运营/定价",
            "action": t,
            "due": _due_mmdd(as_of, 3),
        }
    if "新品企划" in t:
        return {
            "tier": "P1-本周",
            "owner": "企划/买手",
            "action": t,
            "due": _due_mmdd(as_of, 7),
        }
    if ("去化" in t or "滞销" in t) and "补货优先级最高" not in t:
        return {
            "tier": "P1-本周",
            "owner": "运营",
            "action": t,
            "due": _due_mmdd(as_of, 7),
        }
    if "建议订货" in t or "EOQ" in t:
        return {
            "tier": "P1-本周",
            "owner": "采购",
            "action": t,
            "due": _due_mmdd(as_of, 7),
        }
    if "【LLM】" in t:
        return {
            "tier": "P2-辅助",
            "owner": "业务复核",
            "action": t,
            "due": _due_mmdd(as_of, 14),
        }
    return {
        "tier": "P2-跟进",
        "owner": "运营/企划综合",
        "action": t,
        "due": _due_mmdd(as_of, 14),
    }


def build_actions_display(actions: List[str], *, as_of_iso: str) -> Dict[str, Any]:
    """生成行动清单的优先级矩阵（Markdown / 前端共用）。"""
    base = parse_report_date(as_of_iso)
    rows: List[Dict[str, str]] = []
    for a in actions or []:
        if not str(a).strip():
            continue
        row = classify_demo_action(str(a), base)
        rows.append(row)
    rows.sort(key=lambda r: (_TIER_ORDER.get(r.get("tier", ""), 99), r.get("action", "")))
    return {
        "as_of": as_of_iso,
        "note": (
            "以下为演示级「优先级 × 负责 × 建议完成日」矩阵，由规则对行动句做启发式归类；"
            "实际排期请以内部工单/采购日历为准。完整原文见 JSON ``actions``。"
        ),
        "rows": rows,
    }


def longest_common_prefix(strs: List[str]) -> str:
    if len(strs) < 2:
        return ""
    s0 = strs[0]
    upper = min(len(s0), 160)
    for end in range(upper, 0, -1):
        cand = s0[:end]
        if all(s.startswith(cand) for s in strs[1:]):
            return cand.rstrip(" ，、；。:：")
    return ""


def dedupe_pricing_llm_exception_lines(top_rows: List[Dict[str, Any]]) -> Tuple[Optional[str], List[str]]:
    """对 Top N 行的 ``llm_exception_explanation`` 抽取最长公共前缀作为共性，余下为差异化句。

    若公共前缀过短则不做抽取，返回 (None, 原始列表对齐 top_rows 长度)。
    """
    n = len(top_rows)
    raw = [str((top_rows[i] or {}).get("llm_exception_explanation") or "").strip() for i in range(n)]
    texts = [t for t in raw if t]
    if len(texts) < 2:
        return None, raw

    lcp = longest_common_prefix(texts)
    if "。" in lcp:
        head = lcp[: lcp.rfind("。") + 1]
        if len(head) >= 30:
            lcp = head
    if len(lcp) < 30:
        return None, raw

    out = []
    for t in raw:
        if not t:
            out.append("")
            continue
        if t.startswith(lcp):
            rest = t[len(lcp) :].strip().lstrip("，、；。 ")
            out.append(rest if rest else "（与同批次共性一致，无额外增量）")
        else:
            out.append(t)
    return lcp, out


def normalize_trend_growth_in_text(text: str) -> str:
    """将「增速达0.34」类 0~1 小数写法改为「增速约34%」，避免读者误读为 0.34%。

    不改动 channel_dashboard 已带 % 的环比字段（正则不匹配已带 % 的片段）。
    """

    def repl(m: re.Match[str]) -> str:
        prefix, num = m.group(1), m.group(2)
        try:
            x = float(num)
        except ValueError:
            return m.group(0)
        if 0 < x <= 1.5:
            pct = int(round(x * 100))
            return f"{prefix}{pct}%"
        return m.group(0)

    return re.sub(
        r"((?:周环比|月环比|增速|增长率|上升|增长)(?:达|为|约|至|到)\s*)(0?\.\d{2,4})(?![％%\d])",
        repl,
        text or "",
    )


def m2_m3_structure_bridge_note(
    selection: Dict[str, Any],
    category: Dict[str, Any],
) -> Optional[str]:
    """解释「在架 Top 品类（事实）」与「M2 建议方向（策略）」并存时的阅读口径。"""
    if not isinstance(selection, dict) or selection.get("skipped"):
        return None
    if not isinstance(category, dict) or category.get("skipped"):
        return None
    summ = category.get("category_summary") or {}
    if not isinstance(summ, dict):
        return None
    top = str(summ.get("top_category_by_sales") or "").strip()
    if not top:
        return None
    top_sales = summ.get("top_category_daily_sales")
    sales_seg = ""
    if isinstance(top_sales, (int, float)) and top_sales > 0:
        sales_seg = f"日销合计约 {int(top_sales)} 件"
    cats_raw = selection.get("suggested_categories") or []
    cat_list: List[str] = []
    if isinstance(cats_raw, list):
        cat_list = [str(c).strip() for c in cats_raw if str(c).strip()]
    preview = "、".join(cat_list[:8]) if cat_list else ""
    rec = selection.get("recommendation") if isinstance(selection.get("recommendation"), dict) else {}
    cs = str((rec or {}).get("cross_dimension_summary") or "").strip()
    cs_short = (cs[:160] + "…") if len(cs) > 160 else cs

    if cat_list and top in cat_list:
        return (
            f"**结构对齐**：当前在架销售贡献主力为 **{top}**"
            f"（{sales_seg or '详见下方品类 KPI'}）；该品类亦出现在 M2 建议列表中，"
            "可持续巩固主力价位与内容转化，并按企划条目做关联测款。"
        )

    direction = f"「{preview}」" if preview else "上文 M2 建议品类"
    tail = f"M2 结论摘要：{cs_short}" if cs_short else f"M2 建议侧重 {direction} 等方向。"
    return (
        f"**现状与方向**：当前在架结构以 **{top}** 为销售贡献主力"
        f"（{sales_seg or '详见下方品类 KPI'}），反映历史爆款与流量基本盘；"
        f"{tail} 二者并非矛盾：前者描述「卖什么在赚钱」，后者建议「下一波补什么位」。"
        "新品企划与采购补位可优先承接 M2 / 企划条目中的缺口品类。"
    )
