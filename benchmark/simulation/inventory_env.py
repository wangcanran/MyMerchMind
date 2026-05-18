"""多 SKU 库存动力学：日需求、到货、缺货与 KPI。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ecommerce_agent.agents.inventory_warning_agent import InventoryWarningAgent
from ecommerce_agent.agents.replenishment_calculator import ReplenishmentCalculator


@dataclass
class SimulationKPI:
    days: int = 0
    total_demand_units: int = 0
    filled_units: int = 0
    unmet_units: int = 0
    stockout_sku_days: int = 0
    sum_end_on_hand: int = 0

    def to_dict(self) -> Dict:
        fill_rate = (self.filled_units / self.total_demand_units) if self.total_demand_units else 1.0
        return {
            "days": self.days,
            "total_demand_units": self.total_demand_units,
            "filled_units": self.filled_units,
            "unmet_units": self.unmet_units,
            "stockout_sku_days": self.stockout_sku_days,
            "avg_on_hand_per_day": (self.sum_end_on_hand / self.days) if self.days else 0.0,
            "fill_rate": round(fill_rate, 6),
        }


@dataclass
class InventoryEnv:
    """
    状态：`on_hand`、在途订单队列（按到货日）、每 SKU 恒定日需求（来自模板）。
    每步：先处理当日到货，再按日销扣减可用手存（允许缺货，未满足部分计入 unmet）。
    """

    sku_metrics_template: List[Dict]
    lead_time_days: int = 3
    sku_ids: List[str] = field(default_factory=list)
    on_hand: Dict[str, int] = field(default_factory=dict)
    daily_sales: Dict[str, int] = field(default_factory=dict)
    pending_arrivals: Dict[str, List[Tuple[int, int]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.sku_ids:
            self.sku_ids = sorted({str(m["sku_id"]) for m in self.sku_metrics_template})
        for m in self.sku_metrics_template:
            sid = str(m["sku_id"])
            self.daily_sales[sid] = int(m.get("daily_sales", 0))
            self.on_hand.setdefault(sid, int(m.get("stock", 0)))
            self.pending_arrivals.setdefault(sid, [])

    def _deliver_due(self, day: int) -> None:
        for sid in self.sku_ids:
            remaining: List[Tuple[int, int]] = []
            for due_day, qty in self.pending_arrivals.get(sid, []):
                if due_day <= day:
                    self.on_hand[sid] = self.on_hand.get(sid, 0) + int(qty)
                else:
                    remaining.append((due_day, qty))
            self.pending_arrivals[sid] = remaining

    def schedule_order(self, sku_id: str, qty: int, order_day: int) -> None:
        if qty <= 0:
            return
        due = order_day + int(self.lead_time_days)
        sid = str(sku_id)
        self.pending_arrivals.setdefault(sid, []).append((due, int(qty)))

    def current_sku_metrics(self) -> List[Dict]:
        rows: List[Dict] = []
        for m in self.sku_metrics_template:
            sid = str(m["sku_id"])
            row = deepcopy(m)
            row["stock"] = int(self.on_hand.get(sid, 0))
            in_transit_qty = sum(q for _, q in self.pending_arrivals.get(sid, []))
            row["in_transit"] = int(in_transit_qty)
            rows.append(row)
        return rows

    def step_day(
        self,
        day: int,
        kpi: Optional[SimulationKPI] = None,
    ) -> None:
        self._deliver_due(day)
        for sid in self.sku_ids:
            demand = max(0, int(self.daily_sales.get(sid, 0)))
            if kpi is not None:
                kpi.total_demand_units += demand
            oh = int(self.on_hand.get(sid, 0))
            fill = min(oh, demand)
            unmet = demand - fill
            if kpi is not None:
                kpi.filled_units += fill
                kpi.unmet_units += unmet
                if oh < demand:
                    kpi.stockout_sku_days += 1
            self.on_hand[sid] = oh - fill
        if kpi is not None:
            kpi.days += 1
            kpi.sum_end_on_hand += sum(int(self.on_hand.get(s, 0)) for s in self.sku_ids)


def run_inventory_policy(
    env: InventoryEnv,
    *,
    num_days: int,
    decision_interval: int,
    replenishment_cycle_days: int,
    overstock_days: int,
    policy: str,
) -> SimulationKPI:
    """
    policy:
      - ``noop``：不下单
      - ``periodic_agent``：每 ``decision_interval`` 天用库存预警 + 建议补货量下单
    """
    kpi = SimulationKPI()
    inv_agent = InventoryWarningAgent()
    repl_calc = ReplenishmentCalculator()

    for day in range(1, num_days + 1):
        if policy == "periodic_agent" and decision_interval > 0 and (day - 1) % decision_interval == 0:
            metrics = env.current_sku_metrics()
            inv_report = inv_agent.analyze(
                metrics,
                replenishment_cycle_days=replenishment_cycle_days,
                overstock_days=overstock_days,
                limit=50,
            )
            low_rows = inv_report.get("low_stock_alerts") or []
            repl_report = repl_calc.suggest_for_low_stock(low_rows, limit=50)
            for row in repl_report.get("replenishment_rows") or []:
                sid = row.get("sku_id")
                qty = int(row.get("suggested_order_qty") or 0)
                if sid and qty > 0:
                    env.schedule_order(str(sid), qty, day)

        env.step_day(day, kpi=kpi)

    return kpi


def compare_policies(
    sku_metrics_template: List[Dict],
    *,
    num_days: int = 90,
    decision_interval: int = 7,
    lead_time_days: int = 3,
    replenishment_cycle_days: int = 7,
    overstock_days: int = 45,
) -> Dict[str, Dict]:
    """返回 ``noop`` 与 ``periodic_agent`` 的 KPI 字典，便于写入 JSON。"""
    base_template = deepcopy(sku_metrics_template)

    def make_env() -> InventoryEnv:
        return InventoryEnv(
            sku_metrics_template=deepcopy(base_template),
            lead_time_days=lead_time_days,
        )

    out: Dict[str, Dict] = {}
    for pol in ("noop", "periodic_agent"):
        env = make_env()
        kpi = run_inventory_policy(
            env,
            num_days=num_days,
            decision_interval=decision_interval,
            replenishment_cycle_days=replenishment_cycle_days,
            overstock_days=overstock_days,
            policy=pol,
        )
        out[pol] = kpi.to_dict()
    return out
