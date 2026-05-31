import { useCallback, useEffect, useState } from 'react'
import type { ExperienceRecord } from '../types/strategy'
import { fetchExperiences, archiveExperience, approveExperience, createExperience } from '../api/experienceClient'

const CONFIDENCE_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

const SOURCE_LABELS: Record<string, string> = {
  auto_draft: '自动观测',
  strategy_feedback: '策略反馈',
  human: '人工录入',
  rule: '规则生成',
}

export function ExperienceLibrary() {
  const [experiences, setExperiences] = useState<ExperienceRecord[]>([])
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [loading, setLoading] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newNarrative, setNewNarrative] = useState('')
  const [newConfidence, setNewConfidence] = useState('medium')
  const [creating, setCreating] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const PAGE_SIZE = 10

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchExperiences(statusFilter === 'all' ? undefined : statusFilter)
      setExperiences(data.experiences || [])
      setCurrentPage(1)
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => { void load() }, [load])

  const handleArchive = async (id: string) => {
    await archiveExperience(id)
    void load()
  }

  const handleApprove = async (id: string) => {
    await approveExperience(id, 'medium')
    void load()
  }

  const handleCreate = async () => {
    if (!newTitle.trim() || !newNarrative.trim()) return
    setCreating(true)
    try {
      await createExperience({ title: newTitle, narrative: newNarrative, confidence: newConfidence })
      setNewTitle('')
      setNewNarrative('')
      setShowCreate(false)
      void load()
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="experience-library">
      <div className="experience-library__header">
        <h2>经验库</h2>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">全部</option>
          <option value="active">生效中</option>
          <option value="draft">待审批</option>
          <option value="archived">已归档</option>
        </select>
        <button className="btn btn-sm btn-feedback" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? '取消' : '录入经验'}
        </button>
      </div>

      {showCreate && (
        <div className="experience-create-form">
          <div className="form-group">
            <label>经验标题</label>
            <input
              type="text"
              placeholder="例如：涤纶+通勤组合退货率高"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>经验描述（归因+建议）</label>
            <textarea
              placeholder="例如：涤纶面料在通勤场景显廉价感，退货率达15%。建议通勤定位避免涤纶，改用天丝或棉混纺。"
              value={newNarrative}
              onChange={(e) => setNewNarrative(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>置信度</label>
            <select value={newConfidence} onChange={(e) => setNewConfidence(e.target.value)}>
              <option value="high">高（确定性强）</option>
              <option value="medium">中</option>
              <option value="low">低（仅供参考）</option>
            </select>
          </div>
          <button className="btn btn-primary" disabled={creating || !newTitle.trim() || !newNarrative.trim()} onClick={() => void handleCreate()}>
            {creating ? '保存中...' : '保存经验'}
          </button>
        </div>
      )}

      {loading && <p className="muted">加载中...</p>}

      <div className="experience-list">
        {experiences.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE).map((exp) => (
          <div key={exp.experience_id} className={`experience-card experience-card--${exp.status}`}>
            <div className="experience-card__header" onClick={() => setExpandedId(expandedId === exp.experience_id ? null : exp.experience_id)}>
              <span className={`badge badge--${exp.status}`}>{exp.status}</span>
              <span className="experience-card__title">{exp.title}</span>
              <span className={`confidence confidence--${exp.confidence}`}>
                置信度: {CONFIDENCE_LABELS[exp.confidence] || exp.confidence}
              </span>
              <span className="experience-card__source">{SOURCE_LABELS[exp.source] || exp.source}</span>
              <span className="experience-card__date">{exp.created_at}</span>
            </div>

            {expandedId === exp.experience_id && (
              <div className="experience-card__detail">
                <p className="experience-card__narrative">{exp.narrative}</p>
                <div className="experience-card__actions">
                  {exp.status === 'draft' && (
                    <button className="btn btn-sm btn-accept" onClick={() => void handleApprove(exp.experience_id)}>审批通过</button>
                  )}
                  {exp.status !== 'archived' && (
                    <button className="btn btn-sm btn-reject" onClick={() => void handleArchive(exp.experience_id)}>归档</button>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {!loading && experiences.length === 0 && (
        <p className="muted">暂无经验记录。策略反馈后会自动生成经验。</p>
      )}

      {experiences.length > PAGE_SIZE && (
        <div className="pagination">
          <button type="button" className="btn btn-sm" disabled={currentPage <= 1} onClick={() => setCurrentPage((p) => p - 1)}>上一页</button>
          <span className="pagination-info">{currentPage} / {Math.ceil(experiences.length / PAGE_SIZE)}</span>
          <button type="button" className="btn btn-sm" disabled={currentPage >= Math.ceil(experiences.length / PAGE_SIZE)} onClick={() => setCurrentPage((p) => p + 1)}>下一页</button>
        </div>
      )}
    </div>
  )
}
