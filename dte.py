import json
import os
import uuid
import base64
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext
from urllib.parse import urlparse
from db import DB
import requests
from utils import jws
import auth
from jsonschema import Draft7Validator, ValidationError, FormatChecker
from utils import catalogos
import logging
import re
from utils.monto import monto_a_texto_sv, d2
from utils.resumen import normalize_condicion_operacion, validate_pagos_basico
from utils.fecha import fecha_emision_hoy_str, TZ_EL_SALVADOR
from svfe.config import get_emisor_direccion
from pathlib import Path
import jsonpatch

logger = logging.getLogger(__name__)

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "datos_negocio.json")
CONFIG_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "config_negocio.json")
DEFAULT_RECEPCION_URL = "https://sandbox.dtes.mh.gob.sv/recepciondte/api/recepciondte"
PATCHES_DIR = Path(__file__).resolve().parent / "schema_patches"

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


def apply_schema_patch(data: dict) -> dict:
    """Apply stored JSON patches for the given DTE ``data``.

    If a patch file matching ``identificacion.tipoDte`` exists in
    ``schema_patches`` it will be applied and the resulting dictionary is
    returned.  When no patch is found ``data`` is returned unchanged.
    """
    tipo = str(data.get("identificacion", {}).get("tipoDte"))
    if not tipo:
        return data
    patch_file = PATCHES_DIR / f"{tipo}.json"
    if not patch_file.exists():
        return data
    try:
        with patch_file.open("r", encoding="utf-8") as fh:
            ops = json.load(fh)
        return jsonpatch.JsonPatch(ops).apply(data, in_place=False)
    except Exception:  # pragma: no cover - best effort
        return data

# Ensure enough precision when other modules modify the global decimal context
getcontext().prec = 28

# Helper aliases for precise Decimal arithmetic
D = Decimal


def d8(value: "object") -> D:
    """Return ``value`` as :class:`Decimal` with 8 decimal places."""
    return D(str(value)).quantize(D("0.00000000"), rounding=ROUND_HALF_UP)


def numero_a_letras(monto):
    """Convierte ``monto`` numérico a su representación en letras."""
    try:
        texto = monto_a_texto_sv(float(monto))
    except Exception:
        return ""
    if " " in texto:
        partes = texto.split(" ", 1)
        return f"{partes[0]} CON {partes[1]}"
    return texto


def _normalize_payload(value):
    """Recursively trim strings and coerce simple types."""
    if isinstance(value, dict):
        for k, v in list(value.items()):
            value[k] = _normalize_payload(v)
        return value
    if isinstance(value, list):
        for i, v in enumerate(value):
            value[i] = _normalize_payload(v)
        return value
    if isinstance(value, str):
        v = value.strip()
        lower = v.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        if v.startswith("-") and v[1:].isdigit():
            try:
                return int(v)
            except Exception:
                return v
        if "." in v:
            try:
                return float(v)
            except Exception:
                return v
        return v
    return value


def _validate_schema(instance: dict, schema: dict) -> None:
    """Validate ``instance`` against ``schema`` reporting all errors.

    Prints a full report of all schema validation issues found and raises
    ``ValidationError`` with the combined message if any problems exist.
    """
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    errs = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: e.path):
        errs.append(
            {
                "path": list(err.path),
                "message": err.message,
                "validator": err.validator,
                "validator_value": err.validator_value,
            }
        )
    if errs:
        lines = ["Errores de esquema encontrados:"]
        for info in errs:
            path = ".".join(str(p) for p in info["path"]) or "<root>"
            lines.append(f"- {path}: {info['message']}")
        report = "\n".join(lines)
        print(report)
        exc = ValidationError(report)
        exc.errors = errs
        raise exc


def _load_datos_negocio():
    if os.path.exists(DATOS_NEGOCIO_PATH):
        try:
            with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            dte_api = data.get("dte_api")
            if isinstance(dte_api, dict):
                url = dte_api.get("url", "")
                if url and "/fesv/recepciondte" not in url:
                    dte_api["url"] = url.rstrip("/") + "/fesv/recepciondte"

            # Ensure cod_giro is available and mirrors codActividad
            cod_giro = data.get("cod_giro")
            if not cod_giro:
                try:
                    with open(CONFIG_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                        cfg = json.load(fh)
                    cod_giro = cfg.get("cod_giro")
                except Exception:
                    cod_giro = None
            if cod_giro:
                data.setdefault("cod_giro", cod_giro)
                data.setdefault("codActividad", cod_giro)
            elif "codActividad" in data:
                data.setdefault("cod_giro", data.get("codActividad"))

            return data
        except Exception:
            return {}
    return {}


DEPARTAMENTO_CODES = {f"{i:02d}" for i in range(15)}


def _map_departamento(nombre: str | None) -> str:
    """Validate and return a departamento code."""

    if nombre is None:
        raise ValueError("Departamento requerido")

    nombre = str(nombre)
    if nombre.isdigit():
        nombre = nombre.zfill(2)
    if nombre not in DEPARTAMENTO_CODES:
        raise ValueError("Departamento inválido")
    return nombre


MUNICIPIO_RANGES = {
    # Departamento: (primer código, último código)
    "05": ("01", "22"),  # La Libertad
    "06": ("01", "19"),  # San Salvador
}


def _map_municipio(nombre: str | None, departamento: str | None = None) -> str:
    """Validate and return a municipio code."""

    if nombre is None:
        raise ValueError("Municipio requerido")

    nombre = str(nombre)
    if not nombre.isdigit() or len(nombre) != 2:
        raise ValueError("Municipio inválido")

    if departamento:
        dep_code = _map_departamento(departamento)
        start, end = MUNICIPIO_RANGES.get(dep_code, ("00", "99"))
        if nombre < start or nombre > end:
            raise ValueError("Municipio inválido para el departamento")
    return nombre


def _clean_nit(nit):
    if nit:
        return "".join(c for c in str(nit) if c.isdigit())
    return None


def _clean_nrc(nrc):
    if nrc:
        return "".join(c for c in str(nrc) if c.isdigit())
    return None


# --- Helpers ---------------------------------------------------------------

# Catálogo de ``condicionOperacion`` según el esquema oficial.
# 1 = Contado, 2 = Crédito, 3 = Otro
CONDICION_OPERACION_CATALOG = {
    1: "Contado",
    2: "Crédito",
    3: "Otro",
}

_CONDICION_OPERACION_BY_NAME = {
    v.lower(): k for k, v in CONDICION_OPERACION_CATALOG.items()
}
_CONDICION_OPERACION_BY_NAME["credito"] = 2


def _parse_condicion_operacion(value):
    """Return ``condicionOperacion`` code ensuring it is valid.

    ``value`` may be ``None``/empty, a numeric code or a textual description.
    Defaults to ``1`` (Contado) when no value is provided.
    Raises ``ValueError`` if the value is not part of the catalog.
    """

    if value in (None, ""):
        code = 1
    elif isinstance(value, (int, float)):
        code = int(value)
    else:
        val = str(value).strip().lower().replace("...", "")
        if val.isdigit():
            code = int(val)
        else:
            code = _CONDICION_OPERACION_BY_NAME.get(val)
    if code not in CONDICION_OPERACION_CATALOG:
        raise ValueError(f"condicionOperacion inválida: {value}")
    return code

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
        monto = d2(p.get("montoPago", 0))
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
                "montoPago": d2(total),
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
    # Los códigos válidos se obtienen tanto del catálogo local como del
    # esquema oficial del tipo de documento.  Esto permite extender el catálogo
    # sin depender de que el esquema se encuentre actualizado.
    allowed = set(catalogos.TRIBUTOS.keys())
    schema = catalogos.get_dte_schema(tipo_dte)
    if schema:
        allowed.update(
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
            raise ValueError(f"Código de tributo inválido: {codigo}")
        result.append(
            {
                "codigo": codigo,
                # Si no se proporciona descripción, intentar obtenerla del catálogo
                "descripcion": t.get("descripcion")
                or catalogos.TRIBUTOS.get(codigo),
                "valor": d2(t.get("valor", 0)),
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
    if tipo_dte in {"01", "03", "05", "06"}:
        condicion = extra.get("condicion_operacion")
        if condicion is None:
            condicion = fiscal.get("condicion_pago")
        resumen["condicionOperacion"] = _parse_condicion_operacion(condicion)
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

    # Ejemplo de referencia:
    # Base ítem: 23.85000000 (8 dec)
    # IVA ítem: 3.10050000 (8 dec)
    # En resumen: base → 23.85, IVA → 3.10, totalPagar → 26.95 (2 dec)
    # Redondeamos valores numéricos
    for k, v in resumen.items():
        if isinstance(v, (int, float, Decimal)):
            resumen[k] = d2(v)

    return resumen


def recalcular_totales(data: dict) -> list[str]:
    """Recalcula y corrige los totales del resumen en ``data``.

    La función vuelve a calcular los valores de la sección ``resumen`` a partir
    de los ítems del ``cuerpoDocumento``.  Si alguno de los totales declarados
    difiere del valor esperado por más de un centavo, el valor se corrige en el
    lugar.  Devuelve una lista con los nombres de los campos ajustados.
    """

    ident = data.get("identificacion", {})
    cuerpo = data.get("cuerpoDocumento", [])
    resumen = data.get("resumen", {})

    items_total = Decimal("0")
    iva_total = Decimal("0")
    iva_from_items = False
    for item in cuerpo:
        cant = Decimal(str(item.get("cantidad") or 0))
        precio = Decimal(
            str(item.get("precioUnitario") or item.get("precioUni") or 0)
        )
        items_total += cant * precio
        iva_val = item.get("montoIva") or item.get("iva") or item.get("ivaItem")
        if iva_val:
            iva_total += Decimal(str(iva_val))
            iva_from_items = True
    if not iva_from_items:
        iva_total = Decimal(
            str(resumen.get("totalIva") or resumen.get("ivaPerci1") or 0)
        )

    # Omitimos ``total`` para que ``calcular_resumen`` utilice el monto
    # calculado internamente y así podamos comparar contra el declarado.
    venta = {"total_letras": resumen.get("totalLetras", "")}
    fiscal = {
        "descuentos": resumen.get("totalDescu", 0),
        "iva": iva_total,
        "ventas_no_sujetas": resumen.get("totalNoSuj", 0),
        "ventas_exentas": resumen.get("totalExenta", 0),
    }
    extra = {
        "pagos": resumen.get("pagos"),
        "tributos": resumen.get("tributos"),
        "numPagoElectronico": resumen.get("numPagoElectronico"),
        "condicion_operacion": resumen.get("condicionOperacion"),
    }

    esperado = calcular_resumen(
        items_total,
        venta,
        fiscal=fiscal,
        extra=extra,
        tipo_dte=ident.get("tipoDte", "01"),
    )

    modificados: list[str] = []
    for k, v in esperado.items():
        if not isinstance(v, (int, float, Decimal)):
            continue
        ref = Decimal(str(resumen.get(k, 0)))
        nuevo = Decimal(str(v))
        if abs(ref - nuevo) > Decimal("0.01"):
            resumen[k] = float(nuevo) if isinstance(v, Decimal) else v
            modificados.append(k)

    data["resumen"] = resumen
    return modificados


def generar_numero_control(prefijo: str = "DTE-01-S001P001") -> str:
    """Crea un número de control único siguiendo el formato de Hacienda."""
    secuencia = str(uuid.uuid4().int % 10**15).zfill(15)
    return f"{prefijo}-{secuencia}"


def generar_cabecera_dte_data(
    tipo_modelo: int,
    tipo_operacion: int,
    tipo_contingencia: int | None = None,
    motivo_contin: str | None = None,
    ambiente: str = "00",
) -> dict:
    """Genera los datos para la cabecera de un DTE.

    Los campos de código de generación y número de control se crean antes de
    enviar la factura. Los valores que envía Hacienda posteriormente (código de
    generación y sello recibido) se dejan en ``None``.
    """
    if tipo_operacion == 1:
        tipo_modelo = 1
        tipo_contingencia = None
        motivo_contin = None
    else:
        tipo_modelo = 2

    codigo_generacion = str(uuid.uuid4()).upper()
    numero_control = generar_numero_control()
    fecha_generacion = datetime.now().strftime("%d/%m/%Y, %I:%M %p")
    return {
        "codigo_generacion": codigo_generacion,
        "numero_control": numero_control,
        "sello_recepcion": None,
        "tipo_modelo": tipo_modelo,
        "tipo_operacion": tipo_operacion,
        "tipo_contingencia": tipo_contingencia,
        "motivo_contin": motivo_contin,
        "fecha_generacion": fecha_generacion,
        "ambiente": ambiente,
    }

def generar_dte_json(
    db: DB,
    venta_id: int,
    tipo_dte: str = "01",
    *,
    ambiente: str = "00",
    tipo_operacion: int = 1,
    tipo_contingencia: int | None = None,
    motivo_contin: str | None = None,
    tipo_modelo: int | None = None,
    tipo_moneda: str = "USD",
    **kwargs,
) -> dict:
    """Genera un diccionario DTE básico para una venta.

    ``kwargs`` se acepta para compatibilidad con parámetros obsoletos.
    """
    row = db.cursor.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone()
    if not row:
        raise ValueError("Venta no encontrada")
    venta = dict(row)

    if not venta.get("total_letras"):
        total = venta.get("total")
        if total is not None:
            venta["total_letras"] = numero_a_letras(total)
    if not venta.get("total_letras"):
        raise ValueError("El total en letras es obligatorio")

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

    now = datetime.now(TZ_EL_SALVADOR)
    fecha = fecha_emision_hoy_str(now)
    hora = now.strftime("%H:%M:%S")

    if tipo_operacion == 1:
        tipo_modelo = 1
        tipo_contingencia = None
        motivo_contin = None
    else:
        tipo_modelo = 2
        if tipo_contingencia is None:
            raise ValueError("tipoContingencia requerido cuando tipoOperacion=2")
        if tipo_contingencia != 5:
            motivo_contin = None

    identificacion = {
        "version": 1,
        "ambiente": ambiente,
        "tipoDte": tipo_dte,
        "numeroControl": numero_control,
        "codigoGeneracion": codigo_generacion,
        "tipoModelo": tipo_modelo,
        "tipoOperacion": tipo_operacion,
        "tipoContingencia": tipo_contingencia,
        "motivoContin": motivo_contin,
        "fecEmi": fecha,
        "horEmi": hora,
        "tipoMoneda": tipo_moneda,
    }

    emisor = {
        "nombre": datos.get("nombre"),
        "nombreComercial": datos.get("nombreComercial"),
        "nit": datos.get("nit"),
        "nrc": datos.get("nrc"),
        "codActividad": datos.get("cod_giro") or datos.get("codActividad"),
        "descActividad": datos.get("descActividad"),
        "tipoContribuyente": datos.get("tipoContribuyente"),
        "telefono": datos.get("telefono"),
        "correo": datos.get("correo"),
    }
    emisor["direccion"] = get_emisor_direccion()

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
    items_total = D("0")
    commission_total = D("0")
    iva_total = D("0")
    for idx, d in enumerate(detalles, 1):
        try:
            cant = D(str(d.get("cantidad") or 0))
        except Exception:
            cant = D(0)
        try:
            precio = D(str(d.get("precio_unitario") or 0))
        except Exception:
            precio = D(0)

        # Ejemplo para auto-chequeo (no ejecutar):
        # cantidad = 2.5 -> D('2.5')
        # precio = 9.54 -> D('9.54')
        # venta = 2.5 * 9.54 = 23.85 -> d8 = '23.85000000'
        # IVA (13%) = 23.85 * 0.13 = 3.1005 -> d8 = '3.10050000'

        cant_q = d8(cant)
        precio_q = d8(precio)
        venta_item = cant_q * precio_q
        iva_item = D(str(d.get("iva") or 0))
        monto_iva = d8(venta_item * iva_item) if iva_item and iva_item < 1 else d8(iva_item)
        items_total += venta_item
        iva_total += monto_iva
        try:
            commission_total += D(str(d.get("comision") or 0))
        except Exception:
            pass
        item_data = {
            "numItem": idx,
            "descripcion": d.get("descripcion"),
            "cantidad": float(cant_q),
            "precioUnitario": float(precio_q),
            "ventaGravada": float(d8(venta_item)),
        }
        cuerpo.append(item_data)

    resumen = calcular_resumen(
        items_total,
        venta,
        fiscal={**(fiscal or {}), "iva": iva_total},
        extra=extra,
        tipo_dte=tipo_dte,
    )

    # Validaciones básicas de consistencia
    items_total_2 = d2(items_total)
    if abs(items_total_2 - resumen.get("subTotalVentas", 0)) > 0.01:
        print(
            f"Advertencia: la suma de los ítems {items_total_2:.2f} difiere del resumen {resumen.get('subTotalVentas',0):.2f}"
        )

    calc_sub_total = d2(
        resumen.get("subTotalVentas", 0) - resumen.get("totalDescu", 0)
    )
    if abs(calc_sub_total - resumen.get("subTotal", 0)) > 0.01:
        print(
            f"Advertencia: el subtotal calculado {calc_sub_total:.2f} difiere del resumen {resumen.get('subTotal',0):.2f}"
        )

    iva_ref = resumen.get("totalIva")
    if iva_ref is None:
        iva_ref = resumen.get("ivaPerci1", 0)
    calc_total = d2(calc_sub_total + (iva_ref or 0))
    if abs(calc_total - resumen.get("montoTotalOperacion", 0)) > 0.01:
        print(
            f"Advertencia: el monto total {resumen.get('montoTotalOperacion',0):.2f} difiere del calculado {calc_total:.2f}"
        )
    calc_total_commission = d2(calc_total + float(commission_total))
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


def validate_dte_json(payload: dict) -> None:
    """Basic validation and normalization for DTE payload before signing."""
    _normalize_payload(payload)
    required = ["identificacion", "emisor", "receptor", "cuerpoDocumento", "resumen"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(
            "Faltan campos obligatorios: " + ", ".join(missing)
        )

    negocio = _load_datos_negocio()

    ident = payload.get("identificacion", {})
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
        uuid_obj = uuid.UUID(str(cg))
    except Exception:
        raise ValueError("codigoGeneracion debe ser un UUID v4 válido") from None
    if uuid_obj.version != 4:
        raise ValueError("codigoGeneracion debe ser un UUID v4 válido")
    ident["codigoGeneracion"] = str(uuid_obj).upper()
    payload["identificacion"] = ident

    emisor = payload.get("emisor", {})
    emisor["nit"] = _clean_nit(emisor.get("nit") or negocio.get("nit"))
    emisor["nrc"] = _clean_nrc(emisor.get("nrc") or negocio.get("nrc"))
    emisor.setdefault("nombre", negocio.get("nombre"))
    emisor.setdefault("nombreComercial", negocio.get("nombreComercial"))
    emisor.setdefault("codActividad", negocio.get("cod_giro") or negocio.get("codActividad"))
    emisor.setdefault("descActividad", negocio.get("descActividad"))
    emisor.setdefault("tipoEstablecimiento", "01")
    direccion = emisor.get("direccion")
    if not isinstance(direccion, dict):
        direccion = get_emisor_direccion()
    direccion["departamento"] = _map_departamento(direccion.get("departamento"))
    direccion["municipio"] = _map_municipio(
        direccion.get("municipio"), direccion.get("departamento")
    )
    if not direccion.get("complemento"):
        raise ValueError("Faltan campos obligatorios en emisor: direccion.complemento")
    emisor["direccion"] = direccion
    emisor.setdefault("telefono", negocio.get("telefono"))
    emisor.setdefault("correo", negocio.get("correo"))
    emisor.setdefault("codEstableMH", "0000")
    emisor.setdefault("codEstable", "0000")
    emisor.setdefault("codPuntoVentaMH", "0000")
    emisor.setdefault("codPuntoVenta", "0000")
    emisor.pop("giro", None)
    emisor.pop("tipoContribuyente", None)
    required_emisor = {
        "nit": emisor.get("nit"),
        "nrc": emisor.get("nrc"),
        "nombre": emisor.get("nombre"),
        "nombreComercial": emisor.get("nombreComercial"),
        "codActividad": emisor.get("codActividad"),
        "descActividad": emisor.get("descActividad"),
        "direccion.departamento": emisor.get("direccion", {}).get("departamento"),
        "direccion.municipio": emisor.get("direccion", {}).get("municipio"),
        "direccion.complemento": emisor.get("direccion", {}).get("complemento"),
        "telefono": emisor.get("telefono"),
        "correo": emisor.get("correo"),
    }
    missing = [
        key
        for key, value in required_emisor.items()
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if missing:
        raise ValueError(
            "Faltan campos obligatorios en emisor: " + ", ".join(missing)
        )
    payload["emisor"] = emisor

    receptor = payload.get("receptor", {})
    receptor["nrc"] = _clean_nrc(receptor.get("nrc"))
    if "nit" in receptor:
        receptor["numDocumento"] = _clean_nit(receptor.pop("nit"))
    else:
        receptor["numDocumento"] = _clean_nit(receptor.get("numDocumento"))
    receptor.pop("giro", None)
    dir_rec = receptor.get("direccion")
    if dir_rec is not None:
        if not isinstance(dir_rec, dict):
            raise ValueError("direccion de receptor inválida")
        dir_rec["departamento"] = _map_departamento(dir_rec.get("departamento"))
        dir_rec["municipio"] = _map_municipio(
            dir_rec.get("municipio"), dir_rec.get("departamento")
        )
        if not dir_rec.get("complemento"):
            raise ValueError(
                "Faltan campos obligatorios en receptor: direccion.complemento"
            )
        receptor["direccion"] = dir_rec
    payload["receptor"] = receptor

    cuerpo = payload.get("cuerpoDocumento", [])
    tipo_dte = str(payload.get("identificacion", {}).get("tipoDte", ""))
    schema = catalogos.get_dte_schema(tipo_dte)
    if schema:
        item_props = (
            schema.get("properties", {})
            .get("cuerpoDocumento", {})
            .get("items", {})
            .get("properties", {})
        )
        allowed_item_keys = set(item_props.keys())
    else:
        allowed_item_keys = {
            "numItem",
            "tipoItem",
            "numeroDocumento",
            "cantidad",
            "codigo",
            "codTributo",
            "uniMedida",
            "descripcion",
            "precioUni",
            "montoDescu",
            "ventaNoSuj",
            "ventaExenta",
            "ventaGravada",
            "tributos",
            "psv",
            "noGravado",
            "ivaItem",
        }
    precio_key = "precioUni" if "precioUni" in allowed_item_keys else "precioUnitario"
    iva_key = "ivaItem" if "ivaItem" in allowed_item_keys else None

    for item in cuerpo:
        # --- Normalización de nombres ---
        if "precioUnitario" in item and precio_key != "precioUnitario":
            item[precio_key] = item.pop("precioUnitario")
        if "precioUni" in item and precio_key != "precioUni":
            item[precio_key] = item.pop("precioUni")

        iva_val = None
        for k in ("montoIva", "iva", "ivaItem"):
            if k in item:
                iva_val = item.pop(k)
                break
        if iva_key and iva_val is not None:
            item[iva_key] = iva_val

        # --- Filtrar claves no permitidas ---
        for key in list(item.keys()):
            if key not in allowed_item_keys:
                item.pop(key)

        # --- Valores por defecto ---
        if tipo_dte == "01":
            # En la factura de consumidor final los ítems deben declararse con
            # ``tipoItem`` 4 y unidad de medida 99 (no aplica).  Los tributos se
            # reportan únicamente por medio de ``codTributo`` y el arreglo
            # ``tributos`` debe ser ``null``.
            item["tipoItem"] = 4
            item["uniMedida"] = 99
        else:
            item.setdefault("tipoItem", 1)
            item.setdefault("uniMedida", 59)

        item.setdefault("numeroDocumento", None)
        item.setdefault("codigo", None)
        item.setdefault("codTributo", None)
        item.setdefault("montoDescu", 0.0)
        item.setdefault("ventaNoSuj", 0.0)
        item.setdefault("ventaExenta", 0.0)
        item.setdefault("tributos", None)
        item.setdefault("psv", 0.0)
        item.setdefault("noGravado", 0.0)
        if iva_key:
            item.setdefault(iva_key, 0.0)

        cantidad = D(str(item.get("cantidad", 0)))
        precio = D(str(item.get(precio_key, 0)))
        cantidad_q = d8(cantidad)
        precio_q = d8(precio)
        item["cantidad"] = float(cantidad_q)
        item[precio_key] = float(precio_q)
        importe = cantidad_q * precio_q
        item.setdefault("ventaGravada", float(d8(importe)))

        # --- Manejo y validación de tributos ---
        venta_gravada = D(str(item.get("ventaGravada") or 0))
        if tipo_dte == "01":
            # Para consumidor final no se reporta el arreglo ``tributos``.  Si
            # el ítem es gravado se utiliza por defecto el código "A8".
            allowed = set(catalogos.TRIBUTOS.keys())
            if venta_gravada > 0:
                cod = item.get("codTributo") or "A8"
                item["codTributo"] = str(cod).upper()
                if item["codTributo"] not in allowed:
                    raise ValueError(
                        f"codTributo inválido: {item['codTributo']}"
                    )
            else:
                item["codTributo"] = None
            item["tributos"] = None
        else:
            tributos = item.get("tributos")
            if venta_gravada > 0:
                # Si la venta es gravada y no se especifican tributos, se
                # asigna un código por defecto (IVA "A8").
                if not tributos:
                    tributos = ["A8"]
                elif isinstance(tributos, str):
                    tributos = [tributos]
                item["tributos"] = [str(t).upper() for t in tributos]

                # ``codTributo`` toma el primer código de la lista si no fue
                # proporcionado explícitamente.
                cod = item.get("codTributo") or item["tributos"][0]
                item["codTributo"] = str(cod).upper()

                allowed = set(catalogos.TRIBUTOS.keys())
                if item["codTributo"] not in allowed:
                    raise ValueError(
                        f"codTributo inválido: {item['codTributo']}"
                    )
                invalid = [t for t in item["tributos"] if t not in allowed]
                if invalid:
                    raise ValueError(
                        f"Código(s) de tributo inválido(s): {', '.join(invalid)}"
                    )
            else:
                # Si no hay venta gravada, no deben declararse tributos
                item["tributos"] = None
                item["codTributo"] = None
    payload["cuerpoDocumento"] = cuerpo

    resumen = payload.get("resumen", {})
    for k, v in resumen.items():
        if isinstance(v, (int, float)):
            resumen[k] = d2(v)
        elif isinstance(v, str):
            try:
                resumen[k] = d2(float(v))
            except Exception:
                pass
    payload["resumen"] = resumen

    # Recalcular totales y ajustar discrepancias
    cambios = recalcular_totales(payload)
    if cambios:
        print(
            "Advertencia: se corrigieron campos de resumen: " + ", ".join(cambios)
        )

    # --- Catálogo validations ---
    ident = payload.get("identificacion", {})
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
    emisor_nit = payload.get("emisor", {}).get("nit")
    if emisor_nit and len(emisor_nit.replace("-", "")) != catalogos.NIT_LENGTH:
        raise ValueError("NIT inválido en emisor")

    receptor_doc = payload.get("receptor", {}).get("numDocumento")
    if receptor_doc and len(receptor_doc) not in (9, catalogos.NIT_LENGTH):
        raise ValueError("Número de documento inválido en receptor")

    # --- Schema validation ---
    schema = catalogos.get_dte_schema(tipo_dte)
    if schema:
        _validate_schema(payload, schema)


def generar_ticket_json(
    db: DB,
    venta_id: int,
    *,
    ambiente: str = "00",
    tipo_operacion: int = 1,
    tipo_contingencia: int | None = None,
    motivo_contin: str | None = None,
    **kwargs,
) -> dict:
    """Genera la estructura JSON para un Ticket Electrónico."""
    return generar_dte_json(
        db,
        venta_id,
        tipo_dte="03",
        ambiente=ambiente,
        tipo_operacion=tipo_operacion,
        tipo_contingencia=tipo_contingencia,
        motivo_contin=motivo_contin,
        **kwargs,
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
        url = env_conf.get("recepcion_url") or data.get("recepcion_url")
        if url:
            url = url.strip()
        return {"ambiente": ambiente, "url": url or DEFAULT_RECEPCION_URL}
    except Exception:
        return {"ambiente": "pruebas", "url": DEFAULT_RECEPCION_URL}


def _save_signed_dte(dte_data: dict, jws_token: str) -> None:
    """Guarda el JSON original y el JWS en ``/dtes/{anio}/``."""
    try:
        fecha = dte_data.get("identificacion", {}).get("fecEmi") or fecha_emision_hoy_str()
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


class DTEValidationError(Exception):
    """Error de validación que incluye lista de errores y ruta del JSON."""

    def __init__(self, errors, json_path):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.json_path = json_path


def save_dte_json(dte_data: dict) -> str:
    """Guarda ``dte_data`` en ``/dtes/{anio}/`` y devuelve la ruta."""
    try:
        fecha = dte_data.get("identificacion", {}).get("fecEmi") or fecha_emision_hoy_str()
        year = str(fecha)[:4]
        base_dir = os.path.join(os.path.dirname(__file__), "dtes", year)
        os.makedirs(base_dir, exist_ok=True)
        nombre = dte_data.get("identificacion", {}).get("numeroControl") or uuid.uuid4().hex
        json_path = os.path.join(base_dir, f"{nombre}.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(dte_data, fh, ensure_ascii=False)
        return json_path
    except Exception:
        return ""


def _format_validation_errors(exc: Exception) -> list:
    """Convierte la excepción de validación en una lista de mensajes."""
    if isinstance(exc, ValidationError) and getattr(exc, "errors", None):
        formatted = []
        for err in exc.errors:
            path = ".".join(str(p) for p in err.path)
            if path:
                formatted.append(f"{path}: {err.message}")
            else:
                formatted.append(err.message)
        return formatted
    msg = str(exc)
    if ":" in msg:
        head, tail = msg.split(":", 1)
        return [f"{head.strip()}: {part.strip()}" for part in tail.split(",")]
    return [msg]


def _decode_jws_payload(token: str) -> dict:
    """Return the JSON payload embedded in ``token``.

    Raises ``ValueError`` if the token is not a valid JWS string.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("JWS malformado")
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload + padding)
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("documento inválido") from exc


def _post_dte(url: str, token: str, jws_token: str, dte_data: dict | None = None) -> dict:
    token = (token or "").strip().strip('"').replace("\r", "").replace("\n", "")
    token = re.sub(r"^(?:Bearer\s+)+", "", token, flags=re.I)
    if token:
        logger.debug("Token: %s...%s", token[:5], token[-5:])
    else:
        logger.debug("Token: <empty>")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    ident = {}
    if isinstance(dte_data, dict):
        ident = dte_data.get("identificacion") or dte_data.get("identificador") or dte_data

    # Always extract identification fields from the signed JWS payload
    payload = _decode_jws_payload(jws_token)
    pident = payload.get("identificacion") or payload.get("identificador") or {}
    ambiente = pident.get("ambiente")
    tipo_dte = pident.get("tipoDte") or pident.get("tipoDocumento")
    version = pident.get("version")
    codigo = pident.get("codigoGeneracion")

    # If explicit metadata was provided, ensure it matches the JWS payload
    if ident:
        i_amb = ident.get("ambiente")
        i_tipo = ident.get("tipoDte") or ident.get("tipoDocumento")
        i_ver = ident.get("version")
        i_cod = ident.get("codigoGeneracion")
        if i_cod and i_cod != codigo:
            raise ValueError("documento no coincide con codigoGeneracion")
        if i_tipo and i_tipo != tipo_dte:
            raise ValueError("documento no coincide con tipoDte")
        if i_amb and i_amb != ambiente:
            raise ValueError("documento no coincide con ambiente")
        if i_ver and i_ver != version:
            raise ValueError("documento no coincide con version")

    missing = [
        name
        for name, value in (
            ("ambiente", ambiente),
            ("tipoDte", tipo_dte),
            ("version", version),
            ("codigoGeneracion", codigo),
        )
        if value is None
    ]
    if missing:
        raise AssertionError(
            "Faltan campos requeridos: " + ", ".join(missing)
        )

    ambiente = "00"
    version = 2
    id_envio = int(uuid.uuid4()) & 0x7FFFFFFF or 1
    documento = str(jws_token)
    assert documento.count(".") == 2, "documento JWS malformado"
    codigo = str(codigo)

    tipo_dte = str(tipo_dte)
    assert re.fullmatch(r"\d{2}", tipo_dte), "tipoDte debe ser dos dígitos"
    assert tipo_dte in catalogos.TIPOS_DTE, "tipoDte inválido"

    payload = {
        "ambiente": ambiente,
        "version": version,
        "idEnvio": int(id_envio),
        "tipoDte": tipo_dte,
        "documento": documento,
    }
    if codigo:
        payload["codigoGeneracion"] = codigo
    assert payload.get("codigoGeneracion") == codigo, "codigoGeneracion no coincide"

    print({k: type(v).__name__ for k, v in payload.items()})

    required = {
        "ambiente": str,
        "tipoDte": str,
        "version": int,
        "idEnvio": int,
        "documento": str,
    }
    if "codigoGeneracion" in payload:
        required["codigoGeneracion"] = str

    for field, expected in required.items():
        assert field in payload, f"{field} requerido"
        assert isinstance(payload[field], expected), f"{field} debe ser {expected.__name__}"

    assert payload["idEnvio"] > 0
    auth_header = headers.get("Authorization")
    if token:
        assert re.fullmatch(r"Bearer [^\s]+", auth_header), "Authorization header malformado"
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    resp_text = getattr(resp, "text", "")
    status_code = getattr(resp, "status_code", "N/A")
    if isinstance(status_code, int) and status_code >= 400:
        try:
            logger.error("Hacienda %s: %s", status_code, resp_text)
        finally:
            resp.raise_for_status()
    else:
        logger.debug("Hacienda %s: %s", status_code, resp_text)

    try:
        return resp.json()
    except Exception:
        return {"estado": "Error", "detalle": resp_text}


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
    data = apply_schema_patch(data)
    try:
        validate_dte_json(data)
    except Exception as exc:
        json_path = save_dte_json(data)
        errors = _format_validation_errors(exc)
        raise DTEValidationError(errors, json_path) from exc
    resp = _enviar_documento(db, venta_id, data, modo)
    if resp.get("sello"):
        db.update_venta_extra(venta_id, {"selloRecibido": resp["sello"]})
    return resp



def enviar_dte_a_hacienda(jws_token: str) -> dict:
    """Transmite un DTE ya firmado (JWS) al entorno de pruebas de Hacienda."""
    url = "https://sandbox.dtes.mh.gob.sv/recepciondte/api/recepciondte"
    payload = _decode_jws_payload(jws_token)
    ident = payload.get("identificacion") or payload.get("identificador") or {}
    meta = {
        "ambiente": ident.get("ambiente"),
        "version": ident.get("version"),
        "tipoDte": ident.get("tipoDte") or ident.get("tipoDocumento"),
        "codigoGeneracion": ident.get("codigoGeneracion"),
    }
    token = auth.get_token()
    respuesta = _post_dte(url, token, jws_token, meta)
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

    if not data.get("resumen", {}).get("totalLetras"):
        raise ValueError("El total en letras es obligatorio")

    url = config.get("url") or DEFAULT_RECEPCION_URL
    ident = data.get("identificacion") or data.get("identificador") or {}
    meta = {
        "ambiente": ident.get("ambiente"),
        "version": ident.get("version"),
        "tipoDte": ident.get("tipoDte") or ident.get("tipoDocumento"),
        "codigoGeneracion": ident.get("codigoGeneracion"),
    }
    ident["fecEmi"] = fecha_emision_hoy_str()
    ident["horEmi"] = datetime.now(TZ_EL_SALVADOR).strftime("%H:%M:%S")
    if "identificacion" in data:
        data["identificacion"] = ident
    elif "identificador" in data:
        data["identificador"] = ident
    token = auth.get_token()
    auth_host = auth.get_last_auth_host()
    recep_host = urlparse(url).netloc
    if auth_host and recep_host != auth_host:
        raise ValueError(
            f"Host de recepción {recep_host} difiere de autenticación {auth_host}"
        )
    try:
        resumen = data.get("resumen", {})
        condicion = normalize_condicion_operacion(
            resumen.get("condicionOperacion")
        )
        resumen["condicionOperacion"] = condicion
        validate_pagos_basico(resumen, condicion)
        data["resumen"] = resumen
    except ValueError as exc:
        logger.error("ERROR: DTE inválido: %s", exc)
        raise ValueError(f"DTE inválido: {exc}") from exc

    signed = jws.sign_json(data)

    # Verify that metadata matches the signed payload and update it
    payload = _decode_jws_payload(signed)
    pident = payload.get("identificacion") or payload.get("identificador") or {}
    p_amb = pident.get("ambiente")
    p_tipo = pident.get("tipoDte") or pident.get("tipoDocumento")
    p_cod = pident.get("codigoGeneracion")
    if meta.get("ambiente") and meta["ambiente"] != p_amb:
        raise ValueError("ambiente no coincide con datos a firmar")
    if meta.get("tipoDte") and meta["tipoDte"] != p_tipo:
        raise ValueError("tipoDte no coincide con datos a firmar")
    if meta.get("codigoGeneracion") and meta["codigoGeneracion"] != p_cod:
        raise ValueError("codigoGeneracion no coincide con datos a firmar")
    meta["ambiente"] = p_amb
    meta["tipoDte"] = p_tipo
    meta["codigoGeneracion"] = p_cod

    try:
        respuesta = _post_dte(url, token, signed, meta)
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
    data = apply_schema_patch(data)
    try:
        validate_dte_json(data)
    except Exception as exc:
        json_path = save_dte_json(data)
        errors = _format_validation_errors(exc)
        raise DTEValidationError(errors, json_path) from exc
    resp = _enviar_documento(db, venta_id, data, modo)
    if resp.get("sello"):
        db.update_venta_extra(venta_id, {"selloRecibido": resp["sello"]})
    return resp


def enviar_nota_credito(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de crédito."""
    data = generar_nota_credito_json(db, nota_id)
    data = sanitize_dte_payload(data)
    data = apply_schema_patch(data)
    try:
        validate_dte_json(data)
    except Exception as exc:
        json_path = save_dte_json(data)
        errors = _format_validation_errors(exc)
        raise DTEValidationError(errors, json_path) from exc
    return _enviar_documento(db, nota_id, data, modo)


def enviar_nota_debito(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de débito."""
    data = generar_nota_debito_json(db, nota_id)
    data = sanitize_dte_payload(data)
    data = apply_schema_patch(data)
    try:
        validate_dte_json(data)
    except Exception as exc:
        json_path = save_dte_json(data)
        errors = _format_validation_errors(exc)
        raise DTEValidationError(errors, json_path) from exc
    return _enviar_documento(db, nota_id, data, modo)


def enviar_nota_remision(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de remisión."""
    data = generar_nota_remision_json(db, nota_id)
    data = sanitize_dte_payload(data)
    data = apply_schema_patch(data)
    try:
        validate_dte_json(data)
    except Exception as exc:
        json_path = save_dte_json(data)
        errors = _format_validation_errors(exc)
        raise DTEValidationError(errors, json_path) from exc
    return _enviar_documento(db, nota_id, data, modo)


def _enviar_evento(db: DB, evento_id: int, data: dict) -> dict:
    """Firma y envía un evento a Hacienda."""
    config = _load_dte_api_config()
    url = config.get("url") or DEFAULT_RECEPCION_URL
    signed = jws.sign_json(data)
    token = auth.get_token()

    try:
        respuesta = _post_dte(url, token, signed, data)
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

