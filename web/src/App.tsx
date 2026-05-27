import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { fetchReport, fetchReportMarkdown } from './api/client'
import type { AgentReport, ReportParams } from './types/report'
import { ReportDashboard } from './components/ReportDashboard'
import { Sidebar } from './components/Sidebar'
import { StrategyBoard } from './components/StrategyBoard'
import { ExperienceLibrary } from './components/ExperienceLibrary'
import { ErpModule } from './components/ErpModule'
import { CompetitorModule } from './components/CompetitorModule'
import { PriceHistoryModule } from './components/PriceHistoryModule'
import {
  defaultReportParams,
  loadSessionReportSnapshot,
  saveSessionReportSnapshot,
} from './lib/sessionReportCache'

function App() {
  const [page, setPage] = useState('report')
  const [params, setParams] = useState<ReportParams>(defaultReportParams)
  const [report, setReport] = useState<AgentReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mdOpen, setMdOpen] = useState(false)
  const [mdText, setMdText] = useState<string | null>(null)
  const [mdLoading, setMdLoading] = useState(false)
  const [restoredFromSession, setRestoredFromSession] = useState(false)

  useEffect(() => {
    const snap = loadSessionReportSnapshot()
    if (!snap) return
    setReport(snap.report)
    setParams(snap.params)
    setRestoredFromSession(true)
  }, [])

  const runReport = useCallback(async () => {
    setLoading(true)
    setError(null)
    setRestoredFromSession(false)
    try {
      const data = await fetchReport(params)
      setReport(data)
      saveSessionReportSnapshot(params, data)
    } catch (e) {
      setReport(null)
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [params])

  const loadMarkdown = useCallback(async () => {
    setMdLoading(true)
    setError(null)
    try {
      const md =
        report?.markdown ??
        (await fetchReportMarkdown(params))
      setMdText(md)
      setMdOpen(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setMdLoading(false)
    }
  }, [params, report?.markdown])

  const downloadMarkdown = useCallback(async () => {
    try {
      const md =
        report?.markdown ??
        (await fetchReportMarkdown(params))
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `demo_report_${params.seed}.md`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [params, report?.markdown])

  return (
    <div className="app-layout">
      <Sidebar active={page} onChange={setPage} />
      <main className="app-main">
        {page === 'strategy' && <StrategyBoard />}
        {page === 'experience' && <ExperienceLibrary />}
        {page === 'erp' && <ErpModule />}
        {page === 'price-history' && <PriceHistoryModule />}
        {page === 'competitor' && <CompetitorModule />}
        {page === 'report' && (
          <>
            <header className="app-header">
        <div className="app-header__top">
          <h1 className="app-title">电商运营 Agent 看板</h1>
          <span className="app-live" title="与本地编排 API 联动">
            <span className="app-live__dot" aria-hidden />
            编排就绪
          </span>
        </div>
        <p className="app-sub">
          与 CLI 同一套编排；选品需求可写自然语言 / Markdown（或上传文件），非空时走「需求理解 →
          图谱选品」。仅数字参数时仍可用 GET 兼容旧请求。
        </p>
      </header>

      <section className="card card--params" style={{ marginBottom: '1rem' }}>
        <h2 className="card-title">运行参数</h2>
        <div className="param-grid">
          <div className="param-field">
            <label htmlFor="seed">seed</label>
            <input
              id="seed"
              type="number"
              value={params.seed}
              onChange={(e) =>
                setParams((p) => ({ ...p, seed: Number(e.target.value) }))
              }
            />
          </div>
          <div className="param-field">
            <label htmlFor="top_n">top-n</label>
            <input
              id="top_n"
              type="number"
              min={1}
              max={50}
              value={params.top_n}
              onChange={(e) =>
                setParams((p) => ({ ...p, top_n: Number(e.target.value) }))
              }
            />
          </div>
          <div className="param-field">
            <label htmlFor="as_of">as-of（空=今天）</label>
            <input
              id="as_of"
              type="date"
              value={params.as_of}
              onChange={(e) =>
                setParams((p) => ({ ...p, as_of: e.target.value }))
              }
            />
          </div>
          <div className="param-field">
            <label htmlFor="cyc">补货周期（天）</label>
            <input
              id="cyc"
              type="number"
              min={1}
              value={params.replenishment_cycle}
              onChange={(e) =>
                setParams((p) => ({
                  ...p,
                  replenishment_cycle: Number(e.target.value),
                }))
              }
            />
          </div>
          <div className="param-field">
            <label htmlFor="over">高库存阈值（天）</label>
            <input
              id="over"
              type="number"
              min={1}
              value={params.overstock_days}
              onChange={(e) =>
                setParams((p) => ({
                  ...p,
                  overstock_days: Number(e.target.value),
                }))
              }
            />
          </div>
          <div className="param-field">
            <label htmlFor="tgm">企划目标毛利率（可选）</label>
            <input
              id="tgm"
              type="number"
              step={0.01}
              min={0.05}
              max={100}
              placeholder="默认 0.45（45%）"
              value={
                typeof params.target_gross_margin === 'number' &&
                Number.isFinite(params.target_gross_margin)
                  ? params.target_gross_margin
                  : ''
              }
              onChange={(e) => {
                const raw = e.target.value.trim()
                if (raw === '') {
                  setParams((p) => {
                    const { target_gross_margin: _omit, ...rest } = p
                    return rest
                  })
                  return
                }
                const n = Number(raw)
                if (!Number.isFinite(n)) return
                setParams((p) => ({ ...p, target_gross_margin: n }))
              }}
            />
            <p className="muted" style={{ marginTop: '0.25rem', fontSize: '0.75rem' }}>
              用于新品企划 market_intel 的「示意成本上限」：填小数如 0.4，或填 40 表示 40%；空则后端默认
              45%。
            </p>
          </div>
          <div className="param-field" style={{ gridColumn: 'span 2' }}>
            <label htmlFor="fb">feedback-memory（可选绝对路径）</label>
            <input
              id="fb"
              type="text"
              placeholder="默认包内 JSON"
              value={params.feedback_memory}
              onChange={(e) =>
                setParams((p) => ({ ...p, feedback_memory: e.target.value }))
              }
            />
          </div>
          <div className="param-field param-field--wide">
            <label htmlFor="req">选品需求（自然语言或 Markdown，可选）</label>
            <textarea
              id="req"
              placeholder="直接写需求，例如季节、风格、场景、价位、人群等；也可粘贴整篇 Markdown。"
              value={params.selection_requirements ?? ''}
              onChange={(e) =>
                setParams((p) => ({
                  ...p,
                  selection_requirements: e.target.value,
                }))
              }
            />
            <p className="muted" style={{ marginTop: '0.35rem', fontSize: '0.8rem' }}>
              有内容时会调用 LLM 先做需求理解，再跑图谱选品。下方可上传 .md / .txt 填入此处。
            </p>
            <label
              htmlFor="req-file"
              style={{ display: 'block', marginTop: '0.5rem', fontSize: '0.8rem' }}
            >
              上传需求文件
            </label>
            <input
              id="req-file"
              type="file"
              accept=".md,.txt,text/markdown,text/plain"
              style={{ marginTop: '0.25rem', fontSize: '0.85rem' }}
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (!f) return
                const reader = new FileReader()
                reader.onload = () => {
                  setParams((p) => ({
                    ...p,
                    selection_requirements: String(reader.result ?? ''),
                  }))
                }
                reader.readAsText(f, 'UTF-8')
                e.target.value = ''
              }}
            />
          </div>
        </div>
        <div className="param-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={loading}
            onClick={() => void runReport()}
          >
            {loading ? '生成中…' : '生成报告'}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={mdLoading}
            title="若已点「生成报告」，则与页面为同一趟编排；否则会再跑一遍编排（LLM 结果可能不同）"
            onClick={() => void loadMarkdown()}
          >
            {mdLoading ? '加载…' : '预览 Markdown'}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            title="若已点「生成报告」，则与页面为同一趟编排；否则会再跑一遍编排（LLM 结果可能不同）"
            onClick={() => void downloadMarkdown()}
          >
            下载 .md
          </button>
        </div>
        {error && <p className="err">{error}</p>}
        {restoredFromSession && (
          <p className="muted" style={{ marginTop: '0.5rem', fontSize: '0.82rem' }}>
            已从本标签页的浏览器缓存恢复上一份成功生成的报告与参数；关闭标签或清除站点数据后会丢失。
          </p>
        )}
        {mdOpen && mdText !== null && (
          <div>
            <div className="param-actions" style={{ marginTop: '0.75rem' }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setMdOpen(false)}
              >
                关闭预览
              </button>
            </div>
            <pre className="md-preview">{mdText}</pre>
          </div>
        )}
      </section>

      {report && <ReportDashboard report={report} />}

      {!report && !loading && (
        <p className="muted">点击「生成报告」加载看板；填写选品需求则走需求理解 + 图谱选品。</p>
      )}
          </>
        )}
      </main>
    </div>
  )
}

export default App
