import json
import os
import pytest

im = pytest.importorskip("inventory_manager", exc_type=ImportError)
ui_mainwindow = pytest.importorskip("ui_mainwindow", exc_type=ImportError)
dialogs = pytest.importorskip("dialogs", exc_type=ImportError)
from PyQt5.QtWidgets import QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


class DummyDialog:
    def __init__(self, dte_api, fe_config, env_conf, parent=None, datos_negocio=None, **kwargs):
        self.datos_negocio = datos_negocio or {}

    def exec_(self):
        return True

    def get_data(self):
        return (
            {"token_pruebas": "Bearer nuevo", "ambiente": "pruebas"},
            {},
            {},
        )

    def get_negocio_updates(self):
        return {}


class EnvChangeDialog:
    def __init__(self, dte_api, fe_config, env_conf, parent=None, datos_negocio=None, **kwargs):
        self.dte_api = dte_api
        self.fe_config = fe_config
        self.env_conf = env_conf
        self.datos_negocio = datos_negocio or {}

    def exec_(self):
        return True

    def get_data(self):
        new_api = {
            "token_produccion": "Bearer nuevo",
            "ambiente": "produccion",
        }
        new_fe = {"cert": "nuevo"}
        new_urls = {"auth_url": "a", "recepcion_url": "r"}
        return new_api, new_fe, new_urls

    def get_negocio_updates(self):
        return {}


class CaptureDialog:
    def __init__(self, dte_api, fe_config, env_conf, parent=None, datos_negocio=None, **kwargs):
        CaptureDialog.last = {
            "dte_api": dte_api,
            "fe_config": fe_config,
            "env_conf": env_conf,
            "datos_negocio": datos_negocio,
        }

    def exec_(self):
        return False

    def get_data(self):
        return {}, {}, {}

    def get_negocio_updates(self):
        return {}


class RazonSocialDialog:
    def __init__(self, dte_api, fe_config, env_conf, parent=None, datos_negocio=None, **kwargs):
        self.datos_negocio = datos_negocio or {}

    def exec_(self):
        return True

    def get_data(self):
        dte_api = {
            "ambiente": "pruebas",
            "tipo_contribuyente": "Persona Jurídica",
        }
        return dte_api, {}, {}

    def get_negocio_updates(self):
        return {
            "razonSocial": "Mi Empresa",
            "tipoContribuyente": "Persona Jurídica",
        }


def test_datos_negocio_preserved(tmp_path, monkeypatch, qt_app):
    datos_file = tmp_path / "datos_negocio.json"
    config_file = tmp_path / "config_negocio.json"
    datos_file.write_text(
        json.dumps(
            {
                "nit": "123",
                "nombre": "Farmacia",
                "dte_api": {"token_pruebas": "viejo"},
            }
        )
    )
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
    assert guardados["dte_api"] == {
        "token_pruebas": "Bearer nuevo",
        "ambiente": "pruebas",
    }


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
    assert captured["dte_api"].get("token_produccion") == "Bearer nuevo"


def test_razon_social_actualizada_en_config(tmp_path, monkeypatch, qt_app):
    datos_file = tmp_path / "datos_negocio.json"
    config_file = tmp_path / "config_negocio.json"
    datos_file.write_text(
        json.dumps({
            "razonSocial": "",
            "tipoContribuyente": "Persona Natural",
            "dte_api": {"ambiente": "pruebas"},
        })
    )
    config_file.write_text(json.dumps({"ambiente": "pruebas", "pruebas": {}}))

    monkeypatch.setattr(im, "DB", MemoryDB)
    monkeypatch.setattr(ui_mainwindow, "DATOS_NEGOCIO_PATH", str(datos_file))
    monkeypatch.setattr(ui_mainwindow, "CONFIG_NEGOCIO_PATH", str(config_file))
    monkeypatch.setattr(dialogs, "DTEConfigDialog", RazonSocialDialog)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window = ui_mainwindow.MainWindow()
    window._abrir_config_facturacion()

    datos = json.loads(datos_file.read_text())
    assert datos["razonSocial"] == "Mi Empresa"
    assert datos["tipoContribuyente"] == "Persona Jurídica"
    assert datos["dte_api"]["tipo_contribuyente"] == "Persona Jurídica"
