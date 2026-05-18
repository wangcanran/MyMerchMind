import type { AgentReport, ReportParams } from '../types/report'

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
  return u.toString()
}

export async function fetchReport(p: ReportParams): Promise<AgentReport> {
  const q = toSearchParams(p)
  const res = await fetch(`/api/report?${q}`)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<AgentReport>
}

export async function fetchReportMarkdown(p: ReportParams): Promise<string> {
  const q = toSearchParams(p)
  const res = await fetch(`/api/report/markdown?${q}`)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  const data = (await res.json()) as { markdown: string }
  return data.markdown
}
