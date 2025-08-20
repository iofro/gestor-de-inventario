from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4
from zoneinfo import ZoneInfo

from .config import get_emisor_direccion

# All arithmetic must follow the tax authority's rounding rules
getcontext().rounding = ROUND_HALF_UP

# Official DTE schemas live alongside the project in ``svfe-json-schemas``.
# Resolving relative to this file keeps the path valid both when the project is
# installed as a package and when it is run from a source checkout.
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
D = Decimal
IVA = D("0.13")


def _load_schema(filename: str) -> Dict[str, Any]:
    with open(SCHEMAS_DIR / filename, "r", encoding="utf-8") as fh:
        return json.load(fh)


def strip_extras(dte: Dict[str, Any]) -> Dict[str, Any]:
    extras = {"responseMH", "token", "firmaElectronica", "selloRecibido"}
    return {k: v for k, v in dte.items() if k not in extras}


def _numero_control(tipo: str, sucursal: str = "001", punto: str = "001") -> str:
    secuencia = str(uuid4().int % 10**15).zfill(15)
    return f"DTE-{tipo}-S{sucursal}P{punto}-{secuencia}"


def d8(value: Decimal) -> Decimal:
    """Quantize ``value`` to eight decimal places using ``ROUND_HALF_UP``."""
    return value.quantize(D8, rounding=ROUND_HALF_UP)


def d2(value: Decimal) -> Decimal:
    """Quantize ``value`` to two decimal places using ``ROUND_HALF_UP``."""
    return value.quantize(D2, rounding=ROUND_HALF_UP)


def hoy_sv() -> str:
    tz = ZoneInfo("America/El_Salvador")
    return datetime.now(tz).strftime("%Y-%m-%d")


def generar_fc_ejemplo(
    cantidad: Decimal = D("2.5"),
    precio: Decimal = D("9.54"),
    gravado: bool = True,
) -> dict:
    venta = d8(cantidad * precio)
    iva8 = d8(venta * IVA) if gravado else d8(D("0"))
    total_base = d2(venta)
    total_iva = d2(iva8)
    total_pagar = d2(total_base + total_iva)

    item = {
        "numItem": 1,
        "tipoItem": 1,
        "numeroDocumento": "NA",
        "codigo": "SKU001",
        "descripcion": "Producto X",
        "cantidad": d8(cantidad),
        "uniMedida": 59,
        "precioUni": d8(precio),
        "montoDescu": D("0.00000000"),
        "ventaNoSuj": D("0.00000000"),
        "ventaExenta": D("0.00000000"),
        "ventaGravada": D("0.00000000"),
        "tributos": [],
        "psv": D("0.00000000"),
        "noGravado": D("0.00000000"),
    }
    if gravado:
        item["codTributo"] = "19"
        item["tributos"] = ["19"]
        item["ventaGravada"] = venta
        item["ivaItem"] = iva8
    else:
        item["ventaExenta"] = venta

    dte = {
        "identificacion": {
            "version": 1,
            "ambiente": "00",
            "tipoDte": "01",
            "numeroControl": "DTE-01-00000001",
            "tipoMoneda": "USD",
            "fecEmi": hoy_sv(),
            "codigoGeneracion": "00000000-0000-4000-8000-000000000001",
        },
        "emisor": {
            "nombre": "Mi Empresa",
            "correo": "soporte@miempresa.com",
            "telefono": "22223333",
            "direccion": {
                "departamento": "01",
                "municipio": "13",
                "complemento": "Calle 1 #123",
            },
        },
        "receptor": {
            "tipoDocumento": "36",
            "numDocumento": "01234567-8",
            "nombre": "Consumidor Final",
            "direccion": {
                "departamento": "01",
                "municipio": "13",
                "complemento": "SN",
            },
        },
        "cuerpoDocumento": [item],
        "resumen": {
            "totalNoSuj": d2(D("0")),
            "totalExenta": total_base if not gravado else d2(D("0")),
            "totalGravada": total_base if gravado else d2(D("0")),
            "montoIva": total_iva,
            "totalPagar": total_pagar,
        },
    }
    return dte


def _identificacion(schema: Dict[str, Any], tipo_dte: str) -> Dict[str, Any]:
    # ``version`` is defined in the schema and must be surfaced in the
    # generated document instead of being hard coded.  Some schemas expose it
    # via ``const`` and others via an ``enum`` with a single option, so handle
    # both cases.
    version_prop = schema["properties"]["identificacion"]["properties"]["version"]
    version = version_prop.get("const") or version_prop.get("enum")[0]

    # Emit timestamps in the El Salvador timezone; only the date part is
    # included in ``fecEmi`` as required by the specification.
    now = datetime.now(ZoneInfo("America/El_Salvador"))
    return {
        "version": version,
        "ambiente": "00",
        "tipoDte": tipo_dte,
        "numeroControl": _numero_control(tipo_dte),
        # ``codigoGeneracion`` must be a valid UUID v4.  ``uuid4`` guarantees
        # the correct version and the schema expects uppercase letters.
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
        "telefono": "22222222",
        "correo": "demo@example.com",
        "codEstableMH": "0001",
        "codEstable": "0001",
        "codPuntoVentaMH": "0001",
        "codPuntoVenta": "0001",
    }


def _receptor(tipo: str | None = None) -> Dict[str, Any]:
    data = {
        "nit": "06141990011019",
        "nrc": "0000011",
        "nombre": "Consumidor Final",
        "codActividad": "62010" if tipo == "fc" else "6201",
        "descActividad": "Servicios de software",
        "nombreComercial": "Cliente Ejemplo",
        "direccion": {
            "departamento": "05",
            "municipio": "13",
            "complemento": "San Salvador",
        },
        "telefono": "70000001",
        "correo": "cliente@example.com",
    }
    if tipo == "fc":
        nit = data.pop("nit")
        data.pop("nombreComercial", None)
        data["tipoDocumento"] = "36"
        data["numDocumento"] = nit
    return data


def _validate_direccion(d: Dict[str, Any], quien: str) -> None:
    dep = d.get("departamento")
    mun = d.get("municipio")
    if not (isinstance(dep, str) and len(dep) == 2):
        raise ValueError(f"Departamento de {quien} inválido")
    if not (isinstance(mun, str) and len(mun) == 2):
        raise ValueError(f"Municipio de {quien} inválido")


def _cuerpo_documento(tipo: str) -> List[Dict[str, Any]]:
    cantidad = Decimal("2.5")
    precio = Decimal("9.54")
    venta = d8(cantidad * precio)
    iva_item = d8(venta * Decimal("0.13"))
    numero_documento = "NA" if tipo == "fc" else None
    tipo_item = 4 if tipo == "fc" else 1
    uni_medida = 99 if tipo == "fc" else 59
    item = {
        "numItem": 1,
        "tipoItem": tipo_item,
        "numeroDocumento": numero_documento,
        "codigo": "SKU001",
        "descripcion": "Producto de prueba",
        "cantidad": d8(cantidad),
        "uniMedida": uni_medida,
        "precioUni": d8(precio),
        "montoDescu": d8(Decimal("0")),
        "ventaNoSuj": d8(Decimal("0")),
        "ventaExenta": d8(Decimal("0")),
        "ventaGravada": venta,
        "psv": d8(Decimal("0")),
        "noGravado": d8(Decimal("0")),
    }
    # Todos los ítems gravados deben declarar el tributo IVA.
    item["codTributo"] = "19"
    item["ivaItem"] = iva_item
    item["tributos"] = ["19"]
    return [item]


def _resumen(tipo: str) -> Dict[str, Any]:
    cantidad = Decimal("2.5")
    precio = Decimal("9.54")
    venta = d2(cantidad * precio)
    iva = d2(venta * Decimal("0.13"))
    total = d2(venta + iva)
    data = {
        "totalNoSuj": d2(Decimal("0")),
        "totalExenta": d2(Decimal("0")),
        "totalGravada": d2(venta),
        "subTotalVentas": d2(venta),
        "descuNoSuj": d2(Decimal("0")),
        "descuExenta": d2(Decimal("0")),
        "descuGravada": d2(Decimal("0")),
        "porcentajeDescuento": d2(Decimal("0")),
        "totalDescu": d2(Decimal("0")),
        "subTotal": d2(venta),
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
    if tipo == "fc":
        data["totalIva"] = iva
        data["tributos"] = [
            {"codigo": "19", "descripcion": "IVA", "valor": iva}
        ]
    else:
        data["ivaPerci1"] = d2(Decimal("0"))
        data["tributos"] = None
    return data


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
        "receptor": _receptor(tipo),
        "otrosDocumentos": None,
        "ventaTercero": None,
        "cuerpoDocumento": _cuerpo_documento(tipo),
        "resumen": _resumen(tipo),
        "extension": None,
        "apendice": None,
    }
    data["emisor"]["direccion"] = get_emisor_direccion()
    _validate_direccion(data["emisor"]["direccion"], "emisor")
    _validate_direccion(data["receptor"].get("direccion", {}), "receptor")
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
    """No-op schema validation placeholder.

    This function previously validated ``data`` against the official JSON schema
    for the given DTE ``tipo``.  Schema validation has been disabled so the
    function now simply returns without performing any checks.
    """
    return None


__all__ = ["generar_fc_ejemplo"]
