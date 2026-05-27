import type { AgentReport, ReportParams } from '../types/report'

const ERP_STORAGE_KEY = 'erp_sku_data'
const COMPETITOR_STORAGE_KEY = 'competitor_data'
const HISTORY_STORAGE_KEY = 'price_history_data'

function getStoredErpData(): unknown[] | null {
  try {
    const raw = sessionStorage.getItem(ERP_STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    return Array.isArray(data) && data.length > 0 ? data : null
  } catch { return null }
}

function getStoredCompetitorData(): unknown[] | null {
  try {
    const raw = sessionStorage.getItem(COMPETITOR_STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    return Array.isArray(data) && data.length > 0 ? data : null
  } catch { return null }
}

function getStoredPriceHistoryData(): unknown[] | null {
  try {
    const raw = sessionStorage.getItem(HISTORY_STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    return Array.isArray(data) && data.length > 0 ? data : null
  } catch { return null }
}

/** 将价格历史合并到 ERP 数据中（若 ERP 数据存在） */
function mergeHistoryIntoErp(erpData: Record<string, unknown>[]): Record<string, unknown>[] {
  const historyData = getStoredPriceHistoryData()
  if (!historyData) return erpData
  const historyMap = new Map<string, unknown[]>()
  for (const item of historyData as Record<string, unknown>[]) {
    const skuId = String(item.sku_id || '')
    const records = (item.records || item.price_history) as unknown[]
    if (skuId && Array.isArray(records)) {
      historyMap.set(skuId, records)
    }
  }
  return erpData.map((sku) => {
    const records = historyMap.get(String(sku.sku_id || ''))
    return records ? { ...sku, price_history: records } : sku
  })
}

function toSearchParams(p: ReportParams): string {
  const u = new URLSearchParams()
  u.set('seed', String(p.seed))
  u.set('top_n', String(p.top_n))
  if (p.as_of.trim()) u.set('as_of', p.as_of.trim())
  u.set('replenishment_cycle', String(p.replenishment_cycle))
  u.set('overstock_days', String(p.overstock_days))
  if (p.feedback_memory.trim()) {
    u.set('feedback_memory', p.feedback_memory.trim())
  }
  if (
    typeof p.target_gross_margin === 'number' &&
    Number.isFinite(p.target_gross_margin)
  ) {
    u.set('target_gross_margin', String(p.target_gross_margin))
  }
  return u.toString()
}

function reportJsonBody(p: ReportParams): Record<string, unknown> {
  const sel = (p.selection_requirements ?? '').trim()
  const body: Record<string, unknown> = {
    seed: p.seed,
    top_n: p.top_n,
    as_of: p.as_of.trim(),
    replenishment_cycle: p.replenishment_cycle,
    overstock_days: p.overstock_days,
    feedback_memory: p.feedback_memory.trim(),
    selection_requirements: sel.length > 0 ? sel : null,
  }
  if (
    typeof p.target_gross_margin === 'number' &&
    Number.isFinite(p.target_gross_margin)
  ) {
    body.target_gross_margin = p.target_gross_margin
  }
  // 附带 ERP 数据（合并价格历史）
  const erpData = getStoredErpData()
  if (erpData) {
    body.erp_data = mergeHistoryIntoErp(erpData as Record<string, unknown>[])
  } else if (getStoredPriceHistoryData()) {
    // 没有 ERP 数据但有历史数据：构造最小 ERP 记录以携带历史
    const historyData = getStoredPriceHistoryData() as Record<string, unknown>[]
    body.erp_data = historyData.map((item) => ({
      sku_id: item.sku_id,
      name: item.name || item.sku_id,
      price_history: item.records || item.price_history,
    }))
  }
  // 附带竞品数据
  const competitorData = getStoredCompetitorData()
  if (competitorData) {
    body.competitors_data = competitorData
  }
  return body
}

function shouldUsePost(p: ReportParams): boolean {
  return (p.selection_requirements ?? '').trim().length > 0 || getStoredErpData() !== null || getStoredCompetitorData() !== null || getStoredPriceHistoryData() !== null
}

export async function fetchReport(p: ReportParams): Promise<AgentReport> {
  if (shouldUsePost(p)) {
    const res = await fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reportJsonBody(p)),
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(text || `HTTP ${res.status}`)
    }
    return res.json() as Promise<AgentReport>
  }
  const q = toSearchParams(p)
  const res = await fetch(`/api/report?${q}`)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<AgentReport>
}

export async function fetchReportMarkdown(p: ReportParams): Promise<string> {
  if (shouldUsePost(p)) {
    const res = await fetch('/api/report/markdown', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reportJsonBody(p)),
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(text || `HTTP ${res.status}`)
    }
    const data = (await res.json()) as { markdown: string }
    return data.markdown
  }
  const q = toSearchParams(p)
  const res = await fetch(`/api/report/markdown?${q}`)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  const data = (await res.json()) as { markdown: string }
  return data.markdown
}
