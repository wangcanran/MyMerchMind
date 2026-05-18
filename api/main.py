"""FastAPI app: exposes DemoOrchestrator JSON + Markdown report."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from ecommerce_agent.main import build_markdown_report
from ecommerce_agent.orchestrator import DemoOrchestrator

app = FastAPI(title="ECommerce Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _run_orchestrator(
    seed: int,
    top_n: int,
    as_of: str,
    replenishment_cycle_days: int,
    overstock_days: int,
    feedback_memory_path: Optional[Path],
) -> Dict[str, Any]:
    orch = DemoOrchestrator(
        seed=seed,
        top_n=top_n,
        as_of=as_of,
        replenishment_cycle_days=replenishment_cycle_days,
        overstock_days=overstock_days,
        feedback_memory_path=feedback_memory_path,
        enable_selection=True,
        enable_category_management=True,
        enable_pricing=True,
    )
    return orch.run()


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/report")
def get_report(
    seed: int = Query(42, description="随机种子，保证可复现"),
    top_n: int = Query(5, ge=1, le=50, description="榜单条数"),
    as_of: str = Query("", description="报告日期 YYYY-MM-DD，空则今天"),
    replenishment_cycle: int = Query(7, ge=1, le=90, description="补货周期（天）"),
    overstock_days: int = Query(45, ge=1, le=365, description="高库存阈值（覆盖天数）"),
    feedback_memory: str = Query(
        "",
        description="避雷记忆 JSON 绝对路径；空则使用包内默认",
    ),
) -> Dict[str, Any]:
    if not as_of:
        as_of = date.today().isoformat()
    fb: Optional[Path] = None
    if feedback_memory.strip():
        p = Path(feedback_memory).expanduser()
        if not p.is_file():
            raise HTTPException(status_code=400, detail=f"找不到避雷记忆文件：{p}")
        fb = p
    return _run_orchestrator(
        seed=seed,
        top_n=top_n,
        as_of=as_of,
        replenishment_cycle_days=replenishment_cycle,
        overstock_days=overstock_days,
        feedback_memory_path=fb,
    )


@app.get("/api/report/markdown")
def get_report_markdown(
    seed: int = Query(42),
    top_n: int = Query(5, ge=1, le=50),
    as_of: str = Query(""),
    replenishment_cycle: int = Query(7, ge=1, le=90),
    overstock_days: int = Query(45, ge=1, le=365),
    feedback_memory: str = Query(""),
) -> Dict[str, str]:
    if not as_of:
        as_of = date.today().isoformat()
    fb: Optional[Path] = None
    if feedback_memory.strip():
        p = Path(feedback_memory).expanduser()
        if not p.is_file():
            raise HTTPException(status_code=400, detail=f"找不到避雷记忆文件：{p}")
        fb = p
    report = _run_orchestrator(
        seed=seed,
        top_n=top_n,
        as_of=as_of,
        replenishment_cycle_days=replenishment_cycle,
        overstock_days=overstock_days,
        feedback_memory_path=fb,
    )
    return {"markdown": build_markdown_report(report)}
