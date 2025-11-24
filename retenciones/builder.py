from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import uuid4

from db import DB
from dte import generar_cabecera_dte_data, resolve_ambiente
from utils.fecha import TZ_EL_SALVADOR, fecha_iso, normalizar_fecha_iso
from utils.jws import sign_json
from utils.monto import money, monto_a_texto_sv
from utils.stable_json import stable_stringify

from .catalogos_retencion import CatalogosRetencion

logger = logging.getLogger(__name__)

D = Decimal
DEFAULT_RATE = D("0.01")
CR_TIPO_DTE = "07"
_DTE_NUMCONTROL_PREFIX = "DTE-"
_CCF_NUMCONTROL_PATTERN = re.compile(r"^DTE-03-[A-Z0-9]{8}-[0-9]{15}$")


def build_cr_payload(
    factura: Mapping[str, Any],
    *,
    db: DB | None = None,
    catalogos: CatalogosRetencion | None = None,
    tasa: Decimal | str | float = DEFAULT_RATE,
    codigo_retencion: str = "22",
    base_sujeta_override: Decimal | str | float | None = None,
    ambiente: str | None = None,
    tipo_moneda: str = "USD",
    emisor_override: Mapping[str, Any] | None = None,
    receptor_override: Mapping[str, Any] | None = None,
    descripcion: str | None = None,
    fecha_emision: datetime | None = None,
    identificacion_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye el payload base del Comprobante de Retención."""

    if not isinstance(factura, Mapping):
        raise TypeError("El DTE origen debe ser un mapeo")

    catalogos = catalogos or CatalogosRetencion()
    rate = _to_decimal(tasa)
    if rate <= D("0"):
        raise ValueError("La tasa de retención debe ser mayor a 0")

    ident_origen = factura.get("identificacion") or {}
    tipo_rel = _normalize_tipo_dte(ident_origen.get("tipoDte"))
    if tipo_rel != "03":
        raise ValueError("CR-07 solo para DTE 03")
    catalogos.ensure("CAT-002", tipo_rel, field="documentoRelacionado.tipoDte")

    numero_doc_origen = _validate_numero_control_ccf(
        ident_origen.get("numeroControl"),
        "identificacion.numeroControl (origen)",
    )
    codigo_generacion_origen = _require_str(
        ident_origen.get("codigoGeneracion"),
        "identificacion.codigoGeneracion (origen)",
    )
    fecha_origen = _require_str(
        normalizar_fecha_iso(ident_origen.get("fecEmi")),
        "identificacion.fecEmi (origen)",
    )

    cuerpo_origen = factura.get("cuerpoDocumento") or []
    base_sujeta = (
        _calcular_base_gravada(cuerpo_origen)
        if base_sujeta_override is None
        else money(_to_decimal(base_sujeta_override))
    )
    if base_sujeta <= D("0"):
        raise ValueError("La base sujeta debe ser mayor a 0 para generar una retención")
    iva_retenido = money(base_sujeta * rate)
    if iva_retenido <= D("0"):
        raise ValueError("El IVA retenido debe ser mayor a 0")

    emisor = _normalize_emisor(_merge_party(factura.get("emisor"), emisor_override, "emisor"))
    receptor = _normalize_receptor(_merge_party(factura.get("receptor"), receptor_override, "receptor"))

    ident = _build_identificacion(
        db=db,
        ambiente=ambiente,
        tipo_moneda=tipo_moneda,
        override=identificacion_override,
        fecha_emision=fecha_emision,
    )

    catalogos.ensure("CAT-001", ident.get("ambiente"), field="identificacion.ambiente")
    catalogos.ensure("CAT-002", ident.get("tipoDte"), field="identificacion.tipoDte")
    catalogos.ensure("CAT-003", str(ident.get("tipoModelo")), field="identificacion.tipoModelo")
    catalogos.ensure("CAT-004", str(ident.get("tipoOperacion")), field="identificacion.tipoOperacion")

    codigo_retencion_mh = catalogos.ensure(
        "CAT-006",
        str(codigo_retencion).strip().upper(),
        field="cuerpoDocumento[0].codigoRetencionMH",
    )
    if not codigo_retencion_mh:
        raise ValueError("codigoRetencionMH requerido para retención")

    descripcion_item = descripcion or f"Retención IVA {rate * 100:.2f}% del documento {numero_doc_origen}"
    descripcion_item = descripcion_item[:1000]

    tipo_doc_rel = 2  # Para CCF usar siempre número de control como referencia
    num_documento_rel = _validate_numero_control_ccf(numero_doc_origen, "cuerpoDocumento[0].numDocumento")

    documento_relacionado = {
        "numItem": 1,
        "tipoDte": tipo_rel,
        "tipoDoc": tipo_doc_rel,
        "numDocumento": num_documento_rel,
        "fechaEmision": fecha_iso(fecha_origen),
        "montoSujetoGrav": base_sujeta,
        "codigoRetencionMH": codigo_retencion_mh,
        "ivaRetenido": iva_retenido,
        "descripcion": descripcion_item,
    }
    _ensure_referencia_requerida(documento_relacionado, catalogos)

    cuerpo_lista = [documento_relacionado]
    resumen = _recalcular_resumen(cuerpo_lista)

    payload = {
        "identificacion": ident,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": cuerpo_lista,
        "resumen": resumen,
        "extension": {
            "nombEntrega": None,
            "docuEntrega": None,
            "nombRecibe": None,
            "docuRecibe": None,
            "observaciones": None,
        },
        "apendice": None,
    }

    logger.info(
        "CR.BUILD codigoGeneracion=%s codigoGeneracionOrigen=%s base=%.2f retenido=%.2f rate=%.4f",
        ident.get("codigoGeneracion"),
        codigo_generacion_origen,
        float(base_sujeta),
        float(iva_retenido),
        float(rate),
    )

    return payload


def serialize_cr(payload: Mapping[str, Any], *, indent: int | None = 2) -> str:
    """Serialize the payload using the canonical stable JSON helper."""

    return stable_stringify(payload, indent=indent)


def sign_cr(payload: Mapping[str, Any] | str, **sign_kwargs: Any) -> str:
    """Firmar el CR reusando el pipeline existente."""
    return sign_json(payload, **sign_kwargs)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _build_identificacion(
    *,
    db: DB | None,
    ambiente: str | None,
    tipo_moneda: str,
    override: Mapping[str, Any] | None,
    fecha_emision: datetime | None,
) -> dict[str, Any]:
    now = (fecha_emision or datetime.now(TZ_EL_SALVADOR)).astimezone(TZ_EL_SALVADOR)
    ident = dict(override or {})
    resolved_env = resolve_ambiente(ambiente or ident.get("ambiente"))

    if db is not None and ("numeroControl" not in ident or "codigoGeneracion" not in ident):
        cabecera = generar_cabecera_dte_data(1, 1, CR_TIPO_DTE, db, ambiente=resolved_env)
        ident.setdefault("numeroControl", cabecera["numero_control"])
        ident.setdefault("codigoGeneracion", cabecera["codigo_generacion"].upper())
        resolved_env = cabecera.get("ambiente", resolved_env)

    ident.setdefault("numeroControl", _fallback_numero_control())
    ident.setdefault("codigoGeneracion", str(uuid4()).upper())

    ident.update(
        {
            "version": 1,
            "ambiente": resolved_env,
            "tipoDte": CR_TIPO_DTE,
            "tipoModelo": 1,
            "tipoOperacion": 1,
            "tipoContingencia": None,
            "motivoContin": None,
            "fecEmi": now.date().isoformat(),
            "horEmi": now.strftime("%H:%M:%S"),
            "tipoMoneda": tipo_moneda,
        }
    )
    return ident


def _merge_party(
    base: Mapping[str, Any] | None,
    override: Mapping[str, Any] | None,
    label: str,
) -> dict[str, Any]:
    if base is None and override is None:
        raise ValueError(f"No se encontró el bloque '{label}' en el DTE origen")
    merged = dict(base or {})
    if override:
        merged.update(override)
    return merged


def _normalize_emisor(data: Mapping[str, Any] | None) -> dict[str, Any]:
    src = dict(data or {})
    nombre = src.get("nombre")
    nombre_comercial = src.get("nombreComercial") or nombre
    direccion = src.get("direccion") if isinstance(src.get("direccion"), Mapping) else {}

    def _norm_code(value: Any, default: str | None = None) -> str | None:
        text = str(value or "").strip()
        if not text and default is not None:
            text = str(default).strip()
        if not text:
            return None
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            text = digits
        return text.zfill(4) if text.isdigit() else text

    codigo_mh = (
        _norm_code(src.get("codigoMH"))
        or _norm_code(src.get("codEstableMH"))
    )
    codigo = _norm_code(src.get("codigo") or src.get("codEstable") or codigo_mh)
    punto_mh = (
        _norm_code(src.get("puntoVentaMH"))
        or _norm_code(src.get("codPuntoVentaMH"))
    )
    punto = (
        _norm_code(src.get("puntoVenta") or src.get("codPuntoVenta") or punto_mh)
    )

    if not codigo_mh and not codigo:
        codigo_mh = _norm_code(None, "0001")
        codigo = codigo_mh
    if codigo_mh and not codigo:
        codigo = codigo_mh
    if codigo and not codigo_mh:
        codigo_mh = codigo
    if not punto_mh and not punto:
        punto_mh = _norm_code(None, "0001")
        punto = punto_mh
    if punto_mh and not punto:
        punto = punto_mh
    if punto and not punto_mh:
        punto_mh = punto

    allowed = {
        "nit": src.get("nit"),
        "nrc": src.get("nrc"),
        "nombre": nombre,
        "codActividad": src.get("codActividad"),
        "descActividad": src.get("descActividad"),
        "nombreComercial": nombre_comercial,
        "tipoEstablecimiento": src.get("tipoEstablecimiento"),
        "direccion": direccion,
        "telefono": src.get("telefono"),
        "codigoMH": codigo_mh,
        "codigo": codigo,
        "puntoVentaMH": punto_mh,
        "puntoVenta": punto,
        "correo": src.get("correo"),
    }
    return {k: v for k, v in allowed.items() if v not in (None, "")}


def _normalize_receptor(data: Mapping[str, Any] | None) -> dict[str, Any]:
    src = dict(data or {})
    nombre = src.get("nombre")
    nombre_comercial = src.get("nombreComercial") or nombre
    direccion = src.get("direccion") if isinstance(src.get("direccion"), Mapping) else {}
    nrc = src.get("nrc")
    if nrc in (None, ""):
        raise ValueError("receptor.nrc requerido para CR")
    num_doc = src.get("numDocumento") or src.get("dui") or src.get("nit")
    if num_doc in (None, ""):
        raise ValueError("receptor.numDocumento requerido para CR")
    tipo_doc = src.get("tipoDocumento") or src.get("tipo_documento")
    if tipo_doc in (None, ""):
        # Derivar tipoDocumento cuando no se proporcionó explícitamente
        if src.get("nit"):
            tipo_doc = "36"  # NIT
        elif src.get("dui") or (isinstance(num_doc, str) and len(num_doc.replace("-", "")) == 9):
            tipo_doc = "13"  # DUI
    if tipo_doc in (None, ""):
        raise ValueError("receptor.tipoDocumento requerido para CR")
    allowed = {
        "tipoDocumento": tipo_doc,
        "numDocumento": num_doc,
        "nrc": nrc,
        "nombre": nombre,
        "codActividad": src.get("codActividad"),
        "descActividad": src.get("descActividad"),
        "nombreComercial": nombre_comercial,
        "direccion": direccion,
        "telefono": src.get("telefono"),
        "correo": src.get("correo"),
    }
    _ensure_receptor_required(allowed)
    filtered = {k: v for k, v in allowed.items() if v not in (None, "")}
    for key in ("codActividad", "descActividad", "telefono"):
        filtered[key] = allowed[key]
    return filtered


def _to_decimal(value: Decimal | str | float | int) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalize_tipo_dte(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return f"{int(text):02d}"
    return text


def _calcular_base_gravada(items: Any) -> Decimal:
    total = D("0")
    if not isinstance(items, list):
        return total
    for item in items:
        if not isinstance(item, Mapping):
            continue
        for key in ("ventaGravada", "ventas_gravadas", "ventaGrav", "ventasGravadas"):
            if key in item and item[key] not in (None, ""):
                total += _to_decimal(item[key])
                break
    return money(total)


def _fallback_numero_control() -> str:
    random_block = uuid4().hex[:8].upper()
    sequential = f"{int(datetime.now().timestamp() * 1_000):015d}"
    return f"DTE-{CR_TIPO_DTE}-{random_block}-{sequential}"


def _require_str(value: Any, field: str) -> str:
    if value in (None, ""):
        raise ValueError(f"Campo obligatorio ausente: {field}")
    text = str(value).strip()
    if not text:
        raise ValueError(f"Campo obligatorio vacío: {field}")
    return text


def _resolve_referencia_origen(
    tipo_rel: str,
    numero_control: str,
    codigo_generacion: str,
    catalogos: CatalogosRetencion,
) -> tuple[int, str]:
    """Parear tipoDoc/numDocumento sin mezclar GUID con número de control."""

    numero_control = _require_str(numero_control, "identificacion.numeroControl (origen)")
    codigo_generacion = _require_str(codigo_generacion, "identificacion.codigoGeneracion (origen)")

    use_num_control = numero_control.upper().startswith(_DTE_NUMCONTROL_PREFIX)
    if use_num_control:
        tipo_doc = 2
        num_doc = numero_control
    else:
        tipo_doc = 3
        num_doc = codigo_generacion.upper()

    allowed_catalog = {code.strip() for code in catalogos.allowed_values("CAT-007").keys()}
    allowed = {code for code in allowed_catalog if code and code[0].isdigit()}
    allowed.update({"2", "3"})  # asegurar pareo permitido
    if str(tipo_doc) not in allowed:
        raise ValueError(f"cuerpoDocumento[0].tipoDoc '{tipo_doc}' fuera de catálogo permitido {sorted(allowed)}")
    if tipo_doc == 3 and num_doc.upper().startswith(_DTE_NUMCONTROL_PREFIX):
        raise ValueError("tipoDoc=3 no puede usar numDocumento con formato de numeroControl")
    return tipo_doc, num_doc


def _recalcular_resumen(cuerpo: list[Mapping[str, Any]]) -> dict[str, Any]:
    base_sum = money(
        sum(
            _to_decimal(item.get("montoSujetoGrav", 0))
            for item in cuerpo
            if isinstance(item, Mapping)
        )
    )
    ivaretenido_sum = money(
        sum(
            _to_decimal(item.get("ivaRetenido", 0))
            for item in cuerpo
            if isinstance(item, Mapping)
        )
    )
    return {
        "totalSujetoRetencion": base_sum,
        "totalIVAretenido": ivaretenido_sum,
        "totalIVAretenidoLetras": monto_a_texto_sv(ivaretenido_sum),
    }


def _ensure_receptor_required(values: Mapping[str, Any]) -> None:
    for field in ("codActividad", "descActividad", "telefono", "nrc", "tipoDocumento", "numDocumento"):
        if values.get(field) in (None, ""):
            raise ValueError(f"receptor.{field} requerido para CR")


def _ensure_referencia_requerida(item: Mapping[str, Any], catalogos: CatalogosRetencion) -> None:
    if item.get("codigoRetencionMH") in (None, ""):
        raise ValueError("cuerpoDocumento[0].codigoRetencionMH requerido para CR")
    catalogos.ensure("CAT-006", item.get("codigoRetencionMH"), field="cuerpoDocumento[0].codigoRetencionMH")
    if item.get("numDocumento") in (None, ""):
        raise ValueError("cuerpoDocumento[0].numDocumento requerido para CR")
    tipo_doc = item.get("tipoDoc")
    if str(tipo_doc) != "2":
        raise ValueError(f"cuerpoDocumento[0].tipoDoc inválido: {tipo_doc} (esperado 2)")


def _validate_numero_control_ccf(value: Any, field: str) -> str:
    numero = _require_str(value, field).upper()
    if not _CCF_NUMCONTROL_PATTERN.match(numero):
        raise ValueError(f"{field} inválido, se esperaba formato DTE-03-XXXXXXXX-XXXXXXXXXXXXXXX")
    return numero


__all__ = ["build_cr_payload", "serialize_cr", "sign_cr"]
