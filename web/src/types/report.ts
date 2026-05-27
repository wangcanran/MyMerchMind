/** Mirrors ecommerce_agent orchestrator + agent outputs (baseline). */

export interface ReportContext {
  as_of: string
  seed: number
  sku_count: number
  trend_count: number
  top_n: number
  llm_enabled?: boolean
  llm_notice?: string | null
  /** 企划 market_intel 用目标毛利率（归一后 0~1，如 0.45） */
  target_gross_margin?: number
  /** 编排注入：SKU 展示、现价快照、分段规则说明 */
  reporting_rules?: Record<string, string>
}

export interface SkuRowView {
  sku_id: string
  name: string
  daily_sales: number
  stock: number
  return_rate_pct: number
  /** ERP 快照现价（元），与定价模块 current_price 同源口径 */
  list_price?: number | null
  in_transit?: number
}

export interface SalesSummary {
  total_daily_sales: number
  avg_return_rate_pct: number
  top_trend?: string
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
  trend_focus?: TrendFocusRow[]
  channel_dashboard: ChannelDashboard
  return_semantics: ReturnSemantics
  recommendations: string[]
  /** 各榜单分段定义，避免畅销/滞销语义打架 */
  segmentation_glossary?: Record<string, string>
  data_source?: string
  llm_executive_brief?: { executive_summary: string; action_bullets: string[] } | null
  llm_error?: string | null
}

export interface NewProductPlanningEntry {
  title?: string
  competitor_search_query?: string
  intel?: Record<string, unknown>
}

export interface ProductSelection {
  skipped?: boolean
  criteria?: Record<string, unknown> | null
  suggested_categories?: string[]
  recommendation?: Record<string, unknown> | null
  data_source?: string
  llm_error?: string | null
  error?: string | null
  selection_note?: string | null
  /** 需求正文节选（自然语言 / Markdown 入参时由后端带回） */
  requirements_preview?: string | null
  requirements_file?: string | null
  /** 新品企划：M3 ``approve_new`` 后的 ``market_intel``，与后端 ``new_product_planning`` 一致 */
  new_product_planning?: {
    items?: string[]
    note?: string
    criteria_snapshot?: Record<string, unknown> | null
    entries?: NewProductPlanningEntry[]
    /** ``category_management_approve_new`` | ``category_management_no_approve_new`` | ``category_management_skipped`` */
    planning_item_source?: string
  }
}

export interface CategoryManagementSummary {
  category_count?: number
  sku_total?: number
  top_category_by_sales?: string
  /** 销售贡献最大品类的日销合计（件），与 M3 叙事衔接用 */
  top_category_daily_sales?: number
}

export interface CategoryNewCandidate {
  category?: string
  decision?: string
  reason?: string
}

export interface CategoryManagement {
  skipped?: boolean
  /** 编排器写入：M2 建议 vs 在架 Top 品类的阅读口径 */
  m2_m3_bridge_note?: string
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

export interface MarketIntel {
  reference_band?: string | null
  sweet_spot?: number | null
  median?: number | null
  implied_cost_ceiling?: number | null
  assumed_target_gross_margin?: number
  disclaimer?: string | null
  anchor_band_tension?: string
  sweet_vs_band_note?: string | null
}

export interface CompetitorSummary {
  sample_count?: number
  median?: number
  p25?: number
  p75?: number
  sweet_spot?: number
}

export interface PricingSuggestionRow {
  sku_id?: string
  name?: string
  current_price?: number | null
  cost_price?: number | null
  suggested_price?: number
  role?: string
  elasticity?: number | null
  optimal_price?: number | null
  step_plan?: { target_price: number; steps_needed: number; per_step_pct: number; note: string } | null
  price_position_pct?: number | null
  strategy?: string
  pricing_stage?: string
  competitor_summary?: CompetitorSummary
  market_intel?: MarketIntel | null
  competitor_search_query?: string
  competitor_search_used_planning_suffix?: boolean
  reasoning?: string
  exception_explanation_rule?: string | null
  llm_exception_explanation?: string | null
}

export interface PricingSummary {
  total_skus?: number
  skus_with_competitor_data?: number
  data_source?: string
  competitor_search_suffix?: string | null
  skus_with_planning_suffix?: number
  /** M3 ``approve_new`` 企划标题，与 ``product_selection.new_product_planning.items`` 同源 */
  m2_suggestions_not_in_erp_skus?: string[]
}

export interface Pricing {
  skipped?: boolean
  summary?: PricingSummary
  pricing_suggestions?: PricingSuggestionRow[]
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
  experience_store?: { draft: number; active: number; archived: number }
  retrieved_experience_count?: number
  retrieved_experiences?: Array<{
    experience_id: string
    title: string
    narrative?: string
    confidence: string
    _score: number
  }>
  new_draft_count?: number
}

export interface AgentReport {
  /** 与本次 JSON 同一趟编排生成的 Markdown；优先用于预览/下载，勿再单独请求 /api/report/markdown */
  markdown?: string
  context: ReportContext
  product_selection: ProductSelection
  category_management: CategoryManagement
  pricing: Pricing
  sales_review: SalesReview
  inventory_review: InventoryReview
  slow_moving: SlowMoving
  replenishment: Replenishment
  inventory_management: InventoryManagement
  memory_snapshot: MemorySnapshot
  actions: string[]
  /** 行动清单优先级矩阵（与 Markdown ACTIONS 表同源） */
  actions_display?: {
    as_of?: string
    note?: string
    rows: { tier: string; owner: string; action: string; due: string }[]
  }
}

export interface ReportParams {
  seed: number
  top_n: number
  as_of: string
  replenishment_cycle: number
  overstock_days: number
  feedback_memory: string
  /** 自然语言或 Markdown；非空时 POST /api/report 并走「需求理解 → criteria → 图谱选品」 */
  selection_requirements?: string
  /**
   * 企划「示意成本上限」用目标毛利率：0~1 小数（如 0.45），或 >1 表示百分数（如 40）。
   * 未设置时由后端默认 0.45。
   */
  target_gross_margin?: number
}
