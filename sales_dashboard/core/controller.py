"""Central controller coordinating filters and aggregations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from .data_loader import SalesDataset, filter_by_period
from .metrics import DashboardData, build_dashboard_data


class FilterMode(Enum):
    DIA = "Día"
    MES = "Mes"
    ANIO = "Año"
    PERSONALIZADO = "Personalizado"


@dataclass
class FilterState:
    mode: FilterMode
    start: Optional[datetime]
    end: Optional[datetime]


class DashboardController:
    def __init__(self, dataset: SalesDataset, tz_name: str = "UTC") -> None:
        self.dataset = dataset
        self.tz_name = tz_name
        now = datetime.now()
        default_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (default_start + timedelta(days=32)).replace(day=1)
        default_end = next_month - timedelta(microseconds=1)
        self.state = FilterState(mode=FilterMode.MES, start=default_start, end=default_end)
        self.order_by = "ventas"

    def set_state(self, state: FilterState) -> None:
        self.state = state

    def set_order_by(self, order_by: str) -> None:
        self.order_by = order_by

    def apply(self) -> DashboardData:
        df = filter_by_period(self.dataset, self.state.start, self.state.end)
        data = build_dashboard_data(df, self.order_by)
        return data

    def timezone_label(self) -> str:
        return f"Zona horaria: {self.tz_name}"
