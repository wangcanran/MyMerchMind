import type { AgentReport, ReportParams } from '../types/report'

const CACHE_KEY = 'ecommerce_agent_report_session_v1'
const CACHE_VERSION = 1

export function defaultReportParams(): ReportParams {
  return {
    seed: 42,
    top_n: 5,
    as_of: '',
    replenishment_cycle: 7,
    overstock_days: 45,
    feedback_memory: '',
    selection_requirements: '',
  }
}

function mergeParams(raw: unknown): ReportParams {
  const d = defaultReportParams()
  if (!raw || typeof raw !== 'object') return d
  const o = raw as Partial<ReportParams>
  return {
    ...d,
    seed: typeof o.seed === 'number' && Number.isFinite(o.seed) ? o.seed : d.seed,
    top_n: typeof o.top_n === 'number' && o.top_n >= 1 ? o.top_n : d.top_n,
    as_of: typeof o.as_of === 'string' ? o.as_of : d.as_of,
    replenishment_cycle:
      typeof o.replenishment_cycle === 'number' && o.replenishment_cycle >= 1
        ? o.replenishment_cycle
        : d.replenishment_cycle,
    overstock_days:
      typeof o.overstock_days === 'number' && o.overstock_days >= 1
        ? o.overstock_days
        : d.overstock_days,
    feedback_memory:
      typeof o.feedback_memory === 'string' ? o.feedback_memory : d.feedback_memory,
    selection_requirements:
      typeof o.selection_requirements === 'string'
        ? o.selection_requirements
        : (d.selection_requirements ?? ''),
    ...(typeof o.target_gross_margin === 'number' &&
    Number.isFinite(o.target_gross_margin)
      ? { target_gross_margin: o.target_gross_margin }
      : {}),
  }
}

function isAgentReportShape(x: unknown): x is AgentReport {
  if (!x || typeof x !== 'object') return false
  const ctx = (x as AgentReport).context
  return typeof ctx === 'object' && ctx !== null && 'seed' in ctx
}

/** 成功生成报告后写入；刷新同一标签页可恢复。 */
export function saveSessionReportSnapshot(
  params: ReportParams,
  report: AgentReport,
): void {
  try {
    sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        v: CACHE_VERSION,
        savedAt: Date.now(),
        params,
        report,
      }),
    )
  } catch {
    // 配额或其它限制：忽略
  }
}

export function loadSessionReportSnapshot(): {
  params: ReportParams
  report: AgentReport
} | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as {
      v?: number
      params?: unknown
      report?: unknown
    }
    if (parsed.v !== CACHE_VERSION || !isAgentReportShape(parsed.report)) {
      return null
    }
    return {
      params: mergeParams(parsed.params),
      report: parsed.report,
    }
  } catch {
    return null
  }
}
