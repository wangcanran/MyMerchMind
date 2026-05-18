"""示例需求文档存在性检查。"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = PROJECT_ROOT / "ecommerce_agent" / "data" / "samples" / "selection_requirements_sample.md"


def test_selection_requirements_sample_exists() -> None:
    assert SAMPLE.is_file(), f"缺少示例需求文档: {SAMPLE}"
    text = SAMPLE.read_text(encoding="utf-8")
    assert "season" in text.lower() or "季节" in text or "春夏" in text
    assert len(text.strip()) > 80
