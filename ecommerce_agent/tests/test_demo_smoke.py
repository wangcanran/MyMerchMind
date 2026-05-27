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
    assert "pricing" in report
    assert "sales_review" in report
    assert "inventory_review" in report
    assert "slow_moving" in report
    assert "replenishment" in report
    assert "inventory_management" in report
    assert "memory_snapshot" in report
    assert "actions" in report
    assert "actions_display" in report
    assert report["memory_snapshot"]["active_feedback_count"] >= 0


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
    assert "=== SKU PRICING (M3.1) ===" in stdout_text
    assert "=== SALES REVIEW (P0) ===" in stdout_text
    assert "=== CHANNEL REVIEW (M4.1) ===" in stdout_text
    assert "=== RETURN SEMANTICS (M4.2) ===" in stdout_text
    assert "=== INVENTORY WARNINGS (P1) ===" in stdout_text
    assert "=== SLOW MOVING (M3.2) ===" in stdout_text
    assert "=== REPLENISHMENT EOQ (M3.3) ===" in stdout_text
    assert "=== INVENTORY CONTROL BOARD ===" in stdout_text
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
