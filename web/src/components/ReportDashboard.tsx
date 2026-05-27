import { useEffect, useState } from 'react'
import type { AgentReport } from '../types/report'
import {
  ActionsPanel,
  CategoryManagementBlock,
  ChannelBlock,
  ContextStrip,
  InventoryBlock,
  InventoryManagementBlock,
  KpiStrip,
  MemoryBlock,
  NewProductPlanningBlock,
  PricingBlock,
  ProductSelectionBlock,
  ReplenishmentBlock,
  ReturnSemanticsBlock,
  SalesTables,
  SlowMovingBlock,
} from './ReportSections'

const SECTIONS = [
  { id: 'actions', label: '行动清单' },
  { id: 'context', label: '报告上下文' },
  { id: 'kpi', label: '生意概览（P0）' },
  { id: 'selection', label: '选品（M2）' },
  { id: 'category', label: '品类管理（M3）' },
  { id: 'planning', label: '新品企划' },
  { id: 'pricing', label: '定价（M3.1）' },
  { id: 'channel', label: '渠道复盘（M4.1）' },
  { id: 'returns', label: '退货语义（M4.2）' },
  { id: 'sales', label: '畅销 / 滞销 / 高退货' },
  { id: 'inventory', label: '库存预警（P1）' },
  { id: 'inv_mgmt', label: '库存总控' },
  { id: 'slow', label: '滞销清理（M3.2）' },
  { id: 'replenishment', label: '补货 EOQ（M3.3）' },
  { id: 'memory', label: '避雷记忆（M4.3）' },
] as const

type SectionId = (typeof SECTIONS)[number]['id']

export function ReportDashboard({ report }: { report: AgentReport }) {
  const [active, setActive] = useState<SectionId>(SECTIONS[0].id)

  useEffect(() => {
    setActive(SECTIONS[0].id)
  }, [report])

  const panel = (() => {
    switch (active) {
      case 'actions':
        return <ActionsPanel report={report} />
      case 'context':
        return <ContextStrip report={report} />
      case 'kpi':
        return <KpiStrip report={report} />
      case 'selection':
        return <ProductSelectionBlock report={report} />
      case 'planning':
        return <NewProductPlanningBlock report={report} />
      case 'category':
        return <CategoryManagementBlock report={report} />
      case 'pricing':
        return <PricingBlock report={report} />
      case 'channel':
        return <ChannelBlock report={report} />
      case 'returns':
        return <ReturnSemanticsBlock report={report} />
      case 'sales':
        return <SalesTables report={report} />
      case 'inventory':
        return <InventoryBlock report={report} />
      case 'inv_mgmt':
        return <InventoryManagementBlock report={report} />
      case 'slow':
        return <SlowMovingBlock report={report} />
      case 'replenishment':
        return <ReplenishmentBlock report={report} />
      case 'memory':
        return <MemoryBlock report={report} />
      default:
        return <ActionsPanel report={report} />
    }
  })()

  return (
    <div className="report-dashboard">
      <nav className="report-nav" aria-label="报告分块导航">
        <p className="report-nav-hint muted">点选一项，仅展开该块（减少一屏信息）。</p>
        <ul className="report-nav-list" role="tablist">
          {SECTIONS.map((s) => {
            const isActive = active === s.id
            return (
              <li key={s.id} role="presentation">
                <button
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  id={`report-tab-${s.id}`}
                  className={`report-nav-item${isActive ? ' report-nav-item--active' : ''}`}
                  onClick={() => setActive(s.id)}
                >
                  {s.label}
                </button>
              </li>
            )
          })}
        </ul>
      </nav>
      <div
        className="report-panel"
        role="tabpanel"
        aria-labelledby={`report-tab-${active}`}
      >
        {panel}
      </div>
    </div>
  )
}
