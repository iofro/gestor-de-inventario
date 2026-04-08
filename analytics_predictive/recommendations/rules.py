from __future__ import annotations

import math
from datetime import date
from typing import Dict, Iterable, Optional

from ..data.models import ForecastResult, RecommendationResult


def classify_level(coverage_days: float, lead_time_days: int, overstock_threshold: int) -> str:
    if coverage_days < max(lead_time_days, 1):
        return "red"
    if coverage_days > overstock_threshold:
        return "yellow"
    return "green"


def classify_abc_by_impact(impact_by_product: Dict[int, float]) -> Dict[int, str]:
    """Clasificacion ABC por contribucion acumulada de impacto."""

    items = sorted(impact_by_product.items(), key=lambda x: x[1], reverse=True)
    total = sum(max(v, 0.0) for _, v in items)
    if total <= 0:
        return {pid: "C" for pid, _ in items}

    acc = 0.0
    out: Dict[int, str] = {}
    for product_id, value in items:
        acc += max(value, 0.0)
        ratio = acc / total
        if ratio <= 0.80:
            out[product_id] = "A"
        elif ratio <= 0.95:
            out[product_id] = "B"
        else:
            out[product_id] = "C"
    return out


def detect_slow_product(last_sale_day: Optional[date], today: date, threshold_days: int) -> Optional[int]:
    if last_sale_day is None:
        return None
    delta = max((today - last_sale_day).days, 0)
    if delta >= max(threshold_days, 1):
        return delta
    return None


def compute_recommendation(
    *,
    demand_daily_avg: float,
    demand_daily_std: float,
    stock_current: float,
    stock_in_transit: float,
    lead_time_days: int,
    horizons: tuple[int, ...],
    z: float,
    epsilon: float,
    overstock_days_threshold: int,
) -> Dict[str, object]:
    lead = max(int(lead_time_days or 0), 1)
    avg = max(float(demand_daily_avg or 0.0), 0.0)
    std = max(float(demand_daily_std or 0.0), 0.0)
    stock = max(float(stock_current or 0.0), 0.0)
    in_transit = max(float(stock_in_transit or 0.0), 0.0)

    safety_stock = z * std * math.sqrt(lead)
    reorder_point = avg * lead + safety_stock
    coverage_days = stock / max(avg, epsilon)

    suggested_by_horizon: Dict[int, float] = {}
    for h in horizons:
        demand_h = avg * max(int(h), 0)
        suggested = max(0.0, demand_h + safety_stock - stock - in_transit)
        suggested_by_horizon[int(h)] = suggested

    level = classify_level(coverage_days, lead, overstock_days_threshold)
    return {
        "safety_stock": safety_stock,
        "reorder_point": reorder_point,
        "coverage_days": coverage_days,
        "level": level,
        "suggested_by_horizon": suggested_by_horizon,
    }


def derive_alert_type(
    *,
    level: str,
    suggested_qty: float,
    slow_days: Optional[int],
    stock_current: float,
) -> str:
    if slow_days is not None and stock_current > 0:
        return "slow"
    if level == "red" and suggested_qty > 0:
        return "break_risk"
    if level == "yellow" and suggested_qty <= 0:
        return "overstock"
    if suggested_qty > 0:
        return "buy"
    return "ok"


def has_critical_data(
    *,
    lead_time_days: Optional[int],
    demand_daily_avg: float,
    stock_current: float,
) -> bool:
    """Valida datos minimos para emitir recomendacion confiable."""

    if lead_time_days is None or lead_time_days <= 0:
        return False
    if stock_current < 0:
        return False
    # Permite demanda cero, pero exige al menos no-negativa.
    if demand_daily_avg < 0:
        return False
    return True


def build_action_lists(
    recommendations: Iterable[RecommendationResult],
    *,
    horizon_for_buy: int,
) -> tuple[list[RecommendationResult], list[RecommendationResult], list[RecommendationResult]]:
    recs = list(recommendations)
    actionable = [r for r in recs if r.can_recommend]

    buy_today = [
        r for r in actionable
        if r.suggested_by_horizon.get(horizon_for_buy, 0.0) > 0 and r.alert_type in {"buy", "break_risk"}
    ]
    buy_today.sort(key=lambda r: (r.priority_score, r.suggested_by_horizon.get(horizon_for_buy, 0.0)), reverse=True)

    break_risk = [r for r in actionable if r.alert_type == "break_risk"]
    break_risk.sort(key=lambda r: (r.priority_score, r.coverage_days), reverse=True)

    overstock = [r for r in actionable if r.alert_type == "overstock"]
    overstock.sort(key=lambda r: (r.coverage_days, r.priority_score), reverse=True)

    return buy_today, break_risk, overstock
