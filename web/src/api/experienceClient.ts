import type { ExperienceRecord } from '../types/strategy'

const BASE = ''

export async function fetchExperiences(status?: string): Promise<{ experiences: ExperienceRecord[] }> {
  const qs = status ? `?status=${status}` : ''
  const res = await fetch(`${BASE}/api/experiences${qs}`)
  if (!res.ok) throw new Error(`经验列表请求失败: ${res.status}`)
  return res.json()
}

export async function createExperience(body: {
  title: string
  narrative: string
  search_keys?: Record<string, unknown>
  confidence?: string
}): Promise<ExperienceRecord> {
  const res = await fetch(`${BASE}/api/experiences`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: body.title,
      narrative: body.narrative,
      search_keys: body.search_keys || {},
      confidence: body.confidence || 'medium',
    }),
  })
  if (!res.ok) throw new Error(`创建经验失败: ${res.status}`)
  const data = await res.json()
  return data.experience
}

export async function archiveExperience(id: string): Promise<void> {
  const res = await fetch(`${BASE}/api/experiences/${id}/archive`, { method: 'POST' })
  if (!res.ok) throw new Error(`归档失败: ${res.status}`)
}

export async function approveExperience(id: string, confidence: string = 'medium'): Promise<void> {
  const res = await fetch(`${BASE}/api/experiences/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confidence }),
  })
  if (!res.ok) throw new Error(`审批失败: ${res.status}`)
}
