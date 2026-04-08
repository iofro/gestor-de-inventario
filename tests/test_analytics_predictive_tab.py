from datetime import date

from analytics_predictive.data.models import DashboardBundle, RecommendationResult
from analytics_predictive.presentation.predictive_tab import PredictiveAnalyticsTab


class _Manager:
    def __init__(self) -> None:
        self.db = object()


def _sample_rec(product_id: int = 1) -> RecommendationResult:
    return RecommendationResult(
        product_id=product_id,
        level="red",
        alert_type="break_risk",
        priority_score=10.0,
        abc_class="A",
        can_recommend=True,
        reorder_point=10.0,
        safety_stock=2.0,
        coverage_days=1.0,
        days_since_last_sale=None,
        suggested_by_horizon={7: 5.0, 15: 8.0, 30: 15.0},
        explanation="test",
    )


def _sample_payload() -> dict:
    rec = _sample_rec(1)
    bundle = DashboardBundle(
        generated_at="2026-04-02 10:00:00",
        recommendations=[rec],
        buy_today=[rec],
        break_risk=[rec],
        overstock=[],
    )
    return {
        "bundle": bundle,
        "names": {1: "Producto Test"},
        "quality": {},
        "top_profitable": [
            {
                "name": "Producto Test",
                "margin_unit": 3.0,
                "demand_daily": 1.2,
                "score_30d": 108.0,
            }
        ],
    }


def test_predictive_tab_load_and_render(qt_app) -> None:
    tab = PredictiveAnalyticsTab(_Manager())
    tab._on_worker_finished(_sample_payload())

    assert tab.lbl_red.text() == "Rojo: 1"
    assert tab.lbl_buy.text() == "Comprar hoy: 1"
    assert tab.tbl_buy.rowCount() == 1
    assert tab.tbl_profit.rowCount() == 1


def test_predictive_tab_manual_refresh_starts_worker(monkeypatch, qt_app) -> None:
    tab = PredictiveAnalyticsTab(_Manager())
    payload = _sample_payload()

    class _Signal:
        def __init__(self):
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self, value):
            for cb in self._callbacks:
                cb(value)

    class _Signals:
        def __init__(self):
            self.finished = _Signal()
            self.error = _Signal()

    class _FakeWorker:
        def __init__(self, db, *, start, end):
            assert isinstance(start, date)
            assert isinstance(end, date)
            self.signals = _Signals()

        def run(self):
            self.signals.finished.emit(payload)

    class _ImmediatePool:
        def start(self, worker):
            worker.run()

    monkeypatch.setattr(
        "analytics_predictive.presentation.predictive_tab._PredictiveWorker",
        _FakeWorker,
    )
    tab.thread_pool = _ImmediatePool()

    tab.refresh_analysis()

    assert tab._last_payload is payload
    assert "Analisis actualizado" in tab.status_label.text()


def test_predictive_tab_controlled_error(monkeypatch, qt_app) -> None:
    tab = PredictiveAnalyticsTab(_Manager())
    called = {"warn": False}

    def _fake_warning(*args, **kwargs):
        called["warn"] = True

    monkeypatch.setattr(
        "analytics_predictive.presentation.predictive_tab.QMessageBox.warning",
        _fake_warning,
    )

    tab._on_worker_error("boom")

    assert called["warn"] is True
    assert tab.status_label.text() == "Error al calcular analitica."
