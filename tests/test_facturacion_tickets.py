import os
import pytest
from PyQt5.QtWidgets import QApplication
from types import SimpleNamespace

import facturacion_tab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_documents_listed_from_files(qt_app, tmp_path, monkeypatch):
    cf_dir = tmp_path / "facturas_consumidor_final"
    cf_dir.mkdir()
    pdf_path = cf_dir / "20240101_Test_1_ConsumidorFinal.pdf"
    pdf_path.write_text("pdf")
    json_path = cf_dir / "20240101_Test_1_ConsumidorFinal.json"
    json_path.write_text("{}")

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(cf_dir))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(tmp_path / "facturas_credito_fiscal"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_DEBITO_DIR", str(tmp_path / "notas_debito"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    tab = facturacion_tab.FacturacionTab(man)
    docs = tab._scan_documents()
    assert any(d.get("pdf") == str(pdf_path) for d in docs)


def test_document_marked_incomplete_when_missing_pair(qt_app, tmp_path, monkeypatch):
    cf_dir = tmp_path / "facturas_credito_fiscal"
    cf_dir.mkdir()
    pdf_path = cf_dir / "20240102_Test_2_CreditoFiscal.pdf"
    pdf_path.write_text("pdf")

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(tmp_path / "facturas_consumidor_final"))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(cf_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_DEBITO_DIR", str(tmp_path / "notas_debito"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    tab = facturacion_tab.FacturacionTab(man)
    docs = tab._scan_documents()
    match = next(d for d in docs if d.get("pdf") == str(pdf_path))
    assert match.get("estado") == "Incompleta"
