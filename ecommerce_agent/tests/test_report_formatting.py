"""report_formatting 辅助函数单测。"""
from __future__ import annotations

from ecommerce_agent.report_formatting import (
    build_actions_display,
    dedupe_pricing_llm_exception_lines,
    longest_common_prefix,
    normalize_trend_growth_in_text,
)


def test_normalize_trend_growth_in_text() -> None:
    s = "美拉德风格增速达0.34，需关注库存。"
    out = normalize_trend_growth_in_text(s)
    assert "34%" in out
    assert "0.34" not in out


def test_longest_common_prefix() -> None:
    assert longest_common_prefix(["abc", "abd", "abx"]) == "ab"


def test_dedupe_pricing_llm_exception_lines() -> None:
    common = (
        "本次调价幅度较大，需与活动运营及供应链权限统一确认后再执行，避免线上线下价盘冲突。"
    )
    rows = [
        {"llm_exception_explanation": common + " SKU-A 注意退货。"},
        {"llm_exception_explanation": common + " SKU-B 已触成本底线。"},
    ]
    c, parts = dedupe_pricing_llm_exception_lines(rows)
    assert c == common
    assert "SKU-A" in parts[0]
    assert "SKU-B" in parts[1]


def test_build_actions_display_sorts_tiers() -> None:
    ad = build_actions_display(
        ["定价建议：SKU1 调价", "高退货处置：SKU2 处置", "【LLM】辅助句"],
        as_of_iso="2026-05-21",
    )
    tiers = [r["tier"] for r in ad["rows"]]
    assert tiers[0].startswith("P0")

