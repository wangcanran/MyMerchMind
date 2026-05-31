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
  } catch {
    return null
  }
}

function getStoredCompetitorData(): unknown[] | null {
  try {
    const raw = sessionStorage.getItem(COMPETITOR_STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    return Array.isArray(data) && data.length > 0 ? data : null
  } catch {
    return null
  }
}

function getStoredPriceHistoryData(): unknown[] | null {
  try {
    const raw = sessionStorage.getItem(HISTORY_STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    return Array.isArray(data) && data.length > 0 ? data : null
  } catch {
    return null
  }
}

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

async function readJson<T>(response: Response): Promise<T> {
  return response.json() as Promise<T>
}

async function readError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: string; message?: string }
    return data.detail || data.message || `HTTP ${response.status}`
  } catch {
    const text = await response.text()
    return text || `HTTP ${response.status}`
  }
}

async function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return readJson<T>(response)
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

  const erpData = getStoredErpData()
  if (erpData) {
    body.erp_data = mergeHistoryIntoErp(erpData as Record<string, unknown>[])
  } else if (getStoredPriceHistoryData()) {
    const historyData = getStoredPriceHistoryData() as Record<string, unknown>[]
    body.erp_data = historyData.map((item) => {
      const records = (item.records || item.price_history) as Record<string, unknown>[] | undefined
      // Derive daily_sales from last record if not provided directly
      let dailySales = Number(item.daily_sales) || 0
      let price = Number(item.current_price || item.price) || 0
      if (Array.isArray(records) && records.length > 0 && !dailySales) {
        const last7 = records.slice(-7)
        dailySales = Math.round(last7.reduce((s, r) => s + (Number(r.daily_sales) || 0), 0) / last7.length)
        if (!price) price = Number(records[records.length - 1].price) || 0
      }
      return {
        sku_id: item.sku_id,
        name: item.name || item.sku_id,
        price,
        cost_price: Number(item.cost_price) || 0,
        daily_sales: dailySales,
        stock: Number(item.stock) || Math.round(dailySales * 10),
        in_transit: Number(item.in_transit) || 0,
        return_rate: Number(item.return_rate) || 0,
        channel_sales: item.channel_sales || { live: Math.round(dailySales * 0.4), private: Math.round(dailySales * 0.35), shelf: Math.round(dailySales * 0.25) },
        conversion_rate: Number(item.conversion_rate) || 0,
        stock_age_days: Number(item.stock_age_days) || 0,
        price_history: records,
      }
    })
  }

  const competitorData = getStoredCompetitorData()
  if (competitorData) {
    body.competitors_data = competitorData
  }
  return body
}

function shouldUsePost(p: ReportParams): boolean {
  return (
    (p.selection_requirements ?? '').trim().length > 0 ||
    getStoredErpData() !== null ||
    getStoredCompetitorData() !== null ||
    getStoredPriceHistoryData() !== null
  )
}

export async function fetchReportWithProgress(
  p: ReportParams,
  onProgress: (step: string, current: number, total: number) => void,
): Promise<AgentReport> {
  const body = reportJsonBody(p)
  const res = await fetch('/api/report/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(await readError(res))
  }
  const reader = res.body?.getReader()
  if (!reader) throw new Error('No response body')
  const decoder = new TextDecoder()
  let buffer = ''
  let result: AgentReport | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      const dataLine = line.replace(/^data: /, '').trim()
      if (!dataLine) continue
      try {
        const msg = JSON.parse(dataLine)
        if (msg.type === 'progress') {
          onProgress(msg.step, msg.current, msg.total)
        } else if (msg.type === 'result') {
          result = msg.data as AgentReport
        } else if (msg.type === 'error') {
          throw new Error(msg.message)
        }
      } catch (e) {
        if (e instanceof Error && e.message !== dataLine) throw e
      }
    }
  }
  // Process any remaining data in buffer
  if (buffer.trim()) {
    const dataLine = buffer.replace(/^data: /, '').trim()
    if (dataLine) {
      try {
        const msg = JSON.parse(dataLine)
        if (msg.type === 'result') {
          result = msg.data as AgentReport
        } else if (msg.type === 'error') {
          throw new Error(msg.message)
        }
      } catch { /* ignore parse errors on trailing buffer */ }
    }
  }
  if (!result) throw new Error('未收到报告结果')
  return result
}

export async function fetchReport(p: ReportParams): Promise<AgentReport> {
  if (shouldUsePost(p)) {
    const res = await fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reportJsonBody(p)),
    })
    if (!res.ok) {
      throw new Error(await readError(res))
    }
    return readJson<AgentReport>(res)
  }
  const q = toSearchParams(p)
  const res = await fetch(`/api/report?${q}`)
  if (!res.ok) {
    throw new Error(await readError(res))
  }
  return readJson<AgentReport>(res)
}

export async function fetchReportMarkdown(p: ReportParams): Promise<string> {
  if (shouldUsePost(p)) {
    const res = await fetch('/api/report/markdown', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reportJsonBody(p)),
    })
    if (!res.ok) {
      throw new Error(await readError(res))
    }
    const data = await readJson<{ markdown: string }>(res)
    return data.markdown
  }
  const q = toSearchParams(p)
  const res = await fetch(`/api/report/markdown?${q}`)
  if (!res.ok) {
    throw new Error(await readError(res))
  }
  const data = await readJson<{ markdown: string }>(res)
  return data.markdown
}

export async function login(username: string, password: string): Promise<{ message: string }> {
  return postJson<{ message: string }>('/api/login', { username, password })
}

export async function register(
  username: string,
  password: string,
): Promise<{ message: string }> {
  return postJson<{ message: string }>('/api/register', { username, password })
}

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch('/api/health')
  if (!res.ok) {
    throw new Error(await readError(res))
  }
  return readJson<{ status: string }>(res)
}
