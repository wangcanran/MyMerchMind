import re
from typing import Dict, List, Optional, Tuple


def _parse_price_band(price_band: str) -> Optional[Tuple[int, int]]:
    s = (price_band or "").strip()
    if not s:
        return None
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", s)
    if not m:
        return None
    low = int(m.group(1))
    high = int(m.group(2))
    if low <= 0 or high <= 0 or high < low:
        return None
    return low, high


def _suggest_price_from_band(band: Optional[Tuple[int, int]], mode: str) -> Optional[int]:
    if not band:
        return None
    low, high = band
    mid = int(round((low + high) / 2))
    if mode == "discount":
        return max(1, int(round(low * 0.85)))
    if mode == "aggressive":
        return max(1, int(round(mid * 0.95)))
    return mid


class PricingAgent:
    def analyze(
        self,
        *,
        category_management: Optional[Dict] = None,
        product_selection: Optional[Dict] = None,
        competitor_benchmarks: Optional[List[Dict]] = None,
        top_n: int = 5,
    ) -> Dict:
        category_management = category_management or {}
        product_selection = product_selection or {}
        competitor_benchmarks = competitor_benchmarks or []

        portfolio = category_management.get("portfolio_decisions")
        decisions = category_management.get("decisions") or {}
        eval_new = decisions.get("evaluate_new") if isinstance(decisions, dict) else None

        portfolio_rows: List[Dict] = portfolio if isinstance(portfolio, list) else []
        new_rows: List[Dict] = []
        if isinstance(eval_new, dict) and isinstance(eval_new.get("candidates"), list):
            new_rows = [r for r in eval_new["candidates"] if isinstance(r, dict)]

        decision_by_category: Dict[str, str] = {}
        budget_by_category: Dict[str, float] = {}

        for row in portfolio_rows:
            cat = str(row.get("category", "")).strip()
            if not cat:
                continue
            status = str(row.get("status", "")).strip() or "maintain"
            decision_by_category.setdefault(cat, status)
            kpis = row.get("kpis") if isinstance(row.get("kpis"), dict) else {}
            share = kpis.get("sales_share_pct")
            if isinstance(share, (int, float)):
                budget_by_category[cat] = float(share)

        for row in new_rows:
            cat = str(row.get("category", "")).strip()
            if not cat:
                continue
            decision = str(row.get("decision", "")).strip() or "defer_new"
            decision_by_category[cat] = decision
            budget_by_category.setdefault(cat, 5.0)

        suggested_categories: List[str] = []
        cats = product_selection.get("suggested_categories")
        if isinstance(cats, list):
            for c in cats:
                s = str(c).strip()
                if s and s not in suggested_categories:
                    suggested_categories.append(s)
        for c in suggested_categories:
            decision_by_category.setdefault(c, "approve_new")
            budget_by_category.setdefault(c, 5.0)

        competitor_by_cat: Dict[str, Dict] = {}
        for row in competitor_benchmarks:
            if not isinstance(row, dict):
                continue
            key = str(row.get("category_key", "")).strip()
            if not key:
                continue
            competitor_by_cat[key] = row

        rows_out: List[Dict[str, object]] = []
        for cat in sorted(decision_by_category.keys()):
            decision = decision_by_category.get(cat, "maintain")
            comp = competitor_by_cat.get(cat, {})
            price_band = str(comp.get("price_band", "")).strip() if isinstance(comp, dict) else ""
            band = _parse_price_band(price_band)
            mode = "baseline"
            if decision in {"retire_candidate", "reduce", "adjust_or_retire"}:
                mode = "discount"
            if decision in {"approve_new", "invest"}:
                mode = "aggressive"
            suggested_price = _suggest_price_from_band(band, mode=mode)
            if suggested_price is None and band:
                suggested_price = _suggest_price_from_band(band, mode="baseline")
            gap_note = str(comp.get("gap_note", "")).strip() if isinstance(comp, dict) else ""
            budget = float(budget_by_category.get(cat, 0.0))
            rationale = "基于竞品价格带与品类组合决策生成（规则定价）。"
            if gap_note:
                rationale = f"{rationale} {gap_note}"
            rows_out.append(
                {
                    "category": cat,
                    "decision": decision,
                    "budget_share_pct": round(budget, 2),
                    "competitor_price_band": price_band or None,
                    "suggested_price": suggested_price,
                    "pricing_mode": mode,
                    "rationale": rationale,
                }
            )

        rows_out = sorted(rows_out, key=lambda r: (-float(r.get("budget_share_pct", 0.0)), str(r.get("category", ""))))
        preview_rows = rows_out[: max(1, int(top_n))]

        summary = {
            "category_count": len(rows_out),
            "priced_category_preview": [r.get("category") for r in preview_rows],
            "data_source": "rules",
        }

        recommendations: List[str] = []
        for r in preview_rows:
            cat = str(r.get("category", "")).strip()
            price = r.get("suggested_price")
            band = r.get("competitor_price_band")
            if cat and isinstance(price, int):
                recommendations.append(f"定价建议：{cat} 参考竞品价带 {band or 'N/A'}，建议标价约 ¥{price}。")

        return {
            "summary": summary,
            "pricing_rows": rows_out,
            "execution_checklist": [
                "抽样核对 3-5 个竞品链接，确认价带未过期",
                "对标主推款做 2 档价格梯度（引流/利润）",
                "上线后 7 天监控转化、加购与退货率并做微调",
            ],
            "recommendations": recommendations,
            "llm_error": None,
        }

