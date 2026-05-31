import { useCallback, useEffect, useState } from 'react'
import { marked } from 'marked'
import './App.css'
import { fetchReport, fetchReportMarkdown, fetchReportWithProgress } from './api/client'
import type { AgentReport, ReportParams } from './types/report'
import {
  ActionsPanel,
  CategoryManagementBlock,
  ChannelBlock,
  ContextStrip,
  InventoryBlock,
  InventoryManagementBlock,
  KpiStrip,
  MemoryBlock,
  ProductSelectionBlock,
  PricingBlock,
  ReplenishmentBlock,
  ReturnSemanticsBlock,
  SalesTables,
  SlowMovingBlock,
} from './components/ReportSections'
import { Layout } from './components/Layout'
import { LoginPage } from './components/LoginPage'
import { ErpModule } from './components/ErpModule'
import { CompetitorModule } from './components/CompetitorModule'
import { StrategyBoard } from './components/StrategyBoard'
import { ExperienceLibrary } from './components/ExperienceLibrary'
import {
  defaultReportParams,
  loadHistory,
  deleteHistoryEntry,
  saveSessionReportSnapshot,
} from './lib/sessionReportCache'
import type { ReportHistoryEntry } from './lib/sessionReportCache'

const SECTION_CONFIG = [
  { id: 'overview', label: '今日驾驶舱' },
  { id: 'merchandising', label: '上新与价格' },
  { id: 'signals', label: '经营信号' },
  { id: 'execution', label: '库存闭环' },
] as const

type SectionId = (typeof SECTION_CONFIG)[number]['id']
type CollapseState = Record<SectionId, boolean>

const DEFAULT_COLLAPSE_STATE: CollapseState = {
  overview: false,
  merchandising: false,
  signals: false,
  execution: false,
}

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(
    () => sessionStorage.getItem('authenticated') === 'true'
  )
  const [username, setUsername] = useState(
    () => sessionStorage.getItem('username') || ''
  )
  const [params, setParams] = useState<ReportParams>(defaultReportParams)
  const [report, setReport] = useState<AgentReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mdOpen, setMdOpen] = useState(false)
  const [mdText, setMdText] = useState<string | null>(null)
  const [mdLoading, setMdLoading] = useState(false)
  const [activeSection, setActiveSection] = useState<SectionId>('overview')
  const [collapsedSections, setCollapsedSections] =
    useState<CollapseState>(DEFAULT_COLLAPSE_STATE)
  const [page, setPage] = useState<'report' | 'strategy' | 'experience' | 'erp' | 'competitor'>('report')
  const [history, setHistory] = useState<ReportHistoryEntry[]>(loadHistory)


  useEffect(() => {
    if (!loading) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [loading])

  useEffect(() => {
    if (!report) {
      setActiveSection('overview')
      return
    }

    const observers = SECTION_CONFIG
      .map(({ id }) => document.getElementById(id))
      .filter((node): node is HTMLElement => node !== null)

    if (observers.length === 0) {
      return
    }

    const intersectionObserver = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)

        if (visible.length === 0) {
          return
        }

        const nextId = visible[0].target.id as SectionId
        setActiveSection(nextId)
      },
      {
        rootMargin: '-25% 0px -55% 0px',
        threshold: [0.2, 0.45, 0.65],
      },
    )

    observers.forEach((node) => intersectionObserver.observe(node))

    return () => {
      intersectionObserver.disconnect()
    }
  }, [report, collapsedSections])

  const [loadingStep, setLoadingStep] = useState('')
  const [loadingProgress, setLoadingProgress] = useState(0)
  const [justFinished, setJustFinished] = useState(false)

  const runReport = useCallback(async () => {
    setLoading(true)
    setError(null)
    setJustFinished(false)
    setLoadingStep('初始化...')
    setLoadingProgress(0)
    try {
      const data = await fetchReportWithProgress(params, (step, current, total) => {
        setLoadingStep(step)
        setLoadingProgress(Math.round((current / total) * 100))
      })
      setReport(data)
      saveSessionReportSnapshot(params, data)
      setHistory(loadHistory())
      setJustFinished(true)
      setTimeout(() => setJustFinished(false), 8000)
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
      const md = report?.markdown ?? (await fetchReportMarkdown(params))
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
      const md = report?.markdown ?? (await fetchReportMarkdown(params))
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report_${params.seed}.md`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [params, report?.markdown])

  const downloadHtml = useCallback(async () => {
    try {
      const md = report?.markdown ?? (await fetchReportMarkdown(params))
      const body = await marked(md)
      const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MerchMind Report - ${params.as_of || new Date().toISOString().slice(0, 10)}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 2rem; color: #1a2b3c; line-height: 1.7; background: #fafaf8; }
  h1 { font-size: 1.8rem; border-bottom: 2px solid #1c7c72; padding-bottom: 0.5rem; color: #0f2a3a; }
  h2 { font-size: 1.3rem; margin-top: 2rem; color: #1c4a5c; border-left: 4px solid #1c7c72; padding-left: 0.75rem; }
  h3 { font-size: 1.05rem; color: #2a5a6a; }
  table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.88rem; }
  th, td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid #e8e4de; }
  th { background: #f0ece6; font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.03em; }
  tr:hover td { background: rgba(28, 124, 114, 0.04); }
  code { background: #f0ece6; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.85em; }
  ul, ol { padding-left: 1.5rem; }
  li { margin-bottom: 0.3rem; }
  strong { color: #0f2a3a; }
  .footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #e8e4de; font-size: 0.8rem; color: #6b7a8a; }
</style>
</head>
<body>
${body}
<div class="footer">Generated by MerchMind · ${new Date().toLocaleString('zh-CN')}</div>
</body>
</html>`
      const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report_${params.seed}.html`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [params, report?.markdown])

  const renderSidebar = () => (
    <>
      <section className="card card--control">
        <div className="card-heading">
          <div>
            <p className="section-kicker">Control Deck</p>
            <h2 className="card-title">运行参数</h2>
          </div>
          <span className={`status-chip ${loading ? 'status-chip--live' : ''}`}>
            {loading ? '生成中' : report ? '已生成' : '待运行'}
          </span>
        </div>
        <div className="param-grid">
          <div className="param-field">
            <label htmlFor="seed">Seed</label>
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
            <label htmlFor="top_n">Top-N</label>
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
            <label htmlFor="as_of">报告日期</label>
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
            <label htmlFor="tgm">目标毛利率</label>
            <input
              id="tgm"
              type="number"
              step={0.01}
              min={0.05}
              max={100}
              placeholder="0.45 即 45%"
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
          </div>
          <div className="param-field param-field--wide">
            <label htmlFor="req">选品需求（可选）</label>
            <textarea
              id="req"
              placeholder="季节、风格、场景、价位、人群等；也可粘贴 Markdown"
              value={params.selection_requirements ?? ''}
              onChange={(e) =>
                setParams((p) => ({
                  ...p,
                  selection_requirements: e.target.value,
                }))
              }
            />
            <input
              id="req-file"
              type="file"
              accept=".md,.txt,text/markdown,text/plain"
              className="file-input"
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
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => void downloadHtml()}
          >
            下载 HTML
          </button>
        </div>
        {loading && (
          <div className="progress-strip">
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${loadingProgress}%` }} />
            </div>
            <p className="progress-label">{loadingStep}</p>
          </div>
        )}
        {justFinished && (
          <div className="success-strip">报告生成完成</div>
        )}
        {error && <p className="err">{error}</p>}
        {mdOpen && mdText !== null && (
          <div className="md-panel">
            <div className="param-actions">
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

      <section className="card card--nav">
        <div className="card-heading">
          <div>
            <p className="section-kicker">Workspace</p>
            <h2 className="card-title">功能导航</h2>
          </div>
        </div>
        <div className="nav-buttons">
          <button
            type="button"
            className={`nav-btn ${page === 'report' ? 'nav-btn--active' : ''}`}
            onClick={() => setPage('report')}
          >
            运营报告
          </button>
          <button
            type="button"
            className={`nav-btn ${page === 'strategy' ? 'nav-btn--active' : ''}`}
            onClick={() => setPage('strategy')}
          >
            策略追踪
          </button>
          <button
            type="button"
            className={`nav-btn ${page === 'experience' ? 'nav-btn--active' : ''}`}
            onClick={() => setPage('experience')}
          >
            经验库
          </button>
          <button
            type="button"
            className={`nav-btn ${page === 'erp' ? 'nav-btn--active' : ''}`}
            onClick={() => setPage('erp')}
          >
            ERP 数据
          </button>
          <button
            type="button"
            className={`nav-btn ${page === 'competitor' ? 'nav-btn--active' : ''}`}
            onClick={() => setPage('competitor')}
          >
            竞品数据
          </button>
        </div>
      </section>

      {history.length > 0 && (
        <section className="card card--history">
          <div className="card-heading">
            <div>
              <p className="section-kicker">History</p>
              <h2 className="card-title">历史报告</h2>
            </div>
          </div>
          <div className="history-list">
            {history.map((entry) => (
              <div key={entry.id} className="history-item">
                <button
                  type="button"
                  className="history-item-btn"
                  onClick={() => {
                    setReport(entry.report)
                    setParams(entry.params)
                    setPage('report')
                  }}
                >
                  <span className="history-label">{entry.label}</span>
                  <span className="history-time">{new Date(entry.savedAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                </button>
                <button
                  type="button"
                  className="history-delete"
                  onClick={() => { deleteHistoryEntry(entry.id); setHistory(loadHistory()) }}
                  title="删除"
                >
                  x
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

    </>
  )

  if (!isAuthenticated) {
    return (
      <LoginPage
        onLoginSuccess={(nextUsername) => {
          setUsername(nextUsername)
          setIsAuthenticated(true)
          sessionStorage.setItem('authenticated', 'true')
          sessionStorage.setItem('username', nextUsername)
        }}
      />
    )
  }

  const inventoryHealth = report?.inventory_review.inventory_health
  const heroTitle =
    report?.product_selection.strategy_overview?.theme ?? 'MerchMind'
  const heroSubtitle = report
    ? `报告日期：${report.context.as_of || '今日'} · 样本 Top ${report.context.top_n}`
    : ''
  const statusText = loading
    ? '报告生成中'
    : report
      ? `最新报告：${report.context.as_of || '今日'} · Top ${report.context.top_n}`
      : '就绪'
  const workflowSteps = [
    {
      title: '校准输入',
      detail: report
        ? `${report.context.as_of || '今日'} · 样本 Top ${report.context.top_n}`
        : '设定日期、样本范围与库存规则',
    },
    {
      title: '锁定上新',
      detail:
        report?.product_selection.strategy_overview?.hero_category ??
        '先生成报告，识别主推类目与首单节奏',
    },
    {
      title: '校准价格',
      detail:
        report?.pricing.summary?.recommended_campaign_focus ??
        '结合价格护栏与活动主线安排定价',
    },
    {
      title: '安排库存',
      detail: inventoryHealth
        ? `低库存 ${inventoryHealth.low_stock_skus} · 高库存 ${inventoryHealth.overstock_skus}`
        : '将补货、清仓与复盘动作串起来',
    },
  ]

  function jumpToSection(sectionId: SectionId) {
    if (collapsedSections[sectionId]) {
      setCollapsedSections((current) => ({
        ...current,
        [sectionId]: false,
      }))
    }
    setActiveSection(sectionId)
    window.requestAnimationFrame(() => {
      document.getElementById(sectionId)?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      })
    })
  }

  function toggleSection(sectionId: SectionId) {
    setCollapsedSections((current) => ({
      ...current,
      [sectionId]: !current[sectionId],
    }))
  }

  function setAllSections(collapsed: boolean) {
    setCollapsedSections({
      overview: collapsed,
      merchandising: collapsed,
      signals: collapsed,
      execution: collapsed,
    })
  }

  return (
    <Layout
      sidebar={renderSidebar()}
      username={username}
      heroTitle={heroTitle}
      heroSubtitle={heroSubtitle}
      statusText={statusText}
      onLogout={() => {
        setIsAuthenticated(false)
        sessionStorage.removeItem('authenticated')
        sessionStorage.removeItem('username')
      }}
    >
      {page === 'strategy' && (
        <div className="subpage">
          <button type="button" className="btn-back" onClick={() => setPage('report')}>← 返回报告</button>
          <StrategyBoard />
        </div>
      )}
      {page === 'experience' && (
        <div className="subpage">
          <button type="button" className="btn-back" onClick={() => setPage('report')}>← 返回报告</button>
          <ExperienceLibrary />
        </div>
      )}
      {page === 'erp' && (
        <div className="subpage">
          <button type="button" className="btn-back" onClick={() => setPage('report')}>← 返回报告</button>
          <ErpModule />
        </div>
      )}
      {page === 'competitor' && (
        <div className="subpage">
          <button type="button" className="btn-back" onClick={() => setPage('report')}>← 返回报告</button>
          <CompetitorModule />
        </div>
      )}
      {page === 'report' && (
        <>
      {report && (
        <>
      <section className="workflow-strip">
        {workflowSteps.map((step, index) => (
          <article className="workflow-step" key={step.title}>
            <span className="workflow-step-index">0{index + 1}</span>
            <div>
              <h3>{step.title}</h3>
              <p>{step.detail}</p>
            </div>
          </article>
        ))}
      </section>
        <div className="workspace-stack">
          <section className="section-nav-shell">
            <div className="section-nav">
              <div className="section-nav-copy">
                <p className="section-kicker">Navigator</p>
                <h2>快速跳转</h2>
              </div>
              <div className="section-nav-links">
                {SECTION_CONFIG.map((section) => (
                  <button
                    key={section.id}
                    type="button"
                    className={`section-anchor ${
                      activeSection === section.id ? 'section-anchor--active' : ''
                    }`}
                    onClick={() => jumpToSection(section.id)}
                  >
                    {section.label}
                  </button>
                ))}
              </div>
              <div className="section-nav-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-compact"
                  onClick={() => setAllSections(false)}
                >
                  全部展开
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-compact"
                  onClick={() => setAllSections(true)}
                >
                  全部折叠
                </button>
              </div>
            </div>
          </section>

          <section className="workspace-section" id="overview">
            <div className="workspace-header workspace-header--interactive">
              <div>
                <p className="section-kicker">Today First</p>
                <h2>今日驾驶舱</h2>
              </div>
              <p>先看当前行动和经营温度，再决定是否进入选品、定价和库存深挖。</p>
              <button
                type="button"
                className="section-toggle"
                onClick={() => toggleSection('overview')}
                aria-expanded={!collapsedSections.overview}
                aria-controls="overview-content"
              >
                {collapsedSections.overview ? '展开模块' : '折叠模块'}
              </button>
            </div>
            {!collapsedSections.overview && (
              <div
                className="workspace-grid"
                id="overview-content"
              >
                <ActionsPanel report={report} />
                <ContextStrip report={report} />
                <KpiStrip report={report} />
              </div>
            )}
          </section>

          <section className="workspace-section" id="merchandising">
            <div className="workspace-header workspace-header--interactive">
              <div>
                <p className="section-kicker">Merchandising</p>
                <h2>上新与价格决策</h2>
              </div>
              <p>用选品、品类管理和定价三段式把"卖什么"和"怎么卖"连成一条线。</p>
              <button
                type="button"
                className="section-toggle"
                onClick={() => toggleSection('merchandising')}
                aria-expanded={!collapsedSections.merchandising}
                aria-controls="merchandising-content"
              >
                {collapsedSections.merchandising ? '展开模块' : '折叠模块'}
              </button>
            </div>
            {!collapsedSections.merchandising && (
              <div id="merchandising-content" className="workspace-grid">
                <ProductSelectionBlock report={report} />
                <CategoryManagementBlock report={report} />
                <PricingBlock report={report} />
              </div>
            )}
          </section>

          <section className="workspace-section" id="signals">
            <div className="workspace-header workspace-header--interactive">
              <div>
                <p className="section-kicker">Signals</p>
                <h2>经营信号面板</h2>
              </div>
              <p>复盘渠道、退货语义和销售结构，帮助判断本轮选品与定价是否站得住。</p>
              <button
                type="button"
                className="section-toggle"
                onClick={() => toggleSection('signals')}
                aria-expanded={!collapsedSections.signals}
                aria-controls="signals-content"
              >
                {collapsedSections.signals ? '展开模块' : '折叠模块'}
              </button>
            </div>
            {!collapsedSections.signals && (
              <div id="signals-content" className="workspace-grid">
                <ChannelBlock report={report} />
                <ReturnSemanticsBlock report={report} />
                <SalesTables report={report} />
              </div>
            )}
          </section>

          <section className="workspace-section" id="execution">
            <div className="workspace-header workspace-header--interactive">
              <div>
                <p className="section-kicker">Execution</p>
                <h2>库存与执行闭环</h2>
              </div>
              <p>最后一段聚焦补货、清理、库存健康和经验沉淀，确保今天的动作能带来下一轮优化。</p>
              <button
                type="button"
                className="section-toggle"
                onClick={() => toggleSection('execution')}
                aria-expanded={!collapsedSections.execution}
                aria-controls="execution-content"
              >
                {collapsedSections.execution ? '展开模块' : '折叠模块'}
              </button>
            </div>
            {!collapsedSections.execution && (
              <div id="execution-content" className="workspace-grid">
                <InventoryBlock report={report} />
                <InventoryManagementBlock report={report} />
                <SlowMovingBlock report={report} />
                <ReplenishmentBlock report={report} />
                <MemoryBlock report={report} />
              </div>
            )}
          </section>
        </div>
        </>
      )}
      {!report && !loading && (
        <section className="empty-stage">
          <h2>左侧设置参数，点击生成报告</h2>
        </section>
      )}
      </>
      )}
    </Layout>
  )
}

export default App
