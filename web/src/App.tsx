import { useCallback, useState } from 'react'
import './App.css'
import { fetchReport, fetchReportMarkdown } from './api/client'
import type { AgentReport, ReportParams } from './types/report'
import {
  ActionsPanel,
  ChannelBlock,
  ContextStrip,
  InventoryBlock,
  InventoryManagementBlock,
  KpiStrip,
  MemoryBlock,
  ProductSelectionBlock,
  ReplenishmentBlock,
  ReturnSemanticsBlock,
  SalesTables,
  SlowMovingBlock,
} from './components/ReportSections'

const defaultParams = (): ReportParams => ({
  seed: 42,
  top_n: 5,
  as_of: '',
  replenishment_cycle: 7,
  overstock_days: 45,
  feedback_memory: '',
})

function App() {
  const [params, setParams] = useState<ReportParams>(defaultParams)
  const [report, setReport] = useState<AgentReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mdOpen, setMdOpen] = useState(false)
  const [mdText, setMdText] = useState<string | null>(null)
  const [mdLoading, setMdLoading] = useState(false)

  const runReport = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchReport(params)
      setReport(data)
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
      const md = await fetchReportMarkdown(params)
      setMdText(md)
      setMdOpen(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setMdLoading(false)
    }
  }, [params])

  const downloadMarkdown = useCallback(async () => {
    try {
      const md = await fetchReportMarkdown(params)
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
  }, [params])

  return (
    <>
      <header className="app-header">
        <h1 className="app-title">电商运营 Agent 看板</h1>
        <p className="app-sub">
          与 CLI 同一套编排输出；参数与{' '}
          <code>python -m ecommerce_agent.main</code> 对齐。
        </p>
      </header>

      <section className="card" style={{ marginBottom: '1rem' }}>
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
            onClick={() => void loadMarkdown()}
          >
            {mdLoading ? '加载…' : '预览 Markdown'}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => void downloadMarkdown()}
          >
            下载 .md
          </button>
        </div>
        {error && <p className="err">{error}</p>}
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

      {report && (
        <>
          <ActionsPanel report={report} />
          <ContextStrip report={report} />
          <KpiStrip report={report} />
          <ProductSelectionBlock report={report} />
          <ChannelBlock report={report} />
          <ReturnSemanticsBlock report={report} />
          <SalesTables report={report} />
          <InventoryBlock report={report} />
          <InventoryManagementBlock report={report} />
          <SlowMovingBlock report={report} />
          <ReplenishmentBlock report={report} />
          <MemoryBlock report={report} />
        </>
      )}

      {!report && !loading && (
        <p className="muted">点击「生成报告」加载 JSON 看板。</p>
      )}
    </>
  )
}

export default App
