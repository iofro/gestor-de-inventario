import json
from decimal import Decimal

import pytest

from svfe.generators import (
    generar_factura_fiscal,
    generar_consumidor_final,
    generar_nota_debito,
    generar_nota_credito,
    generar_nota_remision,
    validar_contra_schema,
)
from svfe.json_compare import normalize_for_schema, similarity, deep_diff

# Mapping of DTE type to generator
GENERATORS = {
    "ccf": generar_factura_fiscal,
    "fc": generar_consumidor_final,
    "nd": generar_nota_debito,
    "nc": generar_nota_credito,
    "nr": generar_nota_remision,
}

# Golden normalized documents for each DTE type with deterministic ids
GOLDEN_JSON = {
    "ccf": """
{
  "apendice": null,
  "cuerpoDocumento": [
    {
      "cantidad": "2.50000000",
      "codTributo": "A8",
      "codigo": "SKU001",
      "descripcion": "Producto de prueba",
      "montoDescu": "0E-8",
      "noGravado": "0E-8",
      "numItem": 1,
      "numeroDocumento": null,
      "precioUni": "9.54000000",
      "psv": "0E-8",
      "tipoItem": 1,
      "tributos": [
        "A8"
      ],
      "uniMedida": 59,
      "ventaExenta": "0E-8",
      "ventaGravada": "23.85000000",
      "ventaNoSuj": "0E-8"
    }
  ],
  "documentoRelacionado": null,
  "emisor": {
    "codActividad": "46484",
    "codEstable": "0001",
    "codEstableMH": "0001",
    "codPuntoVenta": "0001",
    "codPuntoVentaMH": "0001",
    "correo": "demo@example.com",
    "descActividad": "Venta de productos",
    "direccion": {
      "complemento": "Centro Comercial 1",
      "departamento": "05",
      "municipio": "01"
    },
    "nit": "06142512891020",
    "nombre": "Compañía Demo S.A. de C.V.",
    "nombreComercial": "Demo Comercial",
    "nrc": "1234567",
    "telefono": "22222222",
    "tipoEstablecimiento": "01"
  },
  "extension": null,
  "identificacion": {
    "ambiente": "00",
    "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
    "fecEmi": "2024-01-01",
    "horEmi": "15:30:45",
    "motivoContin": null,
    "numeroControl": "DTE-03-12345678-000000000000001",
    "tipoContingencia": null,
    "tipoDte": "03",
    "tipoModelo": 1,
    "tipoMoneda": "USD",
    "tipoOperacion": 1,
    "version": 3
  },
  "otrosDocumentos": null,
  "receptor": {
    "codActividad": "6201",
    "correo": "cliente@example.com",
    "descActividad": "Servicios de software",
    "direccion": {
      "complemento": "San Salvador",
      "departamento": "05",
      "municipio": "01"
    },
    "nit": "06141990011019",
    "nombre": "Consumidor Final",
    "nombreComercial": "Cliente Ejemplo",
    "nrc": "0000011",
    "telefono": "70000001"
  },
  "resumen": {
    "condicionOperacion": 1,
    "descuExenta": "0.00",
    "descuGravada": "0.00",
    "descuNoSuj": "0.00",
    "ivaPerci1": "0.00",
    "ivaRete1": "0.00",
    "montoTotalOperacion": "26.95",
    "numPagoElectronico": null,
    "pagos": [
      {
        "codigo": "01",
        "montoPago": "26.95",
        "periodo": null,
        "plazo": null,
        "referencia": null
      }
    ],
    "porcentajeDescuento": "0.00",
    "reteRenta": "0.00",
    "saldoFavor": "0.00",
    "subTotal": "23.85",
    "subTotalVentas": "23.85",
    "totalDescu": "0.00",
    "totalExenta": "0.00",
    "totalGravada": "23.85",
    "totalLetras": "VEINTISEIS CON 95/100 USD",
    "totalNoGravado": "0.00",
    "totalNoSuj": "0.00",
    "totalPagar": "26.95",
    "tributos": null
  },
  "ventaTercero": null
}
""",
    "fc": """
{
  "apendice": null,
  "cuerpoDocumento": [
    {
      "cantidad": "2.50000000",
      "codTributo": "A8",
      "codigo": "SKU001",
      "descripcion": "Producto de prueba",
      "montoDescu": "0E-8",
      "noGravado": "0E-8",
      "numItem": 1,
      "numeroDocumento": null,
      "precioUni": "9.54000000",
      "psv": "0E-8",
      "tipoItem": 1,
      "tributos": [
        "A8"
      ],
      "uniMedida": 59,
      "ventaExenta": "0E-8",
      "ventaGravada": "23.85000000",
      "ventaNoSuj": "0E-8"
    }
  ],
  "documentoRelacionado": null,
  "emisor": {
    "codActividad": "46484",
    "codEstable": "0001",
    "codEstableMH": "0001",
    "codPuntoVenta": "0001",
    "codPuntoVentaMH": "0001",
    "correo": "demo@example.com",
    "descActividad": "Venta de productos",
    "direccion": {
      "complemento": "Centro Comercial 1",
      "departamento": "05",
      "municipio": "01"
    },
    "nit": "06142512891020",
    "nombre": "Compañía Demo S.A. de C.V.",
    "nombreComercial": "Demo Comercial",
    "nrc": "1234567",
    "telefono": "22222222",
    "tipoEstablecimiento": "01"
  },
  "extension": null,
  "identificacion": {
    "ambiente": "00",
    "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
    "fecEmi": "2024-01-01",
    "horEmi": "15:30:45",
    "motivoContin": null,
    "numeroControl": "DTE-01-12345678-000000000000001",
    "tipoContingencia": null,
    "tipoDte": "01",
    "tipoModelo": 1,
    "tipoMoneda": "USD",
    "tipoOperacion": 1,
    "version": 1
  },
  "otrosDocumentos": null,
  "receptor": {
    "codActividad": "6201",
    "correo": "cliente@example.com",
    "descActividad": "Servicios de software",
    "direccion": {
      "complemento": "San Salvador",
      "departamento": "05",
      "municipio": "01"
    },
    "nit": "06141990011019",
    "nombre": "Consumidor Final",
    "nombreComercial": "Cliente Ejemplo",
    "nrc": "0000011",
    "telefono": "70000001"
  },
  "resumen": {
    "condicionOperacion": 1,
    "descuExenta": "0.00",
    "descuGravada": "0.00",
    "descuNoSuj": "0.00",
    "ivaPerci1": "0.00",
    "ivaRete1": "0.00",
    "montoTotalOperacion": "26.95",
    "numPagoElectronico": null,
    "pagos": [
      {
        "codigo": "01",
        "montoPago": "26.95",
        "periodo": null,
        "plazo": null,
        "referencia": null
      }
    ],
    "porcentajeDescuento": "0.00",
    "reteRenta": "0.00",
    "saldoFavor": "0.00",
    "subTotal": "23.85",
    "subTotalVentas": "23.85",
    "totalDescu": "0.00",
    "totalExenta": "0.00",
    "totalGravada": "23.85",
    "totalLetras": "VEINTISEIS CON 95/100 USD",
    "totalNoGravado": "0.00",
    "totalNoSuj": "0.00",
    "totalPagar": "26.95",
    "tributos": null
  },
  "ventaTercero": null
}
""",
    "nd": """
{
  "apendice": null,
  "cuerpoDocumento": [
    {
      "cantidad": "2.50000000",
      "codTributo": "A8",
      "codigo": "SKU001",
      "descripcion": "Producto de prueba",
      "montoDescu": "0E-8",
      "noGravado": "0E-8",
      "numItem": 1,
      "numeroDocumento": null,
      "precioUni": "9.54000000",
      "psv": "0E-8",
      "tipoItem": 1,
      "tributos": [
        "A8"
      ],
      "uniMedida": 59,
      "ventaExenta": "0E-8",
      "ventaGravada": "23.85000000",
      "ventaNoSuj": "0E-8"
    }
  ],
  "documentoRelacionado": [
    {
      "fechaEmision": "2024-01-01",
      "numeroDocumento": "DTE-03-00000000-000000000000001",
      "tipoDocumento": "03",
      "tipoGeneracion": 1
    }
  ],
  "emisor": {
    "codActividad": "46484",
    "codEstable": "0001",
    "codEstableMH": "0001",
    "codPuntoVenta": "0001",
    "codPuntoVentaMH": "0001",
    "correo": "demo@example.com",
    "descActividad": "Venta de productos",
    "direccion": {
      "complemento": "Centro Comercial 1",
      "departamento": "05",
      "municipio": "01"
    },
    "nit": "06142512891020",
    "nombre": "Compañía Demo S.A. de C.V.",
    "nombreComercial": "Demo Comercial",
    "nrc": "1234567",
    "telefono": "22222222",
    "tipoEstablecimiento": "01"
  },
  "extension": null,
  "identificacion": {
    "ambiente": "00",
    "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
    "fecEmi": "2024-01-01",
    "horEmi": "15:30:45",
    "motivoContin": null,
    "numeroControl": "DTE-06-12345678-000000000000001",
    "tipoContingencia": null,
    "tipoDte": "06",
    "tipoModelo": 1,
    "tipoMoneda": "USD",
    "tipoOperacion": 1,
    "version": 3
  },
  "otrosDocumentos": null,
  "receptor": {
    "codActividad": "6201",
    "correo": "cliente@example.com",
    "descActividad": "Servicios de software",
    "direccion": {
      "complemento": "San Salvador",
      "departamento": "05",
      "municipio": "01"
    },
    "nit": "06141990011019",
    "nombre": "Consumidor Final",
    "nombreComercial": "Cliente Ejemplo",
    "nrc": "0000011",
    "telefono": "70000001"
  },
  "resumen": {
    "condicionOperacion": 1,
    "descuExenta": "0.00",
    "descuGravada": "0.00",
    "descuNoSuj": "0.00",
    "ivaPerci1": "0.00",
    "ivaRete1": "0.00",
    "montoTotalOperacion": "26.95",
    "numPagoElectronico": null,
    "pagos": [
      {
        "codigo": "01",
        "montoPago": "26.95",
        "periodo": null,
        "plazo": null,
        "referencia": null
      }
    ],
    "porcentajeDescuento": "0.00",
    "reteRenta": "0.00",
    "saldoFavor": "0.00",
    "subTotal": "23.85",
    "subTotalVentas": "23.85",
    "totalDescu": "0.00",
    "totalExenta": "0.00",
    "totalGravada": "23.85",
    "totalLetras": "VEINTISEIS CON 95/100 USD",
    "totalNoGravado": "0.00",
    "totalNoSuj": "0.00",
    "totalPagar": "26.95",
    "tributos": null
  },
  "ventaTercero": null
}
""",
    "nc": """
{
  "apendice": null,
  "cuerpoDocumento": [
    {
      "cantidad": "2.50000000",
      "codTributo": "A8",
      "codigo": "SKU001",
      "descripcion": "Producto de prueba",
      "montoDescu": "0E-8",
      "noGravado": "0E-8",
      "numItem": 1,
      "numeroDocumento": null,
      "precioUni": "9.54000000",
      "psv": "0E-8",
      "tipoItem": 1,
      "tributos": [
        "A8"
      ],
      "uniMedida": 59,
      "ventaExenta": "0E-8",
      "ventaGravada": "23.85000000",
      "ventaNoSuj": "0E-8"
    }
  ],
  "documentoRelacionado": [
    {
      "fechaEmision": "2024-01-01",
      "numeroDocumento": "DTE-03-00000000-000000000000001",
      "tipoDocumento": "03",
      "tipoGeneracion": 1
    }
  ],
  "emisor": {
    "codActividad": "46484",
    "codEstable": "0001",
    "codEstableMH": "0001",
    "codPuntoVenta": "0001",
    "codPuntoVentaMH": "0001",
    "correo": "demo@example.com",
    "descActividad": "Venta de productos",
    "direccion": {
      "complemento": "Centro Comercial 1",
      "departamento": "05",
      "municipio": "01"
    },
    "nit": "06142512891020",
    "nombre": "Compañía Demo S.A. de C.V.",
    "nombreComercial": "Demo Comercial",
    "nrc": "1234567",
    "telefono": "22222222",
    "tipoEstablecimiento": "01"
  },
  "extension": null,
  "identificacion": {
    "ambiente": "00",
    "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
    "fecEmi": "2024-01-01",
    "horEmi": "15:30:45",
    "motivoContin": null,
    "numeroControl": "DTE-05-12345678-000000000000001",
    "tipoContingencia": null,
    "tipoDte": "05",
    "tipoModelo": 1,
    "tipoMoneda": "USD",
    "tipoOperacion": 1,
    "version": 3
  },
  "otrosDocumentos": null,
  "receptor": {
    "codActividad": "6201",
    "correo": "cliente@example.com",
    "descActividad": "Servicios de software",
    "direccion": {
      "complemento": "San Salvador",
      "departamento": "05",
      "municipio": "01"
    },
    "nit": "06141990011019",
    "nombre": "Consumidor Final",
    "nombreComercial": "Cliente Ejemplo",
    "nrc": "0000011",
    "telefono": "70000001"
  },
  "resumen": {
    "condicionOperacion": 1,
    "descuExenta": "0.00",
    "descuGravada": "0.00",
    "descuNoSuj": "0.00",
    "ivaPerci1": "0.00",
    "ivaRete1": "0.00",
    "montoTotalOperacion": "26.95",
    "numPagoElectronico": null,
    "pagos": [
      {
        "codigo": "01",
        "montoPago": "26.95",
        "periodo": null,
        "plazo": null,
        "referencia": null
      }
    ],
    "porcentajeDescuento": "0.00",
    "reteRenta": "0.00",
    "saldoFavor": "0.00",
    "subTotal": "23.85",
    "subTotalVentas": "23.85",
    "totalDescu": "0.00",
    "totalExenta": "0.00",
    "totalGravada": "23.85",
    "totalLetras": "VEINTISEIS CON 95/100 USD",
    "totalNoGravado": "0.00",
    "totalNoSuj": "0.00",
    "totalPagar": "26.95",
    "tributos": null
  },
  "ventaTercero": null
}
""",
    "nr": """
{
  "apendice": null,
  "cuerpoDocumento": [
    {
      "cantidad": "2.50000000",
      "codTributo": "A8",
      "codigo": "SKU001",
      "descripcion": "Producto de prueba",
      "montoDescu": "0E-8",
      "noGravado": "0E-8",
      "numItem": 1,
      "numeroDocumento": null,
      "precioUni": "9.54000000",
      "psv": "0E-8",
      "tipoItem": 1,
      "tributos": [
        "A8"
      ],
      "uniMedida": 59,
      "ventaExenta": "0E-8",
      "ventaGravada": "23.85000000",
      "ventaNoSuj": "0E-8"
    }
  ],
  "documentoRelacionado": [
    {
      "fechaEmision": "2024-01-01",
      "numeroDocumento": "DTE-03-00000000-000000000000001",
      "tipoDocumento": "03",
      "tipoGeneracion": 1
    }
  ],
  "emisor": {
    "codActividad": "46484",
    "codEstable": "0001",
    "codEstableMH": "0001",
    "codPuntoVenta": "0001",
    "codPuntoVentaMH": "0001",
    "correo": "demo@example.com",
    "descActividad": "Venta de productos",
    "direccion": {
      "complemento": "Centro Comercial 1",
      "departamento": "05",
      "municipio": "01"
    },
    "nit": "06142512891020",
    "nombre": "Compañía Demo S.A. de C.V.",
    "nombreComercial": "Demo Comercial",
    "nrc": "1234567",
    "telefono": "22222222",
    "tipoEstablecimiento": "01"
  },
  "extension": null,
  "identificacion": {
    "ambiente": "00",
    "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
    "fecEmi": "2024-01-01",
    "horEmi": "15:30:45",
    "motivoContin": null,
    "numeroControl": "DTE-04-12345678-000000000000001",
    "tipoContingencia": null,
    "tipoDte": "04",
    "tipoModelo": 1,
    "tipoMoneda": "USD",
    "tipoOperacion": 1,
    "version": 3
  },
  "otrosDocumentos": null,
  "receptor": {
    "codActividad": "6201",
    "correo": "cliente@example.com",
    "descActividad": "Servicios de software",
    "direccion": {
      "complemento": "San Salvador",
      "departamento": "05",
      "municipio": "01"
    },
    "nit": "06141990011019",
    "nombre": "Consumidor Final",
    "nombreComercial": "Cliente Ejemplo",
    "nrc": "0000011",
    "telefono": "70000001"
  },
  "resumen": {
    "condicionOperacion": 1,
    "descuExenta": "0.00",
    "descuGravada": "0.00",
    "descuNoSuj": "0.00",
    "ivaPerci1": "0.00",
    "ivaRete1": "0.00",
    "montoTotalOperacion": "26.95",
    "numPagoElectronico": null,
    "pagos": [
      {
        "codigo": "01",
        "montoPago": "26.95",
        "periodo": null,
        "plazo": null,
        "referencia": null
      }
    ],
    "porcentajeDescuento": "0.00",
    "reteRenta": "0.00",
    "saldoFavor": "0.00",
    "subTotal": "23.85",
    "subTotalVentas": "23.85",
    "totalDescu": "0.00",
    "totalExenta": "0.00",
    "totalGravada": "23.85",
    "totalLetras": "VEINTISEIS CON 95/100 USD",
    "totalNoGravado": "0.00",
    "totalNoSuj": "0.00",
    "totalPagar": "26.95",
    "tributos": null
  },
  "ventaTercero": null
}
""",
}

GOLDEN = {k: json.loads(v) for k, v in GOLDEN_JSON.items()}


class FixedUUID:
    def __init__(self):
        self.value = "12345678-1234-1234-1234-1234567890ab"

    @property
    def hex(self):
        return self.value.replace("-", "")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

def fixed_uuid4():
    return FixedUUID()


class FixedDateTime:
    @classmethod
    def now(cls, tz=None):
        from datetime import datetime
        return datetime(2024, 1, 1, 15, 30, 45, tzinfo=tz)


def _assert_base(data):
    item = data["cuerpoDocumento"][0]
    assert str(item["ventaGravada"]) == "23.85000000"
    venta = item["ventaGravada"]
    iva = (venta * Decimal("0.13")).quantize(Decimal("0.00000001"))
    assert str(iva) == "3.10050000"

    resumen = data["resumen"]
    assert str(resumen["totalGravada"]) == "23.85"
    total = resumen.get("totalPagar", resumen["montoTotalOperacion"])
    assert str(total) == "26.95"
    total_iva = resumen.get("totalIva")
    if total_iva is None:
        total_iva = resumen["montoTotalOperacion"] - resumen["totalGravada"]
    total_iva = total_iva.quantize(Decimal("0.01"))
    assert str(total_iva) == "3.10"


@pytest.mark.parametrize("tipo", ["ccf", "fc", "nd", "nc", "nr"])
def test_all_dtes(monkeypatch, tipo):
    monkeypatch.setattr("svfe.generators.uuid4", fixed_uuid4)
    monkeypatch.setattr("svfe.generators.datetime", FixedDateTime)

    data = GENERATORS[tipo]()
    _assert_base(data)
    validar_contra_schema(data, tipo)

    normalized = normalize_for_schema(data)
    golden = GOLDEN[tipo]
    sim = similarity(normalized, golden)
    if sim != 1.0:
        diff = deep_diff(normalized, golden)
        assert sim == 1.0, diff
    assert sim == 1.0

