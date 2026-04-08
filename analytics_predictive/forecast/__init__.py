"""Capa de calculo predictivo liviano."""

from .methods import forecast_linear_trend, forecast_ses, forecast_wma
from .selector import forecast_with_selected_method, select_best_method

__all__ = [
	"forecast_linear_trend",
	"forecast_ses",
	"forecast_wma",
	"forecast_with_selected_method",
	"select_best_method",
]
