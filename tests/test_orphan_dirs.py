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
    json_path = cf_alt / "orphan.json"
    json_path.write_text("{}")

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(tmp_path / "facturas_consumidor_final"))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(tmp_path / "facturas_credito_fiscal"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [str(cf_alt)])

    tab = facturacion_tab.FacturacionTab(man)
    orphans = tab._find_orphan_documents()
    assert any(o.get("json") == str(json_path) for o in orphans)
