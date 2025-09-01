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
        return {"token": "nuevo", "ambiente": "pruebas"}, {}, {}


class EnvChangeDialog:
    def __init__(self, dte_api, fe_config, env_conf, parent=None):
        self.dte_api = dte_api
        self.fe_config = fe_config
        self.env_conf = env_conf

    def exec_(self):
        return True

    def get_data(self):
        new_api = {"token": "nuevo", "ambiente": "produccion"}
        new_fe = {"cert": "nuevo"}
        new_urls = {"auth_url": "a", "recepcion_url": "r"}
        return new_api, new_fe, new_urls


class CaptureDialog:
    def __init__(self, dte_api, fe_config, env_conf, parent=None):
        CaptureDialog.last = {
            "dte_api": dte_api,
            "fe_config": fe_config,
            "env_conf": env_conf,
        }

    def exec_(self):
        return False

    def get_data(self):
        return {}, {}, {}


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
    assert guardados["dte_api"] == {"token": "nuevo", "ambiente": "pruebas"}


def test_environment_change_saved_and_reloaded(tmp_path, monkeypatch, qt_app):
    datos_file = tmp_path / "datos_negocio.json"
    config_file = tmp_path / "config_negocio.json"
    datos_file.write_text(json.dumps({"dte_api": {"ambiente": "pruebas"}}))
    config_file.write_text(json.dumps({"ambiente": "pruebas", "pruebas": {}}))

    monkeypatch.setattr(im, "DB", MemoryDB)
    monkeypatch.setattr(ui_mainwindow, "DATOS_NEGOCIO_PATH", str(datos_file))
    monkeypatch.setattr(ui_mainwindow, "CONFIG_NEGOCIO_PATH", str(config_file))
    monkeypatch.setattr(dialogs, "DTEConfigDialog", EnvChangeDialog)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window = ui_mainwindow.MainWindow()
    window._abrir_config_facturacion()

    config = json.loads(config_file.read_text())
    assert config["ambiente"] == "produccion"
    assert config["produccion"]["firma_electronica"] == {"cert": "nuevo"}

    # verify reloading uses new environment
    monkeypatch.setattr(dialogs, "DTEConfigDialog", CaptureDialog)
    window._abrir_config_facturacion()
    captured = CaptureDialog.last
    assert captured["env_conf"]["firma_electronica"] == {"cert": "nuevo"}
    assert captured["dte_api"]["ambiente"] == "produccion"
