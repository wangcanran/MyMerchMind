"""ecommerce_agent 包初始化。"""

from pathlib import Path


def _load_repo_dotenv() -> None:
    """将仓库根目录 ``.env`` 注入 ``os.environ``（不覆盖已有环境变量）。

    ``LLMConfig`` 等只读环境变量；若不在此处加载 dotenv，则仅当进程或 IDE
    已注入变量、或单独运行带 ``load_dotenv`` 的脚本时密钥才可见。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    repo_root = Path(__file__).resolve().parent.parent
    env_path = repo_root / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


_load_repo_dotenv()
