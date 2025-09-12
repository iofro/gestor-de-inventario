import os
import json
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QApplication, QDialogButtonBox

import facturacion_tab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _create_sale(db):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "C1", None, vid, None, 0, 10, 10, 1)
    pid = db.cursor.lastrowid
    db.add_cliente("C", "", "", "", "", "", "c@x.com", "", "", "")
    cid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cid, vendedor_id=vid)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id, cid


def test_double_click_shows_anular_button(qt_app, tmp_path, monkeypatch):
    invoice_dir = tmp_path / "invoices"
    invoice_dir.mkdir()
    for name in [
        "CF_DIR",
        "CREDITO_DIR",
        "TICKETS_DIR",
        "NOTAS_DEBITO_DIR",
        "NOTAS_CREDITO_DIR",
        "NOTAS_REMISION_DIR",
    ]:
        monkeypatch.setattr(facturacion_tab, name, str(invoice_dir))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    manager = SimpleNamespace(db=db, _clientes=[{"id": cid, "nombre": "C"}], _Distribuidores=[])
    tab = facturacion_tab.FacturacionTab(manager)

    data = {
        "cuerpoDocumento": [],
        "resumen": {},
        "identificacion": {"numeroControl": "NC123"},
    }
    json_path = tmp_path / "factura.json"
    json_path.write_text(json.dumps(data))

    monkeypatch.setattr(
        tab,
        "_selected_factura",
        lambda: {"venta_id": venta_id, "json": str(json_path), "control": "NC123"},
    )

    created = []
    OrigDialog = facturacion_tab.InvoiceDetailDialog

    class RecordingDialog(OrigDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)
        def exec_(self):
            return 0

    monkeypatch.setattr(facturacion_tab, "InvoiceDetailDialog", RecordingDialog)

    tab.mostrar_detalle_factura()

    assert created, "dialog should be created"
    buttons = created[0].findChild(QDialogButtonBox)
    assert any(b.text() == "Anular factura" for b in buttons.buttons())
