from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class PredictiveParams:
    """Parametros basicos y livianos para el modulo predictivo."""

    horizons_days: Tuple[int, ...] = (7, 15, 30)
    base_window_days: int = 28
    min_history_days: int = 7
    recent_error_window_days: int = 7
    linear_min_history_days: int = 30
    ses_alpha: float = 0.35
    service_level_z: float = 1.65
    overstock_days_threshold: int = 45
    slow_product_days: int = 21
    epsilon: float = 0.01
    wma_weights: Tuple[float, ...] = field(
        default_factory=lambda: (0.30, 0.22, 0.16, 0.12, 0.09, 0.06, 0.05)
    )
