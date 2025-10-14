from datetime import date

import pytest


def _add_product(db, nombre, codigo, sku, precio_compra, stock):
    db.add_producto(
        nombre,
        codigo,
        sku,
        None,
        None,
        precio_compra,
        precio_compra * 2 if precio_compra else 0,
        precio_compra * 2 if precio_compra else 0,
        stock,
    )
    return db.cursor.lastrowid


def test_get_sales_statistics_filters_and_groups(db_conn):
    db = db_conn

    db.add_trabajador({"nombre": "Ana", "codigo": "V001", "es_vendedor": True})
    vendedor_id = db.cursor.lastrowid

    prod_a = _add_product(db, "Producto A", "A", "SKU-A", precio_compra=5, stock=100)
    prod_b = _add_product(db, "Producto B", "B", "SKU-B", precio_compra=2, stock=100)
    _add_product(db, "Producto Crítico", "C", "SKU-C", precio_compra=1, stock=3)

    venta1 = db.add_venta("2024-01-10", 60, vendedor_id=vendedor_id)
    db.add_detalle_venta(venta1, prod_a, 3, 10, vendedor_id=vendedor_id)
    db.add_detalle_venta(venta1, prod_b, 2, 15, vendedor_id=vendedor_id)

    venta2 = db.add_venta("2024-02-05", 40)
    db.add_detalle_venta(venta2, prod_b, 4, 10)

    venta3 = db.add_venta("2023-12-15", 30, vendedor_id=vendedor_id)
    db.add_detalle_venta(venta3, prod_a, 2, 15, vendedor_id=vendedor_id)

    stats = db.get_sales_statistics(date(2024, 1, 1), date(2024, 12, 31))

    summary = stats["summary"]
    assert summary["total_transactions"] == 2
    assert summary["total_sales"] == pytest.approx(100)
    assert summary["average_ticket"] == pytest.approx(50)
    assert summary["total_costs"] == pytest.approx(27)
    assert summary["gross_margin"] == pytest.approx(73)

    monthly = stats["periods"]["monthly"]
    assert [row["period"] for row in monthly] == ["2024-02", "2024-01"]

    top_products = stats["top_products"]
    assert top_products[0]["name"] == "Producto B"
    assert top_products[0]["units"] == pytest.approx(6)

    channels = {row["channel"]: row for row in stats["sales_by_channel"]}
    assert channels["Ana"]["total"] == pytest.approx(60)
    assert channels["Sin vendedor"]["total"] == pytest.approx(40)

    critical = stats["critical_stock"]
    assert any(row["name"] == "Producto Crítico" for row in critical)


def test_get_sales_statistics_handles_legacy_schema(monkeypatch, db_conn):
    db = db_conn

    prod = _add_product(db, "Producto Legacy", "L", "SKU-L", precio_compra=4, stock=2)
    venta = db.add_venta("2024-03-01", 25)
    db.add_detalle_venta(venta, prod, 5, 5)

    original_has_column = db._has_column
    original_has_table = db._has_table

    def fake_has_column(table, column):
        if (table, column) in {
            ("ventas", "sincronizada"),
            ("productos", "precio_compra"),
            ("productos", "stock"),
        }:
            return False
        return original_has_column(table, column)

    def fake_has_table(table):
        if table == "trabajadores":
            return False
        return original_has_table(table)

    monkeypatch.setattr(db, "_has_column", fake_has_column)
    monkeypatch.setattr(db, "_has_table", fake_has_table)

    stats = db.get_sales_statistics(None, None)

    summary = stats["summary"]
    assert summary["total_sales"] == pytest.approx(25)
    assert summary["total_transactions"] == 1
    assert summary["average_ticket"] == pytest.approx(25)
    assert summary["total_costs"] == pytest.approx(0)
    assert summary["gross_margin"] == pytest.approx(25)

    top_products = stats["top_products"]
    assert top_products
    assert top_products[0]["name"] == "Producto Legacy"
    assert top_products[0]["margin"] == pytest.approx(25)

    assert stats["critical_stock"] == []

    channels = stats["sales_by_channel"]
    assert len(channels) == 1
    channel = channels[0]
    assert channel["channel"] == "Sin vendedor"
    assert channel["transactions"] == 1
    assert channel["total"] == pytest.approx(25)
    assert channel["average_ticket"] == pytest.approx(25)
