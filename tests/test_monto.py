import sys
import types
import importlib
import pytest

@pytest.fixture()
def monto_func(monkeypatch):
    class DummyModule(types.ModuleType):
        def __getattr__(self, name):
            dummy = type(name, (), {})
            setattr(self, name, dummy)
            return dummy

    PyQt5 = types.ModuleType('PyQt5')
    QtWidgets = DummyModule('PyQt5.QtWidgets')
    QtCore = DummyModule('PyQt5.QtCore')
    QtGui = DummyModule('PyQt5.QtGui')
    PyQt5.QtWidgets = QtWidgets
    PyQt5.QtCore = QtCore
    PyQt5.QtGui = QtGui

    inventory_manager = types.ModuleType('inventory_manager')
    inventory_manager.InventoryManager = type('InventoryManager', (), {})

    dialogs = types.ModuleType('dialogs')
    for name in ['RegisterSaleDialog', 'ClienteSelectorDialog', 'ProductDialog',
                 'RegisterPurchaseDialog', 'DistribuidorDialog', 'ClienteDialog']:
        setattr(dialogs, name, type(name, (), {}))

    factura_sv = types.ModuleType('factura_sv')
    factura_sv.generar_factura_electronica_pdf = lambda *a, **k: None

    modules = {
        'PyQt5': PyQt5,
        'PyQt5.QtWidgets': QtWidgets,
        'PyQt5.QtCore': QtCore,
        'PyQt5.QtGui': QtGui,
        'inventory_manager': inventory_manager,
        'dialogs': dialogs,
        'factura_sv': factura_sv,
    }

    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    ui = importlib.import_module('ui_mainwindow')
    return ui.monto_a_texto_sv

def test_monto_174_50(monto_func):
    assert monto_func(174.50) == "CIENTO SETENTA Y CUATRO 50/100 DÓLARES"

def test_monto_1(monto_func):
    assert monto_func(1) == "UNO 00/100 DÓLARES"

def test_monto_21_30(monto_func):
    assert monto_func(21.30) == "VEINTIUNO 30/100 DÓLARES"
