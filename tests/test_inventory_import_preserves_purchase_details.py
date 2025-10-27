import json
import sys
import types
import importlib.machinery


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


def test_export_and_import_preserve_purchase_details(tmp_path):
    _install_qt_stubs()

    from inventory_manager import InventoryManager
    from db import DB

    manager = InventoryManager(DB(":memory:"))
    manager.db.add_Distribuidor("Distribuidor")
    dist_id = manager.db.cursor.lastrowid
    manager.db.add_vendedor("Proveedor")
    vendor_id = manager.db.cursor.lastrowid
    manager.db.add_producto(
        "Producto",
        "P-001",
        None,
        vendor_id,
        dist_id,
        5,
        7,
        9,
        10,
    )
    product_id = manager.db.cursor.lastrowid

    compra_id = manager.db.add_compra_detallada(
        {
            "fecha": "2024-01-01",
            "total": 50,
            "Distribuidor_id": dist_id,
            "comision_pct": 0,
            "comision_monto": 0,
            "vendedor_id": vendor_id,
        }
    )
    manager.db.add_detalle_compra(
        compra_id,
        product_id,
        5,
        10,
        "2024-12-31",
        0,
        "%",
        0,
        "ninguno",
        0,
        0,
        "",
        codigo_lote="g432rs",
        registro_sanitario="RS-EXP",
    )
    detalle_id = manager.db.cursor.lastrowid

    manager.db.cursor.execute(
        "INSERT INTO ventas (id, fecha, total, cliente_id, Distribuidor_id, vendedor_id, extra, estado, sincronizada) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, "2024-01-02", 20, None, dist_id, None, None, "Pagada", 1),
    )
    manager.db.cursor.execute(
        "INSERT INTO detalles_venta (venta_id, producto_id, cantidad, precio_unitario, descuento, descuento_tipo, iva, comision, iva_tipo, tipo_fiscal, extra, precio_con_iva, vendedor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            product_id,
            2,
            10,
            0,
            "%",
            0,
            0,
            "ninguno",
            "Gravada",
            json.dumps({"lote_id": detalle_id, "producto_id": product_id, "cantidad": 2}),
            10,
            None,
        ),
    )
    manager.db.conn.commit()

    export_path = tmp_path / "inventory.json"
    manager.exportar_inventario_json(str(export_path), {})

    imported = InventoryManager(DB(":memory:"))
    imported.importar_inventario_json(str(export_path), strict=False)

    compras = imported.db.get_compras()
    assert len(compras) == 1
    compra = compras[0]
    assert compra["id"] == compra_id

    detalles = imported.db.get_detalles_compra(compra["id"])
    assert len(detalles) == 1
    detalle = detalles[0]
    assert detalle["id"] == detalle_id
    assert detalle["producto_id"] == product_id
    assert detalle["cantidad"] == 5
    assert detalle["codigo_lote"] == "g432rs"
    assert detalle["registro_sanitario"] == "RS-EXP"

    imported.db.cursor.execute("SELECT extra FROM detalles_venta")
    extra_raw = imported.db.cursor.fetchone()[0]
    parsed = json.loads(extra_raw)
    assert parsed["lote_id"] == detalle_id

