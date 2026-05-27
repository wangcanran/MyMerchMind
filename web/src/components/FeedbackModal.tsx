import { useState } from 'react'
import type { StrategyRecord } from '../types/strategy'

interface Props {
  strategy: StrategyRecord
  onSubmit: (outcome: string, reason: string, kpiData: Record<string, number>) => Promise<void>
  onClose: () => void
}

export function FeedbackModal({ strategy, onSubmit, onClose }: Props) {
  const [outcome, setOutcome] = useState<string>('')
  const [reason, setReason] = useState('')
  const [actualSales, setActualSales] = useState('')
  const [actualReturnRate, setActualReturnRate] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!outcome) return
    setSubmitting(true)
    const kpiData: Record<string, number> = {}
    if (actualSales) kpiData.actual_sales = Number(actualSales)
    if (actualReturnRate) kpiData.actual_return_rate = Number(actualReturnRate) / 100
    try {
      await onSubmit(outcome, reason, kpiData)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>策略反馈</h3>
        <p className="modal__desc">{strategy.description}</p>

        <div className="form-group">
          <label>执行效果</label>
          <div className="outcome-buttons">
            {(['good', 'average', 'poor'] as const).map((o) => (
              <button
                key={o}
                className={`btn btn-outcome ${outcome === o ? `btn-outcome--${o}--active` : ''}`}
                onClick={() => setOutcome(o)}
              >
                {o === 'good' ? '好' : o === 'average' ? '一般' : '差'}
              </button>
            ))}
          </div>
        </div>

        <div className="form-group">
          <label htmlFor="fb-reason">原因说明</label>
          <textarea
            id="fb-reason"
            placeholder="为什么效果好/差？例如：调价后转化率提升30%"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>

        <div className="form-group">
          <label>实际数据（可选）</label>
          <div className="kpi-inputs">
            <input
              type="number"
              placeholder="实际销量"
              value={actualSales}
              onChange={(e) => setActualSales(e.target.value)}
            />
            <input
              type="number"
              placeholder="实际退货率%"
              step="0.1"
              value={actualReturnRate}
              onChange={(e) => setActualReturnRate(e.target.value)}
            />
          </div>
        </div>

        <div className="modal__actions">
          <button className="btn btn-primary" disabled={!outcome || submitting} onClick={() => void handleSubmit()}>
            {submitting ? '提交中...' : '提交反馈'}
          </button>
          <button className="btn btn-ghost" onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}
