from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


@dataclass(frozen=True)
class DailyDemandPoint:
    product_id: int
    day: date
    units: float


@dataclass(frozen=True)
class DailyPurchasePoint:
    product_id: int
    day: date
    units: float


@dataclass(frozen=True)
class LeadTimeHint:
    product_id: int
    estimated_days: Optional[int]
    sample_size: int


@dataclass(frozen=True)
class ProductSnapshot:
    product_id: int
    name: str
    stock_current: float
    cost_unit: float
    sale_price: float
    lead_time_days: Optional[int] = None
    stock_in_transit: float = 0.0


@dataclass(frozen=True)
class ForecastResult:
    product_id: int
    method: str
    demand_daily_avg: float
    demand_daily_std: float
    forecast_by_horizon: Dict[int, float]
    mae: float
    mape: float
    explanation: str


@dataclass(frozen=True)
class RecommendationResult:
    product_id: int
    level: str
    alert_type: str
    priority_score: float
    abc_class: str
    can_recommend: bool
    reorder_point: float
    safety_stock: float
    coverage_days: float
    days_since_last_sale: Optional[int]
    suggested_by_horizon: Dict[int, float]
    explanation: str


@dataclass
class DashboardBundle:
    generated_at: str
    forecasts: List[ForecastResult] = field(default_factory=list)
    recommendations: List[RecommendationResult] = field(default_factory=list)
    buy_today: List[RecommendationResult] = field(default_factory=list)
    break_risk: List[RecommendationResult] = field(default_factory=list)
    overstock: List[RecommendationResult] = field(default_factory=list)


@dataclass
class HistoricalDataBundle:
    sales_daily_by_product: Dict[int, List[DailyDemandPoint]] = field(default_factory=dict)
    purchases_daily_by_product: Dict[int, List[DailyPurchasePoint]] = field(default_factory=dict)
    stock_by_product: Dict[int, ProductSnapshot] = field(default_factory=dict)
    lead_time_hints: Dict[int, LeadTimeHint] = field(default_factory=dict)
    quality: Dict[str, int] = field(default_factory=dict)
