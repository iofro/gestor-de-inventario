from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .methods import (
    forecast_fallback_avg,
    forecast_linear_trend,
    forecast_ses,
    forecast_wma,
    mae,
    mape,
    predict_next_linear_trend,
    predict_next_ses,
    predict_next_wma,
)


@dataclass(frozen=True)
class MethodSelection:
    method: str
    mae: float
    mape: float
    explanation: str


def select_best_method(
    values: Sequence[float],
    *,
    weights: Sequence[float],
    alpha: float,
    recent_window: int = 7,
    min_linear_history: int = 30,
    epsilon: float = 1.0,
) -> MethodSelection:
    """Seleccion automatica por menor error reciente (1 paso adelante)."""

    clean = [float(v) for v in values if v is not None]
    if len(clean) < 3:
        return MethodSelection(
            method="fallback_avg",
            mae=0.0,
            mape=0.0,
            explanation="Historial insuficiente; se usa promedio reciente como fallback.",
        )

    methods: list[tuple[str, Callable[[Sequence[float]], float], int]] = [
        ("wma", lambda train: predict_next_wma(train, weights), 3),
        ("ses", lambda train: predict_next_ses(train, alpha), 3),
    ]
    if len(clean) >= min_linear_history:
        methods.append(("linear", predict_next_linear_trend, min_linear_history))

    max_window = min(max(recent_window, 1), len(clean) - 1)
    start_idx = len(clean) - max_window

    best_name = "fallback_avg"
    best_mae = float("inf")
    best_mape = float("inf")

    for name, predictor, min_points in methods:
        actual: list[float] = []
        predicted: list[float] = []
        for t in range(start_idx, len(clean)):
            train = clean[:t]
            if len(train) < min_points:
                continue
            pred = predictor(train)
            actual.append(clean[t])
            predicted.append(pred)

        if not actual:
            continue

        score_mae = mae(actual, predicted)
        score_mape = mape(actual, predicted, epsilon=epsilon)
        if score_mae < best_mae:
            best_name = name
            best_mae = score_mae
            best_mape = score_mape

    if best_name == "fallback_avg":
        return MethodSelection(
            method="fallback_avg",
            mae=0.0,
            mape=0.0,
            explanation="No hubo suficientes observaciones validas por metodo; se usa fallback.",
        )

    explanation = (
        f"Metodo seleccionado: {best_name}. "
        f"Error reciente MAE={best_mae:.4f}, MAPE={best_mape:.2f}% "
        f"en ventana de {max_window} dias."
    )
    return MethodSelection(method=best_name, mae=best_mae, mape=best_mape, explanation=explanation)


def forecast_with_selected_method(
    method: str,
    values: Sequence[float],
    horizon: int,
    *,
    weights: Sequence[float],
    alpha: float,
) -> float:
    if method == "wma":
        return forecast_wma(values, horizon, weights)
    if method == "ses":
        return forecast_ses(values, horizon, alpha)
    if method == "linear":
        return forecast_linear_trend(values, horizon)
    return forecast_fallback_avg(values, horizon)
