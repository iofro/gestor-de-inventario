"""Core utilities for the sales dashboard."""

from .calculations import calcContribucion, calcMargenBruto, calcTicketPromedio, sortTopProducts
from .controller import DashboardController, FilterMode, FilterState
from .data_loader import DataValidationError, SalesDataset, filter_by_period, load_sales_data
from .formatters import format_currency, format_date, format_percentage
from .metrics import build_dashboard_data, compute_financial_report

__all__ = [
    "calcContribucion",
    "calcMargenBruto",
    "calcTicketPromedio",
    "sortTopProducts",
    "DashboardController",
    "FilterMode",
    "FilterState",
    "DataValidationError",
    "SalesDataset",
    "filter_by_period",
    "load_sales_data",
    "format_currency",
    "format_date",
    "format_percentage",
    "build_dashboard_data",
    "compute_financial_report",
]
