from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4
from zoneinfo import ZoneInfo

# NOTE: jsonschema imports retained for potential future validation logic.
from jsonschema import Draft202012Validator, RefResolver, FormatChecker  # pragma: no cover

getcontext().rounding = ROUND_HALF_UP

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "svfe-json-schemas"

SCHEMA_MAP: Dict[str, tuple[str, str]] = {
    "ccf": ("fe-ccf-v3.json", "03"),
    "fc": ("fe-fc-v1.json", "01"),
    "nd": ("fe-nd-v3.json", "06"),
    "nc": ("fe-nc-v3.json", "05"),
    "nr": ("fe-nr-v3.json", "04"),
}

D8 = Decimal("0.00000001")
D2 = Decimal("0.01")


def _load_schema(filename: str) -> Dict[str, Any]:
    with open(SCHEMAS_DIR / filename, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _numero_control(tipo: str) -> str:
    return f"DTE-{tipo}-{uuid4().hex[:8].upper()}-000000000000001"


def d8(value: Decimal) -> Decimal:
    return value.quantize(D8)


def d2(value: Decimal) -> Decimal:
    return value.quantize(D2)


def _identificacion(schema: Dict[str, Any], tipo_dte: str) -> Dict[str, Any]:
    version = schema["properties"]["identificacion"]["properties"]["version"]["const"]
    now = datetime.now(ZoneInfo("America/El_Salvador"))
    return {
        "version": version,
        "ambiente": "00",
        "tipoDte": tipo_dte,
        "numeroControl": _numero_control(tipo_dte),
        "codigoGeneracion": str(uuid4()).upper(),
        "tipoModelo": 1,
        "tipoOperacion": 1,
        "tipoContingencia": None,
        "motivoContin": None,
        "fecEmi": now.date().isoformat(),
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }


def _emisor() -> Dict[str, Any]:
    return {
        "nit": "06142512891020",
        "nrc": "1234567",
        "nombre": "Compañía Demo S.A. de C.V.",
        "codActividad": "46484",
        "descActividad": "Venta de productos",
        "nombreComercial": "Demo Comercial",
        "tipoEstablecimiento": "01",
        "direccion": {
            "departamento": "05",
            "municipio": "01",
            "complemento": "Centro Comercial 1",
        },
        "telefono": "22222222",
        "correo": "demo@example.com",
        "codEstableMH": "0001",
        "codEstable": "0001",
        "codPuntoVentaMH": "0001",
        "codPuntoVenta": "0001",
    }


def _receptor() -> Dict[str, Any]:
    return {
        "nit": "06141990011019",
        "nrc": "0000011",
        "nombre": "Consumidor Final",
        "codActividad": "6201",
        "descActividad": "Servicios de software",
        "nombreComercial": "Cliente Ejemplo",
        "direccion": {
            "departamento": "05",
            "municipio": "01",
            "complemento": "San Salvador",
        },
        "telefono": "70000001",
        "correo": "cliente@example.com",
    }


def _cuerpo_documento() -> List[Dict[str, Any]]:
    cantidad = Decimal("2.5")
    precio = Decimal("9.54")
    venta = d8(cantidad * precio)
    return [
        {
            "numItem": 1,
            "tipoItem": 1,
            "numeroDocumento": None,
            "codigo": "SKU001",
            "codTributo": None,
            "descripcion": "Producto de prueba",
            "cantidad": d8(cantidad),
            "uniMedida": 59,
            "precioUni": d8(precio),
            "montoDescu": d8(Decimal("0")),
            "ventaNoSuj": d8(Decimal("0")),
            "ventaExenta": d8(Decimal("0")),
            "ventaGravada": venta,
            "tributos": None,
            "psv": d8(Decimal("0")),
            "noGravado": d8(Decimal("0")),
        }
    ]


def _resumen() -> Dict[str, Any]:
    cantidad = Decimal("2.5")
    precio = Decimal("9.54")
    venta = d2(cantidad * precio)
    iva = d2(venta * Decimal("0.13"))
    total = d2(venta + iva)
    return {
        "totalNoSuj": d2(Decimal("0")),
        "totalExenta": d2(Decimal("0")),
        "totalGravada": d2(venta),
        "subTotalVentas": d2(venta),
        "descuNoSuj": d2(Decimal("0")),
        "descuExenta": d2(Decimal("0")),
        "descuGravada": d2(Decimal("0")),
        "porcentajeDescuento": d2(Decimal("0")),
        "totalDescu": d2(Decimal("0")),
        "tributos": None,
        "subTotal": d2(venta),
        "ivaPerci1": d2(Decimal("0")),
        "ivaRete1": d2(Decimal("0")),
        "reteRenta": d2(Decimal("0")),
        "montoTotalOperacion": d2(total),
        "totalNoGravado": d2(Decimal("0")),
        "totalPagar": d2(total),
        "totalLetras": "VEINTISEIS CON 95/100 USD",
        "saldoFavor": d2(Decimal("0")),
        "condicionOperacion": 1,
        "pagos": [
            {
                "codigo": "01",
                "montoPago": d2(total),
                "referencia": None,
                "periodo": None,
                "plazo": None,
            }
        ],
        "numPagoElectronico": None,
    }


def _documento_relacionado(tipo: str) -> Any:
    if tipo in {"nd", "nc", "nr"}:
        return [
            {
                "tipoDocumento": "03",
                "tipoGeneracion": 1,
                "numeroDocumento": "DTE-03-00000000-000000000000001",
                "fechaEmision": "2024-01-01",
            }
        ]
    return None


def _generar(tipo: str) -> Dict[str, Any]:
    schema_file, tipo_dte = SCHEMA_MAP[tipo]
    schema = _load_schema(schema_file)
    data = {
        "identificacion": _identificacion(schema, tipo_dte),
        "documentoRelacionado": _documento_relacionado(tipo),
        "emisor": _emisor(),
        "receptor": _receptor(),
        "otrosDocumentos": None,
        "ventaTercero": None,
        "cuerpoDocumento": _cuerpo_documento(),
        "resumen": _resumen(),
        "extension": None,
        "apendice": None,
    }
    validar_contra_schema(data, tipo)
    return data


def generar_factura_fiscal() -> Dict[str, Any]:
    return _generar("ccf")


def generar_consumidor_final() -> Dict[str, Any]:
    return _generar("fc")


def generar_nota_debito() -> Dict[str, Any]:
    return _generar("nd")


def generar_nota_credito() -> Dict[str, Any]:
    return _generar("nc")


def generar_nota_remision() -> Dict[str, Any]:
    return _generar("nr")


def validar_contra_schema(data: Dict[str, Any], tipo: str) -> None:
    """Valida ``data`` contra el *schema* oficial del DTE ``tipo``.

    Parameters
    ----------
    data:
        Estructura del documento a validar.
    tipo:
        Tipo del DTE. Debe existir en ``SCHEMA_MAP``.

    Raises
    ------
    ValueError
        Cuando el tipo es desconocido o el documento no cumple con el schema.
    """

    if tipo not in SCHEMA_MAP:
        raise ValueError(f"Tipo de DTE desconocido: {tipo}")

    schema_file, _ = SCHEMA_MAP[tipo]
    schema = _load_schema(schema_file)

    # Resolver para que jsonschema pueda manejar referencias relativas ($ref).
    base_uri = f"file://{SCHEMAS_DIR.resolve()}/"
    resolver = RefResolver(base_uri=base_uri, referrer=schema)

    validator = Draft202012Validator(
        schema, resolver=resolver, format_checker=FormatChecker()
    )

    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        mensajes = []
        for error in errors:
            path = ".".join(str(p) for p in error.path) or "<root>"
            mensajes.append(f"{path}: {error.message}")
        raise ValueError("Errores de validación del schema:\n" + "\n".join(mensajes))
    return None


__all__ = [
    "generar_factura_fiscal",
    "generar_consumidor_final",
    "generar_nota_debito",
    "generar_nota_credito",
    "generar_nota_remision",
    "validar_contra_schema",
]
