from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class ProductCardViewModel:
    product_id: int
    product_name: str
    level: str
    suggested_qty: float
    coverage_days: float
    explanation: str


@dataclass
class DashboardViewModel:
    generated_at: str
    buy_today: List[ProductCardViewModel] = field(default_factory=list)
    break_risk: List[ProductCardViewModel] = field(default_factory=list)
    overstock: List[ProductCardViewModel] = field(default_factory=list)
