import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def pytest_ignore_collect(path: Path, config) -> bool:
    if sys.version_info < (3, 10):
        return True

    if not _has_module("pipmaster"):
        return True

    basename = str(getattr(path, "basename", None) or getattr(path, "name", "") or "")
    if basename in {"test_overlap_validation.py", "test_rerank_chunking.py"} and not _has_module("aiohttp"):
        return True
    if basename.startswith("test_qdrant_") and not _has_module("qdrant_client"):
        return True

    return False

