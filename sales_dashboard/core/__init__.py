"""Core utilities for the sales dashboard."""

from .calculations import calcContribucion, calcMargenBruto, calcTicketPromedio, sortTopProducts
from .controller import DashboardController, FilterState, QuickRange
from .data_loader import DataValidationError, SalesDataset, filter_by_period, load_sales_data
from .formatters import format_currency, format_date, format_percentage
from .metrics import build_dashboard_data

__all__ = [
    "calcContribucion",
    "calcMargenBruto",
    "calcTicketPromedio",
    "sortTopProducts",
    "DashboardController",
    "FilterState",
    "QuickRange",
    "DataValidationError",
    "SalesDataset",
    "filter_by_period",
    "load_sales_data",
    "format_currency",
    "format_date",
    "format_percentage",
    "build_dashboard_data",
]
