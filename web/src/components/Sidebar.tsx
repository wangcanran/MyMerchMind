interface Props {
  active: string
  onChange: (page: string) => void
}

const NAV_ITEMS = [
  { key: 'report', label: '报告', icon: '📊' },
  { key: 'strategy', label: '策略看板', icon: '📋' },
  { key: 'experience', label: '经验库', icon: '💡' },
  { key: 'erp', label: 'ERP 数据', icon: '🗄' },
  { key: 'price-history', label: '价格历史', icon: '📈' },
  { key: 'competitor', label: '竞品数据', icon: '🏷' },
]

export function Sidebar({ active, onChange }: Props) {
  return (
    <nav className="sidebar">
      <div className="sidebar__brand">ERP Agent</div>
      {NAV_ITEMS.map((item) => (
        <button
          key={item.key}
          className={`sidebar__item ${active === item.key ? 'sidebar__item--active' : ''}`}
          onClick={() => onChange(item.key)}
        >
          <span className="sidebar__icon">{item.icon}</span>
          <span className="sidebar__label">{item.label}</span>
        </button>
      ))}
    </nav>
  )
}
