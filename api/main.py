"""FastAPI app: exposes DemoOrchestrator JSON + Markdown report."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
import json
import queue
import threading
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ecommerce_agent.main import build_markdown_report
from ecommerce_agent.orchestrator import DemoOrchestrator
from .auth import register_user, verify_user

app = FastAPI(title="ECommerce Agent API", version="0.1.0")

_CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

# 与 POST 体一致；自然语言 / Markdown 不宜放 GET 查询串
MAX_SELECTION_REQUIREMENTS_CHARS = 200_000


class ReportRunBody(BaseModel):
    seed: int = Field(42, description="随机种子，保证可复现")
    top_n: int = Field(5, ge=1, le=50, description="榜单条数")
    as_of: str = Field("", description="报告日期 YYYY-MM-DD，空则今天")
    replenishment_cycle: int = Field(7, ge=1, le=90, description="补货周期（天）")
    overstock_days: int = Field(45, ge=1, le=365, description="高库存阈值（覆盖天数）")
    feedback_memory: str = Field("", description="避雷记忆 JSON 绝对路径；空则包内默认")
    use_llm: bool = Field(
        True,
        description=(
            "是否启用编排内大模型（销量/品类/库存/定价等叙事与结构化增强）。"
            "默认 True（前端全链路）；未配置 API Key 时自动回退规则，见响应 context.llm_notice。"
        ),
    )
    selection_requirements: Optional[str] = Field(
        default=None,
        description="选品需求：自然语言或 Markdown 全文；非空时先 LLM 解析为 criteria 再走图谱选品",
        max_length=MAX_SELECTION_REQUIREMENTS_CHARS,
    )
    target_gross_margin: Optional[float] = Field(
        default=None,
        description=(
            "企划 market_intel 用目标毛利率：0~1 小数（如 0.45）；"
            "可填 >1 表示百分数（如 40 表示 40%）；缺省 0.45；有效范围约 5%~85%"
        ),
    )
    erp_data: Optional[list] = Field(
        default=None,
        description="ERP SKU 数据数组；非空时替代 mock 数据源",
    )
    competitors_data: Optional[list] = Field(
        default=None,
        description="竞品数据数组；非空时替代爬虫/mock竞品源",
    )


_ALLOWED_FEEDBACK_DIRS: list[Path] = [
    Path(__file__).resolve().parent.parent / "ecommerce_agent" / "memory",
    Path(__file__).resolve().parent.parent / "data",
]
_extra = os.environ.get("FEEDBACK_MEMORY_ALLOWED_DIR", "").strip()
if _extra:
    _ALLOWED_FEEDBACK_DIRS.append(Path(_extra).resolve())


def _resolve_feedback_path(raw: str) -> Optional[Path]:
    if not (raw or "").strip():
        return None
    p = Path(raw.strip()).expanduser().resolve()
    # 路径遍历防护：必须位于允许的目录下
    if not any(p == allowed or allowed in p.parents for allowed in _ALLOWED_FEEDBACK_DIRS):
        raise HTTPException(
            status_code=400,
            detail="feedback_memory 路径不在允许的目录范围内",
        )
    if not p.is_file():
        raise HTTPException(status_code=400, detail=f"找不到避雷记忆文件：{p}")
    if p.suffix not in (".json", ".jsonl"):
        raise HTTPException(status_code=400, detail="feedback_memory 仅支持 .json/.jsonl 文件")
    return p


def _normalize_selection_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None
    if len(t) > MAX_SELECTION_REQUIREMENTS_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"selection_requirements 过长（>{MAX_SELECTION_REQUIREMENTS_CHARS} 字符）",
        )
    return t


def _run_orchestrator(
    seed: int,
    top_n: int,
    as_of: str,
    replenishment_cycle_days: int,
    overstock_days: int,
    feedback_memory_path: Optional[Path],
    selection_requirements_text: Optional[str] = None,
    target_gross_margin: Optional[float] = None,
    *,
    use_llm: bool = True,
    erp_data: Optional[list] = None,
    competitors_data: Optional[list] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    from ecommerce_agent.data.erp_adapter import ERPAdapter

    erp_adapter = None
    if erp_data:
        # 将前端传入的 SKU 列表转为 {sku_id: {...}} 格式
        sku_table: Dict[str, Dict] = {}
        for item in erp_data:
            if not isinstance(item, dict):
                continue
            sid = item.get("sku_id", "")
            if not sid:
                continue
            sku_table[sid] = {
                "name": item.get("name", sid),
                "price": item.get("price") or item.get("current_price") or 0,
                "cost_price": item.get("cost_price", 0),
                "daily_sales": item.get("daily_sales", 0),
                "stock": item.get("stock", 0),
                "in_transit": item.get("in_transit", 0),
                "return_rate": item.get("return_rate", 0),
                "channel_sales": item.get("channel_sales", {"live": 0, "private": 0, "shelf": 0}),
                "conversion_rate": item.get("conversion_rate", 0),
                "stock_age_days": item.get("stock_age_days", 0),
                "review_snippets": item.get("review_snippets", []),
                "prior_week_total_units": item.get("prior_week_total_units", 0),
                "prior_month_total_units": item.get("prior_month_total_units", 0),
                "price_history": item.get("price_history"),
            }
        if sku_table:
            erp_adapter = ERPAdapter(
                seed=seed,
                sku_table=sku_table,
            )

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
        selection_requirements_text=selection_requirements_text,
        target_gross_margin=target_gross_margin,
        use_llm=use_llm,
        erp_adapter=erp_adapter,
        uploaded_competitor_products=competitors_data if competitors_data else None,
        progress_callback=progress_callback,
    )
    report = orch.run()

    # 自动将 actions 入库为可追踪策略
    try:
        actions_display = report.get("actions_display", {})
        rows = actions_display.get("rows", [])
        action_texts = [r.get("action", "") for r in rows if isinstance(r, dict)]
        if action_texts:
            store = _default_strategy_store()
            run_id = f"run-{as_of}-seed{seed}"
            store.ingest_from_run(action_texts, run_id=run_id, as_of=as_of)
    except Exception:
        pass  # 策略入库失败不影响报告返回

    return report


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
    target_gross_margin: Optional[float] = Query(
        None,
        description="企划 market_intel 目标毛利率：0~1 或百分数>1；缺省 0.45",
    ),
    use_llm: bool = Query(
        True,
        description="是否启用编排内大模型（默认开；未配置 Key 时回退规则，见 context.llm_notice）",
    ),
) -> Dict[str, Any]:
    """兼容旧版：无正文需求理解。长文本/上传请用 ``POST /api/report``。"""
    if not as_of:
        as_of = date.today().isoformat()
    fb = _resolve_feedback_path(feedback_memory)
    # GET 不读环境变量需求正文，避免意外把服务器 .env 长文带进编排
    report = _run_orchestrator(
        seed=seed,
        top_n=top_n,
        as_of=as_of,
        replenishment_cycle_days=replenishment_cycle,
        overstock_days=overstock_days,
        feedback_memory_path=fb,
        selection_requirements_text=None,
        target_gross_margin=target_gross_margin,
        use_llm=use_llm,
    )
    report["markdown"] = build_markdown_report(report)
    return report


@app.post("/api/report")
def post_report(body: ReportRunBody = Body(...)) -> Dict[str, Any]:
    """生成报告；``selection_requirements`` 为非空字符串时走需求理解（LLM 抽 criteria）+ 图谱选品。"""
    as_of = body.as_of.strip() or date.today().isoformat()
    fb = _resolve_feedback_path(body.feedback_memory)
    sel_text = _normalize_selection_text(body.selection_requirements)
    report = _run_orchestrator(
        seed=body.seed,
        top_n=body.top_n,
        as_of=as_of,
        replenishment_cycle_days=body.replenishment_cycle,
        overstock_days=body.overstock_days,
        feedback_memory_path=fb,
        selection_requirements_text=sel_text,
        target_gross_margin=body.target_gross_margin,
        use_llm=body.use_llm,
        erp_data=body.erp_data,
        competitors_data=body.competitors_data,
    )
    report["markdown"] = build_markdown_report(report)
    return report


@app.post("/api/report/stream")
def post_report_stream(body: ReportRunBody = Body(...)):
    """SSE 流式生成报告，实时推送进度。"""
    as_of = body.as_of.strip() or date.today().isoformat()
    fb = _resolve_feedback_path(body.feedback_memory)
    sel_text = _normalize_selection_text(body.selection_requirements)

    progress_queue: queue.Queue = queue.Queue()

    def progress_cb(step: str, current: int, total: int):
        progress_queue.put({"type": "progress", "step": step, "current": current, "total": total})

    def run_in_thread():
        try:
            report = _run_orchestrator(
                seed=body.seed,
                top_n=body.top_n,
                as_of=as_of,
                replenishment_cycle_days=body.replenishment_cycle,
                overstock_days=body.overstock_days,
                feedback_memory_path=fb,
                selection_requirements_text=sel_text,
                target_gross_margin=body.target_gross_margin,
                use_llm=body.use_llm,
                erp_data=body.erp_data,
                competitors_data=body.competitors_data,
                progress_callback=progress_cb,
            )
            report["markdown"] = build_markdown_report(report)
            progress_queue.put({"type": "result", "data": report})
        except Exception as e:
            progress_queue.put({"type": "error", "message": str(e)})

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    def event_stream():
        while True:
            try:
                msg = progress_queue.get(timeout=2100)
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'error', 'message': '超时'}, ensure_ascii=False)}\n\n"
                break
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            if msg["type"] in ("result", "error"):
                break
        thread.join(timeout=5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get(
    "/api/report/markdown",
    summary="仅导出 Markdown（会整编排再跑一遍）",
    description="与 ``GET /api/report`` 独立调用编排器；LLM 选品等非确定步骤可能与页面 JSON 不一致。请优先使用 ``/api/report`` 返回体中的 ``markdown`` 字段。",
)
def get_report_markdown(
    seed: int = Query(42),
    top_n: int = Query(5, ge=1, le=50),
    as_of: str = Query(""),
    replenishment_cycle: int = Query(7, ge=1, le=90),
    overstock_days: int = Query(45, ge=1, le=365),
    feedback_memory: str = Query(""),
    target_gross_margin: Optional[float] = Query(None),
    use_llm: bool = Query(
        True,
        description="是否启用编排内大模型（默认开；未配置 Key 时回退规则）",
    ),
) -> Dict[str, str]:
    if not as_of:
        as_of = date.today().isoformat()
    fb = _resolve_feedback_path(feedback_memory)
    report = _run_orchestrator(
        seed=seed,
        top_n=top_n,
        as_of=as_of,
        replenishment_cycle_days=replenishment_cycle,
        overstock_days=overstock_days,
        feedback_memory_path=fb,
        selection_requirements_text=None,
        target_gross_margin=target_gross_margin,
        use_llm=use_llm,
    )
    return {"markdown": build_markdown_report(report)}


@app.post("/api/report/markdown")
def post_report_markdown(body: ReportRunBody = Body(...)) -> Dict[str, str]:
    """与 ``POST /api/report`` 相同入参，仅返回 Markdown（仍会整编排跑一遍）。"""
    as_of = body.as_of.strip() or date.today().isoformat()
    fb = _resolve_feedback_path(body.feedback_memory)
    sel_text = _normalize_selection_text(body.selection_requirements)
    report = _run_orchestrator(
        seed=body.seed,
        top_n=body.top_n,
        as_of=as_of,
        replenishment_cycle_days=body.replenishment_cycle,
        overstock_days=body.overstock_days,
        feedback_memory_path=fb,
        selection_requirements_text=sel_text,
        target_gross_margin=body.target_gross_margin,
        use_llm=body.use_llm,
    )
    return {"markdown": build_markdown_report(report)}


# =============================================================================
# 店铺经验 CRUD
# =============================================================================

from ecommerce_agent.memory.experience_store import ExperienceStore


def _default_experience_store() -> ExperienceStore:
    """从环境变量或包默认路径解析 ExperienceStore 实例。"""
    raw = (os.environ.get("ECOMMERCE_EXPERIENCE_STORE_PATH") or "").strip()
    path = Path(raw) if raw else None
    return ExperienceStore(path=path)


class ExperienceSearchBody(BaseModel):
    season: str = Field("", description="spring/summer/autumn/winter；空则不过滤")
    categories: list[str] = Field(default_factory=list, description="类目列表")
    price_tiers: list[str] = Field(default_factory=list, description="价位分桶，如 100-200")
    channels: list[str] = Field(default_factory=list, description="渠道，如 live/private/shelf")
    return_signals: list[str] = Field(default_factory=list, description="退货信号 normal/elevated/high")
    inventory_signals: list[str] = Field(default_factory=list, description="库龄信号 fresh/aging/overstocked")
    conversion_signals: list[str] = Field(default_factory=list, description="转化信号 low/normal/high")
    tag_values: list[str] = Field(default_factory=list, description="标签值列表，如 [天丝, 美拉德]")
    trend_keywords: list[str] = Field(default_factory=list, description="趋势词列表")
    criteria_style: str = Field("", description="选品风格词，如 复古")
    criteria_audience: str = Field("", description="目标人群描述")
    top_k: int = Field(5, ge=1, le=20, description="最多返回条数")


class ExperienceCreateBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=60, description="短标题")
    narrative: str = Field(..., min_length=1, description="叙事正文")
    search_keys: Dict[str, Any] = Field(default_factory=dict, description="检索键字典")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="证据快照")
    confidence: str = Field("high", description="置信度 low/medium/high")
    valid_until: Optional[str] = Field(None, description="有效期 YYYY-MM-DD；null 永不过期")


class ExperienceApproveBody(BaseModel):
    confidence: str = Field("medium", description="审核后置信度 low/medium/high")


@app.get("/api/experiences", summary="列出经验（可按状态筛选）")
def list_experiences(
    status: str = Query("active", description="active/draft/archived/all"),
) -> Dict[str, Any]:
    store = _default_experience_store()
    all_exp = store.list_all()
    if status != "all":
        all_exp = [e for e in all_exp if e.get("status") == status]
    return {"experiences": all_exp, "total": len(all_exp), "stats": store.stats()}


@app.post("/api/experiences/search", summary="按系统字段检索相关经验")
def search_experiences(body: ExperienceSearchBody = Body(...)) -> Dict[str, Any]:
    from ecommerce_agent.memory.experience_store import build_query_keys_from_run
    store = _default_experience_store()
    query = build_query_keys_from_run(
        as_of="",  # season 由调用方直接传 season 字段
        categories=body.categories,
        price_tiers=body.price_tiers,
        channels=body.channels,
        return_signals=body.return_signals,
        inventory_signals=body.inventory_signals,
        conversion_signals=body.conversion_signals,
        tag_values=body.tag_values,
        trend_keywords=body.trend_keywords,
        criteria_style=body.criteria_style,
        criteria_audience=body.criteria_audience,
    )
    # 若调用方直接传了 season 则覆盖
    if body.season:
        query["season"] = body.season
    results = store.retrieve(query, top_k=body.top_k)
    return {"experiences": results, "total": len(results)}


@app.post("/api/experiences", summary="人工录入经验（直接 active）")
def create_experience(body: ExperienceCreateBody = Body(...)) -> Dict[str, Any]:
    store = _default_experience_store()
    entry = store.append_human(
        title=body.title,
        narrative=body.narrative,
        search_keys=body.search_keys,
        evidence=body.evidence,
        confidence=body.confidence,
        valid_until=body.valid_until,
    )
    store.save()
    return {"experience": entry}


@app.post("/api/experiences/{experience_id}/approve", summary="审核通过 draft → active")
def approve_experience(
    experience_id: str,
    body: ExperienceApproveBody = Body(...),
) -> Dict[str, Any]:
    store = _default_experience_store()
    ok = store.approve(experience_id, confidence=body.confidence)
    if not ok:
        raise HTTPException(status_code=404, detail=f"找不到 draft 状态的经验：{experience_id}")
    store.save()
    return {"ok": True, "experience_id": experience_id}


@app.post("/api/experiences/{experience_id}/archive", summary="归档经验（保留历史）")
def archive_experience(experience_id: str) -> Dict[str, Any]:
    store = _default_experience_store()
    ok = store.archive(experience_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"找不到可归档的经验：{experience_id}")
    store.save()
    return {"ok": True, "experience_id": experience_id}


@app.get("/api/experiences/{experience_id}", summary="获取单条经验详情")
def get_experience(experience_id: str) -> Dict[str, Any]:
    store = _default_experience_store()
    entry = store.get_by_id(experience_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"经验不存在：{experience_id}")
    return {"experience": entry}


# =============================================================================
# 策略追踪 CRUD
# =============================================================================

from ecommerce_agent.memory.strategy_store import StrategyStore
from ecommerce_agent.memory.experience_from_feedback import generate_experience_from_feedback


def _default_strategy_store() -> StrategyStore:
    raw = (os.environ.get("ECOMMERCE_STRATEGY_STORE_PATH") or "").strip()
    path = Path(raw) if raw else None
    return StrategyStore(path=path)


class FeedbackBody(BaseModel):
    outcome: str = Field(..., description="good / average / poor")
    reason: str = Field("", description="商家反馈原因")
    kpi_data: Dict[str, Any] = Field(default_factory=dict, description="实际 KPI 数据")


@app.get("/api/strategies", summary="列出策略（支持月份/状态/模块过滤）")
def list_strategies(
    month: str = Query("", description="月份 YYYY-MM"),
    status: str = Query("", description="pending/accepted/rejected/awaiting_feedback/feedback_received"),
    module: str = Query("", description="模块: selection/pricing/inventory/replenishment/slow_moving"),
) -> Dict[str, Any]:
    store = _default_strategy_store()
    items = store.list_filtered(
        month=month or None,
        status=status or None,
        module=module or None,
    )
    return {"strategies": items, "total": len(items)}


@app.get("/api/strategies/stats", summary="策略统计")
def strategy_stats(
    month: str = Query("", description="月份 YYYY-MM"),
) -> Dict[str, Any]:
    store = _default_strategy_store()
    return store.stats(month=month or None)


@app.get("/api/strategies/{strategy_id}", summary="单条策略详情")
def get_strategy(strategy_id: str) -> Dict[str, Any]:
    store = _default_strategy_store()
    entry = store.get_by_id(strategy_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"策略不存在：{strategy_id}")
    return {"strategy": entry}


@app.post("/api/strategies/{strategy_id}/accept", summary="接受策略")
def accept_strategy(strategy_id: str) -> Dict[str, Any]:
    store = _default_strategy_store()
    entry = store.accept(strategy_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"策略不存在：{strategy_id}")
    return {"strategy": entry}


@app.post("/api/strategies/{strategy_id}/reject", summary="拒绝策略")
def reject_strategy(strategy_id: str) -> Dict[str, Any]:
    store = _default_strategy_store()
    entry = store.reject(strategy_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"策略不存在：{strategy_id}")
    return {"strategy": entry}


@app.post("/api/strategies/{strategy_id}/feedback", summary="提交反馈并生成经验")
def submit_strategy_feedback(strategy_id: str, body: FeedbackBody) -> Dict[str, Any]:
    strategy_store = _default_strategy_store()
    entry = strategy_store.submit_feedback(
        strategy_id=strategy_id,
        outcome=body.outcome,
        reason=body.reason,
        kpi_data=body.kpi_data,
    )
    if not entry:
        raise HTTPException(status_code=404, detail=f"策略不存在：{strategy_id}")

    # 自动生成经验
    experience_store = _default_experience_store()
    experience = generate_experience_from_feedback(
        strategy=entry,
        feedback=entry.get("feedback", {}),
        experience_store=experience_store,
    )

    return {
        "strategy": entry,
        "generated_experience": experience,
    }


# =============================================================================
# 用户认证
# =============================================================================


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


@app.post("/api/login", summary="用户登录")
def login(body: LoginBody = Body(...)) -> Dict[str, str]:
    if not verify_user(body.username, body.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"message": "登录成功"}


@app.post("/api/register", summary="用户注册")
def register(body: LoginBody = Body(...)) -> Dict[str, str]:
    try:
        register_user(body.username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "注册成功"}

