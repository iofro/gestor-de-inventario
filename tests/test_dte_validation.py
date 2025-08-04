import pytest
from dte import validate_dte_json


def sample_dte():
    return {
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
            "pagos": [{"codigo": "01", "montoPago": 10.0, "referencia": "efectivo", "periodo": None, "plazo": None}],
            "numPagoElectronico": None,
        },
        "documentoRelacionado": None,
        "otrosDocumentos": None,
        "ventaTercero": None,
        "extension": None,
        "apendice": None,
    }


def test_dte_valido_pasa():
    dte = sample_dte()
    validate_dte_json(dte)


def test_codigo_invalido_rechazado():
    dte = sample_dte()
    dte["identificacion"]["tipoDte"] = "99"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_longitud_nit_invalida():
    dte = sample_dte()
    dte["emisor"]["nit"] = "123"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_estructura_invalida():
    from jsonschema import ValidationError
    dte = sample_dte()
    del dte["emisor"]["nit"]
    with pytest.raises(ValidationError):
        validate_dte_json(dte)
