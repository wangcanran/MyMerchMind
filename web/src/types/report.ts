/** Mirrors ecommerce_agent orchestrator + agent outputs (baseline). */

export interface ReportContext {
  as_of: string
  seed: number
  sku_count: number
  trend_count: number
  top_n: number
  llm_enabled?: boolean
  llm_notice?: string | null
}

export interface SkuRowView {
  sku_id: string
  name: string
  daily_sales: number
  stock: number
  return_rate_pct: number
}

export interface SalesSummary {
  total_daily_sales: number
  avg_return_rate_pct: number
  top_trend: string
}

export interface TrendFocusRow {
  keyword: string
  platform: string
  heat_score: number
  growth_rate_pct: number
}

export interface ChannelDashboard {
  channels?: Record<
    string,
    {
      daily_units: number
      share_pct: number
    }
  >
  week_over_week_pct?: number
  month_over_month_pct?: number
  current_week_est_units?: number
  prior_week_total_units?: number
  current_month_est_units?: number
  prior_month_total_units?: number
}

export interface ReturnSemantics {
  tag_counts?: Record<string, number>
  top_tags?: [string, number][]
  sku_attributions?: { sku_id: string; name: string; tags: string[] }[]
}

export interface SalesReview {
  summary: SalesSummary
  top_skus: SkuRowView[]
  lagging_skus: SkuRowView[]
  high_return_skus: SkuRowView[]
  trend_focus: TrendFocusRow[]
  channel_dashboard: ChannelDashboard
  return_semantics: ReturnSemantics
  recommendations: string[]
  data_source?: string
  llm_executive_brief?: { executive_summary: string; action_bullets: string[] } | null
  llm_error?: string | null
}

export interface MerchMapping {
  suggested_categories?: string[]
  color_focus?: string[]
  material_focus?: string[]
  story?: string
  matched_keyword?: string
}

export interface CompetitorGap {
  category_key?: string
  competitor_new_skus_30d?: number
  ours_new_skus_30d?: number
  gap_note?: string
}

export interface ProductSelection {
  trend_picks: {
    keyword?: string
    merch_mapping: MerchMapping
    competitor_gaps: CompetitorGap[]
    moq: {
      risk_level: string
      suggested_range_pcs: number[]
      note?: string
    }
    data_source?: string
  }[]
  recommendations: string[]
  memory_hits: { sku_id: string; name: string; hits: unknown[] }[]
  data_source?: string
}

export interface LowStockAlert {
  sku_id: string
  name: string
  daily_sales: number
  current_stock: number
  in_transit: number
  coverage_days: number
  suggest_replenish_qty: number
}

export interface OverstockAlert {
  sku_id: string
  name: string
  daily_sales: number
  current_stock: number
  in_transit: number
  total_coverage_days: number
}

export interface InventoryReview {
  low_stock_alerts: LowStockAlert[]
  overstock_alerts: OverstockAlert[]
  recommendations: string[]
}

export interface SlowMovingSku {
  sku_id: string
  name: string
  stock_age_days: number
  conversion_rate: number
  strategy: string
  reason: string
}

export interface SlowMoving {
  slow_moving_skus: SlowMovingSku[]
  recommendations: string[]
}

export interface EoqPayload {
  eoq_units: number
  annual_demand?: number
  seasonal_factor?: number
  note?: string
  formula?: string
}

export interface ReplenishmentRow {
  sku_id: string
  name: string
  daily_sales: number
  eoq: EoqPayload
  suggested_order_qty: number
  note?: string
}

export interface Replenishment {
  replenishment_rows: ReplenishmentRow[]
  recommendations: string[]
}

export interface MemorySnapshot {
  active_feedback_count: number
  product_selection_hits: number
}

export interface AgentReport {
  context: ReportContext
  product_selection: ProductSelection
  sales_review: SalesReview
  inventory_review: InventoryReview
  slow_moving: SlowMoving
  replenishment: Replenishment
  memory_snapshot: MemorySnapshot
  actions: string[]
}

export interface ReportParams {
  seed: number
  top_n: number
  as_of: string
  replenishment_cycle: number
  overstock_days: number
  feedback_memory: string
}
