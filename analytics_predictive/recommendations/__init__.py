"""Capa de reglas de recomendacion para compras."""

from .explanations import build_explanation
from .rules import (
	build_action_lists,
	classify_abc_by_impact,
	classify_level,
	compute_recommendation,
	derive_alert_type,
	detect_slow_product,
	has_critical_data,
)

__all__ = [
	"build_action_lists",
	"build_explanation",
	"classify_abc_by_impact",
	"classify_level",
	"compute_recommendation",
	"derive_alert_type",
	"detect_slow_product",
	"has_critical_data",
]
