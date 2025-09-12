import os
from types import SimpleNamespace
import json
import pytest
from PyQt5.QtWidgets import QApplication

import facturacion_tab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _make_invoice(dir_path, base):
    (dir_path / f"{base}.pdf").write_text("pdf")
    # minimal json to satisfy scanner
    js = {"identificacion": {"numeroControl": base, "tipoDte": "01", "fecEmi": "2024-01-01"},
          "receptor": {"nombre": "Cliente"},
          "resumen": {"totalPagar": 1}}
    (dir_path / f"{base}.json").write_text(json.dumps(js))


def test_sent_filter_shows_accepted_and_rejected(qt_app, tmp_path, monkeypatch):
    inv_dir = tmp_path / "facturas_consumidor_final"
    inv_dir.mkdir()
    bases = [
        "20240101_Test_1_ConsumidorFinal",
        "20240102_Test_2_ConsumidorFinal",
        "20240103_Test_3_ConsumidorFinal",
    ]
    for b in bases:
        _make_invoice(inv_dir, b)

    db = DB(":memory:")
    db.cursor.execute("INSERT INTO clientes (id, nombre) VALUES (1, 'Alice')")
    db.conn.commit()
    ventas = []
    for idx, b in enumerate(bases, start=1):
        v = db.add_venta("2024-01-0{}".format(idx), idx * 10, cliente_id=1)
        db.add_factura_pdf(v, "ConsumidorFinal", str(inv_dir / f"{b}.pdf"))
        ventas.append(v)
    db.registrar_envio_dte(ventas[0], "normal", "Aceptado", "S", "{}")
    db.registrar_envio_dte(ventas[1], "normal", "Rechazado", "", "error")

    manager = SimpleNamespace(db=db, _clientes=[{"id": 1, "nombre": "Alice"}])

    # patch directories so scanner only sees our temp dir
    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(inv_dir))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(inv_dir))
    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(inv_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_DEBITO_DIR", str(inv_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_CREDITO_DIR", str(inv_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_REMISION_DIR", str(inv_dir))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    tab = facturacion_tab.FacturacionTab(manager)
    tab.load_invoices()
    assert tab.table.rowCount() == 3
    estados = {tab.table.item(r, 4).text() for r in range(tab.table.rowCount())}
    assert "Aceptado" in estados
    assert "Rechazado" in estados

    tab.sent_filter_cb.setChecked(True)
    tab.load_invoices()
    assert tab.table.rowCount() == 2
    estados = {tab.table.item(r, 4).text() for r in range(tab.table.rowCount())}
    assert estados == {"Aceptado", "Rechazado"}
