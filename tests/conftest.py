import os
import sys
import time
import gc
import copy
import sqlite3


import pytest

try:
    from PyQt5.QtWidgets import QApplication
except ImportError:  # pragma: no cover - PyQt5 may be missing in CI
    class QApplication:  # minimal stub for tests that don't use the GUI
        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def instance():
            return None

from db import DB


@pytest.fixture(scope="function")
def db_conn(tmp_path):
    """Provide a temporary database connection for tests.

    The database lives in ``tmp_path`` and enforces foreign key constraints.
    After the test the database is aggressively cleaned up so the file can be
    removed even on platforms that keep file handles open briefly (e.g.
    Windows).
    """

    db_path = tmp_path / "test.sqlite"
    db = DB(str(db_path))
    db.conn.execute("PRAGMA foreign_keys=ON")
    # Expose path for tests that want to assert cleanup
    db.db_path = db_path

    yield db

    # Ensure cursors are closed and checkpoints run so SQLite releases locks
    try:
        db.cursor.close()
    except (AttributeError, sqlite3.Error):
        pass
    try:
        db.conn.execute("PRAGMA wal_checkpoint(FULL)")
        db.conn.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error:
        pass
    try:
        db.conn.close()
    except sqlite3.Error:
        pass

    gc.collect()

    # Retry removing the database file a few times (helps on Windows)
    for _ in range(10):
        try:
            if db_path.exists():
                os.remove(db_path)
            break
        except OSError:
            time.sleep(0.1)


@pytest.fixture(scope="session")
def qt_app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def cliente_factory():
    def factory(**overrides):
        data = {
            "id": 1,
            "nombre": "Cliente",
            "codigo": "C001",
            "email": "cli@example.com",
            "nit": "0614-123456-102-3",
            "nrc": "",
        }
        data.update(overrides)
        return data

    return factory


@pytest.fixture
def producto_factory():
    def factory(**overrides):
        data = {
            "id": 1,
            "nombre": "Producto",
            "codigo": "P001",
            "vendedor_id": 1,
            "Distribuidor_id": 1,
            "precio_compra": 0,
            "precio_venta_minorista": 0,
            "precio_venta_mayorista": 0,
            "stock": 0,
        }
        data.update(overrides)
        return data

    return factory


@pytest.fixture
def venta_factory():
    def factory(**overrides):
        data = {
            "id": 1,
            "fecha": "2024-01-01",
            "total": 10,
            "cliente_id": 1,
        }
        data.update(overrides)
        return data

    return factory


@pytest.fixture
def dte_metadata_factory():
    def factory(**overrides):
        base = {
            "identificacion": {
                "version": 1,
                "ambiente": "00",
                "tipoDte": "01",
                "numeroControl": "DTE-01-AB12CD34-000000000000001",
                "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
                "tipoModelo": 1,
                "tipoOperacion": 1,
                "fecEmi": "2024-01-01",
                "horEmi": "12:00:00",
                "tipoMoneda": "USD",
                "tipoContingencia": None,
                "motivoContin": None,
            },
            "emisor": {
                "nit": "06141404100016",
                "nrc": "1234567",
                "nombre": "Empresa SA",
                "codActividad": "12345",
                "descActividad": "Venta de productos",
                "nombreComercial": "Empresa",
                "tipoContribuyente": "Persona Jurídica",
                "tipoEstablecimiento": "01",
                "direccion": {
                    "departamento": "01",
                    "municipio": "01",
                    "complemento": "Calle 1",
                },
                "telefono": "22223333",
                "correo": "info@empresa.com",
                "codEstableMH": "0001",
                "codEstable": "0001",
                "codPuntoVentaMH": "0001",
                "codPuntoVenta": "0001",
            },
            "receptor": {
                "tipoDocumento": "36",
                "numDocumento": "06141404100016",
                "nrc": "7654321",
                "nombre": "Cliente",
                "codActividad": "12345",
                "descActividad": "Compra de productos",
                "direccion": {
                    "departamento": "01",
                    "municipio": "01",
                    "complemento": "Calle 2",
                },
                "telefono": "22223333",
                "correo": "cliente@example.com",
            },
            "cuerpoDocumento": [
                {
                    "numItem": 1,
                    "tipoItem": 1,
                    "numeroDocumento": "DOC1",
                    "codigo": "P1",
                    "cantidad": 1,
                    "uniMedida": 1,
                    "descripcion": "Producto",
                    "precioUni": 10.0,
                    "montoDescu": 0,
                    "ventaNoSuj": 0,
                    "ventaExenta": 0,
                    "ventaGravada": 10.0,
                    "codTributo": None,
                    "tributos": ["D5"],
                    "psv": 0,
                    "noGravado": 0,
                    "ivaItem": 0,
                }
            ],
            "resumen": {
                "totalNoSuj": 0,
                "totalExenta": 0,
                "totalGravada": 10.0,
                "subTotalVentas": 10.0,
                "descuNoSuj": 0,
                "descuExenta": 0,
                "descuGravada": 0,
                "porcentajeDescuento": 0,
                "totalDescu": 0,
                "tributos": [{"codigo": "D5", "descripcion": "IVA", "valor": 0}],
                "subTotal": 10.0,
                "ivaRete1": 0,
                "reteRenta": 0,
                "montoTotalOperacion": 10.0,
                "totalNoGravado": 0,
                "totalPagar": 10.0,
                "totalLetras": "diez",
                "totalIva": 0,
                "saldoFavor": 0,
                "condicionOperacion": 1,
                "pagos": [
                    {
                        "codigo": "01",
                        "montoPago": 10.0,
                        "referencia": "efectivo",
                        "periodo": None,
                        "plazo": None,
                    }
                ],
                "numPagoElectronico": None,
            },
            "documentoRelacionado": None,
            "otrosDocumentos": None,
            "ventaTercero": None,
            "extension": None,
            "apendice": None,
        }
        merged = copy.deepcopy(base)
        for key, value in overrides.items():
            merged[key] = value
        return merged

    return factory


@pytest.fixture
def pdf_json_files(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    json_path = pdf.with_suffix(".json")
    json_path.write_text("{}", encoding="utf-8")
    return pdf, json_path
