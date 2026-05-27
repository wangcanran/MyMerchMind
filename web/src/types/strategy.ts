export interface FeedbackRecord {
  feedback_id: string
  outcome: 'good' | 'average' | 'poor'
  reason: string
  kpi_data: Record<string, number>
  submitted_at: string
}

export interface StrategyRecord {
  strategy_id: string
  run_id: string
  as_of: string
  module: string
  description: string
  status: 'pending' | 'accepted' | 'rejected' | 'awaiting_feedback' | 'feedback_received'
  status_history: Array<{ status: string; at: string }>
  created_at: string
  feedback: FeedbackRecord | null
}

export interface StrategyStats {
  total: number
  accepted: number
  rejected: number
  feedback_received: number
  execution_rate: number
  by_module: Record<string, Record<string, number>>
}

export interface ExperienceRecord {
  experience_id: string
  status: 'draft' | 'active' | 'archived'
  title: string
  narrative: string
  search_keys: Record<string, unknown>
  evidence: Record<string, unknown>
  confidence: 'low' | 'medium' | 'high'
  source: string
  created_at: string
  valid_until: string | null
}
