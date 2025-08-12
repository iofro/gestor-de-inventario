import json
import os
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext
from db import DB
import requests
from utils import jws
import auth
from jsonschema import Draft7Validator, ValidationError
from utils import catalogos
import logging

logger = logging.getLogger(__name__)

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "datos_negocio.json")
CONFIG_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "config_negocio.json")
DEFAULT_RECEPCION_URL = "https://sandbox.dtes.mh.gob.sv/recepciondte/api/recepciondte"

ALLOWED_TOP_KEYS = {
    "identificacion",
    "emisor",
    "receptor",
    "cuerpoDocumento",
    "resumen",
    "documentoRelacionado",
    "otrosDocumentos",
    "ventaTercero",
    "extension",
    "apendice",
}

DISALLOWED_KEYS = {"firmaElectronica", "selloRecibido"}


def _sanitize(data, allowed_keys=None):
    """Recursively remove keys not allowed by ``allowed_keys`` or present in
    ``DISALLOWED_KEYS``."""
    if isinstance(data, dict):
        clean = {}
        for k, v in data.items():
            if k in DISALLOWED_KEYS:
                continue
            if allowed_keys is not None and k not in allowed_keys:
                continue
            if isinstance(v, dict):
                clean[k] = _sanitize(v)
            elif isinstance(v, list):
                clean[k] = [_sanitize(x) for x in v]
            else:
                clean[k] = v
        return clean
    if isinstance(data, list):
        return [_sanitize(x) for x in data]
    return data


def sanitize_dte_payload(data: dict) -> dict:
    """Return ``data`` excluding properties not allowed by the DTE schema."""
    return _sanitize(data, ALLOWED_TOP_KEYS)

# Ensure enough precision when other modules modify the global decimal context
getcontext().prec = 28


def _round(value, digits):
    """Round ``value`` to ``digits`` decimal places using HALF_UP."""
    if value is None:
        value = 0
    fmt = "0." + "0" * digits
    return float(Decimal(str(value)).quantize(Decimal(fmt), rounding=ROUND_HALF_UP))


def _validate_schema(instance: dict, schema: dict) -> None:
    """Validate ``instance`` against ``schema`` reporting all errors.

    Prints a full report of all schema validation issues found and raises
    ``ValidationError`` with the combined message if any problems exist.
    """
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
    if errors:
        lines = ["Errores de esquema encontrados:"]
        for err in errors:
            path = ".".join(str(p) for p in err.path) or "<root>"
            lines.append(f"- {path}: {err.message}")
        report = "\n".join(lines)
        print(report)
        raise ValidationError(report)


def _load_datos_negocio():
    if os.path.exists(DATOS_NEGOCIO_PATH):
        try:
            with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


DEPARTAMENTO_CODES = {
    "Ahuachapán": "01",
    "Santa Ana": "02",
    "Sonsonate": "03",
    "Chalatenango": "04",
    "La Libertad": "05",
    "San Salvador": "06",
    "Cuscatlán": "07",
    "La Paz": "08",
    "Cabañas": "09",
    "San Vicente": "10",
    "Usulután": "11",
    "San Miguel": "12",
    "Morazán": "13",
    "La Unión": "14",
}


def _map_departamento(nombre: str | None) -> str:
    return DEPARTAMENTO_CODES.get(nombre, "01")


def _clean_nit(nit):
    if nit:
        return "".join(c for c in str(nit) if c.isdigit())
    return None


def _clean_nrc(nrc):
    if nrc:
        return "".join(c for c in str(nrc) if c.isdigit())
    return None


# --- Helpers ---------------------------------------------------------------

# Valores por defecto del resumen según el tipo de DTE
RESUMEN_DEFAULTS = {
    "01": {
        "totalNoSuj": 0,
        "totalExenta": 0,
        "totalGravada": 0,
        "subTotalVentas": 0,
        "descuNoSuj": 0,
        "descuExenta": 0,
        "descuGravada": 0,
        "porcentajeDescuento": 0,
        "totalDescu": 0,
        "tributos": None,
        "subTotal": 0,
        "ivaRete1": 0,
        "reteRenta": 0,
        "montoTotalOperacion": 0,
        "totalNoGravado": 0,
        "totalPagar": 0,
        "totalLetras": "",
        "totalIva": 0,
        "saldoFavor": 0,
        "condicionOperacion": 1,
        "pagos": None,
        "numPagoElectronico": None,
    },
    "03": {
        "totalNoSuj": 0,
        "totalExenta": 0,
        "totalGravada": 0,
        "subTotalVentas": 0,
        "descuNoSuj": 0,
        "descuExenta": 0,
        "descuGravada": 0,
        "porcentajeDescuento": 0,
        "totalDescu": 0,
        "tributos": None,
        "subTotal": 0,
        "ivaPerci1": 0,
        "ivaRete1": 0,
        "reteRenta": 0,
        "montoTotalOperacion": 0,
        "totalNoGravado": 0,
        "totalPagar": 0,
        "totalLetras": "",
        "saldoFavor": 0,
        "condicionOperacion": 1,
        "pagos": None,
        "numPagoElectronico": None,
    },
    "04": {
        "totalNoSuj": 0,
        "totalExenta": 0,
        "totalGravada": 0,
        "subTotalVentas": 0,
        "descuNoSuj": 0,
        "descuExenta": 0,
        "descuGravada": 0,
        "porcentajeDescuento": 0,
        "totalDescu": 0,
        "tributos": None,
        "subTotal": 0,
        "montoTotalOperacion": 0,
        "totalLetras": "",
    },
    "05": {
        "totalNoSuj": 0,
        "totalExenta": 0,
        "totalGravada": 0,
        "subTotalVentas": 0,
        "descuNoSuj": 0,
        "descuExenta": 0,
        "descuGravada": 0,
        "totalDescu": 0,
        "tributos": None,
        "subTotal": 0,
        "ivaPerci1": 0,
        "ivaRete1": 0,
        "reteRenta": 0,
        "montoTotalOperacion": 0,
        "totalNoGravado": 0,
        "totalPagar": 0,
        "totalLetras": "",
        "saldoFavor": 0,
        "condicionOperacion": 1,
        "pagos": None,
        "numPagoElectronico": None,
    },
    "06": {
        "totalNoSuj": 0,
        "totalExenta": 0,
        "totalGravada": 0,
        "subTotalVentas": 0,
        "descuNoSuj": 0,
        "descuExenta": 0,
        "descuGravada": 0,
        "totalDescu": 0,
        "tributos": None,
        "subTotal": 0,
        "ivaPerci1": 0,
        "ivaRete1": 0,
        "reteRenta": 0,
        "montoTotalOperacion": 0,
        "totalLetras": "",
        "condicionOperacion": 1,
        "numPagoElectronico": None,
    },
}


import re


def normalizar_pagos(pagos_raw, total):
    """Normaliza la lista de pagos al formato del esquema."""
    pattern = re.compile(r"^(0[1-9]|1[0-4]|99)$")
    pagos = []
    for p in pagos_raw or []:
        codigo = str(p.get("codigo", "")).zfill(2)
        if not pattern.match(codigo):
            continue
        monto = _round(p.get("montoPago", 0), 2)
        pagos.append(
            {
                "codigo": codigo,
                "montoPago": monto,
                "referencia": p.get("referencia"),
                "periodo": p.get("periodo"),
                "plazo": p.get("plazo"),
            }
        )
    if not pagos:
        pagos = [
            {
                "codigo": "01",
                "montoPago": _round(total, 2),
                "referencia": None,
                "periodo": None,
                "plazo": None,
            }
        ]
    return pagos


def armar_tributos(tributos_raw, tipo_dte):
    """Construye la lista de tributos o retorna ``None``."""
    if not tributos_raw:
        return None
    schema_path = catalogos.SCHEMA_MAP.get(tipo_dte)
    allowed = set()
    if schema_path and os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        allowed = set(
            schema.get("properties", {})
            .get("resumen", {})
            .get("properties", {})
            .get("tributos", {})
            .get("items", {})
            .get("properties", {})
            .get("codigo", {})
            .get("enum", [])
        )
    result = []
    for t in tributos_raw or []:
        codigo = str(t.get("codigo", "")).upper()
        if allowed and codigo not in allowed:
            continue
        result.append(
            {
                "codigo": codigo,
                "descripcion": t.get("descripcion"),
                "valor": _round(t.get("valor", 0), 2),
            }
        )
    return result or None


def calcular_resumen(items_total, venta, fiscal=None, extra=None, tipo_dte="01"):
    """Calcula la sección resumen acorde al esquema oficial."""
    fiscal = fiscal or {}
    extra = extra or {}

    items_total = Decimal(str(items_total))
    sumas_val = Decimal(str(fiscal.get("sumas", items_total)))
    descuentos_val = Decimal(str(fiscal.get("descuentos", 0)))
    iva_val = Decimal(str(fiscal.get("iva", 0)))
    total_no_suj = Decimal(str(fiscal.get("ventas_no_sujetas", 0)))
    total_exenta = Decimal(str(fiscal.get("ventas_exentas", 0)))

    sub_total_ventas = total_no_suj + total_exenta + sumas_val
    total_descu = descuentos_val
    porcentaje_desc = (
        (total_descu * Decimal("100") / sub_total_ventas) if sub_total_ventas else Decimal("0")
    )
    sub_total = sub_total_ventas - total_descu
    monto_total = sub_total + iva_val

    resumen = RESUMEN_DEFAULTS.get(tipo_dte, {}).copy()
    resumen.update(
        {
            "totalNoSuj": total_no_suj,
            "totalExenta": total_exenta,
            "totalGravada": sumas_val,
            "subTotalVentas": sub_total_ventas,
            "descuNoSuj": Decimal("0"),
            "descuExenta": Decimal("0"),
            "descuGravada": descuentos_val,
            "totalDescu": total_descu,
            "subTotal": sub_total,
            "montoTotalOperacion": monto_total,
            "totalLetras": venta.get("total_letras", ""),
        }
    )
    if "porcentajeDescuento" in resumen:
        resumen["porcentajeDescuento"] = porcentaje_desc

    if tipo_dte == "01":
        resumen["totalIva"] = iva_val
    else:
        resumen["ivaPerci1"] = resumen.get("ivaPerci1", 0)

    if "totalPagar" in resumen:
        resumen["totalPagar"] = Decimal(str(venta.get("total", monto_total)))
    if "pagos" in resumen:
        resumen["pagos"] = normalizar_pagos(extra.get("pagos"), resumen["totalPagar"])
    if "tributos" in resumen:
        resumen["tributos"] = armar_tributos(extra.get("tributos"), tipo_dte)
    if "numPagoElectronico" in resumen:
        resumen["numPagoElectronico"] = extra.get("numPagoElectronico")

    # Redondeamos valores numéricos
    for k, v in resumen.items():
        if isinstance(v, (int, float, Decimal)):
            resumen[k] = _round(v, 2)

    return resumen


def generar_numero_control(prefijo: str = "DTE-01-S001P001") -> str:
    """Crea un número de control único siguiendo el formato de Hacienda."""
    secuencia = str(uuid.uuid4().int % 10**15).zfill(15)
    return f"{prefijo}-{secuencia}"


def generar_cabecera_dte_data(modelo_facturacion: str, tipo_transmision: str) -> dict:
    """Genera los datos para la cabecera de un DTE.

    Los campos de código de generación y número de control se crean antes de
    enviar la factura. Los valores que envía Hacienda posteriormente (código de
    generación y sello recibido) se dejan en ``None``.
    """
    codigo_generacion = str(uuid.uuid4()).upper()
    numero_control = generar_numero_control()
    fecha_generacion = datetime.now().strftime("%d/%m/%Y, %I:%M %p")
    return {
        "codigo_generacion": codigo_generacion,
        "numero_control": numero_control,
        "sello_recepcion": None,
        "modelo_facturacion": modelo_facturacion,
        "tipo_transmision": tipo_transmision,
        "fecha_generacion": fecha_generacion,
    }

def generar_dte_json(
    db: DB,
    venta_id: int,
    modelo_facturacion: str = "1 - Facturación previo",
    tipo_transmision: str = "1 - Transmisión normal",
    tipo_dte: str = "01",
) -> dict:
    """Genera un diccionario DTE básico para una venta."""
    row = db.cursor.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone()
    if not row:
        raise ValueError("Venta no encontrada")
    venta = dict(row)

    detalles = db.get_detalles_venta(venta_id)
    fiscal = db.get_venta_credito_fiscal(venta_id)
    extra = {}
    raw_extra = venta.get("extra")
    if raw_extra:
        try:
            extra = json.loads(raw_extra)
        except Exception:
            extra = {}

    cliente = None
    if venta.get("cliente_id"):
        cliente = db.get_cliente(venta["cliente_id"])

    datos = _load_datos_negocio()

    codigo_generacion = str(uuid.uuid4()).upper()
    numero_control = generar_numero_control()

    fecha = venta.get("fecha") or datetime.now().strftime("%Y-%m-%d")
    hora = datetime.now().strftime("%H:%M:%S")

    identificacion = {
        "version": "1",
        "tipoDte": tipo_dte,
        "codigoGeneracion": codigo_generacion,
        "numeroControl": numero_control,
        "fecEmi": fecha,
        "horEmi": hora,
        "modeloFacturacion": modelo_facturacion,
        "tipoTransmision": tipo_transmision,
    }

    emisor = {
        "nombre": datos.get("razon_social"),
        "nit": datos.get("nit"),
        "nrc": datos.get("nrc"),
        "giro": datos.get("giro"),
        "direccion": datos.get("direccion"),
    }

    rec = cliente or {}
    def _clean_nit(nit):
        if nit:
            return "".join(c for c in str(nit) if c.isdigit())
        return None

    nit = rec.get("nit")
    if fiscal:
        nit = fiscal.get("nit") or nit

    receptor = {
        "tipoDocumento": "36" if nit else None,
        "numDocumento": _clean_nit(nit),
        "nrc": (fiscal.get("nrc") if fiscal else None) or rec.get("nrc"),
        "nombre": rec.get("nombre"),
        "codActividad": None,
        "descActividad": None,
        "direccion": None,
        "telefono": rec.get("telefono"),
        "correo": rec.get("correo"),
    }
    if fiscal:
        if fiscal.get("no_remision"):
            receptor["noRemision"] = fiscal.get("no_remision")
        if fiscal.get("orden_no"):
            receptor["ordenNo"] = fiscal.get("orden_no")

    cuerpo = []
    items_total = Decimal("0")
    commission_total = Decimal("0")
    for idx, d in enumerate(detalles, 1):
        try:
            cant = Decimal(str(d.get("cantidad") or 0))
        except Exception:
            cant = Decimal(0)
        try:
            price = Decimal(str(d.get("precio_unitario") or 0))
        except Exception:
            price = Decimal(0)
        cant_r = cant.quantize(Decimal("0.00000000"), rounding=ROUND_HALF_UP)
        price_r = price.quantize(Decimal("0.00000000"), rounding=ROUND_HALF_UP)
        items_total += cant_r * price_r
        try:
            commission_total += Decimal(str(d.get("comision") or 0))
        except Exception:
            pass
        cuerpo.append({
            "numItem": idx,
            "descripcion": d.get("descripcion"),
            "cantidad": float(cant_r),
            "precioUnitario": float(price_r),
        })

    resumen = calcular_resumen(
        items_total,
        venta,
        fiscal=fiscal,
        extra=extra,
        tipo_dte=tipo_dte,
    )

    # Validaciones básicas de consistencia
    items_total_2 = _round(items_total, 2)
    if abs(items_total_2 - resumen.get("subTotalVentas", 0)) > 0.01:
        print(
            f"Advertencia: la suma de los ítems {items_total_2:.2f} difiere del resumen {resumen.get('subTotalVentas',0):.2f}"
        )

    calc_sub_total = _round(
        resumen.get("subTotalVentas", 0) - resumen.get("totalDescu", 0), 2
    )
    if abs(calc_sub_total - resumen.get("subTotal", 0)) > 0.01:
        print(
            f"Advertencia: el subtotal calculado {calc_sub_total:.2f} difiere del resumen {resumen.get('subTotal',0):.2f}"
        )

    iva_ref = resumen.get("totalIva")
    if iva_ref is None:
        iva_ref = resumen.get("ivaPerci1", 0)
    calc_total = _round(calc_sub_total + (iva_ref or 0), 2)
    if abs(calc_total - resumen.get("montoTotalOperacion", 0)) > 0.01:
        print(
            f"Advertencia: el monto total {resumen.get('montoTotalOperacion',0):.2f} difiere del calculado {calc_total:.2f}"
        )
    calc_total_commission = _round(calc_total + float(commission_total), 2)
    if "totalPagar" in resumen and abs(calc_total_commission - resumen.get("totalPagar", 0)) > 0.01:
        print(
            f"Advertencia: el total a pagar {resumen.get('totalPagar',0):.2f} difiere del calculado {calc_total_commission:.2f}"
        )

    result = {
        "identificacion": identificacion,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": cuerpo,
        "resumen": resumen,
        # Campos obligatorios que pueden no tener información
        "documentoRelacionado": None,
        "otrosDocumentos": None,
        "ventaTercero": None,
        "extension": None,
        "apendice": None,
        "firmaElectronica": None,
        "selloRecibido": None,
    }
    if fiscal:
        result["condicionPago"] = fiscal.get("condicion_pago")

    if fiscal:
        if fiscal.get("venta_a_cuenta_de"):
            result["ventaACuentaDe"] = fiscal.get("venta_a_cuenta_de")
        if fiscal.get("documento_venta_a_cuenta"):
            result["documentoVentaACuenta"] = fiscal.get("documento_venta_a_cuenta")
    else:
        if extra.get("venta_a_cuenta_de"):
            result["ventaACuentaDe"] = extra.get("venta_a_cuenta_de")
        if extra.get("documento_venta_a_cuenta"):
            result["documentoVentaACuenta"] = extra.get("documento_venta_a_cuenta")

    return result


def validate_dte_json(data: dict) -> None:
    """Basic validation and normalization for DTE payload before signing."""
    required = ["identificacion", "emisor", "receptor", "cuerpoDocumento", "resumen"]
    for key in required:
        if key not in data:
            raise ValueError(f"Falta el campo obligatorio: {key}")

    negocio = _load_datos_negocio()

    ident = data.get("identificacion", {})
    config = _load_dte_api_config()
    ambiente = "01" if config.get("ambiente") == "produccion" else "00"
    ident.setdefault("ambiente", ambiente)
    ident.setdefault("tipoMoneda", "USD")
    ident.setdefault("tipoContingencia", None)
    ident.setdefault("motivoContin", None)
    if "modeloFacturacion" in ident:
        ident["tipoModelo"] = int(str(ident.pop("modeloFacturacion")).split()[0])
    ident.setdefault("tipoModelo", 1)
    if "tipoTransmision" in ident:
        ident["tipoOperacion"] = int(str(ident.pop("tipoTransmision")).split()[0])
    ident.setdefault("tipoOperacion", 1)
    ident["version"] = int(ident.get("version", 1))
    cg = ident.get("codigoGeneracion")
    try:
        ident["codigoGeneracion"] = str(uuid.UUID(str(cg))).upper()
    except Exception:
        ident["codigoGeneracion"] = str(uuid.uuid4()).upper()
    data["identificacion"] = ident

    emisor = data.get("emisor", {})
    emisor["nit"] = _clean_nit(emisor.get("nit") or negocio.get("nit"))
    emisor["nrc"] = _clean_nrc(emisor.get("nrc") or negocio.get("nrc"))
    emisor.setdefault("nombre", negocio.get("razon_social"))
    emisor.setdefault("codActividad", negocio.get("ciiu"))
    emisor.setdefault("descActividad", negocio.get("giro"))
    emisor.setdefault("nombreComercial", negocio.get("nombre_comercial"))
    emisor.setdefault("tipoEstablecimiento", "01")
    direccion = emisor.get("direccion")
    if not isinstance(direccion, dict):
        direccion = {
            "departamento": _map_departamento(negocio.get("departamento")),
            "municipio": "01",
            "complemento": negocio.get("direccion") if direccion is None else direccion,
        }
    emisor["direccion"] = direccion
    emisor.setdefault("telefono", negocio.get("telefono_movil") or negocio.get("telefono_fijo"))
    emisor.setdefault("correo", negocio.get("email"))
    emisor.setdefault("codEstableMH", "0000")
    emisor.setdefault("codEstable", "0000")
    emisor.setdefault("codPuntoVentaMH", "0000")
    emisor.setdefault("codPuntoVenta", "0000")
    emisor.pop("giro", None)
    data["emisor"] = emisor

    receptor = data.get("receptor", {})
    receptor["nrc"] = _clean_nrc(receptor.get("nrc"))
    if "nit" in receptor:
        receptor["numDocumento"] = _clean_nit(receptor.pop("nit"))
    else:
        receptor["numDocumento"] = _clean_nit(receptor.get("numDocumento"))
    receptor.pop("giro", None)
    data["receptor"] = receptor

    cuerpo = data.get("cuerpoDocumento", [])
    items_total = Decimal("0")
    for item in cuerpo:
        if "precioUnitario" in item:
            item["precioUni"] = item.pop("precioUnitario")
        item.setdefault("tipoItem", 1)
        item.setdefault("numeroDocumento", None)
        item.setdefault("codigo", None)
        item.setdefault("codTributo", None)
        item.setdefault("uniMedida", 59)
        item.setdefault("montoDescu", 0.0)
        item.setdefault("ventaNoSuj", 0.0)
        item.setdefault("ventaExenta", 0.0)
        item.setdefault("tributos", None)
        item.setdefault("psv", 0.0)
        item.setdefault("noGravado", 0.0)
        item.setdefault("ivaItem", 0.0)
        cantidad = Decimal(str(item.get("cantidad", 0)))
        precio = Decimal(str(item.get("precioUni", 0)))
        item["cantidad"] = float(cantidad.quantize(Decimal("0.00000000"), rounding=ROUND_HALF_UP))
        item["precioUni"] = float(precio.quantize(Decimal("0.00000000"), rounding=ROUND_HALF_UP))
        importe = cantidad * precio
        item.setdefault(
            "ventaGravada",
            float(importe.quantize(Decimal("0.00000000"), rounding=ROUND_HALF_UP)),
        )
        items_total += importe
    data["cuerpoDocumento"] = cuerpo

    resumen = data.get("resumen", {})
    for k, v in resumen.items():
        if isinstance(v, (int, float)):
            resumen[k] = _round(v, 2)
        elif isinstance(v, str):
            try:
                resumen[k] = _round(float(v), 2)
            except Exception:
                pass
    data["resumen"] = resumen

    total_grav = Decimal(str(resumen.get("totalGravada", 0)))
    total_exenta = Decimal(str(resumen.get("totalExenta", 0)))
    total_no_suj = Decimal(str(resumen.get("totalNoSuj", 0)))
    sub_total_ventas = Decimal(
        str(resumen.get("subTotalVentas", total_grav + total_exenta + total_no_suj))
    )
    total_descu = Decimal(str(resumen.get("totalDescu", 0)))
    total_iva = Decimal(str(resumen.get("totalIva", resumen.get("ivaPerci1", 0))))
    sub_total = Decimal(str(resumen.get("subTotal", 0)))
    total = Decimal(str(resumen.get("totalPagar", resumen.get("montoTotalOperacion", 0))))

    items_total_2 = Decimal(str(_round(items_total, 2)))
    if abs(items_total_2 - sub_total_ventas) > Decimal("0.01"):
        print(
            f"Advertencia: la suma de los ítems {items_total_2:.2f} difiere del resumen {sub_total_ventas:.2f}"
        )

    calc_sub = sub_total_ventas - total_descu
    calc_sub = Decimal(str(_round(calc_sub, 2)))
    if abs(calc_sub - sub_total) > Decimal("0.01"):
        print(
            f"Advertencia: el subtotal calculado {calc_sub:.2f} difiere del resumen {sub_total:.2f}"
        )
    calc_total = calc_sub + total_iva
    calc_total = Decimal(str(_round(calc_total, 2)))
    if abs(calc_total - total) > Decimal("0.01"):
        print(
            f"Advertencia: el total a pagar {total:.2f} difiere del calculado {calc_total:.2f}"
        )

    # --- Catálogo validations ---
    ident = data.get("identificacion", {})
    tipo_dte = ident.get("tipoDte")
    if tipo_dte not in catalogos.TIPOS_DTE:
        raise ValueError("Código de tipoDte inválido")

    # Modelo de facturación / tipo de operación
    modelo_val = ident.get("tipoModelo") or ident.get("modeloFacturacion")
    try:
        modelo_cod = int(str(modelo_val).split("-")[0].strip())
    except Exception:
        raise ValueError("Modelo de facturación inválido")
    if modelo_cod not in catalogos.MODELOS_FACTURACION:
        raise ValueError("Modelo de facturación inválido")
    ident["tipoModelo"] = modelo_cod

    oper_val = ident.get("tipoOperacion") or ident.get("tipoTransmision")
    try:
        oper_cod = int(str(oper_val).split("-")[0].strip())
    except Exception:
        raise ValueError("Tipo de operación inválido")
    ident["tipoOperacion"] = oper_cod

    # Validación de longitud de NIT / numDocumento
    emisor_nit = data.get("emisor", {}).get("nit")
    if emisor_nit and len(emisor_nit.replace("-", "")) != catalogos.NIT_LENGTH:
        raise ValueError("NIT inválido en emisor")

    receptor_doc = data.get("receptor", {}).get("numDocumento")
    if receptor_doc and len(receptor_doc) not in (9, catalogos.NIT_LENGTH):
        raise ValueError("Número de documento inválido en receptor")

    # --- Schema validation ---
    schema_path = catalogos.SCHEMA_MAP.get(tipo_dte)
    if schema_path and os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        _validate_schema(instance=data, schema=schema)


def generar_ticket_json(
    db: DB,
    venta_id: int,
    modelo_facturacion: str = "1 - Facturación previo",
    tipo_transmision: str = "1 - Transmisión normal",
) -> dict:
    """Genera la estructura JSON para un Ticket Electrónico."""
    return generar_dte_json(
        db,
        venta_id,
        modelo_facturacion=modelo_facturacion,
        tipo_transmision=tipo_transmision,
        tipo_dte="03",
    )


def generar_nota_credito_json(db: DB, nota_id: int) -> dict:
    """Genera la estructura JSON para una nota de crédito."""
    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")
    nota = dict(row)
    if nota.get("tipo") != "credito":
        raise ValueError("La nota indicada no es de crédito")

    venta_id = nota.get("venta_id")
    # Determine document type of the original sale
    venta_row = db.cursor.execute(
        "SELECT cliente_id FROM ventas WHERE id=?", (venta_id,)
    ).fetchone()
    tipo_doc = "01"
    if venta_row:
        venta = dict(venta_row)
        if not db.get_venta_credito_fiscal(venta_id) and not venta.get("cliente_id"):
            tipo_doc = "03"
    data = generar_dte_json(db, venta_id, tipo_dte="05")
    data["documentoRelacionado"] = {
        "tipoDoc": tipo_doc,
        "numeroDocumento": data["identificacion"].get("numeroControl") or venta_id,
    }

    for item in data.get("cuerpoDocumento", []):
        if isinstance(item.get("cantidad"), (int, float)):
            item["cantidad"] = -abs(item["cantidad"])
        if isinstance(item.get("precioUnitario"), (int, float)):
            item["precioUnitario"] = -abs(item["precioUnitario"])

    resumen = data.get("resumen", {})
    for k, v in resumen.items():
        if isinstance(v, (int, float)):
            resumen[k] = -abs(v)
    data["resumen"] = resumen
    return data


def generar_nota_debito_json(db: DB, nota_id: int) -> dict:
    """Genera la estructura JSON para una nota de débito."""
    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")
    nota = dict(row)
    if nota.get("tipo") != "debito":
        raise ValueError("La nota indicada no es de débito")

    venta_id = nota.get("venta_id")
    venta_row = db.cursor.execute(
        "SELECT cliente_id FROM ventas WHERE id=?", (venta_id,)
    ).fetchone()
    tipo_doc = "01"
    if venta_row:
        venta = dict(venta_row)
        if not db.get_venta_credito_fiscal(venta_id) and not venta.get("cliente_id"):
            tipo_doc = "03"
    data = generar_dte_json(db, venta_id, tipo_dte="06")
    data["documentoRelacionado"] = {
        "tipoDoc": tipo_doc,
        "numeroDocumento": data["identificacion"].get("numeroControl") or venta_id,
    }
    return data


def generar_nota_remision_json(db: DB, nota_id: int) -> dict:
    """Genera la estructura JSON para una nota de remisión."""
    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")
    nota = dict(row)
    if nota.get("tipo") != "remision":
        raise ValueError("La nota indicada no es de remisión")

    venta_id = nota.get("venta_id")
    venta_row = db.cursor.execute(
        "SELECT cliente_id FROM ventas WHERE id=?", (venta_id,)
    ).fetchone()
    tipo_doc = "01"
    if venta_row:
        venta = dict(venta_row)
        if not db.get_venta_credito_fiscal(venta_id) and not venta.get("cliente_id"):
            tipo_doc = "03"
    data = generar_dte_json(db, venta_id, tipo_dte="04")
    data["documentoRelacionado"] = {
        "tipoDoc": tipo_doc,
        "numeroDocumento": data["identificacion"].get("numeroControl") or venta_id,
    }
    return data


def _load_dte_api_config():
    """Lee configuración de URLs y ambiente desde ``config_negocio.json``."""
    try:
        with open(CONFIG_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        ambiente = data.get("ambiente", "pruebas")
        env_conf = data.get(ambiente, {})
        url = env_conf.get("recepcion_url")
        return {"ambiente": ambiente, "url": url}
    except Exception:
        return {}


def _save_signed_dte(dte_data: dict, jws_token: str) -> None:
    """Guarda el JSON original y el JWS en ``/dtes/{anio}/``."""
    try:
        fecha = dte_data.get("identificacion", {}).get("fecEmi") or datetime.now().strftime("%Y-%m-%d")
        year = str(fecha)[:4]
        base_dir = os.path.join(os.path.dirname(__file__), "dtes", year)
        os.makedirs(base_dir, exist_ok=True)
        nombre = dte_data.get("identificacion", {}).get("numeroControl") or uuid.uuid4().hex
        json_path = os.path.join(base_dir, f"{nombre}.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(dte_data, fh, ensure_ascii=False)
        jws_path = os.path.join(base_dir, f"{nombre}.jws")
        with open(jws_path, "w", encoding="utf-8") as fh:
            fh.write(jws_token)
    except Exception:
        pass


def _post_dte(url: str, token: str, jws_token: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"dte": jws_token}
    resp = requests.post(url, json=payload, headers=headers, timeout=20)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {"estado": "Error", "detalle": resp.text}


def transmitir_dte(
    db: DB, venta_id: int, modo: str = "normal", tipo_dte: str = "01"
) -> dict:
    """Genera y transmite un DTE reutilizando ``_enviar_documento``.

    ``tipo_dte`` permite especificar el código del documento a transmitir,
    usando ``"01"`` para facturas y ``"03"`` para tickets.
    """

    # For contingency mode, simply register the pending state
    if modo == "contingencia":
        return _enviar_documento(db, venta_id, {}, modo)

    if tipo_dte == "03":
        data = generar_ticket_json(db, venta_id)
    else:
        data = generar_dte_json(db, venta_id)

    data = sanitize_dte_payload(data)
    validate_dte_json(data)
    resp = _enviar_documento(db, venta_id, data, modo)
    if resp.get("sello"):
        db.update_venta_extra(venta_id, {"selloRecibido": resp["sello"]})
    return resp



def enviar_dte_a_hacienda(jws_token: str) -> dict:
    """Transmite un DTE ya firmado (JWS) al entorno de pruebas de Hacienda."""
    url = "https://sandbox.dtes.mh.gob.sv/recepciondte/api/recepciondte"
    token = auth.get_token()
    respuesta = _post_dte(url, token, jws_token)
    estado = (
        respuesta.get("estado")
        or respuesta.get("estadoDte")
        or respuesta.get("descripcionEstado")
    )
    if estado:
        respuesta["estado"] = estado
    return respuesta


def _parse_error_response(respuesta: dict) -> str:
    """Construye un mensaje de error a partir de ``descripcionMsg`` y ``observaciones``."""
    partes = []
    desc = respuesta.get("descripcionMsg")
    if desc:
        partes.append(str(desc))
    obs = respuesta.get("observaciones")
    if isinstance(obs, dict):
        for k, v in obs.items():
            partes.append(f"{k}: {v}")
    elif isinstance(obs, list):
        partes.extend(str(o) for o in obs)
    elif obs:
        partes.append(str(obs))
    mensaje = "; ".join(partes)
    if mensaje:
        logger.error(mensaje)
    return mensaje


def _enviar_documento(db: DB, doc_id: int, data: dict, modo: str = "normal") -> dict:
    """Firma y envía ``data`` a la API de Hacienda registrando el envío."""
    config = _load_dte_api_config()
    if modo == "contingencia":
        db.registrar_envio_dte(doc_id, modo, "Pendiente", "")
        return {"estado": "Pendiente"}

    url = config.get("url") or DEFAULT_RECEPCION_URL
    signed = jws.sign_json(data)
    token = auth.get_token()

    try:
        respuesta = _post_dte(url, token, signed)
        sello = respuesta.get("sello") or respuesta.get("selloRecepcion") or ""
        estado = (
            respuesta.get("estado")
            or respuesta.get("estadoDte")
            or respuesta.get("descripcionEstado")
            or "Transmitido"
        )
        detalle = respuesta.get("detalle")
    except Exception:
        db.registrar_envio_dte(doc_id, modo, "Rechazado", "")
        raise

    db.registrar_envio_dte(
        doc_id,
        modo,
        estado,
        sello,
        json.dumps(respuesta, ensure_ascii=False),
    )
    if estado == "Rechazado":
        respuesta["errores"] = _parse_error_response(respuesta)
    res = {"estado": estado, "sello": sello}
    if detalle:
        res["detalle"] = detalle
    return res


def enviar_factura(db: DB, venta_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una factura electrónica."""
    data = generar_dte_json(db, venta_id)
    data = sanitize_dte_payload(data)
    validate_dte_json(data)
    resp = _enviar_documento(db, venta_id, data, modo)
    if resp.get("sello"):
        db.update_venta_extra(venta_id, {"selloRecibido": resp["sello"]})
    return resp


def enviar_nota_credito(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de crédito."""
    data = generar_nota_credito_json(db, nota_id)
    data = sanitize_dte_payload(data)
    validate_dte_json(data)
    return _enviar_documento(db, nota_id, data, modo)


def enviar_nota_debito(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de débito."""
    data = generar_nota_debito_json(db, nota_id)
    data = sanitize_dte_payload(data)
    validate_dte_json(data)
    return _enviar_documento(db, nota_id, data, modo)


def enviar_nota_remision(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de remisión."""
    data = generar_nota_remision_json(db, nota_id)
    data = sanitize_dte_payload(data)
    validate_dte_json(data)
    return _enviar_documento(db, nota_id, data, modo)


def _enviar_evento(db: DB, evento_id: int, data: dict) -> dict:
    """Firma y envía un evento a Hacienda."""
    config = _load_dte_api_config()
    url = config.get("url") or DEFAULT_RECEPCION_URL
    signed = jws.sign_json(data)
    token = auth.get_token()

    try:
        respuesta = _post_dte(url, token, signed)
        sello = respuesta.get("sello") or respuesta.get("selloRecepcion") or ""
        estado = (
            respuesta.get("estado")
            or respuesta.get("estadoEvento")
            or respuesta.get("descripcionEstado")
            or "Transmitido"
        )
        detalle = respuesta.get("detalle")
    except Exception:
        db.registrar_envio_dte(evento_id, "evento", "Rechazado", "")
        raise

    db.registrar_envio_dte(
        evento_id,
        "evento",
        estado,
        sello,
        json.dumps(respuesta, ensure_ascii=False),
    )
    if estado == "Rechazado":
        respuesta["errores"] = _parse_error_response(respuesta)
    res = {"estado": estado, "sello": sello}
    if detalle:
        res["detalle"] = detalle
    return res


def enviar_evento_contingencia(db: DB, evento_id: int, data: dict) -> dict:
    """Envía un evento de contingencia."""
    return _enviar_evento(db, evento_id, data)


def enviar_evento_anulacion(db: DB, evento_id: int, data: dict) -> dict:
    """Envía un evento de anulación."""
    return _enviar_evento(db, evento_id, data)

