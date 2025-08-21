from types import SimpleNamespace
import json
import os
from pathlib import Path
import pytest
from PyQt5.QtWidgets import QApplication

import facturacion_tab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _create_sale(db):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "C1", vid, None, 0, 10, 10, 1)
    pid = db.cursor.lastrowid
    db.add_cliente("C", "", "", "", "", "", "c@x.com", "", "", "")
    cid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cid, vendedor_id=vid)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id, cid


def test_create_nota_generates_sobre(qt_app, tmp_path, monkeypatch):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    db.cursor.execute("UPDATE ventas SET extra=? WHERE id=?", (json.dumps({"ambiente": "01"}), venta_id))
    man = SimpleNamespace(db=db, _clientes=[{"id": cid, "nombre": "C"}], _Distribuidores=[])
    tab = facturacion_tab.FacturacionTab(man)
    monkeypatch.setattr(tab, "_selected_venta", lambda: venta_id)

    base = tmp_path / "nota"

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        return str(base.with_suffix(".pdf")), str(base.with_suffix(".json"))

    monkeypatch.setattr(facturacion_tab, "get_document_paths", fake_paths)
    monkeypatch.setattr(facturacion_tab, "NOTAS_CREDITO_DIR", str(tmp_path))
    monkeypatch.setattr(facturacion_tab, "NOTAS_DEBITO_DIR", str(tmp_path))
    monkeypatch.setattr(facturacion_tab, "NOTAS_REMISION_DIR", str(tmp_path))

    monkeypatch.setattr(facturacion_tab, "generar_nota_credito_pdf", lambda *a, archivo=None, **k: Path(archivo).write_text("PDF"))

    def fake_json(db, nota_id):
        return {
            "identificacion": {
                "version": "1",
                "tipoDte": "05",
                "codigoGeneracion": "XYZ",
                "numeroControl": "NCF-001",
            }
        }

    monkeypatch.setattr(facturacion_tab, "generar_nota_credito_json", fake_json)
    monkeypatch.setattr("utils.jws.sign_json", lambda *a, **k: "a.b.c")

    def fake_sobre(jws, dte_json):
        ident = dte_json["identificacion"]
        return {
            "ambiente": ident.get("ambiente", "00"),
            "idEnvio": 1,
            "version": ident.get("version"),
            "tipoDte": ident.get("tipoDte"),
            "codigoGeneracion": ident.get("codigoGeneracion"),
            "documento": jws,
        }

    monkeypatch.setattr(facturacion_tab.dte, "construir_sobre_recepcion", fake_sobre)
    monkeypatch.setattr(facturacion_tab.QInputDialog, "getDouble", lambda *a, **k: (1.0, True))
    monkeypatch.setattr(facturacion_tab.QInputDialog, "getText", lambda *a, **k: ("motivo", True))
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)

    tab.create_nota("credito")

    assert base.with_suffix(".pdf").exists()
    assert base.with_suffix(".json").exists()
    assert base.with_suffix(".jws").exists()
    sobre_path = base.with_name(base.name + "-sobre.json")
    assert sobre_path.exists()
    data = json.loads(sobre_path.read_text())
    assert data["documento"] == "a.b.c"
    assert data["ambiente"] == "01"
    assert data["idEnvio"] >= 1
