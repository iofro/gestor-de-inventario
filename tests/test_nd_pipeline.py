import re
from copy import deepcopy
from decimal import Decimal

from app.dte import (
    ND_BASE,
    ND_CONTROL_REGEX,
    ensure_numero_control,
    validate_dte,
    build_dte_id_xml,
    sign_dte,
)


def test_nd_minimum_pipeline():
    env = deepcopy(ND_BASE)
    ident = env["identificacion"]
    ident.update(
        {
            "version": 3,
            "ambiente": "00",
            "tipoModelo": 1,
            "tipoOperacion": 1,
            "fecEmi": "2024-01-01",
            "horEmi": "00:00:00",
            "tipoMoneda": "USD",
            "tipoContingencia": None,
            "motivoContin": None,
        }
    )

    env["emisor"] = {
        "nit": "06142512891020",
        "nrc": "1234567",
        "nombre": "Compañía Demo S.A. de C.V.",
        "codActividad": "46484",
        "descActividad": "Venta de productos",
        "nombreComercial": "Demo Comercial",
        "tipoEstablecimiento": "01",
        "telefono": "22222222",
        "correo": "demo@example.com",
        "direccion": {
            "departamento": "06",
            "municipio": "23",
            "complemento": "Calle X",
        },
    }

    env["receptor"] = {
        "nit": "06141990011019",
        "nrc": "0000011",
        "nombre": "Consumidor Final",
        "nombreComercial": "Cliente Ejemplo",
        "codActividad": "6201",
        "descActividad": "Servicios de software",
        "telefono": "70000001",
        "correo": "cliente@example.com",
        "direccion": {
            "departamento": "06",
            "municipio": "23",
            "complemento": "San Salvador",
        },
    }

    env["documentoRelacionado"] = [
        {
            "tipoDocumento": "03",
            "tipoGeneracion": 1,
            "numeroDocumento": "DTE-03-S001P001-000000000000001",
            "fechaEmision": "2024-01-01",
        }
    ]

    env["ventaTercero"] = None

    env["cuerpoDocumento"] = [
            {
                "numItem": 1,
                "tipoItem": 1,
                "numeroDocumento": "123",
                "codigo": "SKU001",
                "codTributo": None,
                "cantidad": Decimal("2.5"),
                "precioUni": Decimal("9.54"),
                "montoDescu": Decimal("0"),
                "ventaGravada": Decimal("23.85"),
                "ventaExenta": Decimal("0"),
                "ventaNoSuj": Decimal("0"),
                "tributos": ["20"],
                "descripcion": "Producto de prueba",
                "uniMedida": 59,
            }
        ]

    env["resumen"] = {
        "subTotal": Decimal("23.85"),
        "subTotalVentas": Decimal("23.85"),
        "descuGravada": Decimal("0"),
        "descuNoSuj": Decimal("0"),
        "descuExenta": Decimal("0"),
        "totalDescu": Decimal("0"),
        "ivaRete1": Decimal("0"),
        "ivaPerci1": Decimal("0"),
        "reteRenta": Decimal("0"),
        "totalGravada": Decimal("23.85"),
        "totalNoSuj": Decimal("0"),
        "totalExenta": Decimal("0"),
        "tributos": [
            {
                "codigo": "20",
                "descripcion": "Impuesto al Valor Agregado 13%",
                "valor": Decimal("3.10"),
            }
        ],
        "montoTotalOperacion": Decimal("26.95"),
        "totalLetras": "VEINTISEIS CON 95/100 USD",
        "condicionOperacion": 1,
        "numPagoElectronico": None,
    }

    env["extension"] = None
    env["apendice"] = None

    ensure_numero_control(env)

    errors = validate_dte(env, "06")
    assert errors == []

    xml_id = build_dte_id_xml(env)
    ident = env["identificacion"]
    assert ident["codigoGeneracion"] in xml_id
    assert ident["numeroControl"] in xml_id

    token = sign_dte(env)
    assert token.count(".") == 2
    assert re.fullmatch(ND_CONTROL_REGEX, ident["numeroControl"])
