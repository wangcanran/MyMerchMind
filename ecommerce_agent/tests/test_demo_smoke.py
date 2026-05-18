"""Baseline demo 冒烟测试。"""
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_orchestrator_structure() -> None:
    from ecommerce_agent.orchestrator import DemoOrchestrator

    report = DemoOrchestrator(seed=42, top_n=3, as_of="2026-04-06").run()
    assert "product_selection" in report
    assert "sales_review" in report
    assert "inventory_review" in report
    assert "slow_moving" in report
    assert "replenishment" in report
    assert "memory_snapshot" in report
    assert "actions" in report
    assert report["memory_snapshot"]["active_feedback_count"] >= 0


def test_category_mapping_resolution() -> None:
    from ecommerce_agent.agents.category_management_agent import CategoryManagementAgent

    agent = CategoryManagementAgent()
    sku_metrics = [
        {
            "sku_id": "SKU-A",
            "name": "黑色外套",
            "daily_sales": 10,
            "stock": 100,
            "in_transit": 0,
            "return_rate": 0.05,
            "conversion_rate": 0.02,
            "stock_age_days": 12,
        },
        {
            "sku_id": "SKU-B",
            "name": "黑色外套",
            "daily_sales": 10,
            "stock": 100,
            "in_transit": 0,
            "return_rate": 0.05,
            "conversion_rate": 0.02,
            "stock_age_days": 12,
        },
    ]
    mapping = {"SKU-A": "连衣裙"}

    out = agent.analyze(sku_metrics=sku_metrics, category_mapping=mapping, top_n=5)
    cs = out.get("category_summary") or {}
    assert cs.get("mapping_enabled") is True
    assert cs.get("mapping_hit_skus") == 1

    rows = out.get("category_kpis") or []
    assert any(r.get("category") == "连衣裙" and r.get("sku_count") == 1 for r in rows)
    assert any(r.get("category") == "外套" and r.get("sku_count") == 1 for r in rows)


def test_category_experience_persistence(tmp_path) -> None:
    import json
    from ecommerce_agent.orchestrator import DemoOrchestrator
    from ecommerce_agent.memory.feedback_store import FeedbackMemoryStore

    mem_path = tmp_path / "memory.json"
    store = FeedbackMemoryStore(path=mem_path)
    store.append_category_experience(
        {
            "experience_id": "exp_tshirt_retire",
            "type": "negative",
            "category": "T恤",
            "decision": "谨慎上新",
            "root_cause": "库存压力/结构风险",
            "revisit_conditions": [{"description": "覆盖天数回落后再评估"}],
            "status": "active",
        }
    )
    store.save()
    orch = DemoOrchestrator(
        seed=42,
        top_n=5,
        as_of="2026-05-11",
        sku_scenario="class_demo",
        feedback_memory_path=mem_path,
    )
    report = orch.run()
    ctx = report.get("context") or {}
    assert "experience_memory_notice" in ctx
    assert mem_path.exists()
    data = json.loads(mem_path.read_text(encoding="utf-8"))
    assert isinstance(data.get("category_experiences"), list)
    cm = report.get("category_management") or {}
    decisions = cm.get("decisions") or {}
    audit = decisions.get("audit_existing") if isinstance(decisions, dict) else None
    assert isinstance(audit, dict)
    results = audit.get("results")
    assert isinstance(results, list)
    assert any(
        isinstance(r, dict)
        and r.get("category") == "T恤"
        and isinstance(r.get("experience_guardrail"), dict)
        and int(r["experience_guardrail"].get("hit_count", 0)) >= 1
        and "库存压力" in " ".join(r["experience_guardrail"].get("root_causes", []) or [])
        and isinstance(r["experience_guardrail"].get("guardrail_actions"), list)
        and any(
            isinstance(a, dict) and a.get("action") == "stop_replenishment"
            for a in (r["experience_guardrail"].get("guardrail_actions") or [])
        )
        for r in results
    )
    merged_actions = report.get("actions") or []
    assert any(isinstance(x, str) and "stop_replenishment" in x and "T恤" in x for x in merged_actions)


def test_llm_constrained_strategy_scenarios() -> None:
    from ecommerce_agent.agents.category_management_agent import CategoryManagementAgent

    class FakeLLM:
        def chat(self, _messages, temperature=0.0):
            _ = temperature
            return """
{
  "card_notes": {
    "audit_existing": "先盘点库存和退货，按阈值执行。",
    "retire": "对库存高且销量低的品类先清退。",
    "evaluate_new": "新品需在预算范围内小步验证。"
  },
  "execution_checklist": ["确认预算上限", "冻结清退品类补货", "7天复盘"],
  "strategy_scenarios": [
    {
      "title": "方案A 保守去化",
      "summary": "对高库存低贡献品类执行折扣去化与调拨。",
      "expected_impact": ["库存压力下降", "回款速度提升"],
      "risks": ["短期毛利下滑"],
      "monitor_7d": ["去化率", "折扣转化"],
      "monitor_30d": ["库存覆盖天数", "现金回收额"]
    },
    {
      "title": "方案B 结构优化",
      "summary": "聚焦高潜SKU，优化版型与详情页。",
      "expected_impact": ["转化率改善", "退货率下降"],
      "risks": ["改版投入增加"],
      "monitor_7d": ["点击到加购转化", "详情页停留时长"],
      "monitor_30d": ["类目退货率", "复购率"]
    },
    {
      "title": "方案C 延后上新观察",
      "summary": "高压品类先延后上新，观察库存与退货信号。",
      "expected_impact": ["避免新增库存风险", "集中资源处理存量"],
      "risks": ["可能错过趋势窗口"],
      "monitor_7d": ["高库存品类数量", "清退动作完成率"],
      "monitor_30d": ["覆盖天数是否回落", "主力品类销量稳定性"]
    }
  ]
}
"""

    agent = CategoryManagementAgent(llm_client=FakeLLM(), use_llm=True)
    sku_metrics = [
        {
            "sku_id": "SKU-A",
            "name": "黑色外套",
            "daily_sales": 12,
            "stock": 360,
            "in_transit": 40,
            "return_rate": 0.09,
            "conversion_rate": 0.015,
            "stock_age_days": 40,
        },
        {
            "sku_id": "SKU-B",
            "name": "白色T恤",
            "daily_sales": 6,
            "stock": 420,
            "in_transit": 60,
            "return_rate": 0.05,
            "conversion_rate": 0.01,
            "stock_age_days": 75,
        },
    ]
    out = agent.analyze(sku_metrics=sku_metrics, top_n=3)
    scenarios = out.get("strategy_scenarios") or []
    assert isinstance(scenarios, list) and len(scenarios) == 3
    assert [s.get("title") for s in scenarios] == ["方案A 保守去化", "方案B 结构优化", "方案C 延后上新观察"]
    assert out.get("data_source") == "hybrid"


def test_llm_placeholders_are_sanitized() -> None:
    from ecommerce_agent.agents.category_management_agent import CategoryManagementAgent

    class FakeLLM:
        def chat(self, _messages, temperature=0.0):
            _ = temperature
            return """
{
  "card_notes": {"audit_existing": "...", "retire": "Ellipsis", "evaluate_new": "..."},
  "execution_checklist": ["Ellipsis"],
  "strategy_scenarios": [
    {"title": "方案A 保守去化", "summary": "...", "expected_impact": ["Ellipsis"], "risks": ["..."], "monitor_7d": ["Ellipsis"], "monitor_30d": ["Ellipsis"]},
    {"title": "方案B 结构优化", "summary": "...", "expected_impact": ["..."], "risks": ["..."], "monitor_7d": ["..."], "monitor_30d": ["..."]},
    {"title": "方案C 延后上新观察", "summary": "...", "expected_impact": ["..."], "risks": ["..."], "monitor_7d": ["..."], "monitor_30d": ["..."]}
  ]
}
"""

    agent = CategoryManagementAgent(llm_client=FakeLLM(), use_llm=True)
    sku_metrics = [{"sku_id": "S1", "name": "咖啡色T恤", "daily_sales": 5, "stock": 200, "in_transit": 0}]
    out = agent.analyze(sku_metrics=sku_metrics, top_n=3)
    ln = out.get("llm_notes") or {}
    assert "Ellipsis" not in str(ln)
    assert "..." not in str(ln)
    scenarios = out.get("strategy_scenarios") or []
    assert scenarios and all(isinstance(s, dict) and s.get("summary") and s.get("summary") != "..." for s in scenarios)


def _decode_output(raw: bytes) -> str:
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def run_demo(output_path: Path) -> str:
    cmd = [
        sys.executable,
        "-m",
        "ecommerce_agent.main",
        "--demo",
        "--seed",
        "42",
        "--top-n",
        "5",
        "--as-of",
        "2026-04-06",
        "--output",
        str(output_path),
    ]

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )

    stdout_text = _decode_output(result.stdout)
    stderr_text = _decode_output(result.stderr)

    assert result.returncode == 0, stderr_text
    assert "=== DEMO CONTEXT ===" in stdout_text
    assert "=== PRODUCT SELECTION (M2) ===" in stdout_text
    assert "=== SALES REVIEW (P0) ===" in stdout_text
    assert "=== CHANNEL REVIEW (M4.1) ===" in stdout_text
    assert "=== RETURN SEMANTICS (M4.2) ===" in stdout_text
    assert "=== INVENTORY WARNINGS (P1) ===" in stdout_text
    assert "=== SLOW MOVING (M3.2) ===" in stdout_text
    assert "=== REPLENISHMENT EOQ (M3.3) ===" in stdout_text
    assert "=== MEMORY (M4.3) ===" in stdout_text
    assert "=== ACTIONS ===" in stdout_text

    assert output_path.exists()
    return output_path.read_text(encoding="utf-8")


def test_demo_smoke() -> None:
    report_1 = PROJECT_ROOT / "demo_report_smoke_1.md"
    report_2 = PROJECT_ROOT / "demo_report_smoke_2.md"

    content_1 = run_demo(report_1)
    content_2 = run_demo(report_2)

    assert content_1 == content_2
    assert "电商运营 Agent Baseline Demo 报告" in content_1


if __name__ == "__main__":
    test_orchestrator_structure()
    test_demo_smoke()
    print("Baseline demo 冒烟测试通过")
