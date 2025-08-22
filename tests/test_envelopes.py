import base64
import json
from copy import deepcopy
from app.dte import (
    NC_BASE,
    ensure_numero_control,
    validate_dte,
    build_dte_id_xml,
    sign_dte,
    LocalRS256Signer,
)


def _merge(dest, src):
    if dest is None:
        dest = {}
    for k, v in src.items():
        if isinstance(v, dict):
            dest[k] = _merge(dest.get(k, {}), v)
        else:
            dest[k] = v
    return dest


def test_nc_base_has_tipo_dte_only():
    ident = NC_BASE["identificacion"]
    assert ident["tipoDte"] == "05"
    # All other fields should be None
    others = {k: v for k, v in ident.items() if k != "tipoDte"}
    assert all(v is None for v in others.values())


def test_pipeline_generates_signed_nce():
    env = deepcopy(NC_BASE)
    sample = {
        "identificacion": {
            "version": 3,
            "ambiente": "00",
            "tipoDte": "05",
            "codigoGeneracion": None,
            "numeroControl": None,
            "fecEmi": "2024-01-01",
            "horEmi": "12:00:00",
            "tipoMoneda": "USD",
            "tipoModelo": 1,
            "tipoOperacion": 1,
            "tipoContingencia": None,
            "motivoContin": None,
        },
        "documentoRelacionado": [
            {
                "tipoDocumento": "03",
                "tipoGeneracion": 1,
                "numeroDocumento": "DTE-03-ABCDEFGH-123456789012345",
                "fechaEmision": "2024-01-01",
            }
        ],
        "emisor": {
            "nit": "06142512891020",
            "nrc": "1234567",
            "nombre": "Demo",
            "nombreComercial": "Demo",
            "codActividad": "46484",
            "descActividad": "Venta",
            "direccion": {
                "departamento": "06",
                "municipio": "01",
                "complemento": "Calle 1",
            },
            "telefono": "2222-2222",
            "correo": "demo@example.com",
            "tipoEstablecimiento": "01",
        },
        "receptor": {
            "nit": "06142512891020",
            "nrc": "0000011",
            "nombre": "Cliente",
            "nombreComercial": "Cliente",
            "codActividad": "00000",
            "descActividad": "Giro",
            "direccion": {
                "departamento": "06",
                "municipio": "01",
                "complemento": "Calle 1",
            },
            "telefono": "7000-0001",
            "correo": "cliente@example.com",
        },
        "ventaTercero": None,
        "cuerpoDocumento": [
                {
                    "numItem": 1,
                    "codigo": "P001",
                    "descripcion": "Producto",
                    "cantidad": 1.0,
                    "precioUni": 1.0,
                    "montoDescu": 0.0,
                    "ventaGravada": 1.0,
                    "ventaNoSuj": 0.0,
                    "ventaExenta": 0.0,
                    "tributos": ["20"],
                    "codTributo": None,
                    "tipoItem": 1,
                    "uniMedida": 59,
                    "numeroDocumento": "NA",
                }
            ],
        "resumen": {
            "totalNoSuj": 0.0,
            "totalExenta": 0.0,
            "totalGravada": 1.0,
            "subTotalVentas": 1.0,
            "descuNoSuj": 0.0,
            "descuExenta": 0.0,
            "descuGravada": 0.0,
            "totalDescu": 0.0,
            "tributos": [
                {"codigo": "20", "descripcion": "IVA", "valor": 0.0}
            ],
            "subTotal": 1.0,
            "ivaPerci1": 0.0,
            "ivaRete1": 0.0,
            "reteRenta": 0.0,
            "montoTotalOperacion": 1.0,
            "totalLetras": "UNO",
            "condicionOperacion": 1.0,
        },
        "extension": None,
        "apendice": None,
    }
    _merge(env, sample)
    ensure_numero_control(env)
    errors = validate_dte(env, "05")
    assert errors == []
    xml_id = build_dte_id_xml(env)
    assert "<TipoDte>05</TipoDte>" in xml_id
    signer = LocalRS256Signer()
    token = sign_dte(env, signer=signer)
    assert token.count(".") == 2
    header = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "==").decode())
    assert header["typ"] == "JWS"
    assert token == sign_dte(env, signer=signer)
