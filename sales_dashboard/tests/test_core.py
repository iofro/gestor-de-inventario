from __future__ import annotations

from datetime import datetime

import pandas as pd

from sales_dashboard.core.calculations import (
    calcContribucion,
    calcTicketPromedio,
    sortTopProducts,
)
from sales_dashboard.core.data_loader import filter_by_period, load_sales_data
from sales_dashboard.core.formatters import format_currency, format_date, format_percentage
from sales_dashboard.core.metrics import build_dashboard_data, compute_financial_report


def test_calc_ticket_promedio_rounds_correctly() -> None:
    assert calcTicketPromedio(122.48, 34) == 3.6


def test_calc_contribucion_handles_zero() -> None:
    assert calcContribucion(100.0, 0.0) == 0.0


def test_sort_top_products_deterministic_order() -> None:
    data = [
        {"producto": "Alpha", "ventas": 100, "margen": 10},
        {"producto": "Beta", "ventas": 100, "margen": 10},
        {"producto": "Gamma", "ventas": 90, "margen": 9},
    ]
    ordered = sortTopProducts(data, "ventas")
    assert [item["producto"] for item in ordered] == ["Alpha", "Beta", "Gamma"]


def test_formatters_expected_output() -> None:
    assert format_currency(12345.67) == "$ 12,345.67"
    assert format_percentage(0.436) == "43.6%"
    assert format_date(datetime(2025, 10, 13)) == "13/10/2025"


def test_load_sales_data_computes_total(tmp_path) -> None:
    df = pd.DataFrame(
        {
            "fecha": ["2025-01-01", "2025-01-02"],
            "producto": ["Alpha", "Beta"],
            "canal": ["Online", "Tienda"],
            "unidades": [2, 1],
            "precio_unit": [5.0, 3.0],
            "costo_unit": [2.0, 1.0],
        }
    )
    csv_path = tmp_path / "data.csv"
    df.to_csv(csv_path, index=False)
    dataset = load_sales_data(csv_path)
    assert "total" in dataset.raw
    assert dataset.raw.loc[0, "total"] == 10.0
    filtered = filter_by_period(dataset, datetime(2025, 1, 2), datetime(2025, 1, 2))
    assert len(filtered) == 1


def test_compute_financial_report_returns_totals() -> None:
    df = pd.DataFrame(
        {
            "fecha": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-02"]),
            "producto": ["A", "B", "C"],
            "canal": ["Online", "Tienda", "Online"],
            "unidades": [2, 1, 3],
            "precio_unit": [5.0, 10.0, 2.0],
            "costo_unit": [2.0, 4.0, 1.0],
            "total": [10.0, 10.0, 6.0],
        }
    )
    report = compute_financial_report(df)
    assert list(report.columns) == ["periodo", "ingresos", "gastos", "resultado"]
    assert len(report) == 3
    assert report.iloc[-1]["periodo"] == "Total"
    assert report.iloc[-1]["ingresos"] == 26.0
    assert report.iloc[-1]["gastos"] == 11.0
    assert report.iloc[-1]["resultado"] == 15.0


def test_build_dashboard_data_includes_financial_report() -> None:
    df = pd.DataFrame(
        {
            "fecha": pd.to_datetime(["2025-01-01", "2025-01-02"]),
            "producto": ["A", "B"],
            "canal": ["Online", "Tienda"],
            "unidades": [1, 2],
            "precio_unit": [5.0, 4.0],
            "costo_unit": [2.0, 1.5],
            "total": [5.0, 8.0],
        }
    )
    data = build_dashboard_data(df, "ventas")
    assert not data.financial_report.empty
    assert set(["ingresos", "gastos", "resultado"]).issubset(data.financial_report.columns)
