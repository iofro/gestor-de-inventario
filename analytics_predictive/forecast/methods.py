from __future__ import annotations

from typing import Iterable, Sequence


def forecast_wma(values: Sequence[float], horizon: int, weights: Sequence[float]) -> float:
    """Pronostico simple por promedio movil ponderado."""

    if horizon <= 0:
        return 0.0
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return 0.0

    n = min(len(clean), len(weights))
    recent = clean[-n:]
    used = list(weights[:n])
    total_w = sum(used) or 1.0
    normalized = [w / total_w for w in used]

    # pesos aplicados del mas reciente al mas antiguo
    recent_rev = list(reversed(recent))
    daily = sum(v * w for v, w in zip(recent_rev, normalized))
    return max(0.0, daily * horizon)


def predict_next_wma(values: Sequence[float], weights: Sequence[float]) -> float:
    return forecast_wma(values, 1, weights)


def forecast_ses(values: Sequence[float], horizon: int, alpha: float = 0.35) -> float:
    """Pronostico simple por suavizamiento exponencial."""

    if horizon <= 0:
        return 0.0
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return 0.0

    a = min(max(alpha, 0.01), 0.99)
    s = clean[0]
    for x in clean[1:]:
        s = a * x + (1.0 - a) * s
    return max(0.0, s * horizon)


def predict_next_ses(values: Sequence[float], alpha: float = 0.35) -> float:
    return forecast_ses(values, 1, alpha)


def forecast_linear_trend(values: Sequence[float], horizon: int) -> float:
    """Pronostico lineal basico por minimos cuadrados.

    Proyecta demanda diaria y suma los proximos ``horizon`` dias.
    """

    if horizon <= 0:
        return 0.0
    clean = [float(v) for v in values if v is not None]
    if len(clean) < 2:
        return 0.0

    n = len(clean)
    x_mean = (n - 1) / 2.0
    y_mean = sum(clean) / n

    var_x = 0.0
    cov_xy = 0.0
    for i, y in enumerate(clean):
        dx = i - x_mean
        var_x += dx * dx
        cov_xy += dx * (y - y_mean)

    if var_x <= 0:
        b = 0.0
    else:
        b = cov_xy / var_x
    a = y_mean - b * x_mean

    total = 0.0
    for k in range(1, horizon + 1):
        y_hat = a + b * (n - 1 + k)
        total += max(0.0, y_hat)
    return max(0.0, total)


def predict_next_linear_trend(values: Sequence[float]) -> float:
    return forecast_linear_trend(values, 1)


def forecast_fallback_avg(values: Sequence[float], horizon: int, lookback: int = 7) -> float:
    if horizon <= 0:
        return 0.0
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return 0.0
    recent = clean[-max(1, lookback) :]
    daily = sum(recent) / len(recent)
    return max(0.0, daily * horizon)


def mae(actual: Iterable[float], predicted: Iterable[float]) -> float:
    a = list(actual)
    p = list(predicted)
    if not a or len(a) != len(p):
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, p)) / len(a)


def mape(actual: Iterable[float], predicted: Iterable[float], epsilon: float = 1.0) -> float:
    a = list(actual)
    p = list(predicted)
    if not a or len(a) != len(p):
        return 0.0
    return (
        sum(abs(x - y) / max(abs(x), epsilon) for x, y in zip(a, p)) / len(a)
    ) * 100.0
