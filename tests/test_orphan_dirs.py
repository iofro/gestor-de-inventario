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

def test_find_orphan_in_additional_dirs(qt_app, tmp_path, monkeypatch):
    cf_alt = tmp_path / "facturas" / "consumidor_final"
    cf_alt.mkdir(parents=True)
    json_path = cf_alt / "20240101_Test_1_ConsumidorFinal.json"
    json_path.write_text("{}")
    pdf_path = cf_alt / "20240101_Test_1_ConsumidorFinal.pdf"
    pdf_path.write_text("pdf")

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(tmp_path / "facturas_consumidor_final"))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(tmp_path / "facturas_credito_fiscal"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [str(cf_alt)])

    tab = facturacion_tab.FacturacionTab(man)
    orphans = tab._find_orphan_documents()
    assert any(o.get("json") == str(json_path) for o in orphans)


def test_pair_across_directories(qt_app, tmp_path, monkeypatch):
    pdf_dir = tmp_path / "facturas_consumidor_final"
    pdf_dir.mkdir()
    json_dir = tmp_path / "facturas" / "consumidor_final"
    json_dir.mkdir(parents=True)

    pdf_path = pdf_dir / "20240102_Test_2_ConsumidorFinal.pdf"
    pdf_path.write_text("pdf")
    json_path = json_dir / "20240102_Test_2_ConsumidorFinal.json"
    json_path.write_text("{}")

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(pdf_dir))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(tmp_path / "facturas_credito_fiscal"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [str(json_dir)])

    tab = facturacion_tab.FacturacionTab(man)
    orphans = tab._find_orphan_documents()
    match = next((o for o in orphans if o.get("name") == "20240102_Test_2_ConsumidorFinal"), None)
    assert match
    assert match.get("pdf") == str(pdf_path)
    assert match.get("json") == str(json_path)
