import json
import importlib.machinery
import sys
import types

import pytest


def _install_qt_stubs():
    for name in list(sys.modules):
        if name.startswith("PyQt5"):
            sys.modules.pop(name, None)

    qt = types.ModuleType("PyQt5")
    qt.__path__ = []
    qt.__spec__ = importlib.machinery.ModuleSpec("PyQt5", loader=None, is_package=True)

    qtcore = types.ModuleType("PyQt5.QtCore")
    qtcore.__spec__ = importlib.machinery.ModuleSpec("PyQt5.QtCore", loader=None)
    qtgui = types.ModuleType("PyQt5.QtGui")
    qtgui.__spec__ = importlib.machinery.ModuleSpec("PyQt5.QtGui", loader=None)

    class _DummyModel:
        def __init__(self, *args, **kwargs):
            pass

        def beginResetModel(self):
            pass

        def endResetModel(self):
            pass

    class _QtNamespace:
        DisplayRole = 0
        BackgroundRole = 1
        Horizontal = 1

    class _DummyColor:
        def __init__(self, *args, **kwargs):
            pass

    qtcore.QAbstractTableModel = _DummyModel
    qtcore.Qt = _QtNamespace
    qtgui.QColor = _DummyColor
    qt.QtCore = qtcore
    qt.QtGui = qtgui

    sys.modules["PyQt5"] = qt
    sys.modules["PyQt5.QtCore"] = qtcore
    sys.modules["PyQt5.QtGui"] = qtgui


InventoryManagerError = None


def _create_manager():
    global InventoryManagerError
    _install_qt_stubs()
    from inventory_manager import InventoryManager, InventoryManagerError as _InventoryManagerError
    from db import DB

    InventoryManagerError = _InventoryManagerError
    return InventoryManager(DB(":memory:"))


def test_export_normalizes_blank_sku(tmp_path):
    manager = _create_manager()
    manager.add_producto("Producto A", "A1", "", None, None, 0, 0, 0, 0)
    manager.add_producto("Producto B", "B1", "   ", None, None, 0, 0, 0, 0)
    manager.add_producto("Producto C", "C1", "\t ", None, None, 0, 0, 0, 0)

    manager.db.cursor.execute("SELECT sku FROM productos ORDER BY id")
    stored_skus = [row[0] for row in manager.db.cursor.fetchall()]
    assert stored_skus == [None, None, None]

    export_path = tmp_path / "inventario.json"
    manager.exportar_inventario_json(str(export_path))

    data = json.loads(export_path.read_text(encoding="utf-8"))
    exported_skus = [item["sku"] for item in data["productos"]]
    assert exported_skus == [None, None, None]

    imported = _create_manager()
    imported.importar_inventario_json(str(export_path))


def test_export_adds_missing_vendor_entries(tmp_path):
    manager = _create_manager()
    manager.add_producto("Producto", "P1", None, None, None, 0, 0, 0, 0)

    db = manager.db
    db.add_trabajador({"codigo": "T-001", "nombre": "Francisco", "es_vendedor": True})
    trabajador_id = db.get_trabajadores()[0]["id"]

    assert all(v["id"] != trabajador_id for v in db.get_vendedores())

    db.add_venta("2025-01-01 00:00:00", 10, vendedor_id=trabajador_id)
    manager.refresh_data()

    export_path = tmp_path / "inventario_vendedor.json"
    manager.exportar_inventario_json(str(export_path))

    data = json.loads(export_path.read_text(encoding="utf-8"))
    vendor_ids = {v["id"] for v in data["vendedores"]}
    assert trabajador_id in vendor_ids
    vendedor = next(v for v in data["vendedores"] if v["id"] == trabajador_id)
    assert vendedor["codigo"] == "T-001"

    imported = _create_manager()
    imported.importar_inventario_json(str(export_path))


def test_export_fails_for_unknown_vendor(tmp_path):
    manager = _create_manager()
    db = manager.db
    db.add_venta("2025-02-01 00:00:00", 5, vendedor_id=999)
    manager.refresh_data()

    export_path = tmp_path / "inventario_error.json"
    with pytest.raises(InventoryManagerError) as exc:
        manager.exportar_inventario_json(str(export_path))
    assert "vendedor inexistente" in str(exc.value)
    assert not export_path.exists()


def test_export_backfills_legacy_sincronizada(tmp_path):
    manager = _create_manager()
    db = manager.db
    venta_id = db.add_venta("2025-03-01 00:00:00", 15)
    db.cursor.execute("UPDATE ventas SET sincronizada=NULL WHERE id=?", (venta_id,))
    db.conn.commit()
    manager.refresh_data()

    export_path = tmp_path / "inventario_legacy.json"
    manager.exportar_inventario_json(str(export_path))

    data = json.loads(export_path.read_text(encoding="utf-8"))
    ventas_ids = [v["id"] for v in data["ventas"]]
    assert venta_id in ventas_ids
