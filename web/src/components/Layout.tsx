import type { ReactNode } from 'react'
import './Layout.css'

interface LayoutProps {
  sidebar: ReactNode
  children: ReactNode
  username: string
  heroTitle: string
  heroSubtitle: string
  statusText: string
  onLogout: () => void
}

export function Layout({
  sidebar,
  children,
  username,
  heroTitle,
  heroSubtitle,
  statusText,
  onLogout,
}: LayoutProps) {
  return (
    <div className="app-shell">
      <aside className="app-shell-sidebar">
        <section className="brand-panel">
          <p className="brand-kicker">MerchMind</p>
          <h1 className="brand-title">智能商品决策平台</h1>
          <p className="brand-copy">
            多源数据洞察 · 趋势预判 · 智能定价 · 经验沉淀
          </p>
          <div className="brand-status">{statusText}</div>
        </section>
        <div className="sidebar-stack">{sidebar}</div>
      </aside>

      <div className="app-shell-content">
        <header className="masthead">
          <div className="masthead-copy">
            <h2>{heroTitle}</h2>
            {heroSubtitle && <p>{heroSubtitle}</p>}
          </div>
          <div className="masthead-user">
            <span>{username}</span>
            <button type="button" onClick={onLogout} className="btn-logout">
              退出
            </button>
          </div>
        </header>

        <main className="app-shell-main">{children}</main>
      </div>
    </div>
  )
}
