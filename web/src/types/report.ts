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

export interface ProductSelection {
  skipped?: boolean
  criteria?: Record<string, unknown> | null
  suggested_categories?: string[]
  recommendation?: Record<string, unknown> | null
  data_source?: string
  llm_error?: string | null
  error?: string | null
}

export interface CategoryManagementSummary {
  category_count?: number
  sku_total?: number
  top_category_by_sales?: string
}

export interface CategoryNewCandidate {
  category?: string
  decision?: string
  reason?: string
}

export interface CategoryManagement {
  skipped?: boolean
  category_summary?: CategoryManagementSummary
  decisions?: {
    evaluate_new?: {
      candidates?: CategoryNewCandidate[]
    }
  }
  llm_notes?: {
    card_notes?: {
      audit_existing?: string
      retire?: string
      evaluate_new?: string
    }
    execution_checklist?: string[]
  }
  strategy_scenarios?: {
    title?: string
    summary?: string
    expected_impact?: string[]
    risks?: string[]
    monitor_7d?: string[]
    monitor_30d?: string[]
  }[]
  data_source?: string
  llm_error?: string | null
}

export interface PricingRow {
  category?: string
  decision?: string
  budget_share_pct?: number
  competitor_price_band?: string | null
  suggested_price?: number | null
  pricing_mode?: string
  rationale?: string
}

export interface Pricing {
  skipped?: boolean
  summary?: {
    category_count?: number
    priced_category_preview?: string[]
    data_source?: string
  }
  pricing_rows?: PricingRow[]
  execution_checklist?: string[]
  recommendations?: string[]
  llm_error?: string | null
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
  category_management: CategoryManagement
  pricing: Pricing
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
