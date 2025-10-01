from decimal import Decimal

import uuid

from dte import generar_nota_remision_json
from utils.fecha import fecha_emision_hoy_str


def test_generar_nota_remision_json_from_dte(db_conn):
    factura = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": str(uuid.uuid4()).upper(),
            "fecEmi": "2024-01-01",
        },
        "emisor": {"nombre": "Emisor"},
        "receptor": {
            "numDocumento": "0614-123456-102-3",
            "tipoDocumento": "36",
            "nrc": "1234567",
            "nombre": "Cliente",
            "codActividad": "6201",
            "descActividad": "Servicios de software",
            "telefono": "70000001",
            "correo": "cliente@example.com",
            "direccion": {
                "departamento": "06",
                "municipio": "23",
                "complemento": "San Salvador",
            },
        },
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "descripcion": "Prod",
                "cantidad": 1,
                "uniMedida": 59,
            }
        ],
    }

    original_fec_emi = factura["identificacion"]["fecEmi"]

    nr = generar_nota_remision_json(
        db_conn,
        factura,
        cantidades={1: 2},
        extension={"docuEntrega": "0614-111111-101-1", "docuRecibe": "0614-222222-102-2"},
    )

    doc_rel = nr["documentoRelacionado"][0]
    ident = factura["identificacion"]
    assert doc_rel["tipoDocumento"] == ident["tipoDte"]
    assert doc_rel["tipoGeneracion"] == 2
    assert doc_rel["numeroDocumento"] == ident["codigoGeneracion"]
    assert doc_rel["fechaEmision"] == original_fec_emi
    assert nr["identificacion"]["fecEmi"] == fecha_emision_hoy_str()

    # receptor sanitized
    assert nr["receptor"]["numDocumento"] == "06141234561023"
    # extension sanitized
    assert nr["extension"]["docuEntrega"] == "06141111111011"
    assert nr["extension"]["docuRecibe"] == "06142222221022"

    item = nr["cuerpoDocumento"][0]
    assert item["precioUni"] == 0.0
    assert item["cantidad"] == 2
    assert item["codTributo"] is None

    resumen = nr["resumen"]
    assert resumen["montoTotalOperacion"] == Decimal("0.00")
    assert resumen["totalNoSuj"] == Decimal("0.00")
    assert resumen["totalGravada"] == Decimal("0.00")
    assert resumen["descuNoSuj"] == Decimal("0.00")
    assert resumen["descuExenta"] == Decimal("0.00")
    assert resumen["descuGravada"] == Decimal("0.00")


def test_generar_nota_remision_json_config_produccion_impone_ambiente(
    monkeypatch, db_conn
):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
        "dte_api": {"prefijo_control": "DTE-01-S001P001"},
    }

    monkeypatch.setattr("dte._load_dte_api_config", lambda: {"ambiente": "produccion"})
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)

    factura = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
            "fecEmi": "2024-01-01",
        },
        "emisor": {"nit": "06141407100012", "nrc": "1234567"},
        "receptor": {
            "numDocumento": "0614-123456-102-3",
            "tipoDocumento": "36",
            "nrc": "1234567",
            "nombre": "Cliente",
            "codActividad": "6201",
            "descActividad": "Servicios de software",
            "telefono": "70000001",
            "correo": "cliente@example.com",
            "direccion": {
                "departamento": "06",
                "municipio": "23",
                "complemento": "San Salvador",
            },
        },
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "descripcion": "Prod",
                "cantidad": 1,
                "uniMedida": 59,
            }
        ],
    }

    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }

    nr = generar_nota_remision_json(
        db_conn,
        factura,
        extension=extension,
        ambiente="00",
    )

    assert nr["identificacion"]["ambiente"] == "01"
