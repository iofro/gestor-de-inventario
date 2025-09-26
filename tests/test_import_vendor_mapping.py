import json
import os
import sqlite3
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import inventory_manager as im
except ImportError as exc:  # pragma: no cover - allow running without PyQt
    info = (
        getattr(exc, "name", ""),
        getattr(exc, "path", ""),
        str(exc),
    )
    if not any("PyQt5" in text for text in info if isinstance(text, str)):
        raise

    for name in ("PyQt5", "PyQt5.QtCore", "PyQt5.QtGui"):
        sys.modules.pop(name, None)

    pyqt5 = types.ModuleType("PyQt5")
    qtcore = types.ModuleType("PyQt5.QtCore")
    qtgui = types.ModuleType("PyQt5.QtGui")

    class _Qt:  # minimal subset used by ProductTableModel
        DisplayRole = 0

    class _QAbstractTableModel:
        def __init__(self, *args, **kwargs):
            pass

    class _QColor:
        def __init__(self, *args, **kwargs):
            pass

    qtcore.QAbstractTableModel = _QAbstractTableModel
    qtcore.Qt = _Qt
    qtgui.QColor = _QColor

    pyqt5.QtCore = qtcore
    pyqt5.QtGui = qtgui

    sys.modules["PyQt5"] = pyqt5
    sys.modules["PyQt5.QtCore"] = qtcore
    sys.modules["PyQt5.QtGui"] = qtgui

    import inventory_manager as im


class _DummyProductTableModel:
    def __init__(self, data, vendedores, distribuidores):  # pragma: no cover - test helper
        self._vendedores = vendedores
        self._distribuidores = distribuidores
        self._data = list(data)

    def update_data(self, data):
        self._data = list(data)

    def beginResetModel(self):  # pragma: no cover - Qt compatibility
        pass

    def endResetModel(self):  # pragma: no cover - Qt compatibility
        pass


im.ProductTableModel = _DummyProductTableModel

class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")

def test_import_maps_vendors(tmp_path):
    if getattr(im.ProductTableModel, "__name__", "") == "_DummyProductTableModel":
        pytest.skip("requires Qt ProductTableModel")

    manager = im.InventoryManager(MemoryDB())

    data = {
        "Distribuidores": [{"id": 1, "nombre": "D1"}],
        "vendedores": [{"id": 99, "nombre": "V1", "Distribuidor_id": 1, "codigo": "V001"}],
        "productos": [
            {
                "id": 1,
                "nombre": "P1",
                "codigo": "P001",
                "sku": "S1",
                "vendedor_id": 99,
                "Distribuidor_id": 1,
                "precio_compra": 0,
                "precio_venta_minorista": 0,
                "precio_venta_mayorista": 0,
                "stock": 0,
            }
        ],
        "clientes": [{"id": 2, "nombre": "C1", "codigo": "C001"}],
        "ventas": [
            {
                "id": 5,
                "fecha": "2024-01-01",
                "total": 10,
                "cliente_id": 2,
                "Distribuidor_id": 1,
                "vendedor_id": 99,
            }
        ],
        "detalles_venta": [
            {
                "venta_id": 5,
                "producto_id": 1,
                "cantidad": 1,
                "precio_unitario": 10,
            }
        ],
    }
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data))

    manager.importar_inventario_json(str(path))

    ventas = manager.db.get_ventas()
    assert len(ventas) == 1
    venta = ventas[0]
    vend = manager.db.get_vendedores()[0]
    assert venta["vendedor_id"] == vend["id"]


def test_import_supplier_and_employee_vendors(tmp_path):
    manager = im.InventoryManager(MemoryDB())

    data = {
        "Distribuidores": [{"id": 1, "nombre": "D1"}],
        "vendedores": [
            {"id": 10, "nombre": "Proveedor", "Distribuidor_id": 1, "codigo": "PRV-1"},
            {
                "id": 11,
                "nombre": "Empleado Vend",
                "Distribuidor_id": None,
                "codigo": "EMP-1",
                "descripcion": "Vendedora",
            },
        ],
        "trabajadores": [
            {
                "id": 11,
                "nombre": "Empleado Vend",
                "codigo": "EMP-1",
                "dui": "00000000-0",
                "es_vendedor": True,
            }
        ],
        "productos": [
            {
                "id": 5,
                "nombre": "P1",
                "codigo": "PROD-1",
                "sku": "SKU-1",
                "vendedor_id": 11,
                "Distribuidor_id": None,
                "precio_compra": 0,
                "precio_venta_minorista": 0,
                "precio_venta_mayorista": 0,
                "stock": 1,
            }
        ],
        "clientes": [],
        "ventas": [],
        "compras": [],
        "detalles_venta": [],
        "detalles_compra": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
    }
    path = tmp_path / "inv_employee.json"
    path.write_text(json.dumps(data))

    try:
        manager.importar_inventario_json(str(path))
    except sqlite3.IntegrityError as exc:  # pragma: no cover - defensive
        pytest.fail(f"Unexpected sqlite3.IntegrityError: {exc}")

    vendedores = manager.db.get_vendedores()
    assert len(vendedores) == 2
    employee_vendor = next(v for v in vendedores if v["Distribuidor_id"] is None)
    supplier_vendor = next(v for v in vendedores if v["Distribuidor_id"] is not None)

    trabajadores = manager.db.get_trabajadores()
    assert len(trabajadores) == 1
    trabajador = trabajadores[0]

    # Employee vendor shares the same identifier and codigo with the trabajador
    assert employee_vendor["id"] == trabajador["id"]
    assert employee_vendor["codigo"] == trabajador["codigo"]

    # Supplier vendor remains available for mapping
    assert supplier_vendor["Distribuidor_id"] is not None

    productos = manager.db.get_productos()
    assert len(productos) == 1
    assert productos[0]["vendedor_id"] == employee_vendor["id"]


def test_import_supplier_employee_codigo_collision(tmp_path):
    manager = im.InventoryManager(MemoryDB())

    data = {
        "Distribuidores": [{"id": 1, "nombre": "D1"}],
        "vendedores": [
            {
                "id": 20,
                "nombre": "Proveedor Shared",
                "Distribuidor_id": 1,
                "codigo": "SHARED",
                "descripcion": "Proveedor",
            },
            {
                "id": 21,
                "nombre": "Empleado Shared",
                "Distribuidor_id": None,
                "codigo": "SHARED",
                "descripcion": "Empleado",
            },
        ],
        "trabajadores": [
            {
                "id": 21,
                "nombre": "Empleado Shared",
                "codigo": "SHARED",
                "dui": "00000000-0",
                "es_vendedor": True,
            }
        ],
        "productos": [
            {
                "id": 101,
                "nombre": "Producto Proveedor",
                "codigo": "PP-1",
                "sku": "SKU-PP",
                "vendedor_id": 20,
                "Distribuidor_id": 1,
                "precio_compra": 0,
                "precio_venta_minorista": 0,
                "precio_venta_mayorista": 0,
                "stock": 2,
            },
            {
                "id": 102,
                "nombre": "Producto Empleado",
                "codigo": "PE-1",
                "sku": "SKU-PE",
                "vendedor_id": 21,
                "Distribuidor_id": None,
                "precio_compra": 0,
                "precio_venta_minorista": 0,
                "precio_venta_mayorista": 0,
                "stock": 1,
            },
        ],
        "clientes": [],
        "ventas": [],
        "compras": [],
        "detalles_venta": [],
        "detalles_compra": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
    }
    path = tmp_path / "inv_shared_codigo.json"
    path.write_text(json.dumps(data))

    try:
        manager.importar_inventario_json(str(path))
    except sqlite3.IntegrityError as exc:  # pragma: no cover - defensive
        pytest.fail(f"Unexpected sqlite3.IntegrityError: {exc}")

    productos = manager.db.get_productos()
    assert len(productos) == 2

    productos_por_nombre = {p["nombre"]: p for p in productos}
    prod_proveedor = productos_por_nombre["Producto Proveedor"]
    prod_empleado = productos_por_nombre["Producto Empleado"]

    assert prod_proveedor["vendedor_id"] == prod_empleado["vendedor_id"]

    trabajadores = manager.db.get_trabajadores()
    assert len(trabajadores) == 1
    trabajador = trabajadores[0]

    # Both products should resolve to the trabajador vendor despite the shared codigo
    assert prod_proveedor["vendedor_id"] == trabajador["id"]
    assert prod_empleado["vendedor_id"] == trabajador["id"]
