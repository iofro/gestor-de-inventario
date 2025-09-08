import os
import json
import pytest
from types import SimpleNamespace
from PyQt5.QtWidgets import QApplication

import facturacion_tab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _make_note(dir_path, base, tipo, total):
    pdf_path = dir_path / f"{base}.pdf"
    pdf_path.write_text("pdf")
    js = {
        "identificacion": {"numeroControl": base, "fecEmi": "2024-01-01"},
        "receptor": {"nombre": "Cliente"},
        "resumen": {"montoTotalOperacion": total},
    }
    (dir_path / f"{base}.json").write_text(json.dumps(js))


def test_scan_and_format_note_totals(qt_app, tmp_path, monkeypatch):
    nd_dir = tmp_path / "notas_debito"
    nd_dir.mkdir()
    nc_dir = tmp_path / "notas_credito"
    nc_dir.mkdir()
    _make_note(nc_dir, "20240101_Test_1_NotaCredito", "NotaCredito", 5)
    _make_note(nd_dir, "20240102_Test_1_NotaDebito", "NotaDebito", 7)

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])
    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(tmp_path / "cf"))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(tmp_path / "cf2"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_DEBITO_DIR", str(nd_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_CREDITO_DIR", str(nc_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_REMISION_DIR", str(tmp_path / "nr"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])
    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(tmp_path / "tickets"))

    tab = facturacion_tab.FacturacionTab(man)

    docs = {d["name"]: d for d in tab._scan_documents()}
    assert docs["20240101_Test_1_NotaCredito"]["total"] == 5
    assert docs["20240101_Test_1_NotaCredito"]["sign"] == -1
    assert docs["20240102_Test_1_NotaDebito"]["total"] == 7
    assert docs["20240102_Test_1_NotaDebito"]["sign"] == 1

    tab.load_invoices()
    totals = {tab.table.item(r, 0).text(): tab.table.item(r, 3).text() for r in range(tab.table.rowCount())}
    assert totals["20240101_Test_1_NotaCredito"] == "−$5.00"
    assert totals["20240102_Test_1_NotaDebito"] == "+$7.00"
