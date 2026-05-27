import { useCallback, useEffect, useState } from 'react'
import type { StrategyRecord, StrategyStats } from '../types/strategy'
import { fetchStrategies, fetchStrategyStats, acceptStrategy, rejectStrategy, submitFeedback } from '../api/strategyClient'
import { FeedbackModal } from './FeedbackModal'

const MODULE_LABELS: Record<string, string> = {
  selection: '选品',
  pricing: '定价',
  inventory: '库存',
  replenishment: '补货',
  slow_moving: '滞销',
  category: '品类',
  other: '其他',
}

const STATUS_LABELS: Record<string, string> = {
  pending: '待决策',
  accepted: '已接受',
  rejected: '已拒绝',
  awaiting_feedback: '待反馈',
  feedback_received: '已反馈',
}

export function StrategyBoard() {
  const [strategies, setStrategies] = useState<StrategyRecord[]>([])
  const [stats, setStats] = useState<StrategyStats | null>(null)
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [loading, setLoading] = useState(false)
  const [feedbackTarget, setFeedbackTarget] = useState<StrategyRecord | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [sData, stData] = await Promise.all([
        fetchStrategies({ month }),
        fetchStrategyStats(month),
      ])
      setStrategies(sData.strategies)
      setStats(stData)
    } finally {
      setLoading(false)
    }
  }, [month])

  useEffect(() => { void load() }, [load])

  const handleAccept = async (id: string) => {
    await acceptStrategy(id)
    void load()
  }

  const handleReject = async (id: string) => {
    await rejectStrategy(id)
    void load()
  }

  const handleFeedbackSubmit = async (outcome: string, reason: string, kpiData: Record<string, number>) => {
    if (!feedbackTarget) return
    await submitFeedback(feedbackTarget.strategy_id, { outcome, reason, kpi_data: kpiData })
    setFeedbackTarget(null)
    void load()
  }

  // Group by module
  const grouped = strategies.reduce<Record<string, StrategyRecord[]>>((acc, s) => {
    const mod = s.module || 'other'
    ;(acc[mod] ??= []).push(s)
    return acc
  }, {})

  return (
    <div className="strategy-board">
      <div className="strategy-board__header">
        <h2>策略看板</h2>
        <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
      </div>

      {stats && (
        <div className="strategy-stats">
          <div className="stat-card"><span className="stat-num">{stats.total}</span><span className="stat-label">总计</span></div>
          <div className="stat-card"><span className="stat-num">{stats.accepted}</span><span className="stat-label">已接受</span></div>
          <div className="stat-card"><span className="stat-num">{stats.feedback_received}</span><span className="stat-label">已反馈</span></div>
          <div className="stat-card"><span className="stat-num">{Math.round(stats.execution_rate * 100)}%</span><span className="stat-label">执行率</span></div>
        </div>
      )}

      {loading && <p className="muted">加载中...</p>}

      {Object.entries(grouped).map(([mod, items]) => (
        <details key={mod} className="strategy-group" open>
          <summary className="strategy-group__title">
            {MODULE_LABELS[mod] || mod} ({items.length})
          </summary>
          <div className="strategy-group__list">
            {items.map((s) => (
              <div key={s.strategy_id} className={`strategy-card strategy-card--${s.status}`}>
                <div className="strategy-card__desc">{s.description}</div>
                <div className="strategy-card__meta">
                  <span className={`badge badge--${s.status}`}>{STATUS_LABELS[s.status] || s.status}</span>
                  <span className="strategy-card__date">{s.as_of}</span>
                </div>
                <div className="strategy-card__actions">
                  {s.status === 'pending' && (
                    <>
                      <button className="btn btn-sm btn-accept" onClick={() => void handleAccept(s.strategy_id)}>接受</button>
                      <button className="btn btn-sm btn-reject" onClick={() => void handleReject(s.strategy_id)}>忽略</button>
                    </>
                  )}
                  {(s.status === 'accepted' || s.status === 'awaiting_feedback') && (
                    <button className="btn btn-sm btn-feedback" onClick={() => setFeedbackTarget(s)}>反馈效果</button>
                  )}
                  {s.status === 'feedback_received' && s.feedback && (
                    <span className={`feedback-badge feedback-badge--${s.feedback.outcome}`}>
                      {s.feedback.outcome === 'good' ? '效果好' : s.feedback.outcome === 'poor' ? '效果差' : '一般'}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </details>
      ))}

      {!loading && strategies.length === 0 && (
        <p className="muted">本月暂无策略记录。生成报告后策略会自动入库。</p>
      )}

      {feedbackTarget && (
        <FeedbackModal
          strategy={feedbackTarget}
          onSubmit={handleFeedbackSubmit}
          onClose={() => setFeedbackTarget(null)}
        />
      )}
    </div>
  )
}
