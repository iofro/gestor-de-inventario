import os
import sys
import time
import gc
import copy
import sqlite3
import json
import base64
import platform
from datetime import datetime
from pathlib import Path
from decimal import Decimal


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

ARTIFACTS_DIR = Path("./artifacts")


def make_jws(payload: dict) -> str:
    """Return a simple unsigned JWS token for ``payload``."""

    def _default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        raise TypeError

    header = base64.urlsafe_b64encode(b"{}" ).decode().rstrip("=")
    body = base64.urlsafe_b64encode(
        json.dumps(payload, default=_default).encode()
    ).decode().rstrip("=")
    return f"{header}.{body}.sig"


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
            "sku": "SKU001",
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
                "numeroControl": "DTE-01-S001P001-000000000000001",
                "codigoGeneracion": "13C694DE-DDA1-499A-B265-4BD5B01CF323",
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
                    "municipio": "13",
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
                    "municipio": "13",
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
                    "tributos": [],
                    "psv": 0,
                    "noGravado": 0,
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
                "tributos": [],
                "subTotal": 10.0,
                "ivaRete1": 0,
                "reteRenta": 0,
                "montoTotalOperacion": 10.0,
                "totalNoGravado": 0,
                "totalPagar": 10.0,
                "totalLetras": "diez",
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


def pytest_configure(config):
    config._cert_diag_records = []


@pytest.fixture(scope="session")
def artifacts_dir():
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


@pytest.fixture
def record_cert_diag(request):
    def _record(data):
        request.config._cert_diag_records.append(data)

    return _record


def _format_list(values):
    if not values:
        return "N/D"
    return ", ".join(sorted({str(value) for value in values if value}))


def pytest_sessionfinish(session, exitstatus):
    records = getattr(session.config, "_cert_diag_records", [])
    if not records:
        return

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS_DIR / "cert_diagnosis_report.md"

    cert_dirs = [rec.get("cert_dir_effective") for rec in records]
    signer_dirs = [rec.get("signer_cert_dir") for rec in records]
    env_dirs = [rec.get("env_CERT_UPLOAD_DIR") for rec in records]

    timestamp = datetime.now().isoformat()
    os_info = platform.platform()

    probable = None
    for rec in records:
        if rec.get("firmador_803") and rec.get("primary_cause"):
            probable = rec
            break

    with report_path.open("w", encoding="utf-8") as fh:
        fh.write("# Reporte de diagnóstico de certificados\n\n")
        fh.write(f"- Fecha y hora: {timestamp}\n")
        fh.write(f"- Sistema operativo: {os_info}\n")
        fh.write(f"- CERT dirs efectivos: {_format_list(cert_dirs)}\n")
        fh.write(f"- FIRMADOR_CERT_DIR observados: {_format_list(signer_dirs)}\n")
        fh.write(f"- CERT_UPLOAD_DIR (env): {_format_list(env_dirs)}\n")
        fh.write(f"- Artefactos guardados en: {ARTIFACTS_DIR.resolve()}\n\n")

        for rec in records:
            fh.write(f"## {rec['title']} — {rec['result']}\n\n")
            fh.write(f"- Escenario: `{rec['scenario']}`\n")
            fh.write(f"- Firmador 803: {'Sí' if rec['firmador_803'] else 'No'}\n")
            fh.write(f"- Ruta diagnóstico JSON: {rec['diagnosis_json']}\n")
            fh.write("- Flags:\n")
            fh.write(f"  - sha512_match: {rec['sha512_match']}\n")
            fh.write(f"  - cert_path_ok: {rec['cert_path_ok']}\n")
            fh.write(f"  - cert_dir_mismatch: {rec['cert_dir_mismatch']}\n")
            fh.write(f"  - password_encoding_detected: {rec['password_encoding_detected']}\n")
            fh.write(f"  - multiple_crts: {rec['multiple_crts']}\n")
            fh.write(f"  - sha256_of_file: {rec['sha256_of_file']}\n")
            fh.write(f"- NIT enviado: {rec['nit_payload']}\n")
            fh.write(f"- Archivo utilizado: {rec['nit_filename']}\n")
            fh.write(f"- NIT dentro del CRT: {rec['nit_from_crt']}\n")
            fh.write(f"- Errores detectados: {rec['diagnosis_errors']}\n")
            fh.write(f"- Directorio efectivo: {rec['cert_dir_effective']}\n")
            fh.write(f"- Directorio del firmador: {rec['signer_cert_dir']}\n")
            fh.write(f"- Recomendación sugerida: {rec['recommendation']}\n\n")

        fh.write("## Causa más probable en este entorno\n\n")
        if probable:
            fh.write(f"- Escenario: {probable['title']} (`{probable['scenario']}`)\n")
            fh.write(f"- Causa detectada: {probable['primary_cause']}\n")
            fh.write(f"- Recomendación: {probable['recommendation']}\n")
        else:
            fh.write("- No se detectaron respuestas 803 en las simulaciones.\n")
