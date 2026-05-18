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
  total_coverage_days?: number
  coverage_gap_days?: number
  safety_stock_days?: number
  target_stock_days?: number
  target_stock_units?: number
  reorder_point_units?: number
  stock_position?: number
  urgency_score?: number
  urgency_level?: string
  demand_band?: string
  channel_focus?: string
  channel_focus_share_pct?: number
}

export interface OverstockAlert {
  sku_id: string
  name: string
  daily_sales: number
  current_stock: number
  in_transit: number
  total_coverage_days: number
  stock_position?: number
  pressure_score?: number
  clearance_priority?: string
  recommended_action?: string
  action_reason?: string
  stock_age_days?: number
  conversion_rate?: number
  return_rate_pct?: number
  channel_focus?: string
}

export interface InventoryHealth {
  sku_count: number
  stock_position_units: number
  low_stock_skus: number
  critical_low_stock_skus: number
  overstock_skus: number
  severe_overstock_skus: number
  healthy_skus: number
  avg_current_coverage_days: number
  avg_total_coverage_days: number
  coverage_bands?: Record<string, number>
}

export interface InventoryActionQueueRow {
  action_type: string
  due_in_days: number
  owner: string
  priority: string
  sku_id: string
  name: string
  reason: string
  recommended_qty: number
}

export interface InventoryPolicySnapshot {
  replenishment_cycle_days: number
  overstock_days: number
}

export interface InventoryLlmNotes {
  priorities_note?: string
  replenishment_focus?: string
  clearance_focus?: string
  coordination_checklist?: string[]
}

export interface InventoryReview {
  low_stock_alerts: LowStockAlert[]
  overstock_alerts: OverstockAlert[]
  recommendations: string[]
  inventory_health?: InventoryHealth
  action_queue?: InventoryActionQueueRow[]
  policy_snapshot?: InventoryPolicySnapshot
  llm_notes?: InventoryLlmNotes | null
  data_source?: string
  llm_error?: string | null
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
  coverage_gap_days?: number
  lead_time_days?: number
  target_stock_units?: number
  reorder_point_units?: number
  order_up_to_units?: number
  stock_position?: number
  order_priority?: string
  order_trigger?: string
}

export interface ReplenishmentLlmNotes {
  business_comment?: string
  procurement_watchouts?: string[]
}

export interface ReplenishmentParams {
  holding_cost_per_unit_per_year?: number
  lead_time_days?: number
  ordering_cost?: number
  seasonal_factor?: number
}

export interface Replenishment {
  replenishment_rows: ReplenishmentRow[]
  recommendations: string[]
  params?: ReplenishmentParams
  llm_notes?: ReplenishmentLlmNotes | null
  llm_replenishment_comment?: string | null
  data_source?: string
  llm_error?: string | null
}

export interface InventoryManagementAction {
  priority: string
  owner: string
  source: string
  sku_id: string
  title: string
  reason: string
}

export interface InventoryManagement {
  inventory_health?: InventoryHealth
  owner_lane_summary?: Record<string, number>
  action_board?: InventoryManagementAction[]
  recommendations?: string[]
  llm_digest?: string
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
  inventory_management: InventoryManagement
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
