import type { ReactNode } from 'react'
import type { AgentReport } from '../types/report'

const PRIORITY_LABELS: Record<string, string> = {
  critical: '严重',
  high: '高',
  medium: '中',
  low: '低',
}

const COVERAGE_BAND_LABELS: Record<string, string> = {
  critical_shortage: '严重缺货',
  replenishment_watch: '补货观察',
  healthy: '健康',
  overstock: '高库存',
  deadstock_like: '近死库存',
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="empty-hint">{children}</p>
}

function PriorityPill({ priority }: { priority?: string }) {
  const level = String(priority || 'medium').toLowerCase()
  return (
    <span className={`priority-pill priority-pill--${level}`}>
      {PRIORITY_LABELS[level] ?? priority ?? '中'}
    </span>
  )
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
  return (
    <section className="card card--selection">
      <h2 className="card-title">选品（M2）</h2>
      {ps.skipped ? (
        <Empty>暂无选品输出</Empty>
      ) : (
        <>
          <p>
            <strong>条件：</strong>
            <span className="muted">
              {ps.criteria ? JSON.stringify(ps.criteria) : '—'}
            </span>
          </p>
          <p className="muted">
            建议品类（Top）：{(ps.suggested_categories ?? []).join('、') || '—'}
          </p>
          {ps.recommendation &&
            typeof ps.recommendation.cross_dimension_summary === 'string' && (
              <p>
                <strong>结论摘要：</strong>
                {String(ps.recommendation.cross_dimension_summary).slice(0, 160)}
              </p>
            )}
          {typeof ps.recommendation?.confidence_score === 'number' && (
            <p className="muted">
              置信度：<span className="tabular">{ps.recommendation.confidence_score}</span> · 数据源：
              {ps.data_source ?? '—'}
            </p>
          )}
          {ps.error && <p className="err">选品：{ps.error}</p>}
          {!ps.error && ps.llm_error && <p className="err">LLM：{ps.llm_error}</p>}
        </>
      )}
    </section>
  )
}

export function CategoryManagementBlock({ report }: { report: AgentReport }) {
  const cm = report.category_management
  const summary = cm.category_summary
  const candidates = cm.decisions?.evaluate_new?.candidates ?? []
  const card = cm.llm_notes?.card_notes
  const checklist = cm.llm_notes?.execution_checklist ?? []
  const scenarios = cm.strategy_scenarios ?? []

  return (
    <section className="card card--structure">
      <h2 className="card-title">品类管理（M3）</h2>
      {cm.skipped ? (
        <Empty>暂无品类管理输出</Empty>
      ) : (
        <>
          {summary && (
            <p className="muted">
              品类数 <span className="tabular">{summary.category_count ?? 0}</span> · SKU 总数{' '}
              <span className="tabular">{summary.sku_total ?? 0}</span> · Top 品类{' '}
              <span className="tabular">{summary.top_category_by_sales ?? '—'}</span>
            </p>
          )}

          <h3 style={{ marginTop: '0.75rem' }}>新品评估</h3>
          {candidates.length === 0 ? (
            <Empty>暂无新品评估输出</Empty>
          ) : (
            <ul className="actions-list">
              {candidates.slice(0, 6).map((r, i) => (
                <li key={i}>
                  {r.category ?? '—'}：{r.decision ?? '—'}（{r.reason ?? '—'}）
                </li>
              ))}
            </ul>
          )}

          {card && (
            <>
              <h3 style={{ marginTop: '0.75rem' }}>决策卡（LLM 提示）</h3>
              <ul className="actions-list">
                {card.audit_existing && <li>盘点现有：{card.audit_existing}</li>}
                {card.retire && <li>淘汰清退：{card.retire}</li>}
                {card.evaluate_new && <li>评估新品：{card.evaluate_new}</li>}
              </ul>
            </>
          )}

          {checklist.length > 0 && (
            <>
              <h3 style={{ marginTop: '0.75rem' }}>执行清单</h3>
              <ol className="actions-list">
                {checklist.slice(0, 8).map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ol>
            </>
          )}

          {scenarios.length > 0 && (
            <>
              <h3 style={{ marginTop: '0.75rem' }}>受约束策略方案（LLM）</h3>
              <ul className="actions-list">
                {scenarios.slice(0, 3).map((s, i) => (
                  <li key={i}>
                    <strong>{s.title ?? `方案${i + 1}`}</strong>：{s.summary ?? '—'}
                  </li>
                ))}
              </ul>
            </>
          )}

          {cm.llm_error && <p className="err">LLM：{cm.llm_error}</p>}
        </>
      )}
    </section>
  )
}

export function PricingBlock({ report }: { report: AgentReport }) {
  const p = report.pricing
  const rows = p.pricing_rows ?? []
  const checklist = p.execution_checklist ?? []
  return (
    <section className="card">
      <h2 className="card-title">定价（M3.1）</h2>
      {p.skipped ? (
        <Empty>暂无定价输出</Empty>
      ) : (
        <>
          <h3>定价建议</h3>
          {rows.length === 0 ? (
            <Empty>暂无定价输出</Empty>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>品类</th>
                    <th>决策</th>
                    <th>竞品价带</th>
                    <th>建议标价</th>
                    <th>模式</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 8).map((r, i) => (
                    <tr key={`${r.category ?? 'cat'}-${i}`}>
                      <td>{r.category ?? '—'}</td>
                      <td>{r.decision ?? '—'}</td>
                      <td className="tabular">{r.competitor_price_band ?? '—'}</td>
                      <td className="tabular">
                        {typeof r.suggested_price === 'number' ? `¥${r.suggested_price}` : '—'}
                      </td>
                      <td className="tabular">{r.pricing_mode ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {checklist.length > 0 && (
            <>
              <h3 style={{ marginTop: '0.75rem' }}>执行清单</h3>
              <ol className="actions-list">
                {checklist.slice(0, 6).map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ol>
            </>
          )}

          {p.llm_error && <p className="err">LLM：{p.llm_error}</p>}
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
  const health = inv.inventory_health
  const llmNotes = inv.llm_notes
  return (
    <section className="card">
      <h2 className="card-title">库存预警（P1）</h2>
      {health && (
        <div className="kpi-row" style={{ marginBottom: '0.9rem' }}>
          <div className="kpi">
            <div className="kpi-label">低库存 SKU</div>
            <div className="kpi-value tabular">{health.low_stock_skus}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">高库存 SKU</div>
            <div className="kpi-value kpi-value--risk tabular">
              {health.overstock_skus}
            </div>
          </div>
          <div className="kpi">
            <div className="kpi-label">平均总覆盖天数</div>
            <div className="kpi-value tabular">
              {health.avg_total_coverage_days?.toFixed(1) ?? '—'} 天
            </div>
          </div>
        </div>
      )}
      <h3>低库存</h3>
      {inv.low_stock_alerts?.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>名称</th>
                <th>可售 / 总覆盖</th>
                <th>优先级</th>
                <th>主渠道</th>
                <th>建议补货</th>
              </tr>
            </thead>
            <tbody>
              {inv.low_stock_alerts.map((r) => (
                <tr key={r.sku_id} className="row-urgent">
                  <td className="tabular">{r.sku_id}</td>
                  <td>{r.name}</td>
                  <td className="tabular">
                    {r.coverage_days} / {r.total_coverage_days ?? '—'} 天
                  </td>
                  <td>
                    <PriorityPill priority={r.urgency_level} />
                  </td>
                  <td>
                    {r.channel_focus ?? '—'}
                    {r.channel_focus_share_pct !== undefined && (
                      <span className="muted">
                        {' '}
                        {r.channel_focus_share_pct.toFixed(1)}%
                      </span>
                    )}
                  </td>
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
                <th>压力分</th>
                <th>建议动作</th>
              </tr>
            </thead>
            <tbody>
              {inv.overstock_alerts.map((r) => (
                <tr key={r.sku_id}>
                  <td className="tabular">{r.sku_id}</td>
                  <td>{r.name}</td>
                  <td className="tabular">{r.total_coverage_days}</td>
                  <td className="tabular">{r.pressure_score ?? '—'}</td>
                  <td>{r.recommended_action ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>暂无高库存预警</Empty>
      )}
      {inv.recommendations?.length ? (
        <>
          <h3 style={{ marginTop: '1rem' }}>规则建议</h3>
          <ul className="actions-list">
            {inv.recommendations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
      {llmNotes && (
        <div className="llm-note-card">
          <h3>LLM 协同提示</h3>
          {llmNotes.priorities_note && <p>{llmNotes.priorities_note}</p>}
          {llmNotes.replenishment_focus && (
            <p className="muted">补货焦点：{llmNotes.replenishment_focus}</p>
          )}
          {llmNotes.clearance_focus && (
            <p className="muted">去化焦点：{llmNotes.clearance_focus}</p>
          )}
          {llmNotes.coordination_checklist?.length ? (
            <ul className="actions-list">
              {llmNotes.coordination_checklist.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
      {inv.llm_error && (
        <p className="err" style={{ marginTop: '0.75rem' }}>
          LLM：{inv.llm_error}
        </p>
      )}
    </section>
  )
}

export function InventoryManagementBlock({ report }: { report: AgentReport }) {
  const mgmt = report.inventory_management
  const health = mgmt.inventory_health
  const ownerRows = Object.entries(mgmt.owner_lane_summary ?? {}).sort(
    (a, b) => b[1] - a[1],
  )
  const board = mgmt.action_board ?? []
  const digestRows = (mgmt.llm_digest ?? '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)

  return (
    <section className="card card--structure">
      <h2 className="card-title">库存总控（Inventory Management）</h2>
      {health ? (
        <>
          <div className="kpi-row">
            <div className="kpi">
              <div className="kpi-label">库存位置总量</div>
              <div className="kpi-value tabular">
                {health.stock_position_units}
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-label">严重缺货</div>
              <div className="kpi-value tabular">
                {health.critical_low_stock_skus}
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-label">高库存</div>
              <div className="kpi-value kpi-value--risk tabular">
                {health.overstock_skus}
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-label">健康 SKU</div>
              <div className="kpi-value tabular">{health.healthy_skus}</div>
            </div>
          </div>
          {health.coverage_bands && (
            <div className="tag-list" style={{ marginTop: '0.85rem' }}>
              {Object.entries(health.coverage_bands).map(([key, count]) => (
                <span key={key} className="tag tag--muted">
                  {COVERAGE_BAND_LABELS[key] ?? key} ×{count}
                </span>
              ))}
            </div>
          )}
        </>
      ) : (
        <Empty>暂无库存总控摘要</Empty>
      )}
      {ownerRows.length ? (
        <div className="owner-lane-grid">
          {ownerRows.map(([owner, count]) => (
            <div key={owner} className="owner-lane-card">
              <div className="kpi-label">{owner} 待办</div>
              <div className="owner-lane-value tabular">{count}</div>
            </div>
          ))}
        </div>
      ) : null}
      <h3 style={{ marginTop: '1rem' }}>库存动作板</h3>
      {board.length === 0 ? (
        <Empty>暂无跨团队动作</Empty>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>优先级</th>
                <th>Owner</th>
                <th>SKU</th>
                <th>动作</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              {board.map((row, index) => (
                <tr key={`${row.source}-${row.owner}-${row.sku_id}-${index}`}>
                  <td>
                    <PriorityPill priority={row.priority} />
                  </td>
                  <td>{row.owner}</td>
                  <td className="tabular">{row.sku_id}</td>
                  <td>{row.title}</td>
                  <td>{row.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {mgmt.recommendations?.length ? (
        <>
          <h3 style={{ marginTop: '1rem' }}>总控建议</h3>
          <ul className="actions-list">
            {mgmt.recommendations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
      {digestRows.length ? (
        <div className="llm-note-card">
          <h3>LLM 总结</h3>
          <ul className="actions-list">
            {digestRows.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
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
  const llmNotes = report.replenishment.llm_notes
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
                <th>优先级</th>
                <th>建议订货</th>
                <th>EOQ</th>
                <th>触发条件</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.sku_id}>
                  <td className="tabular">
                    {r.sku_id} {r.name}
                  </td>
                  <td>
                    <PriorityPill priority={r.order_priority} />
                  </td>
                  <td className="tabular">{r.suggested_order_qty}</td>
                  <td className="tabular">{r.eoq?.eoq_units ?? 0}</td>
                  <td>{r.order_trigger ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {report.replenishment.recommendations?.length ? (
        <>
          <h3 style={{ marginTop: '1rem' }}>补货建议</h3>
          <ul className="actions-list">
            {report.replenishment.recommendations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
      {llmNotes && (
        <div className="llm-note-card">
          <h3>采购解读</h3>
          {llmNotes.business_comment && <p>{llmNotes.business_comment}</p>}
          {llmNotes.procurement_watchouts?.length ? (
            <ul className="actions-list">
              {llmNotes.procurement_watchouts.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
      {report.replenishment.llm_error && (
        <p className="err" style={{ marginTop: '0.75rem' }}>
          LLM：{report.replenishment.llm_error}
        </p>
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
