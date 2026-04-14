import type { ReactNode } from 'react'
import type { AgentReport } from '../types/report'

function Empty({ children }: { children: ReactNode }) {
  return <p className="empty-hint">{children}</p>
}

export function ActionsPanel({ report }: { report: AgentReport }) {
  const items = report.actions ?? []
  return (
    <section className="card card--actions">
      <h2 className="card-title">行动清单</h2>
      {items.length === 0 ? (
        <Empty>暂无行动建议</Empty>
      ) : (
        <ol className="actions-list">
          {items.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ol>
      )}
    </section>
  )
}

export function KpiStrip({ report }: { report: AgentReport }) {
  const s = report.sales_review.summary
  return (
    <section className="card">
      <h2 className="card-title">生意概览（销量复盘 P0）</h2>
      <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-label">总日销量</div>
          <div className="kpi-value tabular">{s.total_daily_sales} 件</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">平均退货率</div>
          <div className="kpi-value kpi-value--risk tabular">
            {s.avg_return_rate_pct.toFixed(2)}%
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">当前最热趋势</div>
          <div className="kpi-value tabular" style={{ fontSize: '1rem' }}>
            {s.top_trend}
          </div>
        </div>
      </div>
      {report.sales_review.llm_executive_brief && (
        <div style={{ marginTop: '1rem' }}>
          <h3>LLM 执行摘要</h3>
          <p>{report.sales_review.llm_executive_brief.executive_summary}</p>
          <ul className="actions-list">
            {report.sales_review.llm_executive_brief.action_bullets.map(
              (b, i) => (
                <li key={i}>{b}</li>
              ),
            )}
          </ul>
        </div>
      )}
      {report.sales_review.llm_error && (
        <p className="err" style={{ marginTop: '0.5rem' }}>
          LLM：{report.sales_review.llm_error}
        </p>
      )}
    </section>
  )
}

export function ContextStrip({ report }: { report: AgentReport }) {
  const c = report.context
  return (
    <section className="card">
      <h2 className="card-title">报告上下文</h2>
      <p className="muted">
        日期 <strong>{c.as_of || '—'}</strong> · 种子{' '}
        <span className="tabular">{c.seed}</span> · SKU{' '}
        <span className="tabular">{c.sku_count}</span> · 趋势{' '}
        <span className="tabular">{c.trend_count}</span> · Top{' '}
        <span className="tabular">{c.top_n}</span>
        {c.llm_enabled !== undefined && (
          <>
            {' '}
            · LLM {c.llm_enabled ? '开启' : '关闭'}
          </>
        )}
      </p>
      {c.llm_notice && (
        <p className="muted" style={{ marginTop: '0.35rem' }}>
          {c.llm_notice}
        </p>
      )}
    </section>
  )
}

export function ProductSelectionBlock({ report }: { report: AgentReport }) {
  const ps = report.product_selection
  const pick = ps.trend_picks?.[0]
  return (
    <section className="card card--selection">
      <h2 className="card-title">选品（M2）</h2>
      {!pick ? (
        <Empty>暂无选品输出</Empty>
      ) : (
        <>
          <p>
            <strong>主趋势：</strong>
            {pick.keyword ?? '—'}
          </p>
          <p>
            <strong>映射说明：</strong>
            {pick.merch_mapping?.story ?? '—'}
          </p>
          <p className="muted">
            类目：{(pick.merch_mapping?.suggested_categories ?? []).join('、') ||
              '—'}
          </p>
          <p className="muted">
            色彩：{(pick.merch_mapping?.color_focus ?? []).join('、')} · 材质：{' '}
            {(pick.merch_mapping?.material_focus ?? []).join('、')}
          </p>
          <p>
            <strong>首单区间：</strong>
            <span className="tabular">
              {(pick.moq?.suggested_range_pcs ?? []).join(' – ')}
            </span>{' '}
            件 · <strong>风险：</strong>
            <span className="row-risk" style={{ color: 'var(--color-risk)' }}>
              {pick.moq?.risk_level}
            </span>
          </p>
          {pick.moq?.note && <p className="muted">{pick.moq.note}</p>}
          <h3 style={{ marginTop: '0.75rem' }}>竞品缺口</h3>
          {(pick.competitor_gaps ?? []).length === 0 ? (
            <Empty>无竞品缺口数据</Empty>
          ) : (
            <ul className="actions-list">
              {(pick.competitor_gaps ?? []).slice(0, 5).map((g, i) => (
                <li key={i}>
                  {g.category_key}：竞品上新 {g.competitor_new_skus_30d} vs 我方{' '}
                  {g.ours_new_skus_30d} — {g.gap_note}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}

export function SalesTables({ report }: { report: AgentReport }) {
  const sr = report.sales_review
  return (
    <section className="card">
      <h2 className="card-title">畅销 / 滞销 / 高退货</h2>
      <h3>畅销 SKU</h3>
      <SkuTable rows={sr.top_skus} variant="growth" />
      <h3 style={{ marginTop: '1rem' }}>滞销 SKU</h3>
      <SkuTable rows={sr.lagging_skus} />
      <h3 style={{ marginTop: '1rem' }}>高退货风险 SKU</h3>
      <SkuTable rows={sr.high_return_skus} variant="risk" />
      <h3 style={{ marginTop: '1rem' }}>趋势关注</h3>
      {sr.trend_focus?.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>关键词</th>
                <th>平台</th>
                <th>热度</th>
                <th>增长 %</th>
              </tr>
            </thead>
            <tbody>
              {sr.trend_focus.map((t, i) => (
                <tr key={i}>
                  <td>{t.keyword}</td>
                  <td>{t.platform}</td>
                  <td className="tabular">{t.heat_score}</td>
                  <td className="tabular">{t.growth_rate_pct}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>暂无趋势数据</Empty>
      )}
    </section>
  )
}

function SkuTable({
  rows,
  variant,
}: {
  rows: {
    sku_id: string
    name: string
    daily_sales: number
    stock: number
    return_rate_pct: number
  }[]
  variant?: 'growth' | 'risk'
}) {
  if (!rows?.length) return <Empty>暂无数据</Empty>
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>SKU</th>
            <th>名称</th>
            <th>日销</th>
            <th>库存</th>
            <th>退货率</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.sku_id}
              className={
                variant === 'risk'
                  ? 'row-risk'
                  : variant === 'growth'
                    ? ''
                    : ''
              }
            >
              <td className="tabular">{r.sku_id}</td>
              <td>{r.name}</td>
              <td className="tabular">{r.daily_sales}</td>
              <td className="tabular">{r.stock}</td>
              <td className="tabular">{r.return_rate_pct.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ChannelBlock({ report }: { report: AgentReport }) {
  const ch = report.sales_review.channel_dashboard
  const channels = ch.channels
  if (!channels || !Object.keys(channels).length) {
    return (
      <section className="card card--structure">
        <h2 className="card-title">渠道复盘（M4.1）</h2>
        <Empty>暂无渠道数据</Empty>
      </section>
    )
  }
  const maxShare = Math.max(
    ...Object.values(channels).map((c) => c.share_pct ?? 0),
    1,
  )
  return (
    <section className="card card--structure">
      <h2 className="card-title">渠道复盘（M4.1）</h2>
      <div className="channel-bars">
        {Object.entries(channels).map(([name, payload]) => (
          <div key={name} className="channel-row">
            <span>{name}</span>
            <div className="channel-bar">
              <div
                className="channel-bar-fill"
                style={{
                  width: `${((payload.share_pct ?? 0) / maxShare) * 100}%`,
                }}
              />
            </div>
            <span className="tabular">{payload.share_pct ?? 0}%</span>
          </div>
        ))}
      </div>
      <p className="muted" style={{ marginTop: '0.75rem' }}>
        周预估 {ch.current_week_est_units}，上周 {ch.prior_week_total_units}，周环比{' '}
        <span className="tabular">{ch.week_over_week_pct ?? 0}</span>% · 月预估{' '}
        {ch.current_month_est_units}，上月 {ch.prior_month_total_units}，月环比{' '}
        <span className="tabular">{ch.month_over_month_pct ?? 0}</span>%
      </p>
    </section>
  )
}

export function ReturnSemanticsBlock({ report }: { report: AgentReport }) {
  const rs = report.sales_review.return_semantics
  const tags = rs.top_tags ?? []
  return (
    <section className="card">
      <h2 className="card-title">退货语义（M4.2）</h2>
      {tags.length === 0 ? (
        <Empty>未命中关键词规则</Empty>
      ) : (
        <>
          <div className="tag-list">
            {tags.map(([tag, cnt], i) => (
              <span key={i} className="tag">
                {tag} ×{cnt}
              </span>
            ))}
          </div>
        </>
      )}
    </section>
  )
}

export function InventoryBlock({ report }: { report: AgentReport }) {
  const inv = report.inventory_review
  return (
    <section className="card">
      <h2 className="card-title">库存预警（P1）</h2>
      <h3>低库存</h3>
      {inv.low_stock_alerts?.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>名称</th>
                <th>可售天</th>
                <th>建议补货</th>
              </tr>
            </thead>
            <tbody>
              {inv.low_stock_alerts.map((r) => (
                <tr key={r.sku_id} className="row-urgent">
                  <td className="tabular">{r.sku_id}</td>
                  <td>{r.name}</td>
                  <td className="tabular">{r.coverage_days}</td>
                  <td className="tabular">{r.suggest_replenish_qty}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>暂无低库存预警</Empty>
      )}
      <h3 style={{ marginTop: '1rem' }}>高库存</h3>
      {inv.overstock_alerts?.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>名称</th>
                <th>总覆盖天</th>
                <th>库存</th>
                <th>在途</th>
              </tr>
            </thead>
            <tbody>
              {inv.overstock_alerts.map((r) => (
                <tr key={r.sku_id}>
                  <td className="tabular">{r.sku_id}</td>
                  <td>{r.name}</td>
                  <td className="tabular">{r.total_coverage_days}</td>
                  <td className="tabular">{r.current_stock}</td>
                  <td className="tabular">{r.in_transit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>暂无高库存预警</Empty>
      )}
    </section>
  )
}

export function SlowMovingBlock({ report }: { report: AgentReport }) {
  const rows = report.slow_moving.slow_moving_skus ?? []
  return (
    <section className="card">
      <h2 className="card-title">滞销清理（M3.2）</h2>
      {rows.length === 0 ? (
        <Empty>暂无滞销命中</Empty>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>库龄</th>
                <th>转化</th>
                <th>策略</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.sku_id} className="row-risk">
                  <td className="tabular">{r.sku_id}</td>
                  <td className="tabular">{r.stock_age_days} 天</td>
                  <td className="tabular">
                    {(r.conversion_rate * 100).toFixed(2)}%
                  </td>
                  <td>
                    {r.strategy} — {r.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function ReplenishmentBlock({ report }: { report: AgentReport }) {
  const rows = report.replenishment.replenishment_rows ?? []
  return (
    <section className="card card--structure">
      <h2 className="card-title">补货 EOQ（M3.3）</h2>
      {rows.length === 0 ? (
        <Empty>暂无低库存可计算 EOQ</Empty>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>建议订货</th>
                <th>EOQ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.sku_id}>
                  <td className="tabular">
                    {r.sku_id} {r.name}
                  </td>
                  <td className="tabular">{r.suggested_order_qty}</td>
                  <td className="tabular">{r.eoq?.eoq_units ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function MemoryBlock({ report }: { report: AgentReport }) {
  const m = report.memory_snapshot
  return (
    <section className="card">
      <h2 className="card-title">避雷记忆（M4.3）</h2>
      <p>
        活跃避雷条数：{' '}
        <span className="tabular">{m.active_feedback_count}</span> · 选品命中 SKU
        数：<span className="tabular">{m.product_selection_hits}</span>
      </p>
    </section>
  )
}
