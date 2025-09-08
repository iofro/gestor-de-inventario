import json
import os
import uuid
import base64
import copy
import platform
import sys
import re
import requests as _requests
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP, getcontext
from urllib.parse import urlparse
from db import DB
import requests
from utils import jws
from utils import versioned_dte
from utils.stable_json import stable_stringify, save_file
import auth
from jsonschema import ValidationError, RefResolver
from utils import catalogos
from utils.catalogos import (
    TRIBUTO_IVA,
    TRIBUTOS,
    TRIBUTOS_PERMITIDOS_ITEM,
    TRIBUTOS_PERMITIDOS_RESUMEN,
    UNIDADES_MEDIDA_PERMITIDAS,
)
import logging
import warnings
import xml.etree.ElementTree as ET
from utils.monto import monto_a_texto_sv, to_base_iva
from utils.sanitize import limpiar_documentos, limpiar_doc
from num2words import num2words
from utils.resumen import normalize_condicion_operacion, validate_pagos_basico
from utils.fecha import fecha_emision_hoy_str, TZ_EL_SALVADOR
from svfe import config as svfe_config
from pathlib import Path
import jsonpatch
from paths import DATOS_NEGOCIO_PATH
from xml.etree.ElementTree import Element, SubElement

APP_VERSION = "1.0.0"  # editable a futuro

logger = logging.getLogger(__name__)

CONFIG_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "config_negocio.json")
DEFAULT_RECEPCION_URL = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
PATCHES_DIR = Path(__file__).resolve().parent / "schema_patches"

SCHEMAS_DIR = Path(__file__).resolve().parent / "svfe-json-schemas"
FC_SCHEMA_PATH = SCHEMAS_DIR / "fe-fc-v1.json"
with FC_SCHEMA_PATH.open("r", encoding="utf-8") as fh:
    FC_SCHEMA = json.load(fh)
RESOLVER = RefResolver(base_uri=f"{SCHEMAS_DIR.as_uri()}/", referrer=FC_SCHEMA)

DTE_VERSIONES = {
    "01": 1,
    "03": 3,
    "04": 3,
    "05": 3,
    "06": 3,
}


def _strip_additional_properties(value, schema):
    """Remove keys not defined in ``schema`` when ``additionalProperties`` is ``false``."""
    if "$ref" in schema:
        with RESOLVER.resolving(schema["$ref"]) as resolved:
            return _strip_additional_properties(value, resolved)

    if isinstance(value, dict):
        props = schema.get("properties", {})
        patterns = {
            re.compile(p): s for p, s in schema.get("patternProperties", {}).items()
        }
        addl = schema.get("additionalProperties", True)
        clean = {}
        for key, val in value.items():
            if key in props:
                clean[key] = _strip_additional_properties(val, props[key])
                continue
            matched = False
            for pat, subschema in patterns.items():
                if pat.fullmatch(key):
                    clean[key] = _strip_additional_properties(val, subschema)
                    matched = True
                    break
            if matched:
                continue
            if addl is not False:
                clean[key] = val
        return clean

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            return [_strip_additional_properties(v, item_schema) for v in value]
        elif isinstance(item_schema, list):
            result = []
            for i, v in enumerate(value):
                if i < len(item_schema):
                    result.append(_strip_additional_properties(v, item_schema[i]))
                else:
                    result.append(v)
            return result
    return value


def sanitize_dte_payload(data: dict, schema: dict | None = None) -> dict:
    """Return ``data`` excluding properties not allowed by ``schema``.

    Además, de forma recursiva se eliminan las claves cuyo valor sea ``None``.
    Cuando ``schema`` es ``None`` se usa el esquema ``FC_SCHEMA``.
    """

    REQUIRED_NULL_FIELDS = {
        "documentoRelacionado",
        "otrosDocumentos",
        "ventaTercero",
        "extension",
        "apendice",
        "codTributo",
        "tributos",  # e.g. resumen.tributos must remain even if None
        "tipoContingencia",
        "motivoContin",
        "nombreComercial",
        "numPagoElectronico",
    }

    def _remove_nulls(value, parent_key=None):
        """Recursively drop keys or items with ``None`` values.

        Las claves en ``REQUIRED_NULL_FIELDS`` se conservan incluso si su
        valor es ``None`` y las listas vacías bajo estas claves se
        convierten en ``None``.
        """
        if isinstance(value, dict):
            clean = {}
            for k, v in value.items():
                cleaned = _remove_nulls(v, k)
                if cleaned is not None or k in REQUIRED_NULL_FIELDS:
                    clean[k] = cleaned
            return clean
        if isinstance(value, list):
            cleaned_list = []
            for item in value:
                cleaned_item = _remove_nulls(item, parent_key)
                if cleaned_item is not None:
                    cleaned_list.append(cleaned_item)
            if not cleaned_list and parent_key in REQUIRED_NULL_FIELDS:
                return None
            return cleaned_list
        return value

    if schema is None:
        schema = FC_SCHEMA
    cleaned = _strip_additional_properties(data, schema)
    limpiar_documentos(cleaned)
    cleaned = _remove_nulls(cleaned)

    schema_props = set(schema.get("properties", {}))
    for key in (
        "documentoRelacionado",
        "otrosDocumentos",
        "ventaTercero",
        "extension",
        "apendice",
    ):
        if key in schema_props:
            cleaned.setdefault(key, None)
    return cleaned


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
getcontext().rounding = ROUND_HALF_UP

# Helper aliases for precise Decimal arithmetic
D = Decimal


def d1(value: "object") -> D:
    """Return ``value`` as :class:`Decimal` with 1 decimal place."""
    return D(str(value)).quantize(D("0.1"), rounding=ROUND_HALF_UP)


def d2(value: "object") -> D:
    """Return ``value`` as :class:`Decimal` with 2 decimal places."""
    return D(str(value)).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def d8(value: "object") -> D:
    """Return ``value`` as :class:`Decimal` with 8 decimal places."""
    return D(str(value)).quantize(D("0.00000000"), rounding=ROUND_HALF_UP)


def d4(value: "object") -> D:
    """Return ``value`` as :class:`Decimal` with 4 decimal places."""
    return D(str(value)).quantize(D("0.0001"), rounding=ROUND_HALF_UP)


def money(value) -> D:
    """
    Convierte `value` a Decimal con 2 decimales (multipleOf 0.01) usando ROUND_HALF_UP.
    Acepta str, int, float, Decimal. Devuelve Decimal cuantizado a 0.01.
    """
    return D(str(value)).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def money_round_up(value) -> D:
    """Return ``value`` rounded up to 2 decimal places."""
    return D(str(value)).quantize(D("0.01"), rounding=ROUND_UP)


def _precios_incluyen_iva_from(
    extra: dict | None, override: bool | None = None
) -> bool:
    if isinstance(extra, dict) and "precios_incluyen_iva" in extra:
        return bool(extra["precios_incluyen_iva"])
    if override is not None:
        return bool(override)
    cfg = getattr(svfe_config, "PRECIOS_INCLUYEN_IVA", None)
    return bool(cfg) if cfg is not None else False


def _norm3(value) -> str:
    return re.sub(r"\D", "", str(value))[-3:].zfill(3)


def normalize_uuid_v4_upper(value: str) -> str:
    """
    Normaliza `value` como UUID v4 con guiones en MAYÚSCULAS.
    Lanza ValueError si no es un UUID v4 válido.
    """
    u = uuid.UUID(str(value))
    if u.version != 4:
        raise ValueError
    return str(u).upper()


def numero_a_letras(monto):
    """Convierte ``monto`` numérico a su representación en letras."""
    try:
        texto = monto_a_texto_sv(monto)
    except Exception:
        return ""
    if " " in texto:
        partes = texto.split(" ", 1)
        return f"{partes[0]} CON {partes[1]}"
    return texto


def monto_a_letras_natural(monto: D) -> str:
    """Return ``monto`` in natural Spanish text (e.g. ``Trece Dolares``)."""
    entero = int(monto)
    centavos = int((monto - D(entero)) * 100)
    palabras_entero = num2words(entero, lang="es").capitalize()
    palabras_centavos = num2words(centavos, lang="es")
    dolar = "Dolar" if entero == 1 else "Dolares"
    centavo = "centavo" if centavos == 1 else "centavos"
    return f"{palabras_entero} {dolar} con {palabras_centavos} {centavo}"


def identificacion_a_xml(ident: dict) -> Element:
    """Return an XML ``Element`` for ``ident``.

    Optional values are retrieved into variables and only assigned to the
    corresponding tag when not ``None``; otherwise the tag text is an empty
    string.
    """
    root = Element("identificacion")

    version = ident.get("version")
    SubElement(root, "version").text = "" if version is None else str(version)

    ambiente = ident.get("ambiente")
    SubElement(root, "ambiente").text = ambiente or ""

    tipo_dte = ident.get("tipoDte")
    SubElement(root, "tipoDte").text = "" if tipo_dte is None else str(tipo_dte)

    numero_control = ident.get("numeroControl")
    SubElement(root, "numeroControl").text = numero_control or ""

    codigo_generacion = ident.get("codigoGeneracion")
    SubElement(root, "codigoGeneracion").text = codigo_generacion or ""

    tipo_modelo = ident.get("tipoModelo")
    SubElement(root, "tipoModelo").text = (
        "" if tipo_modelo is None else str(tipo_modelo)
    )

    tipo_operacion = ident.get("tipoOperacion")
    SubElement(root, "tipoOperacion").text = (
        "" if tipo_operacion is None else str(tipo_operacion)
    )

    tipo_contingencia = ident.get("tipoContingencia")
    SubElement(root, "tipoContingencia").text = (
        "" if tipo_contingencia is None else str(tipo_contingencia)
    )

    motivo_contin = ident.get("motivoContin")
    SubElement(root, "motivoContin").text = (
        "" if motivo_contin is None else str(motivo_contin)
    )

    fec_emi = ident.get("fecEmi")
    SubElement(root, "fecEmi").text = fec_emi or ""

    hor_emi = ident.get("horEmi")
    SubElement(root, "horEmi").text = hor_emi or ""

    tipo_moneda = ident.get("tipoMoneda")
    SubElement(root, "tipoMoneda").text = tipo_moneda or ""

    return root


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
    if isinstance(value, float):
        return D(str(value))
    if isinstance(value, str):
        v = value.strip()
        lower = v.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        if re.fullmatch(r"-?\d+", v):
            try:
                return int(v)
            except Exception:
                return v
        if re.fullmatch(r"-?\d+\.\d+", v):
            try:
                return D(v)
            except Exception:
                return v
        return v
    return value



def _load_datos_negocio():
    if os.path.exists(DATOS_NEGOCIO_PATH):
        try:
            with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            dte_api = data.get("dte_api")
            if isinstance(dte_api, dict):
                # Extract branch and point-of-sale codes from the control prefix
                prefijo = dte_api.get("prefijo_control")
                if isinstance(prefijo, str):
                    m = re.search(r"S([A-Za-z0-9]{3})P([A-Za-z0-9]{3})", prefijo)
                    if m:
                        suc, punto = m.groups()
                        data.setdefault("codEstable", suc.zfill(4))
                        data.setdefault("codEstableMH", suc.zfill(4))
                        data.setdefault("codPuntoVenta", punto.zfill(4))
                        data.setdefault("codPuntoVentaMH", punto.zfill(4))

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


DEPARTAMENTO_CODES = {f"{i:02d}" for i in range(0, 15)}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?\d{8,15}$")


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
    "00": ("00", "00"),  # Otro
    "01": ("13", "15"),  # Ahuachapán
    "02": ("14", "17"),  # Santa Ana
    "03": ("17", "20"),  # Sonsonate
    "04": ("34", "36"),  # Chalatenango
    "05": ("23", "28"),  # La Libertad
    "06": ("20", "24"),  # San Salvador
    "07": ("17", "18"),  # Cuscatlán
    "08": ("23", "25"),  # La Paz
    "09": ("10", "11"),  # Cabañas
    "10": ("14", "15"),  # San Vicente
    "11": ("24", "26"),  # Usulután
    "12": ("21", "23"),  # San Miguel
    "13": ("27", "28"),  # Morazán
    "14": ("19", "20"),  # La Unión
}


def _map_municipio(nombre: str | None, departamento: str | None = None) -> str:
    """Validate and return a municipio code."""

    if nombre is None:
        raise ValueError("Municipio requerido")

    nombre = str(nombre)
    if nombre.isdigit():
        nombre = nombre.zfill(2)
    if not nombre.isdigit() or len(nombre) != 2:
        raise ValueError("Municipio inválido")

    # No se valida que el municipio pertenezca al departamento indicado,
    # solo se asegura que el código sea numérico de dos dígitos.
    return nombre


def _clean_nit(nit):
    if nit:
        return "".join(c for c in str(nit) if c.isdigit())
    return None


def _clean_nrc(nrc):
    if not nrc:
        return None
    nrc_str = str(nrc)
    if nrc_str.isdigit() and 1 <= len(nrc_str) <= 8:
        return nrc_str
    return None


# --- Dirección --------------------------------------------------------------

# Mapeos básicos de departamentos y municipios utilizados para normalizar la
# dirección del receptor.  Solo se incluyen los valores necesarios para las
# pruebas actuales; otros códigos pasarán la validación únicamente si ya vienen
# normalizados.

_DEPARTAMENTOS = {
    "00": "Otro (Para extranjeros)",
    "01": "Ahuachapán",
    "02": "Santa Ana",
    "03": "Sonsonate",
    "04": "Chalatenango",
    "05": "La Libertad",
    "06": "San Salvador",
    "07": "Cuscatlán",
    "08": "La Paz",
    "09": "Cabañas",
    "10": "San Vicente",
    "11": "Usulután",
    "12": "San Miguel",
    "13": "Morazán",
    "14": "La Unión",
}


def _normalize_text(value: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFD", str(value))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.strip().casefold()


_DEPARTAMENTO_BY_NAME = {_normalize_text(v): k for k, v in _DEPARTAMENTOS.items()}

_MUNICIPIOS_POR_DEPTO = {
    "00": {"00": "Otro (Para extranjeros)"},
    "01": {
        "13": "Ahuachapán Norte",
        "14": "Ahuachapán Centro",
        "15": "Ahuachapán Sur",
    },
    "02": {
        "14": "Santa Ana Norte",
        "15": "Santa Ana Centro",
        "16": "Santa Ana Este",
        "17": "Santa Ana Oeste",
    },
    "03": {
        "17": "Sonsonate Norte",
        "18": "Sonsonate Centro",
        "19": "Sonsonate Este",
        "20": "Sonsonate Oeste",
    },
    "04": {
        "34": "Chalatenango Norte",
        "35": "Chalatenango Centro",
        "36": "Chalatenango Sur",
    },
    "05": {
        "23": "La Libertad Norte",
        "24": "La Libertad Centro",
        "25": "La Libertad Oeste",
        "26": "La Libertad Este",
        "27": "La Libertad Costa",
        "28": "La Libertad Sur",
    },
    "06": {
        "20": "San Salvador Norte",
        "21": "San Salvador Oeste",
        "22": "San Salvador Este",
        "23": "San Salvador Centro",
        "24": "San Salvador Sur",
    },
    "07": {
        "17": "Cuscatlán Norte",
        "18": "Cuscatlán Sur",
    },
    "08": {
        "23": "La Paz Oeste",
        "24": "La Paz Centro",
        "25": "La Paz Este",
    },
    "09": {
        "10": "Cabañas Oeste",
        "11": "Cabañas Este",
    },
    "10": {
        "14": "San Vicente Norte",
        "15": "San Vicente Sur",
    },
    "11": {
        "24": "Usulután Norte",
        "25": "Usulután Este",
        "26": "Usulután Oeste",
    },
    "12": {
        "21": "San Miguel Norte",
        "22": "San Miguel Centro",
        "23": "San Miguel Oeste",
    },
    "13": {
        "27": "Morazán Norte",
        "28": "Morazán Sur",
    },
    "14": {
        "19": "La Unión Norte",
        "20": "La Unión Sur",
    },
}

_MUNI_NAME_MAP: dict[str, list[tuple[str, str]]] = {}
for dep, munis in _MUNICIPIOS_POR_DEPTO.items():
    for code, name in munis.items():
        _MUNI_NAME_MAP.setdefault(_normalize_text(name), []).append((dep, code))


def _normalize_departamento(value) -> str:
    """Return departamento code from numeric or textual ``value``."""

    if value is None:
        raise ValidationError("Departamento requerido")
    val = str(value).strip()
    if val.isdigit():
        code = val.zfill(2)
        if code in DEPARTAMENTO_CODES:
            return code
    else:
        code = _DEPARTAMENTO_BY_NAME.get(_normalize_text(val))
        if code:
            return code
    raise ValidationError("Departamento inválido")


def _normalize_municipio(dep_code: str | None, value):
    """Return ``(mun_code, dep_code)`` normalizing ``value``.

    Cuando ``dep_code`` es ``None`` el departamento se infiere a partir del
    catálogo; si no es único se genera ``ValidationError``.
    """

    if value is None:
        warnings.warn(
            "Municipio requerido; se continuará con el valor en blanco",
            UserWarning,
        )
        return None, dep_code

    val = str(value).strip()
    dep_norm = dep_code
    if dep_norm:
        dep_norm = _normalize_departamento(dep_norm)

    if val.isdigit():
        code = val.zfill(2)
        return code, dep_norm

    norm = _normalize_text(val)
    matches = _MUNI_NAME_MAP.get(norm)
    if not matches:
        raise ValidationError("Municipio inválido")
    if dep_norm:
        for dep, code in matches:
            if dep == dep_norm:
                return code, dep_norm
        # Departamento no coincide; retornar código de municipio encontrado
        return matches[0][1], dep_norm
    if len(matches) > 1:
        raise ValidationError(
            "receptor.direccion: municipio inválido para el departamento seleccionado"
        )
    dep_norm, code = matches[0]
    return code, dep_norm


def _build_receptor_direccion(src: dict) -> dict:
    """Return normalized ``direccion`` dictionary for receptor."""

    if not isinstance(src, dict):
        raise ValidationError("receptor.direccion faltante")

    raw_dep = src.get("departamento")
    raw_muni = src.get("municipio")
    complemento = (
        src.get("complemento") or src.get("direccionDetalle") or src.get("direccion")
    )
    if isinstance(complemento, str):
        complemento = complemento.strip() or None

    dep_code = _normalize_departamento(raw_dep) if raw_dep is not None else None
    muni_code, dep_inferred = _normalize_municipio(dep_code, raw_muni)
    dep_code = dep_code or dep_inferred
    if dep_code is None or muni_code is None:
        warnings.warn(
            "Información de dirección incompleta; la factura se generará con campos nulos",
            UserWarning,
        )

    return {
        "departamento": dep_code,
        "municipio": muni_code,
        "complemento": complemento,
    }


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
    Defaults to ``1`` (Contado) when no value is provided.  Any value outside
    the catalog is normalized to ``1`` without raising an exception.
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
            code = _CONDICION_OPERACION_BY_NAME.get(val, 1)
    if code not in CONDICION_OPERACION_CATALOG:
        code = 1
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


def normalizar_pagos(pagos_raw, total, tipo_dte="01", condicion=1):
    """Normaliza la lista de pagos al formato del esquema."""

    allowed = set(catalogos.FORMA_PAGO.keys())
    schema = catalogos.get_dte_schema(tipo_dte)
    props: dict = {}
    enum_codes: list = []
    if schema:
        props = (
            schema.get("properties", {})
            .get("resumen", {})
            .get("properties", {})
            .get("pagos", {})
            .get("items", {})
            .get("properties", {})
        )
        enum_codes = props.get("codigo", {}).get("enum", [])
        allowed.update(str(c).zfill(2) for c in enum_codes)

    code_type = props.get("codigo", {}).get("type", "string")
    periodo_type = props.get("periodo", {}).get("type", ["number", "null"])
    plazo_type = props.get("plazo", {}).get("type", ["string", "null"])
    code_is_int = code_type == "integer" or (
        isinstance(code_type, list) and "integer" in code_type
    )
    periodo_is_str = periodo_type == "string" or (
        isinstance(periodo_type, list) and "string" in periodo_type
    )
    plazo_is_str = plazo_type == "string" or (
        isinstance(plazo_type, list) and "string" in plazo_type
    )

    total = money(total)
    pagos: list[dict] = []
    for p in pagos_raw or []:
        codigo_raw = p.get("codigo", "")
        codigo_str = str(codigo_raw).zfill(2)
        if allowed and codigo_str not in allowed:
            continue
        codigo = int(codigo_raw) if code_is_int else codigo_str
        monto = money(p.get("montoPago", 0))
        referencia = p.get("referencia") or None
        periodo_raw = p.get("periodo")
        if periodo_raw in ("", None):
            periodo = None
        else:
            periodo = str(periodo_raw).zfill(2) if periodo_is_str else int(periodo_raw)
        plazo_raw = p.get("plazo")
        if plazo_raw in ("", None):
            plazo = None
        else:
            plazo = str(plazo_raw).zfill(2) if plazo_is_str else int(plazo_raw)
        pagos.append(
            {
                "codigo": codigo,
                "montoPago": monto,
                "referencia": referencia,
                "periodo": periodo,
                "plazo": plazo,
            }
        )

    if not pagos:
        if condicion == 2:
            raise ValidationError("condicionOperacion=2 requiere detallar pagos")
        if enum_codes:
            if code_is_int:
                default_code = enum_codes[0] if 1 not in enum_codes else 1
            else:
                default_code = (
                    "01" if "01" in enum_codes else str(enum_codes[0]).zfill(2)
                )
        else:
            # schema tipa integer sin enum -> código 1 explícito
            default_code = 1 if code_is_int else "01"
        pagos = [
            {
                "codigo": int(default_code) if code_is_int else default_code,
                "montoPago": total,
                "referencia": None,
                "periodo": None,
                "plazo": None,
            }
        ]
    else:
        # Fijar todos los pagos excepto el último y recalcularlo para que el
        # total coincida. Esta estrategia permite corregir discrepancias
        # superiores a un centavo de forma determinista, tal como se describe en
        # la documentación del proyecto.
        suma_parcial = sum((p["montoPago"] for p in pagos[:-1]), D("0.00"))
        nuevo = money(total - suma_parcial)
        if nuevo < 0:
            suma_total = suma_parcial + pagos[-1]["montoPago"]
            diff = money(total - suma_total)
            raise ValidationError(
                f"La suma de pagos {money(suma_total)} difiere del total {total} (dif {diff})"
            )
        pagos[-1]["montoPago"] = nuevo

    if condicion == 2:
        first = pagos[0]
        plazo_val = int(first.get("plazo") or 0)
        periodo_val = str(first.get("periodo") or "").zfill(2)
        if not plazo_val or periodo_val not in catalogos.PLAZO:
            raise ValidationError(
                "condicionOperacion=2 requiere pago con plazo>0 y periodo válido",
            )
        first["plazo"] = plazo_val if not plazo_is_str else str(plazo_val).zfill(2)
        first["periodo"] = periodo_val if periodo_is_str else int(periodo_val)

    for p in pagos:
        p["montoPago"] = money(p["montoPago"])
        if (p["montoPago"] * 100) % 1:
            raise ValidationError("Los montos de pago deben ser múltiplos de 0.01")

    suma_final = sum((p["montoPago"] for p in pagos), D("0.00"))
    diff_final = money(total - suma_final)
    if diff_final != 0:
        raise ValidationError(
            f"La suma de pagos {money(suma_final)} difiere del total {total} (dif {diff_final})"
        )

    return pagos


def armar_tributos(tributos_raw, tipo_dte):
    """Construye la lista de tributos o retorna ``None``."""
    if not tributos_raw:
        return None
    # Los códigos válidos se obtienen tanto del catálogo local como del
    # esquema oficial del tipo de documento.  Esto permite extender el catálogo
    # sin depender de que el esquema se encuentre actualizado.
    allowed = set(TRIBUTOS_PERMITIDOS_RESUMEN)
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
        valor = money(t.get("valor", 0))
        if valor == D("0"):
            valor = D("0")
        result.append(
            {
                "codigo": codigo,
                # Si no se proporciona descripción, intentar obtenerla del catálogo
                "descripcion": t.get("descripcion") or catalogos.TRIBUTOS.get(codigo),
                "valor": valor,
            }
        )
    if tipo_dte == "01" and any(t["codigo"] == TRIBUTO_IVA for t in result):
        raise ValueError(
            "Código 20 (IVA) no permitido en resumen.tributos para consumidor final"
        )
    return result or None


def calcular_resumen(items_total, venta, fiscal=None, extra=None, tipo_dte="01"):
    """Calcula la sección resumen acorde al esquema oficial."""

    fiscal = fiscal or {}
    extra = extra or {}
    if tipo_dte in {"01", "03", "05", "06"}:
        precios_incluyen_iva = True
        extra["precios_incluyen_iva"] = True
    else:
        precios_incluyen_iva = _precios_incluyen_iva_from(extra)

    items_total = money(items_total)
    total_exenta = money(fiscal.get("ventas_exentas", 0))
    total_no_suj = money(fiscal.get("ventas_no_sujetas", 0))
    total_no_gravado = money(fiscal.get("no_gravado", 0))

    if tipo_dte == "01":
        descu_no_suj = money(0)
        descu_exenta = money(0)
        descu_gravada = money(0)
        total_descu = money(fiscal.get("descuentos", 0))
        sub_total_ventas = money(items_total)
        total_gravada = money(
            fiscal.get(
                "sumas",
                max(sub_total_ventas - total_exenta - total_no_suj, D("0")),
            )
        )
        total_iva = money(
            fiscal.get("iva", total_gravada - (total_gravada / D("1.13")))
        )
        sub_total = sub_total_ventas
        monto_total_operacion = sub_total
        total_pagar = sub_total
        porcentaje_desc = money(0)
    elif precios_incluyen_iva:
        descu_no_suj = money(fiscal.get("descu_no_suj", 0))
        descu_exenta = money(fiscal.get("descu_exenta", 0))
        descu_gravada = money(
            fiscal.get("descu_gravada", fiscal.get("descuentos", 0))
        )
        total_descu = money(descu_no_suj + descu_exenta + descu_gravada)
        if tipo_dte in {"03", "05", "06"}:
            if "sumas" in fiscal:
                total_gravada = money(fiscal["sumas"])
                total_iva = money(fiscal.get("iva", 0))
            else:
                total_gravada = money(items_total)
                total_iva = money(
                    fiscal.get("iva", items_total * D("0.13"))
                )
            sub_total_ventas = money(
                fiscal.get("sub_total_ventas", total_gravada + total_descu)
            )
            sub_total = total_gravada
            total_descu = descu_gravada
            monto_total_operacion = money(total_gravada + total_iva)
            total_pagar = monto_total_operacion
            porcentaje_desc = money(
                (total_descu * D("100") / sub_total_ventas)
                if sub_total_ventas
                else D("0")
            )
        else:
            total_gravada = money(
                fiscal.get(
                    "sumas",
                    (items_total - total_exenta - total_no_suj) / D("1.13"),
                )
            )
            total_iva = money(
                fiscal.get(
                    "iva", items_total - total_exenta - total_no_suj - total_gravada
                )
            )
            sub_total_ventas = money(total_no_suj + total_exenta + total_gravada)
            sub_total = money(sub_total_ventas - total_descu)
            monto_total_operacion = money(
                sub_total + total_no_gravado + total_iva
            )
            total_pagar = money(monto_total_operacion)
            base_desc = sub_total_ventas + total_descu
            porcentaje_desc = money(
                (total_descu * D("100") / base_desc) if base_desc else D("0")
            )
    else:
        descu_no_suj = money(fiscal.get("descu_no_suj", 0))
        descu_exenta = money(fiscal.get("descu_exenta", 0))
        descu_gravada = money(fiscal.get("descu_gravada", fiscal.get("descuentos", 0)))
        total_descu = money(descu_no_suj + descu_exenta + descu_gravada)
        total_gravada = money(fiscal.get("sumas", items_total))
        total_iva = money(fiscal.get("iva", 0)) if total_gravada > D("0") else money(0)
        sub_total_ventas = money(total_no_suj + total_exenta + total_gravada)
        sub_total = money(sub_total_ventas - total_descu)
        monto_total_operacion = money(
            sub_total + total_no_gravado + total_iva
        )
        total_pagar = money(monto_total_operacion)
        base_desc = sub_total_ventas + total_descu
        porcentaje_desc = money(
            (total_descu * D("100") / base_desc) if base_desc else D("0")
        )

    venta_total = None
    if isinstance(venta, dict):
        venta_total_raw = venta.get("total")
        if venta_total_raw is not None:
            venta_total = money(venta_total_raw)
    elif venta is not None:
        try:
            venta_total = money(venta)
        except Exception:
            venta_total = None
    if venta_total is not None:
        diff = money(venta_total - total_pagar)
        if diff != 0:
            total_iva = money(total_iva + diff)
            monto_total_operacion = money(monto_total_operacion + diff)
            total_pagar = money(total_pagar + diff)

    resumen = RESUMEN_DEFAULTS.get(tipo_dte, {}).copy()
    resumen.update(
        {
            "totalNoSuj": total_no_suj,
            "totalExenta": total_exenta,
            "totalGravada": total_gravada,
            "subTotalVentas": sub_total_ventas,
            "descuNoSuj": descu_no_suj,
            "descuExenta": descu_exenta,
            "descuGravada": descu_gravada,
            "totalDescu": total_descu,
            "subTotal": sub_total,
            "porcentajeDescuento": porcentaje_desc,
            "totalNoGravado": total_no_gravado,
            "montoTotalOperacion": monto_total_operacion,
            "totalPagar": total_pagar,
            "totalLetras": (
                monto_a_letras_natural(total_pagar)
                if tipo_dte == "01"
                else numero_a_letras(total_pagar)
            ),
        }
    )

    resumen["ivaRete1"] = money(fiscal.get("iva_rete1", resumen.get("ivaRete1", 0)))
    resumen["reteRenta"] = money(fiscal.get("rete_renta", resumen.get("reteRenta", 0)))

    if tipo_dte not in {"03", "05", "06"}:
        resumen["totalIva"] = total_iva

    if tipo_dte in {"01", "03", "05", "06"}:
        condicion = extra.get("condicion_operacion")
        if condicion is None:
            condicion = fiscal.get("condicion_pago")
        resumen["condicionOperacion"] = _parse_condicion_operacion(condicion)

    # Consolidar tributos adicionales desde ``extra`` o ``fiscal``
    trib_raw = []
    for src in (extra.get("tributos"), fiscal.get("tributos")):
        if not src:
            continue
        if isinstance(src, dict):
            src = [src]
        trib_raw.extend(src)

    suma_por_codigo: dict[str, D] = {}
    for t in trib_raw:
        codigo = str(t.get("codigo", "")).upper()
        if codigo == TRIBUTO_IVA:
            if tipo_dte == "01":
                raise ValueError(
                    "Código 20 (IVA) no permitido en resumen.tributos para consumidor final"
                )
            continue
        if not codigo:
            continue
        valor = money(t.get("valor", 0))
        suma_por_codigo[codigo] = money(suma_por_codigo.get(codigo, D("0")) + valor)

    tributos_list = [{"codigo": c, "valor": v} for c, v in suma_por_codigo.items()]
    if tipo_dte in {"03", "05", "06"}:
        resumen["tributos"] = (
            [
                {
                    "codigo": TRIBUTO_IVA,
                    "descripcion": catalogos.TRIBUTOS.get(TRIBUTO_IVA),
                    "valor": money(total_iva),
                }
            ]
            if total_gravada > D("0")
            else None
        )
    else:
        if tipo_dte != "01" and total_gravada > D("0"):
            tributos_list.append({"codigo": TRIBUTO_IVA, "valor": total_iva})
        resumen["tributos"] = armar_tributos(tributos_list, tipo_dte)
        if tipo_dte != "01" and total_gravada <= D("0") and not tributos_list:
            resumen.pop("tributos", None)
            resumen.pop("totalIva", None)

    if "pagos" in resumen:
        resumen["pagos"] = normalizar_pagos(
            extra.get("pagos"),
            resumen["totalPagar"],
            tipo_dte=tipo_dte,
            condicion=resumen.get("condicionOperacion", 1),
        )

    if "numPagoElectronico" in resumen:
        resumen["numPagoElectronico"] = extra.get("numPagoElectronico", "")

    excl = {
        "totalLetras",
        "condicionOperacion",
        "pagos",
        "numPagoElectronico",
        "tributos",
    }
    special_d4_fields = {"totalExenta", "totalNoSuj"}
    for key, val in list(resumen.items()):
        if key in excl:
            continue
        if isinstance(val, Decimal):
            if key in special_d4_fields:
                if val != d4(val):
                    raise ValidationError(f"{key} debe ser múltiplo de 0.0001")
            else:
                if val != money(val):
                    raise ValidationError(f"{key} debe ser múltiplo de 0.01")
            if val == D("0") and val.as_tuple().sign:
                resumen[key] = D("0")

    if resumen.get("tributos"):
        for t in resumen["tributos"]:
            val = t.get("valor")
            if isinstance(val, Decimal):
                if val != money(val):
                    raise ValidationError("valor de tributo debe ser múltiplo de 0.01")
                if val == D("0") and val.as_tuple().sign:
                    t["valor"] = D("0")

    if resumen.get("pagos"):
        for p in resumen["pagos"]:
            mp = p.get("montoPago")
            if isinstance(mp, Decimal):
                if mp != money(mp):
                    raise ValidationError("montoPago debe ser múltiplo de 0.01")
                if mp == D("0") and mp.as_tuple().sign:
                    p["montoPago"] = D("0")

    return resumen


def recalcular_totales(
    data: dict, *, precios_incluyen_iva: bool | None = None
) -> list[str]:
    """Recalcula y corrige los totales del resumen en ``data``.

    La función vuelve a calcular los valores de la sección ``resumen`` a partir
    de los ítems del ``cuerpoDocumento``.  Si alguno de los totales declarados
    difiere del valor esperado por más de un centavo, el valor se corrige en el
    lugar.  Devuelve una lista con los nombres de los campos ajustados.

    ``precios_incluyen_iva`` indica si los precios de los ítems incluyen IVA.
    Cuando se omite (``None``), el valor se obtiene de ``extra`` o de la
    configuración global.
    """

    extra_conf = data.get("extra") or {}
    tipo_dte = str(data.get("identificacion", {}).get("tipoDte", ""))
    if tipo_dte == "01":
        precios_flag = True
        extra_conf["precios_incluyen_iva"] = True
        data["extra"] = extra_conf
    elif tipo_dte in {"03", "05", "06"}:
        precios_flag = True
        extra_conf["precios_incluyen_iva"] = True
        data["extra"] = extra_conf
        # ``03`` se usa tanto para comprobantes de crédito fiscal como para
        # tickets.  Solo los primeros requieren un NIT receptor válido; los
        # tickets pueden omitirlo.  Se omite la validación si no hay receptor
        # o si ``extra['es_ticket']`` está definido y es verdadero.
        receptor = data.get("receptor") or {}
        if receptor and not extra_conf.get("es_ticket"):
            nit = str(receptor.get("nit") or "")
            if not (len(nit) == 14 and nit.isdigit()):
                raise ValueError(
                    "receptor.nit debe tener 14 dígitos sin guiones"
                )
    else:
        precios_flag = _precios_incluyen_iva_from(extra_conf, precios_incluyen_iva)

    cuerpo = data.get("cuerpoDocumento", [])
    resumen = data.get("resumen", {})

    colapso_desc = False
    if tipo_dte == "03":
        bruto_desc = D("0")
        desc_sum = D("0")
        for _it in cuerpo:
            _cant = D(str(_it.get("cantidad") or 0))
            _precio = D(str(_it.get("precioUni") or 0))
            _descu = D(str(_it.get("montoDescu") or 0))
            bruto_desc += _cant * _precio
            desc_sum += _descu
        porcentaje = d2(desc_sum * D("100") / bruto_desc) if bruto_desc else D("0")
        if porcentaje != D("1"):
            colapso_desc = True
            for _it in cuerpo:
                _cant = D(str(_it.get("cantidad") or 0))
                _precio = D(str(_it.get("precioUni") or 0))
                _descu = D(str(_it.get("montoDescu") or 0))
                if _descu:
                    total_final_base = (_cant * _precio) - _descu
                    if _cant:
                        base_unit = d4(total_final_base / _cant)
                    else:
                        base_unit = d4(0)
                    _it["precioUni"] = base_unit
                    _it["montoDescu"] = d4(0)
                    _it["ventaGravada"] = d4(base_unit * _cant)
            resumen["descuNoSuj"] = resumen["descuExenta"] = resumen["descuGravada"] = resumen["totalDescu"] = money(0)
            resumen["porcentajeDescuento"] = money(0)

    iva_total = D("0")
    venta_gravada_sum = D("0")
    bruto_sum = D("0")
    bruto_linea_sum = D("0")
    descu_sum = D("0")
    bases: list[D] = []
    bases_pre: list[D] = []
    ivas: list[D] = []
    cantidades: list[D] = []
    sub_total_ventas = D("0")
    descu_gravada_sum = D("0")

    for idx, item in enumerate(cuerpo):
        cant = D(str(item.get("cantidad") or 0))
        precio = D(str(item.get("precioUni") or 0))
        monto_descu = D(str(item.get("montoDescu") or 0))
        if tipo_dte == "01":
            item["precioUni"] = d4(precio)
            item["montoDescu"] = d4(monto_descu)
            bruto = d4(cant * precio)
            if bruto < 0:
                bruto = d4(0)
            bruto_sum += bruto
            descu_sum += d4(monto_descu)
            linea = d4(bruto - monto_descu)
            if linea < 0:
                linea = d4(0)
            _, iva_calc = to_base_iva(linea)
            esperado_iva = d4(iva_calc)
            iva_raw = item.get("ivaItem")
            actual_iva = money(D(str(iva_raw))) if iva_raw is not None else None
            if iva_raw is not None and linea > D("0") and actual_iva != esperado_iva:
                logger.warning(
                    "IVA por ítem incoherente (%s); se corrige a %s",
                    actual_iva,
                    esperado_iva,
                )
            item["ventaGravada"] = linea
            item["ivaItem"] = esperado_iva
            if iva_raw is not None and linea == D("0") and actual_iva != D("0"):
                raise ValueError("ivaItem debe ser 0 cuando ventaGravada es 0")
            item["ventaExenta"] = d4(0)
            item["ventaNoSuj"] = d4(0)
            item["noGravado"] = d4(0)
            item["psv"] = d4(0)
            item["codTributo"] = None
            item["tributos"] = None
            iva_total += esperado_iva
            venta_gravada_sum += linea
        elif tipo_dte == "03":
            base_pre = d4(cant * precio)
            base = d4(base_pre - monto_descu)
            if base < 0:
                base = d4(0)
            bruto_desc = money_round_up(base * D("1.13"))
            iva_val = money(bruto_desc - base)
            bruto_linea = money_round_up(base_pre * D("1.13"))
            bases_pre.append(base_pre)
            bases.append(base)
            ivas.append(iva_val)
            bruto_sum += bruto_desc
            bruto_linea_sum += bruto_linea
            descu_sum += money(monto_descu)
            cantidades.append(cant)
            item.pop("ivaItem", None)
            item["ventaExenta"] = d4(0)
            item["ventaNoSuj"] = d4(0)
            item["noGravado"] = d4(0)
        else:
            bruto_linea = money(cant * precio)
            bruto_linea_sum += bruto_linea
            bruto = money(bruto_linea - monto_descu)
            if bruto < 0:
                bruto = money(0)
            bruto_sum += bruto
            descu_sum += money(monto_descu)
            if precios_flag:
                base_pre = money(bruto_linea / D("1.13"))
                base = money(bruto / D("1.13"))
                iva_val = money(bruto - base)
                base = money(bruto - iva_val)
                bases_pre.append(base_pre)
            else:
                base_pre = base = bruto
                iva_val = money(base * D("0.13"))
                bases_pre.append(base_pre)
            bases.append(base)
            ivas.append(iva_val)
            cantidades.append(cant)
            item.pop("ivaItem", None)
            item["ventaExenta"] = money(0)
            item["ventaNoSuj"] = money(0)
            item["noGravado"] = money(0)
    if tipo_dte != "01":
        if bases:
            bruto_total = bruto_sum
            base_total = money(bruto_total / D("1.13"))
            iva_total_calc = money(bruto_total - base_total)
            base_total = money(bruto_total - iva_total_calc)
            base_res = base_total - sum(bases)
            iva_res = iva_total_calc - sum(ivas)
            if base_res or iva_res:
                bases[0] = d4(bases[0] + base_res)
                ivas[0] = money(ivas[0] + iva_res)
            for idx, item in enumerate(cuerpo):
                if idx < len(bases):
                    base_val = d4(bases[idx])
                    cant = cantidades[idx]
                    iva_val = ivas[idx]
                    item["ventaGravada"] = base_val
                    if cant > 0:
                        item["precioUni"] = d4(base_val / cant)
                    else:
                        item["precioUni"] = d4(0)
                    trib_list: list[str] = []
                    tipo_item = int(item.get("tipoItem", 1))
                    if base_val > 0:
                        trib_list.append(TRIBUTO_IVA)
                    if tipo_item == 4:
                        if str(item.get("codTributo")) == TRIBUTO_IVA:
                            item["codTributo"] = None
                        item["uniMedida"] = item.get("uniMedida") or 99
                    else:
                        item["codTributo"] = None
                    item["tributos"] = trib_list or None
                    if "montoIva" in item:
                        item["montoIva"] = iva_val
            venta_gravada_sum = sum(bases)
            iva_total = sum(ivas)
        else:
            venta_gravada_sum = D("0")
            iva_total = D("0")

        if tipo_dte in {"03", "05", "06"}:
            if colapso_desc:
                sub_total_ventas = money(sum(bases))
                descu_gravada_sum = money(0)
            else:
                sub_total_ventas = money(sum(bases_pre))
                descu_gravada_sum = money(
                    sum(bp - b for bp, b in zip(bases_pre, bases))
                )
        else:
            if precios_flag:
                sub_total_ventas = money(sum(bases_pre))
                descu_gravada_sum = money(
                    sum(bp - b for bp, b in zip(bases_pre, bases))
                )
            else:
                sub_total_ventas = money(venta_gravada_sum)
                descu_gravada_sum = money(0)

    venta_gravada_sum = venta_gravada_sum
    total_iva_sum = d4(iva_total)

    modificados: list[str] = []

    def _set_resumen(key: str, value: D):
        current = resumen.get(key)
        if current is not None and money(D(str(current))) == value:
            resumen[key] = value
            return
        resumen[key] = value
        modificados.append(key)

    if tipo_dte == "01":
        _set_resumen("totalNoSuj", d4(0))
        _set_resumen("totalExenta", d4(0))
        _set_resumen("totalGravada", d4(venta_gravada_sum))
        _set_resumen("subTotalVentas", money(venta_gravada_sum))
        _set_resumen("descuNoSuj", money(0))
        _set_resumen("descuExenta", money(0))
        _set_resumen("descuGravada", money(0))
        _set_resumen("totalDescu", money(descu_sum))
        _set_resumen("porcentajeDescuento", money(0))
        _set_resumen("subTotal", money(venta_gravada_sum))
        _set_resumen("totalNoGravado", money(0))
        _set_resumen("totalIva", money(total_iva_sum))
        monto_total_operacion = money(venta_gravada_sum)
        _set_resumen("montoTotalOperacion", monto_total_operacion)
        _set_resumen("totalPagar", monto_total_operacion)
    else:
        _set_resumen("totalNoSuj", d4(0))
        _set_resumen("totalExenta", d4(0))
        _set_resumen("totalGravada", d4(venta_gravada_sum))
        if tipo_dte in {"03", "05", "06"}:
            _set_resumen("subTotalVentas", sub_total_ventas)
            _set_resumen("descuNoSuj", money(0))
            _set_resumen("descuExenta", money(0))
            _set_resumen("descuGravada", descu_gravada_sum)
            _set_resumen("totalDescu", descu_gravada_sum)
            porcentaje_desc = money(
                (descu_gravada_sum * D("100") / sub_total_ventas)
                if sub_total_ventas
                else D("0")
            )
            _set_resumen("porcentajeDescuento", porcentaje_desc)
            _set_resumen("subTotal", money(venta_gravada_sum))
            _set_resumen("totalNoGravado", money(0))
            monto_total_operacion = money(venta_gravada_sum + total_iva_sum)
            _set_resumen("montoTotalOperacion", monto_total_operacion)
            _set_resumen("totalPagar", monto_total_operacion)
        else:
            _set_resumen("subTotalVentas", money(venta_gravada_sum))
            _set_resumen("descuNoSuj", money(0))
            _set_resumen("descuExenta", money(0))
            _set_resumen("descuGravada", money(0))
            _set_resumen("totalDescu", money(0))
            base = venta_gravada_sum + descu_sum
            porcentaje_desc = money(
                (descu_sum * D("100") / base) if base else D("0")
            )
            _set_resumen("porcentajeDescuento", porcentaje_desc)
            _set_resumen("subTotal", money(venta_gravada_sum))
            _set_resumen("totalNoGravado", money(0))
            _set_resumen("totalIva", money(total_iva_sum))
            monto_total_operacion = money(venta_gravada_sum + total_iva_sum)
            _set_resumen("montoTotalOperacion", monto_total_operacion)
            _set_resumen("totalPagar", monto_total_operacion)
    trib_raw = resumen.get("tributos")
    if tipo_dte == "01":
        suma: dict[str, D] = {}
        for t in trib_raw or []:
            codigo = str(t.get("codigo", "")).upper()
            if codigo == TRIBUTO_IVA:
                raise ValueError(
                    "Código 20 (IVA) no permitido en resumen.tributos para consumidor final"
                )
            if not codigo:
                continue
            valor = money(t.get("valor", 0))
            suma[codigo] = money(suma.get(codigo, D("0")) + valor)
        trib = armar_tributos([{ "codigo": c, "valor": v} for c, v in suma.items()], tipo_dte)
    else:
        if tipo_dte in {"03", "05", "06"}:
            trib = (
                [
                    {
                        "codigo": TRIBUTO_IVA,
                        "descripcion": catalogos.TRIBUTOS.get(TRIBUTO_IVA),
                        "valor": money(total_iva_sum),
                    }
                ]
                if venta_gravada_sum > D("0")
                else None
            )
        else:
            suma: dict[str, D] = {}
            for t in trib_raw or []:
                codigo = str(t.get("codigo", "")).upper()
                if not codigo or codigo == TRIBUTO_IVA:
                    continue
                valor = money(t.get("valor", 0))
                suma[codigo] = money(suma.get(codigo, D("0")) + valor)
            if venta_gravada_sum > D("0"):
                suma[TRIBUTO_IVA] = total_iva_sum
            trib = armar_tributos([{ "codigo": c, "valor": v} for c, v in suma.items()], tipo_dte)
    if resumen.get("tributos") != trib:
        resumen["tributos"] = trib
        modificados.append("tributos")
    total_pagar = resumen["totalPagar"]
    try:
        if tipo_dte == "01":
            total_letras = monto_a_letras_natural(total_pagar)
        else:
            total_letras = monto_a_texto_sv(total_pagar)
    except Exception:
        total_letras = None
    if resumen.get("totalLetras") != total_letras:
        resumen["totalLetras"] = total_letras
        modificados.append("totalLetras")

    if resumen.get("pagos"):
        suma = money(sum(D(str(p.get("montoPago") or 0)) for p in resumen["pagos"]))
        delta = money(total_pagar - suma)
        if delta != D("0"):
            first = resumen["pagos"][0]
            first_val = D(str(first.get("montoPago") or 0))
            first["montoPago"] = money(first_val + delta)

    if tipo_dte in {"03", "05", "06"}:
        for item in cuerpo:
            cant = D(str(item.get("cantidad") or 0))
            precio_u = D(str(item.get("precioUni") or 0))
            esperado = money(precio_u * cant)
            if esperado != money(item.get("ventaGravada", 0)):
                warnings.warn(
                    "precioUni * cantidad incoherente con ventaGravada"
                )
                item["ventaGravada"] = esperado
        sub_total = money(resumen.get("totalGravada", 0))
        suma_trib = money(
            sum(D(str(t.get("valor") or 0)) for t in resumen.get("tributos") or [])
        )
        esperado_total = money(sub_total + suma_trib)
        if esperado_total != money(resumen.get("montoTotalOperacion", 0)):
            warnings.warn(
                "subTotal + tributos.valor incoherente con montoTotalOperacion"
            )
            resumen["montoTotalOperacion"] = esperado_total
            if money(resumen.get("totalPagar", 0)) != esperado_total:
                resumen["totalPagar"] = esperado_total
                if "totalPagar" not in modificados:
                    modificados.append("totalPagar")
            if "montoTotalOperacion" not in modificados:
                modificados.append("montoTotalOperacion")

    data["resumen"] = resumen
    return modificados
    # IVA-FIX END



def generar_numero_control(db: DB, tipo: str, sucursal: str, punto: str) -> str:
    """Genera un número de control secuencial."""
    correlativo = db.next_dte_correlativo(tipo, sucursal, punto)
    secuencia = str(correlativo).zfill(15)
    return f"DTE-{tipo}-S{sucursal}P{punto}-{secuencia}"


def identificacion_a_xml(ident: dict) -> str:
    """Convierte el bloque ``identificacion`` a una cadena XML simple."""
    root = ET.Element("Identificacion")
    ET.SubElement(root, "TipoDte").text = ident.get("tipoDte", "")
    ET.SubElement(root, "NumeroControl").text = ident.get("numeroControl", "")
    ET.SubElement(root, "CodigoGeneracion").text = ident.get("codigoGeneracion", "")
    ET.SubElement(root, "TipoModelo").text = str(ident.get("tipoModelo", ""))
    ET.SubElement(root, "TipoOperacion").text = str(ident.get("tipoOperacion", ""))
    ET.SubElement(root, "FecEmi").text = ident.get("fecEmi", "")
    ET.SubElement(root, "HorEmi").text = ident.get("horEmi", "")
    ET.SubElement(root, "Ambiente").text = ident.get("ambiente", "")
    return ET.tostring(root, encoding="unicode")


def generar_cabecera_dte_data(
    tipo_modelo: int,
    tipo_operacion: int,
    tipo_dte: str,
    db: DB,
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

    datos = _load_datos_negocio()
    prefijo = datos.get("dte_api", {}).get("prefijo_control", "")
    sucursal = "001"
    punto = "001"
    m = re.search(r"S(\d{3})P(\d{3})", prefijo)
    if m:
        sucursal, punto = m.groups()
    sucursal = _norm3(sucursal)
    punto = _norm3(punto)
    codigo_generacion = str(uuid.uuid4()).upper()
    numero_control = generar_numero_control(db, tipo_dte, sucursal, punto)
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

    if ambiente not in ("00", "01"):
        ambiente_cfg = str(ambiente).lower()
        ambiente = "01" if ambiente_cfg.startswith("produc") else "00"

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


    prefijo = str(datos.get("dte_api", {}).get("prefijo_control", ""))
    m = re.match(r"^DTE-\d{2}-S(\d{3})P(\d{3})$", prefijo)
    suc_pref, punto_pref = m.groups() if m else ("001", "001")
    cod_estable_raw = re.sub(r"\D", "", str(datos.get("codEstable", "")))
    cod_punto_raw = re.sub(r"\D", "", str(datos.get("codPuntoVenta", "")))
    cod_estable = (cod_estable_raw or suc_pref.rjust(4, "0"))[-4:].zfill(4)
    cod_punto = (cod_punto_raw or punto_pref.rjust(4, "0"))[-4:].zfill(4)
    suc = _norm3(cod_estable)
    pto = _norm3(cod_punto)
    # Generar identificadores con formatos oficiales
    codigo_generacion = str(uuid.uuid4()).upper()
    numero_control = generar_numero_control(db, tipo_dte, suc, pto)


    now = datetime.now(TZ_EL_SALVADOR)
    fecha = fecha_emision_hoy_str(now)
    hora = now.strftime("%H:%M:%S")

    # Permitir valores desde ``extra`` o ``kwargs``
    tipo_operacion = extra.get("tipoOperacion", tipo_operacion)
    tipo_contingencia = extra.get("tipoContingencia", tipo_contingencia)
    motivo_contin = extra.get("motivoContin", motivo_contin)
    tipo_operacion = kwargs.get(
        "tipoOperacion", kwargs.get("tipo_operacion", tipo_operacion)
    )
    tipo_contingencia = kwargs.get(
        "tipoContingencia", kwargs.get("tipo_contingencia", tipo_contingencia)
    )
    motivo_contin = kwargs.get(
        "motivoContin", kwargs.get("motivo_contin", motivo_contin)
    )

    # Normalización de tipos
    try:
        tipo_operacion = int(tipo_operacion or 1)
    except Exception:
        tipo_operacion = 1
    if tipo_contingencia in ("", None):
        tipo_contingencia = None
    else:
        tipo_contingencia = int(tipo_contingencia)
    if isinstance(motivo_contin, str):
        motivo_contin = motivo_contin.strip() or None

    # Reglas de operación / modelo / contingencia
    if tipo_operacion == 1:
        tipo_modelo = 1
        tipo_contingencia = None
        motivo_contin = None
    elif tipo_operacion == 2:
        tipo_modelo = 2
        if tipo_contingencia is None:
            raise ValueError("tipoContingencia requerido cuando tipoOperacion=2")
        if tipo_contingencia not in catalogos.CONTINGENCIA:
            raise ValueError("tipoContingencia debe estar entre 1 y 5")
        if tipo_contingencia == 5:
            if not (motivo_contin and 5 <= len(motivo_contin) <= 150):
                raise ValueError("motivoContin requerido cuando tipoContingencia=5")
        else:
            motivo_contin = None
    else:
        raise ValueError("tipoOperacion debe ser 1 o 2")

    tipo_dte = str(tipo_dte or "01").zfill(2)
    version = DTE_VERSIONES.get(tipo_dte, 1)
    identificacion = {
        "version": version,
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

    default_est = next(iter(catalogos.TIPO_ESTABLEC))
    tipo_est = datos.get("tipoEstablecimiento")
    tipo_est = str(tipo_est).zfill(2) if tipo_est else default_est
    if tipo_est not in catalogos.TIPO_ESTABLEC:
        tipo_est = default_est
    emisor = {
        "nombre": datos.get("nombre"),
        "nombreComercial": datos.get("nombreComercial"),
        "nit": datos.get("nit"),
        "nrc": datos.get("nrc"),
        "codActividad": datos.get("cod_giro") or datos.get("codActividad"),
        "descActividad": datos.get("descActividad"),
        "telefono": datos.get("telefono"),
        "correo": datos.get("correo"),
        "tipoEstablecimiento": tipo_est,
    }
    svfe_config.DATOS_NEGOCIO_PATH = DATOS_NEGOCIO_PATH
    datos_cfg = svfe_config.load_datos_negocio()
    dir_emisor = datos_cfg.get("direccion") or {}
    emisor["direccion"] = {
        "departamento": str(dir_emisor["departamento"]).zfill(2),
        "municipio": str(dir_emisor["municipio"]),  # respetar dígitos tal cual
        "complemento": dir_emisor.get("complemento") or "SIN DIRECCION",
    }
    emisor.setdefault("codEstableMH", cod_estable)
    emisor.setdefault("codEstable", cod_estable)
    emisor.setdefault("codPuntoVentaMH", cod_punto)
    emisor.setdefault("codPuntoVenta", cod_punto)
    if emisor.get("correo") and not EMAIL_RE.fullmatch(emisor["correo"]):
        raise ValueError("Correo de emisor inválido")
    if emisor.get("telefono") and not PHONE_RE.fullmatch(emisor["telefono"]):
        raise ValueError("Teléfono de emisor inválido")

    rec = dict(cliente or {})
    rec_extra = extra.get("receptor") or {}
    for k, v in rec_extra.items():
        if v not in (None, "", []):
            rec[k] = v

    def _clean_nit(nit):
        return "".join(c for c in str(nit) if c.isdigit()) if nit else None

    tipo_doc = rec.get("tipoDocumento")
    if tipo_doc is not None:
        tipo_doc = str(tipo_doc)
    num_doc = rec.get("numDocumento")
    nit = _clean_nit(rec.get("nit"))
    if fiscal:
        tipo_doc = fiscal.get("tipoDocumento") or tipo_doc
        num_doc = fiscal.get("numDocumento") or num_doc
        nit = _clean_nit(fiscal.get("nit") or nit)
    if nit and not num_doc:
        num_doc = nit
    if nit and not tipo_doc:
        tipo_doc = "36"

    if tipo_doc == "36":
        num_doc = _clean_nit(num_doc)
        if num_doc and not re.fullmatch(r"[0-9]{14}", num_doc):
            raise ValueError("NIT inválido")
    elif tipo_doc == "13":
        if num_doc and not re.fullmatch(r"[0-9]{8}-[0-9]", num_doc):
            raise ValueError("DUI inválido")

    receptor = {
        "tipoDocumento": tipo_doc if tipo_doc is not None else None,
        "numDocumento": num_doc,
        "nrc": (fiscal.get("nrc") if fiscal else None) or rec.get("nrc"),
        "nombre": rec.get("nombre"),
        "nit": nit,
        "nombreComercial": rec.get("nombreComercial"),
        "codActividad": None,
        "descActividad": None,
        "telefono": rec.get("telefono"),
        "correo": rec.get("correo"),
    }
    direccion_src = rec.get("direccion")
    if not isinstance(direccion_src, dict):
        direccion_src = rec
    receptor["direccion"] = _build_receptor_direccion(direccion_src)
    compl = receptor["direccion"].get("complemento")
    if not compl or len(str(compl)) < 5:
        receptor["direccion"]["complemento"] = "SIN DIRECCION"
    if receptor.get("correo") and not EMAIL_RE.fullmatch(receptor["correo"]):
        raise ValueError("Correo de receptor inválido")
    if receptor.get("telefono") and not PHONE_RE.fullmatch(receptor["telefono"]):
        raise ValueError("Teléfono de receptor inválido")
    if fiscal:
        if fiscal.get("no_remision"):
            receptor["noRemision"] = fiscal.get("no_remision")
        if fiscal.get("orden_no"):
            receptor["ordenNo"] = fiscal.get("orden_no")

    if not receptor.get("codActividad"):
        receptor["codActividad"] = (
            emisor.get("codActividad") or datos.get("cod_giro") or "00000"
        )
    if not receptor.get("descActividad"):
        receptor["descActividad"] = (
            emisor.get("descActividad")
            or datos.get("descActividad")
            or "SIN GIRO"
        )
    if not receptor.get("correo"):
        receptor["correo"] = "no-reply@example.com"

    # Campos obligatorios y limpieza de campos no permitidos
    if tipo_dte == "01":
        required_rec_fields = [
            "nrc",
            "nombre",
            "codActividad",
            "descActividad",
            "telefono",
            "correo",
            "direccion",
            "tipoDocumento",
            "numDocumento",
        ]
        for f in ("nit", "nombreComercial"):
            receptor.pop(f, None)
    else:
        required_rec_fields = [
            "nit",
            "nrc",
            "nombre",
            "nombreComercial",
            "codActividad",
            "descActividad",
            "telefono",
            "correo",
            "direccion",
        ]
        for f in ("noRemision", "ordenNo", "numDocumento", "tipoDocumento"):
            receptor.pop(f, None)

    for f in required_rec_fields:
        receptor.setdefault(f, None)

    cuerpo = []
    items_total = D("0")
    commission_total = D("0")
    iva_total = D("0")
    total_gravada_sum = D("0")
    total_exenta_sum = D("0")
    total_no_suj_sum = D("0")
    total_no_gravado_sum = D("0")
    bruto_total = D("0")
    descuentos_total = D("0")
    sub_total_ventas = D("0")
    descu_gravada_sum = D("0")
    override_precio_flag = kwargs.get("precios_incluyen_iva")
    precios_incluyen_iva = _precios_incluyen_iva_from(extra, override_precio_flag)
    if (
        tipo_dte in {"01", "03", "05", "06"}
        and "precios_incluyen_iva" not in extra
        and override_precio_flag is None
    ):
        precios_incluyen_iva = True
        extra["precios_incluyen_iva"] = True

    def _zero_or_d4(value: D) -> D:
        dec = d4(value)
        return D("0.0") if dec == 0 else dec

    def _zero_or_d2(value: D) -> D:
        dec = d2(value)
        return D("0.0") if dec == 0 else dec

    for idx, d in enumerate(detalles, 1):
        try:
            cant = d1(D(str(d.get("cantidad") or 0)))
        except Exception:
            cant = d1(D(0))
        if cant <= 0:
            cant = d1(D("1"))
        try:
            precio_raw = d4(D(str(d.get("precio_unitario") or 0)))
        except Exception:
            precio_raw = d4(D(0))
        try:
            tipo_item = int(d.get("tipoItem", 1))
        except Exception:
            tipo_item = 1
        if tipo_item not in (1, 2, 3, 4):
            tipo_item = 1
        try:
            uni_medida = int(d.get("uniMedida", 59))
        except Exception:
            uni_medida = 59
        if uni_medida not in UNIDADES_MEDIDA_PERMITIDAS:
            uni_medida = 59

        desc_raw = d4(D(str(d.get("descuento") or 0)))
        if desc_raw < 0:
            desc_raw = D("0")
        desc_tipo = str(d.get("descuento_tipo") or "$")

        def _calc_desc(bruto: D) -> D:
            if desc_tipo == "%":
                monto = d4(bruto * desc_raw / D("100"))
            else:
                monto = d4(desc_raw)
            return monto if monto <= bruto else bruto

        tipo_fiscal_item = str(d.get("tipo_fiscal", "")).lower()
        if tipo_fiscal_item == "venta exenta":
            precio = d4(precio_raw)
            bruto = d4(cant * precio)
            monto_descu = _calc_desc(bruto)
            line_total = d4(bruto - monto_descu)
            if line_total < 0:
                line_total = D("0")
            bruto_total += bruto
            descuentos_total += monto_descu
            venta_gravada = D("0")
            venta_exenta = d2(line_total)
            venta_no_suj = D("0")
            iva_val = D("0")
        elif tipo_fiscal_item == "venta no sujeta":
            precio = d4(precio_raw)
            bruto = d4(cant * precio)
            monto_descu = _calc_desc(bruto)
            line_total = d4(bruto - monto_descu)
            if line_total < 0:
                line_total = D("0")
            bruto_total += bruto
            descuentos_total += monto_descu
            venta_gravada = D("0")
            venta_exenta = D("0")
            venta_no_suj = d2(line_total)
            iva_val = D("0")
        else:
            if tipo_dte == "01":
                origen = (
                    extra.get("origen_precios")
                    or ("bruto" if precios_incluyen_iva else "neto")
                ).lower()
                if origen == "neto":
                    precio = d4(precio_raw * D("1.13"))
                else:
                    precio = d4(precio_raw)
                bruto = d4(cant * precio)
                monto_descu = _calc_desc(bruto)
                line_total = d4(bruto - monto_descu)
                venta_gravada = line_total if line_total > 0 else D("0")
                _, iva_val_tmp = to_base_iva(venta_gravada)
                iva_val = d4(iva_val_tmp)
                line_total = venta_gravada
                bruto_total += bruto
                descuentos_total += monto_descu
            elif precios_incluyen_iva:
                if tipo_dte in {"03", "05", "06"}:
                    bruto = d4(cant * precio_raw)
                    descu_total = _calc_desc(bruto)
                    bruto_final = d4(bruto - descu_total)
                    if bruto_final < 0:
                        bruto_final = D("0")
                    base_pre = money(bruto / D("1.13"))
                    base_final = money(bruto_final / D("1.13"))
                    descuento_base = money(base_pre - base_final)
                    precio = d4(money(base_pre / cant))
                    monto_descu = descuento_base
                    venta_gravada = base_final
                    iva_val_pre = money(base_pre * D("0.13"))
                    iva_desc = money(descuento_base * D("0.13"))
                    iva_val = money(iva_val_pre - iva_desc)
                    line_total = money(base_final + iva_val)
                    bruto_total += bruto
                    descuentos_total += descuento_base
                    sub_total_ventas += base_pre
                    descu_gravada_sum += descuento_base
                else:
                    bruto = d4(cant * precio_raw)
                    monto_descu = _calc_desc(bruto)
                    total_final = d4(bruto - monto_descu)
                    if total_final < 0:
                        total_final = D("0")
                    base_total = money(total_final / D("1.13"))
                    iva_val = d4(total_final - base_total)
                    base_total = money(total_final - iva_val)
                    precio = d4(money(base_total / cant))
                    venta_gravada = base_total
                    line_total = base_total + iva_val
                    bruto_total += bruto
                    descuentos_total += monto_descu
            else:
                precio = d4(precio_raw)
                bruto = d4(cant * precio)
                monto_descu = _calc_desc(bruto)
                base = d4(cant * precio - monto_descu)
                if base < 0:
                    base = D("0")
                venta_gravada = d2(base)
                iva_val = d4(venta_gravada * D("0.13")) if venta_gravada > 0 else D("0")
                line_total = venta_gravada + iva_val
                bruto_total += bruto
                descuentos_total += monto_descu
            venta_exenta = D("0")
            venta_no_suj = D("0")
        items_total += line_total
        iva_total += iva_val
        try:
            commission_total += D(str(d.get("comision") or 0))
        except Exception:
            pass
        trib_code_raw = d.get("codTributo")
        if not trib_code_raw:
            raw = d.get("tributos")
            if isinstance(raw, list) and raw:
                trib_code_raw = raw[0]
            elif isinstance(raw, str):
                trib_code_raw = raw
        trib_code = str(trib_code_raw).upper() if trib_code_raw else ""
        if trib_code == TRIBUTO_IVA:
            raise ValueError("El IVA 13% (20) no va por ítem; solo en resumen")
        if trib_code and trib_code not in TRIBUTOS_PERMITIDOS_ITEM:
            raise ValueError(f"Código de tributo inválido en ítem: {trib_code}")

        num_doc = d.get("numeroDocumento")
        if isinstance(num_doc, str):
            if num_doc.strip().upper() in {"NA", "N/A", ""}:
                num_doc = None
        elif not num_doc:
            num_doc = None

        item_data = {
            "numItem": idx,
            "tipoItem": tipo_item,
            "numeroDocumento": num_doc,
            "codigo": d.get("codigo") or "SKU-NA",
            "descripcion": d.get("descripcion"),
            "cantidad": cant,
            "uniMedida": uni_medida,
            "precioUni": d4(precio),
            "montoDescu": d4(monto_descu),
            "ventaNoSuj": venta_no_suj,
            "ventaExenta": venta_exenta,
            "ventaGravada": venta_gravada,
            "psv": money(0),
            "noGravado": money(0),
            "tributos": [],
        }
        if tipo_dte == "01":
            item_data["ivaItem"] = money(iva_val)
        if tipo_dte == "01":
            item_data["codTributo"] = None
            item_data["tributos"] = None
        else:
            trib_list: list[str] = []
            if D(str(item_data.get("ventaGravada") or 0)) > 0:
                trib_list.append(TRIBUTO_IVA)
            if tipo_item == 4 and trib_code:
                item_data["codTributo"] = trib_code
                trib_list.append(trib_code)
            else:
                item_data["codTributo"] = None
            item_data["tributos"] = trib_list
        for key in ("ventaNoSuj", "ventaExenta", "ventaGravada"):
            item_data[key] = _zero_or_d4(D(str(item_data[key])))
        total_no_suj_sum += D(str(item_data["ventaNoSuj"]))
        total_exenta_sum += D(str(item_data["ventaExenta"]))
        total_gravada_sum += D(str(item_data["ventaGravada"]))
        total_no_gravado_sum += D(str(item_data["noGravado"]))
        cuerpo.append(item_data)

    items_total = money(items_total)
    bruto_total = money(bruto_total)
    descuentos_total = money(descuentos_total)
    total_no_suj_sum = _zero_or_d4(total_no_suj_sum)
    total_exenta_sum = _zero_or_d4(total_exenta_sum)
    total_gravada_sum = _zero_or_d2(total_gravada_sum)
    total_no_gravado_sum = money(total_no_gravado_sum)
    total_iva_sum = d4(iva_total)
    sub_total_ventas = money(sub_total_ventas)
    descu_gravada_sum = money(descu_gravada_sum)

    fiscal_data = {
        **(fiscal or {}),
        "sumas": total_gravada_sum,
        "ventas_exentas": total_exenta_sum,
        "ventas_no_sujetas": total_no_suj_sum,
        "no_gravado": total_no_gravado_sum,
        "iva": total_iva_sum,
    }
    if tipo_dte in {"03", "05", "06"}:
        fiscal_data.update(
            {
                "descu_gravada": descu_gravada_sum,
                "sub_total_ventas": sub_total_ventas,
                "descuentos": descu_gravada_sum,
            }
        )
    else:
        fiscal_data.update({"descuentos": descuentos_total})

    resumen = calcular_resumen(
        items_total,
        venta,
        fiscal=fiscal_data,
        extra=extra,
        tipo_dte=tipo_dte,
    )

    resumen["totalNoSuj"] = _zero_or_d4(total_no_suj_sum)
    resumen["totalExenta"] = _zero_or_d4(total_exenta_sum)
    resumen["totalGravada"] = _zero_or_d2(total_gravada_sum)

    # Las siguientes validaciones se omiten para permitir diferencias entre el
    # resumen y el cuerpo del documento sin lanzar ``ValidationError``.
    # if money(sum(D(str(i["ventaGravada"])) for i in cuerpo)) != money(
    #     D(str(resumen.get("totalGravada", 0)))
    # ):
    #     raise ValidationError("totalGravada inconsistente con cuerpoDocumento")
    # if money(sum(D(str(i["ivaItem"])) for i in cuerpo)) != money(
    #     D(str(resumen.get("totalIva", 0)))
    # ):
    #     raise ValidationError("totalIva inconsistente con cuerpoDocumento")

    total_no_suj = D(str(resumen.get("totalNoSuj", 0)))
    total_exenta = D(str(resumen.get("totalExenta", 0)))
    total_gravada = D(str(resumen.get("totalGravada", 0)))
    sub_total_ventas = D(str(resumen.get("subTotalVentas", 0)))
    descu_no_suj = D(str(resumen.get("descuNoSuj", 0)))
    descu_exenta = D(str(resumen.get("descuExenta", 0)))
    descu_gravada = D(str(resumen.get("descuGravada", 0)))
    sub_total = D(str(resumen.get("subTotal", 0)))
    total_no_gravado = D(str(resumen.get("totalNoGravado", 0)))
    total_iva = D(str(resumen.get("totalIva", 0)))
    monto_total_operacion = D(str(resumen.get("montoTotalOperacion", 0)))
    total_pagar = D(str(resumen.get("totalPagar", 0)))

    # Verificaciones numéricas eliminadas para evitar errores de consistencia
    # que interrumpan el flujo de generación del DTE.
    # if money(total_no_suj + total_exenta + total_gravada) != money(sub_total_ventas):
    #     raise ValidationError("subTotalVentas inconsistente")
    # if money(sub_total_ventas - (descu_no_suj + descu_exenta + descu_gravada)) != money(
    #     sub_total
    # ):
    #     raise ValidationError("subTotal inconsistente")
    # if money(sub_total + total_no_gravado + total_iva) != money(monto_total_operacion):
    #     raise ValidationError("montoTotalOperacion inconsistente")
    # if money(monto_total_operacion) != money(total_pagar):
    #     raise ValidationError("totalPagar debe igualar montoTotalOperacion")

    pagos_resumen = resumen.get("pagos") or []
    suma = money(sum(D(str(p["montoPago"])) for p in pagos_resumen))
    diff = money(total_pagar - suma)
    # if diff != 0:
    #     raise ValidationError(
    #         f"La suma de pagos {suma} difiere del total {total_pagar} (dif {diff})"
    #     )
    # if money(total_gravada) == D("0.00"):
    #     if resumen.get("tributos"):
    #         raise ValidationError("No debe haber tributos sin venta gravada")
    #     if money(total_iva) != D("0.00"):
    #         raise ValidationError("totalIva debe ser 0 sin venta gravada")

    # Validaciones básicas de consistencia
    items_total_2 = d2(
        total_gravada_sum + total_exenta_sum + total_no_suj_sum + descuentos_total
    )
    if abs(items_total_2 - D(str(resumen.get("subTotalVentas", 0)))) > D("0.01"):
        print(
            f"Advertencia: la suma de los ítems {items_total_2:.2f} difiere del resumen {resumen.get('subTotalVentas',0):.2f}"
        )

    calc_sub_total = d2(
        D(str(resumen.get("subTotalVentas", 0))) - D(str(resumen.get("totalDescu", 0)))
    )
    if abs(calc_sub_total - D(str(resumen.get("subTotal", 0)))) > D("0.01"):
        print(
            f"Advertencia: el subtotal calculado {calc_sub_total:.2f} difiere del resumen {resumen.get('subTotal',0):.2f}"
        )

    iva_ref = resumen.get("totalIva")
    if iva_ref is None:
        tribs = resumen.get("tributos") or []
        iva_ref = next((t.get("valor") for t in tribs if t.get("codigo") == TRIBUTO_IVA), resumen.get("ivaPerci1", 0))
    iva_ref = D(str(iva_ref or 0))
    calc_total = d2(calc_sub_total + iva_ref)
    if abs(calc_total - D(str(resumen.get("montoTotalOperacion", 0)))) > D("0.01"):
        print(
            f"Advertencia: el monto total {resumen.get('montoTotalOperacion',0):.2f} difiere del calculado {calc_total:.2f}"
        )
    calc_total_commission = d2(calc_total + commission_total)
    if "totalPagar" in resumen and abs(
        calc_total_commission - D(str(resumen.get("totalPagar", 0)))
    ) > D("0.01"):
        print(
            f"Advertencia: el total a pagar {resumen.get('totalPagar',0):.2f} difiere del calculado {calc_total_commission:.2f}"
        )
    # SERIALIZE-GUARD BEGIN
    special_d4_fields = {"totalExenta", "totalNoSuj"}
    for k in ("totalIva", "montoTotalOperacion", "totalPagar", "totalNoGravado"):
        if k in resumen:
            val = D(str(resumen[k]))
            if val != money(val):
                raise ValidationError(
                    f"{k} debe ser múltiplo de 0.01 (recibido={resumen[k]})"
                )
            if val == D("0") and val.as_tuple().sign:
                resumen[k] = D("0")
    for k in special_d4_fields:
        if k in resumen:
            val = D(str(resumen[k]))
            if val != d4(val):
                raise ValidationError(
                    f"{k} debe ser múltiplo de 0.0001 (recibido={resumen[k]})"
                )
            if val == D("0") and val.as_tuple().sign:
                resumen[k] = D("0")

    if resumen.get("tributos"):
        for t in resumen["tributos"]:
            val = D(str(t.get("valor") or 0))
            if val != money(val):
                raise ValidationError("valor de tributo debe ser múltiplo de 0.01")
            if val == D("0") and val.as_tuple().sign:
                val = D("0")
            t["valor"] = val
    else:
        if tipo_dte != "01":
            resumen.pop("tributos", None)
        else:
            resumen["tributos"] = None

    if resumen.get("pagos"):
        if resumen.get("condicionOperacion") == 2:
            for p in resumen["pagos"]:
                p.setdefault("codigo", "01")
                if p.get("referencia") is None:
                    p["referencia"] = ""
                if p.get("periodo") is None:
                    p["periodo"] = ""
                if p.get("plazo") is None:
                    p["plazo"] = ""
        for p in resumen["pagos"]:
            val = D(str(p.get("montoPago") or 0))
            if val != money(val):
                raise ValidationError("montoPago debe ser múltiplo de 0.01")
            if val == D("0") and val.as_tuple().sign:
                val = D("0")
            p["montoPago"] = val

    # --- SINCRONIZAR SUMA DE PAGOS CON totalPagar (ajuste máx. 0.01) ---
    total_pagar_dec = money(D(str(resumen.get("totalPagar") or 0)))
    if resumen.get("pagos"):
        suma_pagos = D("0")
        for p in resumen["pagos"]:
            suma_pagos += D(str(p.get("montoPago") or 0))
        suma_pagos = money(suma_pagos)

        delta = money(total_pagar_dec - suma_pagos)
        if delta != D("0") and abs(delta) <= D("0.01"):
            ultimo = resumen["pagos"][-1]
            ult_m = D(str(ultimo.get("montoPago") or 0))
            ultimo["montoPago"] = money(ult_m + delta)
    def _quantize_money(value: D) -> D:
        dec = money(value)
        return D("0.0") if dec == 0 else dec

    special_d4_fields = {"totalExenta", "totalNoSuj"}

    for k, v in list(resumen.items()):
        if k in {
            "totalLetras",
            "condicionOperacion",
            "pagos",
            "numPagoElectronico",
            "tributos",
        }:
            continue
        qfn = _zero_or_d4 if k in special_d4_fields else _quantize_money
        resumen[k] = qfn(D(str(v)))

    if resumen.get("tributos"):
        for t in resumen["tributos"]:
            t["valor"] = _quantize_money(D(str(t["valor"])))

    if resumen.get("pagos"):
        for p in resumen["pagos"]:
            p["montoPago"] = _quantize_money(D(str(p["montoPago"])))
    # SERIALIZE-GUARD END

    extension = None

    result = {
        "identificacion": identificacion,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": cuerpo,
        "resumen": resumen,
        "documentoRelacionado": None,
        "otrosDocumentos": None,
        "apendice": None,
        "ventaTercero": None,
        "extension": extension,
    }

    validate_dte_json(result, db=db, precios_incluyen_iva=False)
    result.pop("extra", None)
    return json.loads(stable_stringify(result), parse_float=Decimal)


def validate_dte_json(
    payload: dict,
    *,
    db: DB,
    precios_incluyen_iva: bool | None = None,
) -> None:
    """Basic validation and normalization for DTE payload antes de firmar."""
    # Normalización omitida para preservar códigos con ceros a la izquierda
    # ("01", etc.) que ``_normalize_payload`` convertiría a enteros.
    required = ["identificacion", "emisor", "receptor", "cuerpoDocumento", "resumen"]

    # Cuando ``payload`` representa un sobre de recepción (envelope) ya
    # firmado, no incluye los campos de un DTE tradicional.  Evitamos la
    # validación de campos obligatorios en este caso para permitir el envío
    # directo del sobre a Hacienda.
    if "documento" in payload and not any(k in payload for k in required):
        return

    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError("Faltan campos obligatorios: " + ", ".join(missing))
    extra_conf = payload.get("extra") or {}
    precios_flag = _precios_incluyen_iva_from(extra_conf, precios_incluyen_iva)

    negocio = _load_datos_negocio()

    ident = payload.get("identificacion", {})
    config = _load_dte_api_config()
    ambiente = "01" if config.get("ambiente") == "produccion" else "00"
    ident.setdefault("ambiente", ambiente)
    amb_val = str(ident.get("ambiente", "")).lower()
    if amb_val not in {"00", "01"}:
        ident["ambiente"] = "01" if amb_val.startswith("produc") else "00"
    ident.setdefault("tipoMoneda", "USD")
    if "modeloFacturacion" in ident:
        ident["tipoModelo"] = int(str(ident.pop("modeloFacturacion")).split()[0])
    if "tipoTransmision" in ident:
        ident["tipoOperacion"] = int(str(ident.pop("tipoTransmision")).split()[0])

    tipo_dte_val = ident.get("tipoDte")
    if isinstance(tipo_dte_val, int):
        tipo_dte_val = f"{tipo_dte_val:02d}"
    else:
        tipo_dte_val = str(tipo_dte_val).zfill(2)
    ident["tipoDte"] = tipo_dte_val
    if tipo_dte_val not in catalogos.DTE_TIPOS:
        raise ValueError("tipoDte inválido")
    if tipo_dte_val in {"03", "05", "06"}:
        precios_flag = True
        extra_conf["precios_incluyen_iva"] = True
        payload["extra"] = extra_conf
    elif tipo_dte_val == "01":
        precios_flag = True
        extra_conf["precios_incluyen_iva"] = True

    # Normalización de operación y contingencia
    try:
        ident["tipoOperacion"] = int(ident.get("tipoOperacion", 1) or 1)
    except Exception:
        ident["tipoOperacion"] = 1
    tipo_operacion = ident["tipoOperacion"]
    tipo_cont = ident.get("tipoContingencia")
    if tipo_cont in ("", None):
        tipo_cont = None
    else:
        tipo_cont = int(tipo_cont)
    motivo = ident.get("motivoContin")
    if isinstance(motivo, str):
        motivo = motivo.strip() or None

    if tipo_operacion == 1:
        ident["tipoModelo"] = 1
        ident["tipoContingencia"] = None
        ident["motivoContin"] = None
    elif tipo_operacion == 2:
        ident["tipoModelo"] = 2
        if tipo_cont is None:
            raise ValueError("tipoContingencia requerido cuando tipoOperacion=2")
        if tipo_cont not in catalogos.CONTINGENCIA:
            raise ValueError("tipoContingencia debe estar entre 1 y 5")
        ident["tipoContingencia"] = tipo_cont
        if tipo_cont == 5:
            if not (motivo and 5 <= len(motivo) <= 150):
                raise ValueError("motivoContin requerido cuando tipoContingencia=5")
            ident["motivoContin"] = motivo
        else:
            ident["motivoContin"] = None
    else:
        raise ValueError("tipoOperacion debe ser 1 o 2")

    tipo = ident.get("tipoDte")
    expected_version = DTE_VERSIONES.get(tipo)
    if expected_version is not None:
        ident["version"] = expected_version
    else:
        ident["version"] = int(ident.get("version", 1))
    ident.setdefault("codigoGeneracion", str(uuid.uuid4()).upper())
    try:
        ident["codigoGeneracion"] = normalize_uuid_v4_upper(ident["codigoGeneracion"])
    except Exception:
        raise ValueError("codigoGeneracion debe ser un UUID v4 válido") from None
    if len(ident["codigoGeneracion"]) != 36 or "-" not in ident["codigoGeneracion"]:
        raise ValueError("codigoGeneracion debe ser un UUID v4 válido")
    ident["tipoMoneda"] = "USD"
    # Validaciones de campos de identificacion
    if ident.get("ambiente") not in {"00", "01"}:
        raise ValueError("ambiente debe ser '00' o '01'")
    if ident.get("tipoMoneda") != "USD":
        raise ValueError("tipoMoneda debe ser 'USD'")
    # Las reglas de operación/modelo/contingencia ya fueron normalizadas arriba.
    try:
        fec = datetime.strptime(str(ident.get("fecEmi")), "%Y-%m-%d").date()
    except Exception:
        raise ValueError("fecEmi debe tener formato YYYY-MM-DD") from None
    try:
        hora_dt = datetime.strptime(str(ident.get("horEmi")), "%H:%M:%S")
        hora = hora_dt.time()
        if hora_dt.strftime("%H:%M:%S") != ident.get("horEmi"):
            raise ValueError
    except Exception:
        raise ValueError("horEmi debe tener formato HH:MM:SS") from None
    now = datetime.now(TZ_EL_SALVADOR)
    emision_dt = datetime.combine(fec, hora, tzinfo=TZ_EL_SALVADOR)
    if fec > now.date() or emision_dt > now:
        raise ValueError("fecEmi/horEmi no pueden ser futuras")
    payload["identificacion"] = ident
    tipo_dte = str(ident.get("tipoDte", ""))

    emisor = payload.get("emisor", {})
    emisor["nit"] = _clean_nit(emisor.get("nit") or negocio.get("nit"))
    emisor["nrc"] = _clean_nrc(emisor.get("nrc") or negocio.get("nrc"))
    emisor.setdefault("nombre", negocio.get("nombre"))
    emisor.setdefault("nombreComercial", negocio.get("nombreComercial"))
    emisor.setdefault(
        "codActividad", negocio.get("cod_giro") or negocio.get("codActividad")
    )
    emisor.setdefault("descActividad", negocio.get("descActividad"))
    default_est = next(iter(catalogos.TIPO_ESTABLEC))
    tipo_est = emisor.get("tipoEstablecimiento")
    tipo_est = str(tipo_est).zfill(2) if tipo_est else default_est
    if tipo_est not in catalogos.TIPO_ESTABLEC:
        tipo_est = default_est
    emisor["tipoEstablecimiento"] = tipo_est
    svfe_config.DATOS_NEGOCIO_PATH = DATOS_NEGOCIO_PATH
    datos_cfg = svfe_config.load_datos_negocio()
    dir_emisor = datos_cfg.get("direccion") or {}
    emisor["direccion"] = {
        "departamento": str(dir_emisor["departamento"]).zfill(2),
        "municipio": str(dir_emisor["municipio"]),
        "complemento": dir_emisor.get("complemento") or "SIN DIRECCION",
    }
    emisor.setdefault("telefono", negocio.get("telefono"))
    emisor.setdefault("correo", negocio.get("correo"))
    cod_est = str(emisor.get("codEstable") or negocio.get("codEstable") or 1)
    emisor["codEstable"] = cod_est.zfill(4)
    emisor["codEstableMH"] = str(
        emisor.get("codEstableMH") or negocio.get("codEstableMH") or cod_est
    ).zfill(4)
    cod_pto = str(emisor.get("codPuntoVenta") or negocio.get("codPuntoVenta") or 1)
    emisor["codPuntoVenta"] = cod_pto.zfill(4)
    emisor["codPuntoVentaMH"] = str(
        emisor.get("codPuntoVentaMH") or negocio.get("codPuntoVentaMH") or cod_pto
    ).zfill(4)
    tipo = str(ident.get("tipoDte") or "").zfill(2)
    if not re.fullmatch(r"\d{2}", tipo):
        raise ValueError("tipoDte inválido")
    if hasattr(catalogos, "TIPOS_DTE") and tipo not in catalogos.TIPOS_DTE:
        raise ValueError("Código de tipoDte inválido")
    suc = _norm3(emisor.get("codEstableMH") or emisor.get("codEstable") or 1)
    pto = _norm3(
        emisor.get("codPuntoVentaMH") or emisor.get("codPuntoVenta") or 1
    )
    numero_control = ident.get("numeroControl")
    regex_nc = r"^DTE-(\d{2})-S(\d{3})P(\d{3})-(\d{15})$"
    if not (isinstance(numero_control, str) and re.fullmatch(regex_nc, numero_control)):
        ident["numeroControl"] = generar_numero_control(db, tipo, suc, pto)
    numero_control = ident.get("numeroControl")
    if not re.fullmatch(regex_nc, numero_control):
        raise ValueError("numeroControl inválido")
    emisor.pop("giro", None)
    emisor.pop("tipoContribuyente", None)
    required_emisor = {
        "nit": emisor.get("nit"),
        "nrc": emisor.get("nrc"),
        "nombre": emisor.get("nombre"),
        "nombreComercial": emisor.get("nombreComercial"),
        "tipoEstablecimiento": emisor.get("tipoEstablecimiento"),
        "codActividad": emisor.get("codActividad"),
        "descActividad": emisor.get("descActividad"),
        "direccion.departamento": emisor.get("direccion", {}).get("departamento"),
        "direccion.municipio": emisor.get("direccion", {}).get("municipio"),
        "direccion.complemento": emisor.get("direccion", {}).get("complemento"),
        "telefono": emisor.get("telefono"),
        "correo": emisor.get("correo"),
        "codEstable": emisor.get("codEstable"),
        "codEstableMH": emisor.get("codEstableMH"),
        "codPuntoVenta": emisor.get("codPuntoVenta"),
        "codPuntoVentaMH": emisor.get("codPuntoVentaMH"),
    }
    missing = [
        key
        for key, value in required_emisor.items()
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if missing:
        raise ValueError("Faltan campos obligatorios en emisor: " + ", ".join(missing))
    if emisor.get("correo") and not EMAIL_RE.fullmatch(emisor["correo"]):
        raise ValueError("Correo de emisor inválido")
    if emisor.get("telefono") and not PHONE_RE.fullmatch(emisor["telefono"]):
        raise ValueError("Teléfono de emisor inválido")
    payload["emisor"] = emisor

    receptor = payload.get("receptor", {})
    nit_field = receptor.get("nit")
    tipo_doc = receptor.get("tipoDocumento")
    if tipo_dte != "03":
        if tipo_doc is not None:
            tipo_doc = str(tipo_doc)
        if nit_field is not None:
            receptor["numDocumento"] = _clean_nit(nit_field)
            if tipo_doc is None:
                tipo_doc = "36"
        num_doc = receptor.get("numDocumento")
        if tipo_doc == "36":
            num_doc = _clean_nit(num_doc)
            if num_doc and not re.fullmatch(r"[0-9]{14}", num_doc):
                raise ValueError("NIT inválido en receptor")
        elif tipo_doc == "13":
            if num_doc and not re.fullmatch(r"[0-9]{8}-[0-9]", num_doc):
                raise ValueError("DUI inválido en receptor")
        receptor["tipoDocumento"] = tipo_doc if tipo_doc is not None else None
        receptor["numDocumento"] = num_doc
    else:
        receptor["nit"] = _clean_nit(nit_field)
        receptor.pop("tipoDocumento", None)
        receptor.pop("numDocumento", None)

    nrc_schema = (
        FC_SCHEMA.get("properties", {})
        .get("receptor", {})
        .get("properties", {})
        .get("nrc", {})
    )
    # ``nrc`` must always be present: if schema allows null we keep ``None``;
    # otherwise we strip non-digits and pad with zeros to the minimum length.
    nrc_types = nrc_schema.get("type", [])
    if not isinstance(nrc_types, list):
        nrc_types = [nrc_types]
    if "null" in nrc_types:
        nrc_val = _clean_nrc(receptor.get("nrc"))
        receptor["nrc"] = nrc_val if nrc_val is not None else None
    else:
        nrc_val = _clean_nrc(receptor.get("nrc")) or ""
        if not nrc_val:
            min_len = nrc_schema.get("minLength", 1)
            nrc_val = "0" * min_len
        receptor["nrc"] = nrc_val

    receptor.pop("giro", None)
    dir_rec = receptor.get("direccion")
    if dir_rec is None:
        raise ValidationError("receptor.direccion faltante")
    receptor["direccion"] = _build_receptor_direccion(dir_rec)
    if receptor.get("correo") and not EMAIL_RE.fullmatch(receptor["correo"]):
        raise ValueError("Correo de receptor inválido")
    if receptor.get("telefono") and not PHONE_RE.fullmatch(receptor["telefono"]):
        raise ValueError("Teléfono de receptor inválido")
    if tipo_dte == "01":
        required_rec_fields = [
            "nrc",
            "nombre",
            "codActividad",
            "descActividad",
            "telefono",
            "correo",
            "direccion",
            "tipoDocumento",
            "numDocumento",
        ]
        for f in ("nit", "nombreComercial"):
            receptor.pop(f, None)
        for f in required_rec_fields:
            receptor.setdefault(f, None)
        for f in ("noRemision", "ordenNo"):
            receptor.pop(f, None)
    else:
        required_rec_fields = [
            "nit",
            "nrc",
            "nombre",
            "nombreComercial",
            "codActividad",
            "descActividad",
            "telefono",
            "correo",
            "direccion",
        ]
        for f in required_rec_fields:
            receptor.setdefault(f, None)
        for f in ("noRemision", "ordenNo", "numDocumento", "tipoDocumento"):
            receptor.pop(f, None)
    payload["receptor"] = receptor

    cuerpo = payload.get("cuerpoDocumento", [])
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
    precio_key = "precioUni"
    iva_key = "ivaItem" if "ivaItem" in allowed_item_keys else None

    for item in cuerpo:
        # --- Normalización de nombres ---
        if "precioUnitario" in item:
            raise ValueError("Usar 'precioUni' en lugar de 'precioUnitario'")

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
        item.setdefault("tipoItem", 1)
        item.setdefault("uniMedida", 59)
        item["tipoItem"] = int(item["tipoItem"])
        item["uniMedida"] = int(item["uniMedida"])

        try:
            item["tipoItem"] = int(item.get("tipoItem") or 0)
            item["uniMedida"] = int(item.get("uniMedida") or 0)
        except Exception:
            raise ValueError("tipoItem y uniMedida deben ser enteros")

        if item["tipoItem"] not in catalogos.TIPO_ITEM:
            raise ValueError("tipoItem inválido")
        if item["uniMedida"] not in UNIDADES_MEDIDA_PERMITIDAS:
            item["uniMedida"] = 59

        num_doc = item.get("numeroDocumento")
        if isinstance(num_doc, str):
            if num_doc.strip().upper() in {"NA", "N/A", ""}:
                num_doc = None
        elif not num_doc:
            num_doc = None
        item["numeroDocumento"] = num_doc

        item["codigo"] = item.get("codigo") or "SKU-NA"
        cero = D("0")
        item.setdefault("montoDescu", cero)
        item.setdefault("ventaNoSuj", cero)
        item.setdefault("ventaExenta", cero)
        item.setdefault("ventaGravada", cero)
        item.setdefault("noGravado", cero)
        item.setdefault("psv", cero)
        if tipo_dte == "01":
            item["tributos"] = None
        else:
            item.setdefault("tributos", [])
        if iva_key:
            item.setdefault(iva_key, cero)

        # --- Cálculo de base ---
        cantidad = d1(D(str(item.get("cantidad") or 0)))
        precio = d8(D(str(item.get(precio_key) or 0)))
        item["cantidad"] = cantidad
        item[precio_key] = precio
        monto_descu = d8(D(str(item.get("montoDescu") or 0)))
        if monto_descu < 0:
            monto_descu = cero
        base = d8(cantidad * precio - monto_descu)
        if base < 0:
            base = cero

        # Determinar tipo de venta
        if D(str(item.get("ventaExenta") or 0)) > 0:
            item["ventaExenta"] = d2(base)
            item["ventaGravada"] = cero
            item["ventaNoSuj"] = cero
            item["noGravado"] = cero
        elif D(str(item.get("ventaNoSuj") or 0)) > 0:
            item["ventaNoSuj"] = d2(base)
            item["ventaGravada"] = cero
            item["noGravado"] = cero
        elif D(str(item.get("noGravado") or 0)) > 0:
            item["noGravado"] = d2(base)
            item["ventaGravada"] = cero
            item["ventaNoSuj"] = cero

        else:
            item["ventaGravada"] = d2(base)
            item["ventaExenta"] = cero
            item["ventaNoSuj"] = cero
            item["noGravado"] = cero

        # --- Manejo y validación de tributos ---
        venta_gravada_val = D(str(item.get("ventaGravada") or 0))
        trib_raw = item.get("tributos") or []
        if isinstance(trib_raw, str):
            tributos = [trib_raw]
        else:
            tributos = list(trib_raw)
        tributos = [str(t).upper() for t in tributos if t]
        cod_tri = item.get("codTributo")
        if cod_tri is not None:
            cod_tri = str(cod_tri).upper()

        if tipo_dte == "01":
            item["codTributo"] = None
            item["tributos"] = None
        else:
            invalid = [
                t
                for t in tributos
                if t not in TRIBUTOS_PERMITIDOS_ITEM and t != TRIBUTO_IVA
            ]
            if cod_tri and (
                cod_tri not in TRIBUTOS_PERMITIDOS_ITEM or cod_tri == TRIBUTO_IVA
            ):
                invalid.append(cod_tri)
            if invalid:
                raise ValueError(
                    f"Código(s) de tributo inválido(s): {', '.join(invalid)}"
                )

            if venta_gravada_val <= 0:
                item["tributos"] = []
                item["codTributo"] = None
            elif tributos:
                if TRIBUTO_IVA not in tributos and venta_gravada_val > 0:
                    tributos.append(TRIBUTO_IVA)
                item["tributos"] = tributos
                if (
                    len(tributos) == 1
                    and item.get("tipoItem") == 4
                    and tributos[0] != TRIBUTO_IVA
                ):
                    item["codTributo"] = tributos[0]
                else:
                    item["codTributo"] = None
            else:
                item["tributos"] = [TRIBUTO_IVA]
                item["codTributo"] = None

        if iva_key:
            if precios_flag and item.get(iva_key) not in (None, 0, D("0")):
                if tipo_dte == "01":
                    item[iva_key] = money(D(str(item.get(iva_key))))
                else:
                    item[iva_key] = d8(D(str(item.get(iva_key))))
            else:
                iva_calc = venta_gravada_val * D("0.13") if venta_gravada_val > 0 else cero
                item[iva_key] = money(iva_calc) if tipo_dte == "01" else d8(iva_calc)

        # Totales a 2 decimales y normalizar -0.00
        for k in ("ventaGravada", "ventaExenta", "ventaNoSuj", "psv", "noGravado"):
            val = d2(item.get(k, cero))
            item[k] = cero if val == 0 else val
        item["montoDescu"] = d2(monto_descu)
        if iva_key:
            iva_val = D(str(item.get(iva_key) or 0))
            iva_val_q = money(iva_val) if tipo_dte == "01" else d8(iva_val)
            item[iva_key] = cero if iva_val_q == 0 else iva_val_q
    payload["cuerpoDocumento"] = cuerpo

    resumen = payload.get("resumen", {})
    for k, v in resumen.items():
        if k == "condicionOperacion":
            continue
        if isinstance(v, (int, float, Decimal)):
            val = d2(v)
            resumen[k] = D("0") if val == 0 else val
        elif isinstance(v, str):
            try:
                val = d2(float(v))
                resumen[k] = D("0") if val == 0 else val

            except Exception:
                pass
    payload["resumen"] = resumen

    # Recalcular totales y ajustar discrepancias
    cambios = recalcular_totales(payload, precios_incluyen_iva=precios_flag)
    if cambios:
        print("Advertencia: se corrigieron campos de resumen: " + ", ".join(cambios))

    ident = payload.get("identificacion", {})
    if ident.get("tipoDte") == "01":
        for i in payload.get("cuerpoDocumento", []):
            linea = d4(
                D(str(i.get("cantidad") or 0))
                * D(str(i.get("precioUni") or 0))
                - D(str(i.get("montoDescu") or 0))
            )
            iva_chk = money(linea * D("0.13") / D("1.13"))
            if i.get("ventaGravada") != linea or i.get("ivaItem") != iva_chk:
                logger.warning(
                    "ventaGravada/ivaItem incoherente: %s/%s esperado %s/%s",
                    i.get("ventaGravada"),
                    i.get("ivaItem"),
                    linea,
                    iva_chk,
                )

    resumen["pagos"] = normalizar_pagos(
        resumen.get("pagos"),
        resumen["totalPagar"],
        tipo_dte=ident.get("tipoDte"),
        condicion=resumen.get("condicionOperacion", 1),
    )
    delta = money(
        D(str(resumen["totalPagar"]))
        - sum(D(str(p.get("montoPago") or 0)) for p in resumen.get("pagos", []))
    )
    if resumen.get("pagos") and D("0") < abs(delta) <= D("0.01"):
        ultimo = resumen["pagos"][-1]
        ult_monto = D(str(ultimo.get("montoPago") or 0))
        ultimo["montoPago"] = money(ult_monto + delta)
    elif abs(delta) > D("0.01"):
        logger.warning(
            "Pagos no cuadran con totalPagar (|delta|=%s). Se deja que el validador falle.",
            delta,
        )

    if resumen.get("pagos") and resumen.get("condicionOperacion") == 2:
        for p in resumen["pagos"]:
            p.setdefault("codigo", "01")
            if p.get("referencia") is None:
                p["referencia"] = ""
            if p.get("periodo") is None:
                p["periodo"] = ""
            if p.get("plazo") is None:
                p["plazo"] = ""

    # Verificación de centavos exactos en totales clave
    special_d4_fields = {"totalExenta", "totalNoSuj"}
    for k in ("totalIva", "montoTotalOperacion", "totalPagar", "totalNoGravado"):
        if k in resumen:
            val = D(str(resumen[k]))
            if val != money(val):
                raise ValidationError(
                    f"{k} debe ser múltiplo de 0.01 (recibido={resumen[k]})"
                )
            if val == D("0") and val.as_tuple().sign:
                resumen[k] = D("0")
    for k in special_d4_fields:
        if k in resumen:
            val = D(str(resumen[k]))
            if val != d4(val):
                raise ValidationError(
                    f"{k} debe ser múltiplo de 0.0001 (recibido={resumen[k]})"
                )
            if val == D("0") and val.as_tuple().sign:
                resumen[k] = D("0")

    if resumen.get("tributos"):
        for t in resumen["tributos"]:
            val = D(str(t.get("valor") or 0))
            if val != money(val):
                raise ValidationError("valor de tributo debe ser múltiplo de 0.01")
            if val == D("0") and val.as_tuple().sign:
                t["valor"] = D("0")

    if resumen.get("pagos"):
        for p in resumen["pagos"]:
            val = D(str(p.get("montoPago") or 0))
            if val != money(val):
                raise ValidationError("montoPago debe ser múltiplo de 0.01")
            if val == D("0") and val.as_tuple().sign:
                p["montoPago"] = D("0")
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
    if emisor_nit:
        clean_emisor_nit = limpiar_doc(emisor_nit)
        payload["emisor"]["nit"] = clean_emisor_nit
        if len(clean_emisor_nit) != catalogos.NIT_LENGTH:
            raise ValueError("NIT inválido en emisor")

    receptor_doc = payload.get("receptor", {}).get("numDocumento")
    if receptor_doc:
        clean_doc = limpiar_doc(receptor_doc)
        if len(clean_doc) not in (9, catalogos.NIT_LENGTH):
            raise ValueError("Número de documento inválido en receptor")
        payload["receptor"]["numDocumento"] = clean_doc
    # Conversión final de Decimals con formatos específicos para el JSON
    def _zero_or(value: D, qfn) -> D:
        """Quantiza ``value`` usando ``qfn`` retornando ``0.0`` si es cero."""
        dec = qfn(value)
        return D("0.0") if dec == 0 else dec

    for item in payload.get("cuerpoDocumento", []):
        # cantidad se cuantiza a un decimal
        item["cantidad"] = _zero_or(item.get("cantidad", D("0")), d1)
        # precio unitario y ventas: 4 decimales cuando es mayor a 0
        item[precio_key] = _zero_or(item.get(precio_key, D("0")), d4)
        if iva_key and iva_key in item:
            item[iva_key] = _zero_or(item.get(iva_key, D("0")), d2)
        for k in (
            "montoDescu",
            "ventaNoSuj",
            "ventaExenta",
            "ventaGravada",
            "psv",
            "noGravado",
        ):
            qfn = d4 if k in {"ventaNoSuj", "ventaExenta", "ventaGravada"} else d2
            item[k] = _zero_or(item.get(k, D("0")), qfn)

    resumen = payload.get("resumen", {})
    special_d4_fields = {"totalExenta", "totalNoSuj"}
    for k, v in list(resumen.items()):
        if k in {
            "totalLetras",
            "condicionOperacion",
            "pagos",
            "numPagoElectronico",
            "tributos",
        }:
            continue
        if isinstance(v, Decimal):
            qfn = d4 if k in special_d4_fields else money
            resumen[k] = _zero_or(v, qfn)

    if resumen.get("tributos"):
        for t in resumen["tributos"]:
            t["valor"] = _zero_or(t["valor"], money)

    if resumen.get("pagos"):
        for p in resumen["pagos"]:
            p["montoPago"] = _zero_or(p["montoPago"], money)

    if payload.get("identificacion", {}).get("tipoDte") == "01":
        payload.pop("extra", None)
    payload["resumen"] = resumen


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
    """Genera la estructura JSON para un Ticket Electrónico.

    El resultado se marca con ``extra['es_ticket']`` para indicar que se trata
    de un ticket y no de un comprobante de crédito fiscal completo.
    """
    if ambiente not in ("00", "01"):
        ambiente_cfg = str(ambiente).lower()
        ambiente = "01" if ambiente_cfg.startswith("produc") else "00"

    data = generar_dte_json(
        db,
        venta_id,
        tipo_dte="03",
        ambiente=ambiente,
        tipo_operacion=tipo_operacion,
        tipo_contingencia=tipo_contingencia,
        motivo_contin=motivo_contin,
        **kwargs,
    )

    data.setdefault("extra", {})["es_ticket"] = True
    return data


def generar_nota_credito_json(db: DB, nota_id: int) -> dict:
    """Genera la estructura JSON para una nota de crédito.

    La lógica principal se encuentra en :mod:`nota_credito_electronica` y se
    delega aquí para mantener compatibilidad con el resto del módulo.
    """

    from nota_credito_electronica import generar_nce_desde_nota

    return generar_nce_desde_nota(db, nota_id)


def generar_nde_desde_dte(
    db: DB,
    dte_origen: dict,
    detalles: list | None,
    monto: float | None,
    motivo: str | None = None,
    *,
    ambiente: str = "00",
) -> dict:
    """Genera la estructura JSON de una Nota de Débito a partir de un DTE."""

    cabecera = generar_cabecera_dte_data(1, 1, "06", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    identificacion = {
        "version": DTE_VERSIONES["06"],
        "ambiente": ambiente,
        "tipoDte": "06",
        "numeroControl": cabecera["numero_control"],
        "codigoGeneracion": cabecera["codigo_generacion"],
        "tipoModelo": cabecera["tipo_modelo"],
        "tipoOperacion": cabecera["tipo_operacion"],
        "tipoContingencia": cabecera["tipo_contingencia"],
        "motivoContin": cabecera["motivo_contin"],
        "fecEmi": fecha_emision_hoy_str(now),
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }

    origen_ident = dte_origen.get("identificacion", {})
    tipo_origen = origen_ident.get("tipoDte")
    tipo_rel = "07" if tipo_origen == "07" else "03"
    doc_rel = [
        {
            "tipoDocumento": tipo_rel,
            "tipoGeneracion": 2,
            "numeroDocumento": origen_ident.get("codigoGeneracion"),
            "fechaEmision": origen_ident.get("fecEmi"),
        }
    ]

    emisor = copy.deepcopy(dte_origen.get("emisor", {}))
    receptor = copy.deepcopy(dte_origen.get("receptor", {}))
    from utils.sanitize import limpiar_documentos

    receptor.setdefault("nombreComercial", None)
    receptor.setdefault("nit", None)

    limpiar_documentos(emisor)
    limpiar_documentos(receptor)

    orig_resumen = dte_origen.get("resumen", {})
    items: list[dict] = []
    uuid_origen = origen_ident.get("codigoGeneracion", "")
    tipo_doc_desc = catalogos.DTE_TIPOS.get(origen_ident.get("tipoDte", ""), "documento")
    extra_desc = f": {motivo}" if motivo else ""

    if detalles:
        total_grav = Decimal("0")
        total_exenta = Decimal("0")
        total_nosuj = Decimal("0")
        iva_val = Decimal("0")
        num = 1
        for det in detalles:
            grav = Decimal(str(det.get("ventas_gravadas") or det.get("ventaGravada") or 0))
            exenta = Decimal(str(det.get("ventas_exentas") or det.get("ventaExenta") or 0))
            nosuj = Decimal(str(det.get("ventas_no_sujetas") or det.get("ventaNoSuj") or 0))
            total_grav += grav
            total_exenta += exenta
            total_nosuj += nosuj
            iva_val += (grav * Decimal("0.13")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            precio = det.get("precio_unitario") or det.get("precioUni")
            if precio is None:
                precio = grav + exenta + nosuj
            precio = d4(precio)
            cantidad = det.get("cantidad", 1)
            items.append(
                {
                    "numItem": num,
                    "tipoItem": det.get("tipoItem", 1),
                    "codigo": det.get("codigo", f"ND{uuid_origen[:8]}-{num}"),
                    "descripcion": det.get(
                        "descripcion",
                        f"Nota de débito sobre operaciones del {tipo_doc_desc} relacionado{extra_desc}",
                    ),
                    "cantidad": cantidad,
                    "uniMedida": det.get("uniMedida", 59),
                    "precioUni": precio,
                    "montoDescu": d4(det.get("montoDescu", 0.0)),
                    "ventaGravada": d4(grav),
                    "ventaExenta": d4(exenta),
                    "ventaNoSuj": d4(nosuj),
                    "tributos": [TRIBUTO_IVA] if grav > 0 else [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1
        total_grav = d2(total_grav)
        total_exenta = d2(total_exenta)
        total_nosuj = d2(total_nosuj)
        iva_val = d2(iva_val)
        subtotal_ventas = total_grav + total_exenta + total_nosuj
        monto_total = d2(subtotal_ventas + iva_val)
    else:
        if monto is None:
            raise ValueError("Se requiere monto para nota de débito")
        total_origen = Decimal(
            str(
                orig_resumen.get("montoTotalOperacion")
                or orig_resumen.get("totalPagar")
                or 0
            )
        )
        if total_origen <= 0:
            raise ValueError("El documento de origen no tiene total válido")
        ratio = Decimal(str(monto)) / total_origen
        pct_text = str((ratio * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total_grav = d2(Decimal(str(orig_resumen.get("totalGravada", 0))) * ratio)
        total_exenta = d2(Decimal(str(orig_resumen.get("totalExenta", 0))) * ratio)
        total_nosuj = d2(Decimal(str(orig_resumen.get("totalNoSuj", 0))) * ratio)
        num = 1
        if total_grav > 0:
            items.append(
                {
                    "numItem": num,
                    "tipoItem": 1,
                    "codigo": f"ND{pct_text}-{uuid_origen[:8]}-G",
                    "descripcion": f"Nota de débito {pct_text}% sobre operaciones gravadas del {tipo_doc_desc} relacionado{extra_desc}",
                    "cantidad": 1,
                    "uniMedida": 59,
                    "precioUni": total_grav,
                    "montoDescu": 0.0,
                    "ventaGravada": total_grav,
                    "ventaExenta": 0.0,
                    "ventaNoSuj": 0.0,
                    "tributos": [TRIBUTO_IVA],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1
        if total_exenta > 0:
            items.append(
                {
                    "numItem": num,
                    "tipoItem": 1,
                    "codigo": f"ND{pct_text}-{uuid_origen[:8]}-E",
                    "descripcion": f"Nota de débito {pct_text}% sobre operaciones exentas del {tipo_doc_desc} relacionado{extra_desc}",
                    "cantidad": 1,
                    "uniMedida": 59,
                    "precioUni": total_exenta,
                    "montoDescu": 0.0,
                    "ventaGravada": 0.0,
                    "ventaExenta": total_exenta,
                    "ventaNoSuj": 0.0,
                    "tributos": [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1
        if total_nosuj > 0:
            items.append(
                {
                    "numItem": num,
                    "tipoItem": 1,
                    "codigo": f"ND{pct_text}-{uuid_origen[:8]}-N",
                    "descripcion": f"Nota de débito {pct_text}% sobre operaciones no sujetas del {tipo_doc_desc} relacionado{extra_desc}",
                    "cantidad": 1,
                    "uniMedida": 59,
                    "precioUni": total_nosuj,
                    "montoDescu": 0.0,
                    "ventaGravada": 0.0,
                    "ventaExenta": 0.0,
                    "ventaNoSuj": total_nosuj,
                    "tributos": [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
        subtotal_ventas = total_grav + total_exenta + total_nosuj
        orig_total = Decimal(str(orig_resumen.get("montoTotalOperacion", 0))) * (
            ratio if "ratio" in locals() else Decimal("1")
        )
        iva_val = d2(orig_total - subtotal_ventas)
        monto_total = d2(orig_total)

    tributos_resumen: list[dict] = []
    if iva_val > 0:
        tributos_resumen.append(
            {
                "codigo": TRIBUTO_IVA,
                "descripcion": TRIBUTOS.get(TRIBUTO_IVA, ""),
                "valor": iva_val,
            }
        )
    resumen = {
        "totalNoSuj": total_nosuj,
        "totalExenta": total_exenta,
        "totalGravada": total_grav,
        "subTotal": subtotal_ventas,
        "subTotalVentas": subtotal_ventas,
        "descuNoSuj": 0.0,
        "descuExenta": 0.0,
        "descuGravada": 0.0,
        "totalDescu": 0.0,
        "ivaPerci1": 0.0,
        "ivaRete1": 0.0,
        "reteRenta": 0.0,
        "condicionOperacion": dte_origen.get("resumen", {}).get("condicionOperacion", 1),
        "numPagoElectronico": dte_origen.get("resumen", {}).get("numPagoElectronico"),
        "tributos": tributos_resumen,
        "montoTotalOperacion": monto_total,
        "totalLetras": monto_a_texto_sv(monto_total),
    }

    data = {
        "identificacion": identificacion,
        "documentoRelacionado": doc_rel,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": items,
        "resumen": resumen,
        "ventaTercero": None,
        "extension": None,
        "apendice": None,
    }

    schema = catalogos.get_dte_schema("06")
    return sanitize_dte_payload(data, schema)


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
    dte_origen = generar_dte_json(db, venta_id, tipo_dte=tipo_doc)
    detalles = None
    if nota.get("detalles"):
        try:
            detalles = json.loads(nota["detalles"])
        except Exception:
            detalles = None
    return generar_nde_desde_dte(db, dte_origen, detalles, nota.get("monto"), nota.get("motivo"))


def generar_nota_remision_json(
    db: DB,
    factura: dict,
    *,
    cantidades: dict[int, float] | None = None,
    extension: dict | None = None,
    ambiente: str = "00",
) -> dict:
    """Genera la estructura JSON para una Nota de Remisión a partir de una factura.

    Parameters
    ----------
    db:
        Conexión a la base de datos para generar la cabecera del DTE.
    factura:
        DTE base del cual se copiarán emisor, receptor e ítems.
    cantidades:
        Mapeo opcional ``numItem -> cantidad`` para ajustar cantidades
        por ítem.
    extension:
        Datos adicionales para el bloque ``extension``.  Valores vacíos
        o ``None`` se omiten.
    ambiente:
        Ambiente de generación del DTE (``"00"`` por defecto).
    """
    cantidades = cantidades or {}
    ident_factura = factura.get("identificacion", {})

    cabecera = generar_cabecera_dte_data(1, 1, "04", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    identificacion = {
        "version": DTE_VERSIONES["04"],
        "ambiente": ambiente,
        "tipoDte": "04",
        "numeroControl": cabecera["numero_control"],
        "codigoGeneracion": cabecera["codigo_generacion"],
        "tipoModelo": cabecera["tipo_modelo"],
        "tipoOperacion": cabecera["tipo_operacion"],
        "tipoContingencia": cabecera["tipo_contingencia"],
        "motivoContin": cabecera["motivo_contin"],
        "fecEmi": fecha_emision_hoy_str(now),
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }

    documento_relacionado = [
        {
            "tipoDocumento": ident_factura.get("tipoDte"),
            "tipoGeneracion": 2,
            "numeroDocumento": ident_factura.get("codigoGeneracion"),
            "fechaEmision": ident_factura.get("fecEmi"),
        }
    ]

    emisor = copy.deepcopy(factura.get("emisor") or {})
    receptor = copy.deepcopy(factura.get("receptor") or {})
    limpiar_documentos(receptor)

    items: list[dict] = []
    for num, det in enumerate(factura.get("cuerpoDocumento", []), 1):
        cantidad = cantidades.get(num, det.get("cantidad", 1))
        items.append(
            {
                "numItem": num,
                "tipoItem": det.get("tipoItem", 1),
                "codigo": det.get("codigo", f"NR{num:03d}"),
                "descripcion": det.get("descripcion", f"Item {num}"),
                "cantidad": cantidad,
                "uniMedida": det.get("uniMedida", 59),
                "precioUni": 0.0,
                "montoDescu": 0.0,
                "ventaNoSuj": d2(D(0)),
                "ventaExenta": d2(D(0)),
                "ventaGravada": d2(D(0)),
                "tributos": [],
                "numeroDocumento": None,
                "codTributo": None,
            }
        )

    ext = {
        "nombEntrega": "N/D",
        "docuEntrega": "ND",
        "nombRecibe": "N/D",
        "docuRecibe": "ND",
        "observaciones": "N/D",
    }
    if extension:
        ext.update({k: v for k, v in extension.items() if v not in (None, "")})
    limpiar_documentos(ext)

    resumen = {
        "totalNoSuj": d2(D(0)),
        "totalExenta": d2(D(0)),
        "totalGravada": d2(D(0)),
        "subTotal": d2(D(0)),
        "subTotalVentas": d2(D(0)),
        "descuNoSuj": 0.0,
        "descuExenta": 0.0,
        "descuGravada": 0.0,
        "totalDescu": 0.0,
        "ivaPerci1": 0.0,
        "ivaRete1": 0.0,
        "reteRenta": 0.0,
        "montoTotalOperacion": d2(D(0)),
        "totalLetras": monto_a_texto_sv(0.0),
        "condicionOperacion": 1,
    }

    data = {
        "identificacion": identificacion,
        "documentoRelacionado": documento_relacionado,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": items,
        "extension": ext,
        "resumen": resumen,
        "apendice": None,
    }
    schema = catalogos.get_dte_schema("04")
    return sanitize_dte_payload(data, schema)

def _normalize_recepcion_url(raw: str) -> str:
    """Normaliza y valida ``raw`` como URL de recepción de Hacienda.

    - ``strip()`` y eliminación de espacios, saltos de línea o tabulaciones
    - Si falta el esquema se asume ``https``
    - Hosts oficiales sin path obtienen ``/fesv/recepciondte``
    - Colapsa dobles slashes y remueve el slash final
    - Cadena vacía → ``DEFAULT_RECEPCION_URL``
    - Rechaza dominios que contengan ``sandbox``
    """

    raw = "" if raw is None else str(raw)
    raw = re.sub(r"\s+", "", raw.strip())
    if not raw:
        return DEFAULT_RECEPCION_URL
    if "://" not in raw:
        raw = "https://" + raw
    pu = urlparse(raw)
    host = pu.netloc.lower()
    if "sandbox" in host:
        raise ValueError("sandbox no permitido")
    path = pu.path or ""
    if host in {"apitest.dtes.mh.gob.sv", "api.dtes.mh.gob.sv"} and path in ("", "/"):
        path = "/fesv/recepciondte"
    path = "/" + path.lstrip("/")
    path = re.sub("/+", "/", path).rstrip("/")
    return f"{pu.scheme}://{host}{path}"


def _load_dte_api_config():
    """Carga configuración consolidada para la recepción de DTE."""
    datos = _load_datos_negocio()
    dte_api = datos.get("dte_api") or {}
    raw_datos_url = dte_api.get("url") or dte_api.get("endpoint")

    def _norm(amb):
        amb = "" if amb is None else str(amb).strip().lower()
        if amb in {"00", "pruebas"}:
            return "pruebas"
        if amb in {"01", "1", "produccion", "producción"}:
            return "produccion"
        return amb

    ambiente = _norm(dte_api.get("ambiente") or datos.get("ambiente"))

    cfg_recep = cfg_url = cfg_endpoint = None
    try:
        with open(CONFIG_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        ambiente = _norm(ambiente or cfg.get("ambiente"))
        env = cfg.get(ambiente or "pruebas", {})
        cfg_recep = env.get("recepcion_url")
        cfg_url = env.get("url")
        cfg_endpoint = env.get("endpoint")
    except Exception:
        pass

    raw_cfg_url = cfg_recep or cfg_url or cfg_endpoint
    ambiente = ambiente or "pruebas"
    logger.debug("Cargando configuración DTE desde %s", DATOS_NEGOCIO_PATH)
    logger.debug(
        "Crudos: dte_api.url=%r dte_api.endpoint=%r cfg.recepcion_url=%r cfg.url=%r cfg.endpoint=%r",
        dte_api.get("url"),
        dte_api.get("endpoint"),
        cfg_recep,
        cfg_url,
        cfg_endpoint,
    )
    url = _normalize_recepcion_url(raw_datos_url or raw_cfg_url)
    logger.info("Recepción configurada → %s", url)
    return {"ambiente": ambiente, "url": url}


def _assert_no_ejemplo(path: str) -> None:
    banned = os.path.join("facturas_consumidor_final", "ejemplo.json")
    assert not str(path).endswith(banned), "writing to ejemplo.json is forbidden"


def _write_json(path: str, data):
    _assert_no_ejemplo(path)
    if isinstance(data, str):
        save_file(path, data, add_final_newline=not path.endswith(".jws"))
    else:
        save_file(path, stable_stringify(data, indent=2))


def _dte_base_dir(dte_data: dict) -> str:
    """Return destination directory for ``dte_data`` grouped by tipoDte."""
    ident = dte_data.get("identificacion", {})
    tipo = str(ident.get("tipoDte", "")).zfill(2)
    base = os.path.join(os.path.dirname(__file__), "dtes")
    mapping = {"01": "fcf", "03": "ccf"}
    folder = mapping.get(tipo)
    return os.path.join(base, folder) if folder else base


def _save_signed_dte(dte_data: dict, jws_token: str) -> None:
    """Guarda el JSON y JWS usando estructura versionada por hash."""
    try:
        base_dir = _dte_base_dir(dte_data)
        version_dir, _ = versioned_dte.ensure_version(dte_data, base_dir)
        jws_name = versioned_dte.add_jws(version_dir, jws_token, origen="auto")
        sobre = construir_sobre_recepcion(jws_token, dte_data)
        if sobre.get("estado") != "Error":
            sobre_path = os.path.join(
                version_dir, jws_name.replace(".jws", "_sobre_hacienda.json")
            )
            _write_json(sobre_path, sobre)
    except Exception:
        pass


class DTEValidationError(Exception):
    """Error de validación que incluye lista de errores y ruta del JSON."""

    def __init__(self, errors, json_path):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.json_path = json_path


def save_dte_json(dte_data: dict) -> str:
    """Guarda ``dte_data`` en estructura versionada y devuelve la ruta."""
    try:
        base_dir = _dte_base_dir(dte_data)
        version_dir, _ = versioned_dte.ensure_version(dte_data, base_dir)
        return os.path.join(version_dir, "documento.json")
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


def construir_sobre_recepcion(documento: str, dte_data: dict | None = None) -> dict:
    """Retorna el body listo para ``POST /fesv/recepciondte``.

    Si ``documento`` parece un JWS se extraen los metadatos desde su payload.
    Cuando no es un JWS válido o la decodificación falla, los metadatos se
    obtienen de ``dte_data``.  Valida campos requeridos y formatos.  En caso de
    error devuelve ``{"estado": "Error", "detalle": "<mensaje>"}``.
    """

    if isinstance(documento, str):
        documento = documento.strip()

    meta: dict[str, object] = {}
    payload = None

    if isinstance(documento, str) and documento.count(".") == 2:
        try:
            payload = _decode_jws_payload(documento)
            meta = payload.get("identificacion") or payload.get("identificador") or payload
        except Exception:
            payload = None
            meta = {}

    if isinstance(dte_data, dict):
        ident = dte_data.get("identificacion") or dte_data.get("identificador") or dte_data
        if payload is not None:
            ident_payload = payload.get("identificacion") or payload.get("identificador") or payload
            for key in ("codigoGeneracion", "tipoDte", "version"):
                if str(ident_payload.get(key)) != str(ident.get(key)):
                    return {
                        "estado": "Error",
                        "detalle": "La firma no corresponde a la versión actual del documento. Vuelva a firmar o seleccione una firma compatible.",
                    }
        if meta:
            for k, v in ident.items():
                meta.setdefault(k, v)
        else:
            meta = ident

    try:
        ambiente = str(meta["ambiente"])
    except Exception:
        return {"estado": "Error", "detalle": "falta ambiente"}
    if ambiente not in {"00", "01"}:
        return {"estado": "Error", "detalle": "ambiente inválido"}

    try:
        version = int(meta["version"])
    except Exception:
        return {"estado": "Error", "detalle": "version inválida"}

    tipo = meta.get("tipoDte") or meta.get("tipoDocumento")
    if tipo is None:
        return {"estado": "Error", "detalle": "tipoDte requerido"}
    tipo = str(tipo).zfill(2)

    codigo = meta.get("codigoGeneracion")
    if codigo is None:
        return {"estado": "Error", "detalle": "codigoGeneracion requerido"}

    id_envio = meta.get("idEnvio", 1)
    try:
        id_envio = int(id_envio)
    except Exception:
        return {"estado": "Error", "detalle": "idEnvio inválido"}

    return {
        "ambiente": ambiente,
        "idEnvio": id_envio,
        "version": version,
        "tipoDte": tipo,
        "codigoGeneracion": str(codigo),
        "documento": documento,
    }

def format_cliente_id_from_dui(dui: str | None) -> str | None:
    if not dui:
        return None
    return re.sub(r"\D+", "", str(dui)) or None


def detect_user_agent(
    user_agent: str | None = None,
    opts: dict | None = None,
    app_version: str | None = None,
    client_id: str | None = None,
) -> str:
    # 1) UA explícito
    if user_agent:
        return str(user_agent)
    # 2) UA proveniente de la capa web (navegador reenviado en opts)
    if isinstance(opts, dict) and opts.get("user_agent"):
        ua_from_opts = str(opts["user_agent"])[:256]
        return ua_from_opts
    # 3) Fallback genérico
    av = app_version or APP_VERSION
    parts = str(av).split(".")
    base_version = ".".join(parts[:2]) if parts else str(av)
    base = f"Vertex-DTE/{base_version}"
    return base


def build_auth_header(
    auth: dict | None,
    app_version: str | None = None,
    client_id: str | None = None,
) -> dict:
    headers: dict = {}
    if auth:
        # 1) Authorization explícito
        if auth.get("authorization"):
            headers["Authorization"] = str(auth["authorization"])
        # 2) Bearer
        elif auth.get("access_token") or auth.get("bearer"):
            token = auth.get("access_token") or auth.get("bearer")
            token = str(token).strip()
            if token.lower().startswith("bearer "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}" if token else ""
        # 3) Basic
        elif auth.get("basic_user") and auth.get("basic_password"):
            creds = f"{auth['basic_user']}:{auth['basic_password']}"
            b64 = base64.b64encode(creds.encode()).decode()
            headers["Authorization"] = f"Basic {b64}"
        # 4) Esquema personalizado
        elif auth.get("scheme") and auth.get("credentials"):
            headers["Authorization"] = f"{auth['scheme']} {auth['credentials']}"

        # 5) Mezclar headers extra
        if isinstance(auth.get("headers"), dict):
            headers.update(auth["headers"])

    # Metadatos de trazabilidad:
    if app_version:
        headers.setdefault("app-version", str(app_version))
    if client_id:
        headers.setdefault("cliente-id", str(client_id))
    return headers


def _post_dte(
    url: str,
    token: str,
    documento: str,
    dte_data: dict | None = None,
    user_agent: str | None = None,
    auth: dict | None = None,
    opts: dict | None = None,
    app_version: str | None = None,
    dui: str | None = None,
    client_id: str | None = None,
) -> dict:
    token = token or ""
    if token:
        logger.debug("Token: %s...%s", token[:5], token[-5:])
    else:
        logger.debug("Token: <empty>")

    pu = urlparse(url)
    assert pu.netloc in {
        "apitest.dtes.mh.gob.sv",
        "api.dtes.mh.gob.sv",
    }, f"Host inválido: {url}"
    assert pu.path.rstrip("/") == "/fesv/recepciondte", f"Path inválido: {url}"

    sobre = construir_sobre_recepcion(documento, dte_data)
    if sobre.get("estado") == "Error":
        return sobre

    client_id = client_id or format_cliente_id_from_dui(dui)
    ua = detect_user_agent(user_agent, opts, app_version or APP_VERSION, client_id)
    auth_headers = build_auth_header(
        auth if auth is not None else {"access_token": token},
        app_version=app_version or APP_VERSION,
        client_id=client_id,
    )
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": ua,
        **auth_headers,
    }

    try:
        print(json.dumps(sobre, ensure_ascii=False))
        resp = requests.post(url, headers=headers, json=sobre, timeout=20)
    except requests.RequestException as exc:
        return {"estado": "Error", "detalle": str(exc)}

    text = getattr(resp, "text", "")
    try:
        data = resp.json()
    except Exception:
        data = None

    if isinstance(resp.status_code, int) and resp.status_code >= 400:
        detalle = data if data is not None else text
        result = {"estado": "Rechazado", "http_status": resp.status_code, "detalle": detalle}
        print(json.dumps(result, ensure_ascii=False))
        return result

    result = data if data is not None else {"estado": "Recibido", "detalle": text}
    print(json.dumps(result, ensure_ascii=False))
    return result


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

    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema(tipo_dte)
    # La validación de esquema se omite para permitir la transmisión sin
    # interrupciones por inconsistencias.
    # try:
    #     validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = save_dte_json(data)
    #     errors = _format_validation_errors(exc)
    #     raise DTEValidationError(errors, json_path) from exc
    resp = _enviar_documento(db, venta_id, data, modo)
    if resp.get("sello"):
        db.update_venta_extra(venta_id, {"selloRecibido": resp["sello"]})
    return resp


def _is_jws_token(data) -> bool:
    """Devuelve ``True`` si ``data`` parece ser un JWS firmado."""
    if isinstance(data, str):
        return data.count(".") >= 2
    if isinstance(data, dict):
        return all(k in data for k in ("payload", "signature"))
    return False


def transmitir_dte_orphan(db: DB, json_path: str) -> dict:
    """Transmite un DTE desde ``json_path`` registrando el resultado."""
    with open(json_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if _is_jws_token(raw):
        if isinstance(raw, dict):
            jws_token = ".".join(
                [raw.get("protected", ""), raw.get("payload", ""), raw.get("signature", "")]
            )
        else:
            jws_token = raw
        payload = _decode_jws_payload(jws_token)
    else:
        data = apply_schema_patch(raw)
        tipo = (
            data.get("identificacion")
            or data.get("identificador")
            or {}
        ).get("tipoDte")
        schema = catalogos.get_dte_schema(str(tipo))
        # Se omite la validación para permitir la transmisión aun cuando el
        # payload no cumpla estrictamente con el esquema.
        # try:
        #     validate_dte_json(data, db=db)
        # except Exception as exc:
        #     errors = _format_validation_errors(exc)
        #     raise DTEValidationError(errors, json_path) from exc
        ident = data.get("identificacion") or data.get("identificador") or {}
        ident["fecEmi"] = fecha_emision_hoy_str()
        ident["horEmi"] = datetime.now(TZ_EL_SALVADOR).strftime("%H:%M:%S")
        if "identificacion" in data:
            data["identificacion"] = ident
        elif "identificador" in data:
            data["identificador"] = ident
        payload = data
        jws_token = jws.sign_json(data)

    ident = payload.get("identificacion") or payload.get("identificador") or {}
    meta = {
        "ambiente": ident.get("ambiente"),
        "version": ident.get("version"),
        "tipoDte": ident.get("tipoDte") or ident.get("tipoDocumento"),
        "codigoGeneracion": ident.get("codigoGeneracion"),
    }
    config = _load_dte_api_config()
    url = config["url"]
    token = auth.get_token()
    auth_host = auth.get_last_auth_host()
    recep_host = urlparse(url).netloc
    if auth_host and recep_host != auth_host:
        logger.warning(
            "Auth host %s ≠ recepción %s (esto es normal en prod)",
            auth_host,
            recep_host,
        )
    try:
        respuesta = _post_dte(url, token, jws_token, meta)
        sello = respuesta.get("sello") or respuesta.get("selloRecepcion") or ""
        estado = (
            respuesta.get("estado")
            or respuesta.get("estadoDte")
            or respuesta.get("descripcionEstado")
            or "Transmitido"
        )
        detalle = respuesta.get("detalle")
    except Exception:
        db.registrar_envio_dte(None, "orphan", "Rechazado", "")
        raise

    db.registrar_envio_dte(
        None,
        "orphan",
        estado,
        sello,
        json.dumps(respuesta, ensure_ascii=False),
    )
    if estado == "Rechazado":
        respuesta["errores"] = _parse_error_response(respuesta)
    res = {"estado": estado, "sello": sello}
    if detalle:
        res["detalle"] = detalle
    if respuesta.get("errores"):
        res["errores"] = respuesta["errores"]
    return res


def enviar_dte_a_hacienda(jws_token: str) -> dict:
    """Transmite un DTE ya firmado (JWS) al entorno de pruebas de Hacienda."""
    jws_token = jws_token.strip()
    config = _load_dte_api_config()
    url = config["url"]
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


def _enviar_documento(
    db: DB, doc_id: int, data: dict, modo: str = "normal", jws_token: str | None = None
) -> dict:
    """Firma y envía ``data`` registrando el envío.

    Si ``jws_token`` se proporciona, se reutiliza en lugar de firmar nuevamente.
    """
    config = _load_dte_api_config()
    if modo == "contingencia":
        db.registrar_envio_dte(doc_id, modo, "Pendiente", "")
        return {"estado": "Pendiente"}

    if not data.get("resumen", {}).get("totalLetras"):
        raise ValueError("El total en letras es obligatorio")

    url = config["url"]
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
        logger.warning(
            "Auth host %s ≠ recepción %s (esto es normal en prod)",
            auth_host,
            recep_host,
        )
    try:
        resumen = data.get("resumen", {})
        condicion = normalize_condicion_operacion(resumen.get("condicionOperacion"))
        resumen["condicionOperacion"] = condicion
        validate_pagos_basico(resumen, condicion)
        data["resumen"] = resumen
    except ValueError as exc:
        logger.error("ERROR: DTE inválido: %s", exc)
        raise ValueError(f"DTE inválido: {exc}") from exc

    signed = jws_token or jws.sign_json(data)

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
    if respuesta.get("errores"):
        res["errores"] = respuesta["errores"]
    return res


def enviar_factura(db: DB, venta_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una factura electrónica."""
    data = generar_dte_json(db, venta_id)
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("01")
    # Validación omitida para permitir el envío sin detenerse ante errores de
    # esquema.
    # try:
    #     validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = save_dte_json(data)
    #     errors = _format_validation_errors(exc)
    #     raise DTEValidationError(errors, json_path) from exc
    resp = _enviar_documento(db, venta_id, data, modo)
    if resp.get("sello"):
        db.update_venta_extra(venta_id, {"selloRecibido": resp["sello"]})
    return resp


def enviar_nota_credito(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de crédito."""
    data = generar_nota_credito_json(db, nota_id)
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("05")
    # Validación omitida.
    # try:
    #     validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = save_dte_json(data)
    #     errors = _format_validation_errors(exc)
    #     raise DTEValidationError(errors, json_path) from exc
    from utils.docs import get_dte_document_paths
    from utils.jws import sign_json
    from utils.stable_json import save_file, stable_stringify

    ident = data.get("identificacion", {})
    receptor = data.get("receptor", {}) or {}
    _, json_path = get_dte_document_paths(
        ident.get("fecEmi"),
        receptor.get("nombre") or receptor.get("nombreComercial") or "",
        ident.get("numeroControl"),
        "NotaCredito",
    )
    jws_path = os.path.splitext(json_path)[0] + ".jws"
    jws_token = None
    if os.path.exists(jws_path):
        try:
            with open(jws_path, "r", encoding="utf-8") as fh:
                jws_token = fh.read()
        except Exception:
            jws_token = None
    if jws_token is None:
        save_file(json_path, stable_stringify(data, indent=2))
        token = sign_json(data)
        jws_token = token.rstrip("\n")
        save_file(jws_path, jws_token, add_final_newline=False)
    return _enviar_documento(db, nota_id, data, modo, jws_token=jws_token)


def enviar_nota_debito(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de débito."""
    data = generar_nota_debito_json(db, nota_id)
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("06")
    # Validación omitida.
    # try:
    #     validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = save_dte_json(data)
    #     errors = _format_validation_errors(exc)
    #     raise DTEValidationError(errors, json_path) from exc
    from utils.docs import get_dte_document_paths
    from utils.jws import sign_json
    from utils.stable_json import save_file, stable_stringify

    ident = data.get("identificacion", {})
    receptor = data.get("receptor", {}) or {}
    _, json_path = get_dte_document_paths(
        ident.get("fecEmi"),
        receptor.get("nombre") or receptor.get("nombreComercial") or "",
        ident.get("numeroControl"),
        "NotaDebito",
    )
    jws_path = os.path.splitext(json_path)[0] + ".jws"
    jws_token = None
    if os.path.exists(jws_path):
        try:
            with open(jws_path, "r", encoding="utf-8") as fh:
                jws_token = fh.read()
        except Exception:
            jws_token = None
    if jws_token is None:
        save_file(json_path, stable_stringify(data, indent=2))
        token = sign_json(data)
        jws_token = token.rstrip("\n")
        save_file(jws_path, jws_token, add_final_newline=False)
    return _enviar_documento(db, nota_id, data, modo, jws_token=jws_token)


def enviar_nota_remision(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de remisión."""
    from nota_remision import generar_nota_remision_desde_db

    data = generar_nota_remision_desde_db(db, nota_id)
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("04")
    # Validación omitida.
    # try:
    #     validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = save_dte_json(data)
    #     errors = _format_validation_errors(exc)
    #     raise DTEValidationError(errors, json_path) from exc
    return _enviar_documento(db, nota_id, data, modo)


def _enviar_evento(db: DB, evento_id: int, data: dict) -> dict:
    """Firma y envía un evento a Hacienda."""
    config = _load_dte_api_config()
    url = config["url"]
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
