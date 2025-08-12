import json
import pytest

import inventory_manager as im
import ui_mainwindow
import dialogs
from PyQt5.QtWidgets import QMessageBox


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


class DummyDialog:
    def __init__(self, dte_api, fe_config, env_conf, parent=None):
        pass

    def exec_(self):
        return True

    def get_data(self):
        return {"token": "nuevo"}, {}, {}


def test_datos_negocio_preserved(tmp_path, monkeypatch, qt_app):
    datos_file = tmp_path / "datos_negocio.json"
    config_file = tmp_path / "config_negocio.json"
    datos_file.write_text(json.dumps({"nit": "123", "nombre": "Farmacia", "dte_api": {"token": "viejo"}}))
    config_file.write_text("{}")

    monkeypatch.setattr(im, "DB", MemoryDB)
    monkeypatch.setattr(ui_mainwindow, "DATOS_NEGOCIO_PATH", str(datos_file))
    monkeypatch.setattr(ui_mainwindow, "CONFIG_NEGOCIO_PATH", str(config_file))
    monkeypatch.setattr(dialogs, "DTEConfigDialog", DummyDialog)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window = ui_mainwindow.MainWindow()
    window._abrir_config_facturacion()

    guardados = json.loads(datos_file.read_text())
    assert guardados["nit"] == "123"
    assert guardados["nombre"] == "Farmacia"
    assert guardados["dte_api"] == {"token": "nuevo"}
