"""Central controller coordinating filters and aggregations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Tuple

from .data_loader import SalesDataset, filter_by_period
from .metrics import DashboardData, build_dashboard_data


class QuickRange(Enum):
    HOY = "Hoy"
    AYER = "Ayer"
    ULTIMOS_7 = "Últimos 7 días"
    ESTE_MES = "Este mes"
    MES_ANTERIOR = "Mes anterior"
    PERSONALIZADO = "Personalizado"


@dataclass
class FilterState:
    quick_range: QuickRange
    start: Optional[datetime]
    end: Optional[datetime]


class DashboardController:
    def __init__(self, dataset: SalesDataset, tz_name: str = "UTC") -> None:
        self.dataset = dataset
        self.tz_name = tz_name
        now = datetime.now()
        start, end = self._range_for(QuickRange.ULTIMOS_7, now)
        self.state = FilterState(quick_range=QuickRange.ULTIMOS_7, start=start, end=end)
        self.order_by = "ventas"

    def _range_for(self, quick_range: QuickRange, reference: datetime) -> Tuple[datetime, datetime]:
        today = reference.replace(hour=0, minute=0, second=0, microsecond=0)
        if quick_range == QuickRange.HOY:
            start = today
            end = today + timedelta(days=1) - timedelta(microseconds=1)
        elif quick_range == QuickRange.AYER:
            start = today - timedelta(days=1)
            end = today - timedelta(microseconds=1)
        elif quick_range == QuickRange.ULTIMOS_7:
            start = today - timedelta(days=6)
            end = today + timedelta(days=1) - timedelta(microseconds=1)
        elif quick_range == QuickRange.ESTE_MES:
            start = today.replace(day=1)
            next_month = (start + timedelta(days=32)).replace(day=1)
            end = next_month - timedelta(microseconds=1)
        elif quick_range == QuickRange.MES_ANTERIOR:
            first_this_month = today.replace(day=1)
            last_month_end = first_this_month - timedelta(microseconds=1)
            start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = last_month_end
        else:  # PERSONALIZADO
            start = self.state.start or today
            end = self.state.end or today + timedelta(days=1) - timedelta(microseconds=1)
        return start, end

    def set_quick_range(self, quick_range: QuickRange) -> None:
        now = datetime.now()
        start, end = self._range_for(quick_range, now)
        self.state = FilterState(quick_range=quick_range, start=start, end=end)

    def set_custom_dates(self, start: datetime, end: datetime) -> None:
        self.state = FilterState(quick_range=QuickRange.PERSONALIZADO, start=start, end=end)

    def set_order_by(self, order_by: str) -> None:
        self.order_by = order_by

    def apply(self) -> DashboardData:
        df = filter_by_period(self.dataset, self.state.start, self.state.end)
        data = build_dashboard_data(df, self.order_by)
        return data

    def timezone_label(self) -> str:
        return f"Zona horaria: {self.tz_name}"
