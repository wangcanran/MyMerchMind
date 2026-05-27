import type { StrategyRecord, StrategyStats } from '../types/strategy'

const BASE = ''

export async function fetchStrategies(params: {
  month?: string
  status?: string
  module?: string
}): Promise<{ strategies: StrategyRecord[]; total: number }> {
  const qs = new URLSearchParams()
  if (params.month) qs.set('month', params.month)
  if (params.status) qs.set('status', params.status)
  if (params.module) qs.set('module', params.module)
  const res = await fetch(`${BASE}/api/strategies?${qs}`)
  if (!res.ok) throw new Error(`策略列表请求失败: ${res.status}`)
  return res.json()
}

export async function fetchStrategyStats(month?: string): Promise<StrategyStats> {
  const qs = month ? `?month=${month}` : ''
  const res = await fetch(`${BASE}/api/strategies/stats${qs}`)
  if (!res.ok) throw new Error(`策略统计请求失败: ${res.status}`)
  return res.json()
}

export async function acceptStrategy(id: string): Promise<StrategyRecord> {
  const res = await fetch(`${BASE}/api/strategies/${id}/accept`, { method: 'POST' })
  if (!res.ok) throw new Error(`接受策略失败: ${res.status}`)
  const data = await res.json()
  return data.strategy
}

export async function rejectStrategy(id: string): Promise<StrategyRecord> {
  const res = await fetch(`${BASE}/api/strategies/${id}/reject`, { method: 'POST' })
  if (!res.ok) throw new Error(`拒绝策略失败: ${res.status}`)
  const data = await res.json()
  return data.strategy
}

export async function submitFeedback(
  id: string,
  body: { outcome: string; reason: string; kpi_data?: Record<string, number> }
): Promise<{ strategy: StrategyRecord; generated_experience: unknown }> {
  const res = await fetch(`${BASE}/api/strategies/${id}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`提交反馈失败: ${res.status}`)
  return res.json()
}
