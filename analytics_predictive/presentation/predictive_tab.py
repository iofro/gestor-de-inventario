from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, Qt, QDate, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..data.read_only_repository import ReadOnlyRepository
from ..pipeline import PredictiveAnalyticsService


class _WorkerSignals(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)


class _PredictiveWorker(QRunnable):
    def __init__(self, db: Any, *, start: date | None, end: date | None) -> None:
        super().__init__()
        self.db = db
        self.start = start
        self.end = end
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            repo = ReadOnlyRepository(self.db)
            service = PredictiveAnalyticsService(repo)
            extracted = repo.extract_historical_data(start=self.start, end=self.end)
            bundle = service.run_from_extracted(extracted)

            names = {
                pid: snap.name
                for pid, snap in extracted.stock_by_product.items()
            }

            top_profitable = []
            forecast_map = {f.product_id: f for f in bundle.forecasts}
            for pid, snap in extracted.stock_by_product.items():
                f = forecast_map.get(pid)
                if f is None:
                    continue
                margin_unit = max(float(snap.sale_price) - float(snap.cost_unit), 0.0)
                score = margin_unit * max(float(f.demand_daily_avg), 0.0) * 30.0
                top_profitable.append(
                    {
                        "product_id": pid,
                        "name": snap.name,
                        "margin_unit": margin_unit,
                        "demand_daily": float(f.demand_daily_avg),
                        "score_30d": score,
                    }
                )
            top_profitable.sort(key=lambda x: x["score_30d"], reverse=True)

            self.signals.finished.emit(
                {
                    "bundle": bundle,
                    "names": names,
                    "quality": dict(extracted.quality),
                    "top_profitable": top_profitable[:20],
                }
            )
        except Exception as exc:
            self.signals.error.emit(str(exc))


class PredictiveAnalyticsTab(QWidget):
    """Pestana de analitica predictiva con carga bajo demanda."""

    def __init__(self, manager: Any, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.thread_pool = QThreadPool.globalInstance()
        self._last_payload: dict | None = None
        self._loading = False
        self._cache: dict[tuple[str, str], tuple[datetime, dict]] = {}
        self._cache_ttl_seconds = 120

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Analitica Predictiva")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        root.addWidget(title)

        controls = QFrame()
        controls.setObjectName("ModernCard")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(14, 14, 14, 14)
        controls_layout.setSpacing(10)

        controls_layout.addWidget(QLabel("Horizonte:"))
        self.horizon_combo = QComboBox()
        self.horizon_combo.addItems(["7", "15", "30"])
        controls_layout.addWidget(self.horizon_combo)

        controls_layout.addWidget(QLabel("Periodo:"))
        self.period_combo = QComboBox()
        self.period_combo.addItem("Ultimos 30 dias", 30)
        self.period_combo.addItem("Ultimos 60 dias", 60)
        self.period_combo.addItem("Ultimos 90 dias", 90)
        controls_layout.addWidget(self.period_combo)

        controls_layout.addStretch(1)
        self.refresh_btn = QPushButton("Actualizar analisis")
        self.refresh_btn.clicked.connect(self.refresh_analysis)
        controls_layout.addWidget(self.refresh_btn)

        root.addWidget(controls)

        summary = QFrame()
        summary.setObjectName("ModernCard")
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(14, 14, 14, 14)
        summary_layout.setHorizontalSpacing(10)
        summary_layout.setVerticalSpacing(8)

        self.lbl_red = QLabel("Rojo: 0")
        self.lbl_red.setStyleSheet("background:#FEE2E2; color:#991B1B; padding:8px; border-radius:6px;")
        self.lbl_yellow = QLabel("Amarillo: 0")
        self.lbl_yellow.setStyleSheet("background:#FEF3C7; color:#92400E; padding:8px; border-radius:6px;")
        self.lbl_green = QLabel("Verde: 0")
        self.lbl_green.setStyleSheet("background:#DCFCE7; color:#166534; padding:8px; border-radius:6px;")
        self.lbl_buy = QLabel("Comprar hoy: 0")
        self.lbl_break = QLabel("Riesgo quiebre: 0")
        self.lbl_over = QLabel("Sobrestock: 0")

        summary_layout.addWidget(self.lbl_red, 0, 0)
        summary_layout.addWidget(self.lbl_yellow, 0, 1)
        summary_layout.addWidget(self.lbl_green, 0, 2)
        summary_layout.addWidget(self.lbl_buy, 1, 0)
        summary_layout.addWidget(self.lbl_break, 1, 1)
        summary_layout.addWidget(self.lbl_over, 1, 2)
        root.addWidget(summary)

        self.status_label = QLabel("Sin datos. Presiona 'Actualizar analisis'.")
        self.status_label.setStyleSheet("color:#4b5563;")
        root.addWidget(self.status_label)

        self.tbl_buy = self._make_table(["Producto", "Prioridad", "ABC", "Sugerido", "Justificacion"])
        self.tbl_break = self._make_table(["Producto", "Cobertura", "Prioridad", "ABC", "Justificacion"])
        self.tbl_over = self._make_table(["Producto", "Cobertura", "Prioridad", "ABC", "Justificacion"])
        self.tbl_profit = self._make_table(["Producto", "Margen unit.", "Demanda diaria", "Impacto 30d"])

        root.addWidget(QLabel("Comprar hoy"))
        root.addWidget(self.tbl_buy)
        root.addWidget(QLabel("Riesgo de quiebre"))
        root.addWidget(self.tbl_break)
        root.addWidget(QLabel("Sobrestock"))
        root.addWidget(self.tbl_over)
        root.addWidget(QLabel("Top productos rentables"))
        root.addWidget(self.tbl_profit)

    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def refresh_analysis(self) -> None:
        if self._loading:
            return
        days = int(self.period_combo.currentData())
        end = date.today()
        start = end - timedelta(days=max(days - 1, 0))
        cache_key = (start.isoformat(), end.isoformat())

        cached = self._cache.get(cache_key)
        if cached is not None:
            ts, payload = cached
            age = (datetime.now() - ts).total_seconds()
            if age <= self._cache_ttl_seconds:
                self._on_worker_finished(payload)
                self.status_label.setText(
                    f"Analisis cargado desde cache ({int(age)}s). "
                    f"Productos analizados: {len(payload.get('bundle').recommendations) if payload.get('bundle') else 0}"
                )
                return

        self._loading = True
        self.refresh_btn.setEnabled(False)
        self.status_label.setText("Calculando analitica predictiva...")

        worker = _PredictiveWorker(self.manager.db, start=start, end=end)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def _on_worker_error(self, message: str) -> None:
        self._loading = False
        self.refresh_btn.setEnabled(True)
        self.status_label.setText("Error al calcular analitica.")
        QMessageBox.warning(
            self,
            "Analitica predictiva",
            f"No se pudo calcular el analisis:\n{message}",
        )

    def _on_worker_finished(self, payload: dict) -> None:
        self._loading = False
        self.refresh_btn.setEnabled(True)
        self._last_payload = payload

        days = int(self.period_combo.currentData())
        end = date.today()
        start = end - timedelta(days=max(days - 1, 0))
        self._cache[(start.isoformat(), end.isoformat())] = (datetime.now(), payload)

        bundle = payload.get("bundle")
        names = payload.get("names") or {}
        top_profitable = payload.get("top_profitable") or []

        if bundle is None:
            self.status_label.setText("No se recibieron datos de analitica.")
            return

        red = sum(1 for r in bundle.recommendations if r.level == "red")
        yellow = sum(1 for r in bundle.recommendations if r.level == "yellow")
        green = sum(1 for r in bundle.recommendations if r.level == "green")

        self.lbl_red.setText(f"Rojo: {red}")
        self.lbl_yellow.setText(f"Amarillo: {yellow}")
        self.lbl_green.setText(f"Verde: {green}")
        self.lbl_buy.setText(f"Comprar hoy: {len(bundle.buy_today)}")
        self.lbl_break.setText(f"Riesgo quiebre: {len(bundle.break_risk)}")
        self.lbl_over.setText(f"Sobrestock: {len(bundle.overstock)}")

        horizon = int(self.horizon_combo.currentText())

        self._fill_buy_table(bundle.buy_today, names, horizon)
        self._fill_break_table(bundle.break_risk, names)
        self._fill_over_table(bundle.overstock, names)
        self._fill_profit_table(top_profitable)

        self.status_label.setText(
            f"Analisis actualizado: {bundle.generated_at}. "
            f"Productos analizados: {len(bundle.recommendations)}"
        )

    def _fill_buy_table(self, rows: list, names: dict, horizon: int) -> None:
        self.tbl_buy.setRowCount(len(rows))
        for i, r in enumerate(rows):
            suggested = float(r.suggested_by_horizon.get(horizon, 0.0))
            self.tbl_buy.setItem(i, 0, QTableWidgetItem(str(names.get(r.product_id, f"Producto {r.product_id}"))))
            self.tbl_buy.setItem(i, 1, QTableWidgetItem(f"{r.priority_score:.2f}"))
            self.tbl_buy.setItem(i, 2, QTableWidgetItem(r.abc_class))
            self.tbl_buy.setItem(i, 3, QTableWidgetItem(f"{suggested:.2f}"))
            self.tbl_buy.setItem(i, 4, QTableWidgetItem(r.explanation))

    def _fill_break_table(self, rows: list, names: dict) -> None:
        self.tbl_break.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.tbl_break.setItem(i, 0, QTableWidgetItem(str(names.get(r.product_id, f"Producto {r.product_id}"))))
            self.tbl_break.setItem(i, 1, QTableWidgetItem(f"{r.coverage_days:.2f}"))
            self.tbl_break.setItem(i, 2, QTableWidgetItem(f"{r.priority_score:.2f}"))
            self.tbl_break.setItem(i, 3, QTableWidgetItem(r.abc_class))
            self.tbl_break.setItem(i, 4, QTableWidgetItem(r.explanation))

    def _fill_over_table(self, rows: list, names: dict) -> None:
        self.tbl_over.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.tbl_over.setItem(i, 0, QTableWidgetItem(str(names.get(r.product_id, f"Producto {r.product_id}"))))
            self.tbl_over.setItem(i, 1, QTableWidgetItem(f"{r.coverage_days:.2f}"))
            self.tbl_over.setItem(i, 2, QTableWidgetItem(f"{r.priority_score:.2f}"))
            self.tbl_over.setItem(i, 3, QTableWidgetItem(r.abc_class))
            self.tbl_over.setItem(i, 4, QTableWidgetItem(r.explanation))

    def _fill_profit_table(self, rows: list[dict]) -> None:
        self.tbl_profit.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.tbl_profit.setItem(i, 0, QTableWidgetItem(str(r.get("name") or "")))
            self.tbl_profit.setItem(i, 1, QTableWidgetItem(f"{float(r.get('margin_unit') or 0.0):.2f}"))
            self.tbl_profit.setItem(i, 2, QTableWidgetItem(f"{float(r.get('demand_daily') or 0.0):.2f}"))
            self.tbl_profit.setItem(i, 3, QTableWidgetItem(f"{float(r.get('score_30d') or 0.0):.2f}"))
