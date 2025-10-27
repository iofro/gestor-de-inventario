import json
import sys
import types
import importlib.machinery


def _install_qt_stubs():
    if "PyQt5" in sys.modules:
        sys.modules.pop("PyQt5", None)
        sys.modules.pop("PyQt5.QtCore", None)
        sys.modules.pop("PyQt5.QtGui", None)

    qt = types.ModuleType("PyQt5")
    qtcore = types.ModuleType("PyQt5.QtCore")
    qtgui = types.ModuleType("PyQt5.QtGui")
    qt.__path__ = []
    qt.__spec__ = importlib.machinery.ModuleSpec("PyQt5", loader=None, is_package=True)
    qtcore.__spec__ = importlib.machinery.ModuleSpec("PyQt5.QtCore", loader=None)
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
            self.args = args
            self.kwargs = kwargs

    qtcore.QAbstractTableModel = _DummyModel
    qtcore.Qt = _QtNamespace
    qtgui.QColor = _DummyColor
    qt.QtCore = qtcore
    qt.QtGui = qtgui

    sys.modules["PyQt5"] = qt
    sys.modules["PyQt5.QtCore"] = qtcore
    sys.modules["PyQt5.QtGui"] = qtgui


def test_import_recreates_missing_purchase(tmp_path):
    _install_qt_stubs()

    from inventory_manager import InventoryManager
    from db import DB

    data = {
        "schemaVersion": 1,
        "productos": [
            {
                "id": 1,
                "nombre": "Producto",
                "codigo": "P1",
                "precio_compra": 5,
                "precio_venta_minorista": 5,
                "precio_venta_mayorista": 5,
                "stock": 2,
            }
        ],
        "vendedores": [],
        "distribuidores": [],
        "clientes": [],
        "ventas": [],
        "detalles_venta": [],
        "compras": [],
        "movimientos": [],
        "detalles_compra": [
            {
                "id": 1,
                "compra_id": 99,
                "producto_id": 1,
                "cantidad": 2,
                "precio_unitario": 5,
                "descuento": 1,
                "iva": 0.6,
                "iva_tipo": "añadido",
                "comision_monto": 0.4,
                "comision_tipo": "Añadida al total",
            }
        ],
        "dte_envios": [],
        "notas": [],
        "facturas_pdf": [],
        "tickets_pdf": [],
        "trabajadores": [],
        "datos_negocio": {},
        "ventas_credito_fiscal": [],
    }

    inv_file = tmp_path / "inventory.json"
    inv_file.write_text(json.dumps(data))

    manager = InventoryManager(DB(":memory:"))
    manager.importar_inventario_json(str(inv_file))

    compras = manager.db.get_compras()
    assert len(compras) == 1
    compra = compras[0]
    assert compra["total"] == 10.0
    assert compra["comision_monto"] == 0.4

    detalles = manager.db.get_detalles_compra(compra["id"])
    assert len(detalles) == 1
    detalle = detalles[0]
    assert detalle["producto_id"] is not None
    assert detalle["cantidad"] == 2
    assert detalle.get("codigo_lote", "") == ""
    assert detalle.get("registro_sanitario", "") == ""
