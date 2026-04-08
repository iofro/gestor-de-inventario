from __future__ import annotations

from datetime import date
from datetime import datetime
from typing import Dict, List

from .config import PredictiveParams
from .data.models import DashboardBundle, ForecastResult, HistoricalDataBundle, RecommendationResult
from .data.read_only_repository import ReadOnlyRepository
from .data.series_builder import demand_stats
from .forecast import forecast_with_selected_method, select_best_method
from .recommendations import (
    build_action_lists,
    build_explanation,
    classify_abc_by_impact,
    compute_recommendation,
    derive_alert_type,
    detect_slow_product,
    has_critical_data,
)


class PredictiveAnalyticsService:
    """Orquestador base del modulo predictivo (sin acople a UI actual)."""

    def __init__(self, repository: ReadOnlyRepository, params: PredictiveParams | None = None) -> None:
        self.repository = repository
        self.params = params or PredictiveParams()

    def run(self, start: date | None = None, end: date | None = None) -> DashboardBundle:
        extracted = self.repository.extract_historical_data(start=start, end=end)
        return self.run_from_extracted(extracted)

    def run_from_extracted(self, extracted: HistoricalDataBundle) -> DashboardBundle:
        stock_by_product = extracted.stock_by_product
        product_ids = sorted(stock_by_product.keys())

        forecasts: List[ForecastResult] = []
        recommendations: List[RecommendationResult] = []
        impact_by_product: Dict[int, float] = {}

        # Mapa de ultimo dia de venta por producto para alerta de lentitud.
        last_sale_day: Dict[int, date | None] = {}
        for pid, points in extracted.sales_daily_by_product.items():
            last_sale_day[pid] = points[-1].day if points else None

        for product_id in product_ids:
            snapshot = stock_by_product.get(product_id)
            if snapshot is None:
                continue

            points = extracted.sales_daily_by_product.get(product_id, [])
            values = [float(p.units) for p in points]
            avg, std = demand_stats(points)

            choice = select_best_method(
                values,
                weights=self.params.wma_weights,
                alpha=self.params.ses_alpha,
                recent_window=self.params.recent_error_window_days,
                min_linear_history=self.params.linear_min_history_days,
                epsilon=self.params.epsilon,
            )

            by_horizon: Dict[int, float] = {}
            for h in self.params.horizons_days:
                by_horizon[h] = forecast_with_selected_method(
                    choice.method,
                    values,
                    h,
                    weights=self.params.wma_weights,
                    alpha=self.params.ses_alpha,
                )

            forecasts.append(
                ForecastResult(
                    product_id=product_id,
                    method=choice.method,
                    demand_daily_avg=avg,
                    demand_daily_std=std,
                    forecast_by_horizon=by_horizon,
                    mae=choice.mae,
                    mape=choice.mape,
                    explanation=choice.explanation,
                )
            )

            hinted = extracted.lead_time_hints.get(product_id)
            lead_time_val = snapshot.lead_time_days
            if lead_time_val is None and hinted and hinted.estimated_days:
                lead_time_val = hinted.estimated_days

            stock_current = float(snapshot.stock_current)
            stock_in_transit = float(snapshot.stock_in_transit)

            can_recommend = has_critical_data(
                lead_time_days=lead_time_val,
                demand_daily_avg=avg,
                stock_current=stock_current,
            )

            lead_time = int(lead_time_val or 7)

            rec = compute_recommendation(
                demand_daily_avg=avg,
                demand_daily_std=std,
                stock_current=stock_current,
                stock_in_transit=stock_in_transit,
                lead_time_days=lead_time,
                horizons=self.params.horizons_days,
                z=self.params.service_level_z,
                epsilon=self.params.epsilon,
                overstock_days_threshold=self.params.overstock_days_threshold,
            )

            impact = max((snapshot.sale_price - snapshot.cost_unit), 0.0) * max(sum(values), 0.0)
            impact_by_product[product_id] = impact

            slow_days = detect_slow_product(
                last_sale_day=last_sale_day.get(product_id),
                today=date.today(),
                threshold_days=self.params.slow_product_days,
            )

            suggested_default = rec["suggested_by_horizon"].get(self.params.horizons_days[1], 0.0)
            alert_type = derive_alert_type(
                level=str(rec["level"]),
                suggested_qty=float(suggested_default),
                slow_days=slow_days,
                stock_current=stock_current,
            )

            explanation = build_explanation(
                suggested_qty=float(suggested_default),
                demand_daily_avg=avg,
                coverage_days=float(rec["coverage_days"]),
                lead_time_days=lead_time,
                method=choice.method,
                alert_type=alert_type,
                abc_class="C",
                days_since_last_sale=slow_days,
                can_recommend=can_recommend,
            )

            recommendations.append(
                RecommendationResult(
                    product_id=product_id,
                    level=str(rec["level"]),
                    alert_type=alert_type,
                    priority_score=0.0,
                    abc_class="C",
                    can_recommend=can_recommend,
                    reorder_point=float(rec["reorder_point"]),
                    safety_stock=float(rec["safety_stock"]),
                    coverage_days=float(rec["coverage_days"]),
                    days_since_last_sale=slow_days,
                    suggested_by_horizon=dict(rec["suggested_by_horizon"]),
                    explanation=explanation,
                )
            )

        # Priorizacion ABC y puntaje auditable por impacto + urgencia.
        abc_map = classify_abc_by_impact(impact_by_product)
        horizon_default = self.params.horizons_days[1]

        finalized: List[RecommendationResult] = []
        for rec in recommendations:
            abc = abc_map.get(rec.product_id, "C")
            abc_weight = {"A": 3.0, "B": 2.0, "C": 1.0}.get(abc, 1.0)
            urgency = 0.0
            if rec.alert_type == "break_risk":
                urgency = 3.0
            elif rec.alert_type == "buy":
                urgency = 2.0
            elif rec.alert_type == "overstock":
                urgency = 1.5
            elif rec.alert_type == "slow":
                urgency = 1.0

            qty = float(rec.suggested_by_horizon.get(horizon_default, 0.0))
            priority = abc_weight * urgency * (1.0 + min(qty / 100.0, 2.0))

            explanation = build_explanation(
                suggested_qty=qty,
                demand_daily_avg=float(next((f.demand_daily_avg for f in forecasts if f.product_id == rec.product_id), 0.0)),
                coverage_days=rec.coverage_days,
                lead_time_days=max(int(rec.reorder_point // max(float(next((f.demand_daily_avg for f in forecasts if f.product_id == rec.product_id), 0.0)), self.params.epsilon)), 1),
                method=next((f.method for f in forecasts if f.product_id == rec.product_id), "fallback_avg"),
                alert_type=rec.alert_type,
                abc_class=abc,
                days_since_last_sale=rec.days_since_last_sale,
                can_recommend=rec.can_recommend,
            )

            finalized.append(
                RecommendationResult(
                    product_id=rec.product_id,
                    level=rec.level,
                    alert_type=rec.alert_type,
                    priority_score=priority,
                    abc_class=abc,
                    can_recommend=rec.can_recommend,
                    reorder_point=rec.reorder_point,
                    safety_stock=rec.safety_stock,
                    coverage_days=rec.coverage_days,
                    days_since_last_sale=rec.days_since_last_sale,
                    suggested_by_horizon=rec.suggested_by_horizon,
                    explanation=explanation,
                )
            )

        buy_today, break_risk, overstock = build_action_lists(
            finalized,
            horizon_for_buy=horizon_default,
        )

        return DashboardBundle(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            forecasts=forecasts,
            recommendations=finalized,
            buy_today=buy_today,
            break_risk=break_risk,
            overstock=overstock,
        )
