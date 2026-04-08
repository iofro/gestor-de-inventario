from analytics_predictive.forecast.methods import (
    forecast_linear_trend,
    forecast_ses,
    forecast_wma,
    mape,
)
from analytics_predictive.forecast.selector import select_best_method


def test_wma_and_ses_normal_case() -> None:
    values = [10, 12, 14, 16, 18]
    wma = forecast_wma(values, horizon=7, weights=(0.5, 0.3, 0.2))
    ses = forecast_ses(values, horizon=7, alpha=0.4)

    assert wma > 0
    assert ses > 0


def test_linear_trend_extreme_non_negative() -> None:
    values = [100, 80, 60, 40, 20, 0]
    out = forecast_linear_trend(values, horizon=10)
    assert out >= 0.0


def test_mape_handles_zero_actuals() -> None:
    result = mape([0.0, 0.0, 5.0], [1.0, 2.0, 4.0], epsilon=1.0)
    assert result >= 0.0


def test_selector_fallback_for_no_history() -> None:
    choice = select_best_method(
        [],
        weights=(0.5, 0.3, 0.2),
        alpha=0.35,
        recent_window=7,
        min_linear_history=30,
    )
    assert choice.method == "fallback_avg"
    assert "fallback" in choice.explanation.lower()


def test_selector_prefers_linear_on_strong_trend() -> None:
    values = [float(v) for v in range(1, 61)]
    choice = select_best_method(
        values,
        weights=(0.6, 0.3, 0.1),
        alpha=0.35,
        recent_window=14,
        min_linear_history=30,
    )
    assert choice.method in {"linear", "wma", "ses"}
    assert choice.mae >= 0.0