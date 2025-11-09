from __future__ import annotations

import sys
import types


def _install_fake_pyqt(monkeypatch):
    pyqt_mod = types.ModuleType("PyQt5")
    qtcore_mod = types.ModuleType("PyQt5.QtCore")
    qtgui_mod = types.ModuleType("PyQt5.QtGui")

    class _FakeModel:
        pass

    qtcore_mod.QAbstractTableModel = _FakeModel
    qtcore_mod.Qt = types.SimpleNamespace(DisplayRole=0, DecorationRole=1)
    qtgui_mod.QColor = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "PyQt5", pyqt_mod)
    monkeypatch.setitem(sys.modules, "PyQt5.QtCore", qtcore_mod)
    monkeypatch.setitem(sys.modules, "PyQt5.QtGui", qtgui_mod)


def test_inventory_manager_anexo_methods_use_dte_provider(monkeypatch, db_conn):
    _install_fake_pyqt(monkeypatch)

    import inventory_manager

    fake_rows = [{"venta_id": 1}]
    calls = {"rows": [], "i": 0, "ii": 0, "xix": 0}

    def fake_get_rows(db, periodo):
        calls["rows"].append(periodo)
        assert db is db_conn
        return fake_rows

    def fake_build_i(rows, db):
        calls["i"] += 1
        assert rows is fake_rows
        assert db is db_conn
        return ["I"]

    def fake_build_ii(rows, db):
        calls["ii"] += 1
        assert rows is fake_rows
        assert db is db_conn
        return ["II"]

    def fake_build_xix(periodo):
        calls["xix"] += 1
        assert periodo == "202401"
        return ["XIX"]

    monkeypatch.setattr(
        inventory_manager.dte_provider,
        "get_facturacion_rows",
        fake_get_rows,
    )
    monkeypatch.setattr(
        inventory_manager.dte_provider,
        "build_anexo_i_contribuyentes",
        fake_build_i,
    )
    monkeypatch.setattr(
        inventory_manager.dte_provider,
        "build_anexo_i_consumidor",
        fake_build_ii,
    )
    monkeypatch.setattr(
        inventory_manager.dte_provider,
        "build_anexo_i_anulados",
        fake_build_xix,
    )

    manager = inventory_manager.InventoryManager(db_conn)

    assert manager.get_anexo_contribuyentes_registros("202401") == ["I"]
    assert manager.get_anexo_consumidor_final_registros("202401") == ["II"]
    assert manager.get_anexo_xix_registros("202401") == ["XIX"]
    assert calls["rows"] == ["202401", "202401"]
    assert calls["i"] == 1
    assert calls["ii"] == 1
    assert calls["xix"] == 1
