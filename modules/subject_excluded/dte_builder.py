from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import dte
from utils.monto import d2, monto_a_texto_sv

# Patrón simple reutilizado en FE/CCF para validar correos y teléfonos
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\d{8}$")

def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _get_vendor(db, vendedor_id: int | None) -> dict:
    if vendedor_id is None:
        return {}
    try:
        for vend in db.get_vendedores():
            if vend.get("id") == vendedor_id:
                return vend
    except Exception:
        pass
    try:
        row = db.cursor.execute("SELECT * FROM vendedores WHERE id=?", (vendedor_id,)).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


def _get_product(db, producto_id: int | None) -> dict:
    if producto_id is None:
        return {}
    try:
        for prod in db.get_productos():
            if prod.get("id") == producto_id:
                return prod
    except Exception:
        pass
    try:
        row = db.cursor.execute("SELECT * FROM productos WHERE id=?", (producto_id,)).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


def _build_identificacion(
    db,
    compra: dict,
    *,
    ambiente: str = "00",
    modo_contingencia: bool = False,
    tipo_contingencia: int | None = None,
    motivo_contingencia: str | None = None,
) -> tuple[dict, int]:
    datos_negocio = dte._load_datos_negocio() or {}
    prefijo = datos_negocio.get("dte_api", {}).get("prefijo_control", "")
    sucursal = "001"
    punto = "001"
    if isinstance(prefijo, str):
        try:
            import re

            m = re.search(r"S([A-Za-z0-9]{3})P([A-Za-z0-9]{3})", prefijo)
            if m:
                sucursal = m.group(1).zfill(3)
                punto = m.group(2).zfill(3)
        except Exception:
            pass

    numero_control, correlativo = dte.generar_numero_control(db, "14", sucursal, punto)
    now = datetime.now()
    fecha_emision = compra.get("fecha") or now.strftime("%Y-%m-%d %H:%M:%S")
    try:
        dt_emision = datetime.strptime(fecha_emision, "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            dt_emision = datetime.strptime(fecha_emision, "%Y-%m-%d")
        except Exception:
            dt_emision = now

    tipo_modelo = 2 if modo_contingencia else 1
    tipo_cont = tipo_contingencia if modo_contingencia else None
    motivo_cont = motivo_contingencia if modo_contingencia else None

    if modo_contingencia:
        try:
            tipo_cont_int = int(tipo_cont) if tipo_cont is not None else None
        except Exception:
            tipo_cont_int = None
        if tipo_cont_int is None:
            raise ValueError("tipoContingencia requerido en modo contingencia para FSE")
        if not 1 <= tipo_cont_int <= 5:
            raise ValueError("tipoContingencia debe estar entre 1 y 5 para FSE en contingencia")
        tipo_cont = tipo_cont_int
        if tipo_cont == 5:
            if not isinstance(motivo_contingencia, str) or not motivo_contingencia.strip():
                raise ValueError("motivoContin requerido cuando tipoContingencia=5")
            motivo_cont = motivo_contingencia.strip()
        else:
            motivo_cont = None

    identificacion = {
        "version": 1,
        "ambiente": datos_negocio.get("ambiente", ambiente) or ambiente,
        "tipoDte": "14",
        "numeroControl": numero_control,
        "codigoGeneracion": str(uuid.uuid4()).upper(),
        "tipoModelo": tipo_modelo,
        "tipoOperacion": 2 if modo_contingencia else 1,
        "tipoContingencia": tipo_cont,
        "motivoContin": motivo_cont,
        "fecEmi": dt_emision.strftime("%Y-%m-%d"),
        "horEmi": dt_emision.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }
    return identificacion, correlativo


def _build_emisor(datos_negocio: dict) -> dict:
    direccion_cfg = datos_negocio.get("direccion") or {}
    return {
        "nit": datos_negocio.get("nit", "") or "",
        "nrc": datos_negocio.get("nrc", "") or "",
        "nombre": datos_negocio.get("razonSocial") or datos_negocio.get("nombre") or "",
        "codActividad": datos_negocio.get("codActividad") or datos_negocio.get("cod_giro"),
        "descActividad": datos_negocio.get("descActividad") or datos_negocio.get("desc_giro"),
        "direccion": {
            "departamento": direccion_cfg.get("departamento"),
            "municipio": direccion_cfg.get("municipio"),
            "complemento": direccion_cfg.get("complemento"),
        },
        "telefono": datos_negocio.get("telefono"),
        "correo": datos_negocio.get("correo"),
        "codEstableMH": datos_negocio.get("codEstableMH"),
        "codEstable": datos_negocio.get("codEstable"),
        "codPuntoVentaMH": datos_negocio.get("codPuntoVentaMH"),
        "codPuntoVenta": datos_negocio.get("codPuntoVenta"),
    }


def _clean_doc(value: Any) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9A-Za-z]", "", str(value))
    return cleaned or None


def _normalize_phone(phone: Any, fallback: str | None = None) -> str | None:
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) >= 8:
        digits = digits[-8:]
    if not digits and fallback:
        digits = re.sub(r"\D", "", str(fallback))
        digits = digits[-8:] if digits else ""
    if not digits:
        digits = "00000000"
    return digits if PHONE_RE.fullmatch(digits) else None


def _normalize_email(email: Any, fallback: str | None = None) -> str:
    for candidate in (email, fallback, "noreply@example.com"):
        if not candidate:
            continue
        text = str(candidate).strip()
        if EMAIL_RE.fullmatch(text):
            return text
    return "noreply@example.com"


def _build_receptor(vendedor: dict, datos_negocio: dict) -> dict:
    """Construye sujetoExcluido asegurando campos obligatorios con fallbacks."""

    direccion = vendedor.get("direccion") if isinstance(vendedor.get("direccion"), dict) else {}
    emisor_dir = datos_negocio.get("direccion") or {}

    def _clean_digits(value: Any) -> str | None:
        cleaned = _clean_doc(value)
        return "".join(ch for ch in cleaned or "" if ch.isdigit())

    nit_raw = _clean_digits(vendedor.get("nit"))
    dui_raw = _clean_digits(vendedor.get("dui"))

    tipo_doc = None
    num_doc = None
    if nit_raw and len(nit_raw) in (9, 14):
        tipo_doc = "36"
        num_doc = nit_raw
    elif dui_raw and len(dui_raw) == 9:
        tipo_doc = "13"
        num_doc = dui_raw
    else:
        raise ValueError("Proveedor sujeto excluido sin NIT/DUI válido para FSE")

    # Actividad económica: si no existe en proveedor, copia la del emisor
    cod_actividad = vendedor.get("codActividad") or vendedor.get("cod_giro") or datos_negocio.get("codActividad")
    desc_actividad = vendedor.get("descActividad") or vendedor.get("desc_giro") or datos_negocio.get("descActividad")
    if not cod_actividad:
        cod_actividad = datos_negocio.get("codActividad") or "00000"
    if not desc_actividad:
        desc_actividad = datos_negocio.get("descActividad") or "GIRO NO REGISTRADO"

    dep = direccion.get("departamento") or emisor_dir.get("departamento") or "06"
    muni = direccion.get("municipio") or emisor_dir.get("municipio") or "23"
    complemento = (
        direccion.get("complemento")
        or vendedor.get("direccion")
        or emisor_dir.get("complemento")
        or "SIN DIRECCION REGISTRADA"
    )

    telefono = _normalize_phone(vendedor.get("telefono") or vendedor.get("celular"), datos_negocio.get("telefono"))
    correo = _normalize_email(vendedor.get("email"), datos_negocio.get("correo"))

    return {
        "tipoDocumento": str(tipo_doc).zfill(2) if tipo_doc else "36",
        "numDocumento": num_doc or "",
        "nombre": vendedor.get("nombre") or vendedor.get("razon_social") or "PROVEEDOR SIN NOMBRE",
        "codActividad": cod_actividad,
        "descActividad": desc_actividad,
        "direccion": {
            "departamento": str(dep).zfill(2),
            "municipio": str(muni).zfill(2),
            "complemento": complemento,
        },
        "telefono": telefono or "00000000",
        "correo": correo,
    }


def _compute_detalles(db, compra: dict, detalles: list[dict]) -> tuple[list[dict], dict]:
    cuerpo = []
    total_compra = Decimal("0")
    total_desc = Decimal("0")

    if not detalles:
        # Fallback: usa la cabecera si no hay partidas desglosadas
        detalles = [
            {
                "producto_id": compra.get("producto_id"),
                "cantidad": compra.get("cantidad") or 1,
                "precio_unitario": compra.get("precio_unitario") or compra.get("total") or 0,
                "descripcion": compra.get("descripcion") or compra.get("detalle") or "",
            }
        ]

    for idx, det in enumerate(detalles, start=1):
        prod = _get_product(db, det.get("producto_id"))
        qty = _decimal(det.get("cantidad"))
        precio = _decimal(det.get("precio_unitario") or det.get("precio") or det.get("precio_unitario_ref"))
        subtotal = qty * precio
        descuento_valor = _decimal(det.get("descuento"))
        descuento_tipo = (det.get("descuento_tipo") or "%").strip()
        if descuento_tipo == "%":
            descuento_monto = subtotal * (descuento_valor / Decimal("100"))
        else:
            descuento_monto = descuento_valor
        descuento_monto = max(descuento_monto, Decimal("0"))
        total_desc += descuento_monto
        compra_neta = subtotal - descuento_monto
        total_compra += compra_neta
        desc = (det.get("descripcion") or prod.get("nombre") or "").strip()
        if len(desc) < 3:
            desc = "COMPRA SUJETO EXCLUIDO"
        cuerpo.append(
            {
                "numItem": idx,
                "tipoItem": det.get("tipo_item") or prod.get("tipo_item") or 1,
                "codigo": prod.get("codigo"),
                "descripcion": desc,
                "cantidad": float(d2(qty)),
                "uniMedida": det.get("unidad_medida") or prod.get("unidad_medida") or prod.get("uniMedida") or 59,
                "precioUni": float(d2(precio)),
                "montoDescu": float(d2(descuento_monto)),
                "compra": float(d2(compra_neta)),
            }
        )
    resumen = {
        "total_compra": total_compra,
        "total_descuento": total_desc,
    }
    return cuerpo, resumen


def _build_resumen(resumen_vals: dict, condicion_operacion: int, pagos: list[dict]) -> tuple[dict, Decimal]:
    total_compra = resumen_vals.get("total_compra", Decimal("0"))
    total_desc = resumen_vals.get("total_descuento", Decimal("0"))
    sub_total = total_compra - total_desc
    iva_retenido = Decimal("0")
    renta_retenida = Decimal("0")
    total_pagar = sub_total - iva_retenido - renta_retenida
    if total_pagar < Decimal("0"):
        total_pagar = Decimal("0")
    resumen = {
        "totalCompra": float(d2(total_compra)),
        "descu": float(d2(total_desc)),
        "totalDescu": float(d2(total_desc)),
        "subTotal": float(d2(sub_total)),
        "ivaRete1": float(d2(iva_retenido)),
        "reteRenta": float(d2(renta_retenida)),
        "totalPagar": float(d2(total_pagar)),
        "totalLetras": monto_a_texto_sv(float(d2(total_pagar))),
        "condicionOperacion": condicion_operacion,
        "pagos": pagos,
        "observaciones": "",
    }
    return resumen, total_pagar


def _build_pagos(condicion_operacion: int, monto_total: Decimal) -> list[dict]:
    if condicion_operacion == 2:
        # Crédito: requiere plazo y periodo según catálogo (placeholder)
        return [
            {
                "codigo": "99",  # TODO: validar contra catálogo de formas de pago actualizado
                "montoPago": float(d2(monto_total)),
                "referencia": "",
                "plazo": "01",
                "periodo": 30,
            }
        ]
    return [
        {
            "codigo": "01",  # TODO: validar contra catálogo de formas de pago actualizado
            "montoPago": float(d2(monto_total)),
            "referencia": "",
            "plazo": None,
            "periodo": None,
        }
    ]


def build_fse_from_compra(
    db,
    compra_id: int,
    *,
    modo_contingencia: bool = False,
    tipo_contingencia: int | None = None,
    motivo_contingencia: str | None = None,
) -> dict:
    """
    Lee la compra sujeto excluido y construye el dict JSON del DTE FSE (tipoDte 14).
    No firma ni envía; solo devuelve el dict listo para el schema fe-fse-v1.
    """

    compra = db.get_compra(compra_id)
    if not compra:
        raise ValueError(f"Compra {compra_id} no existe")

    if not compra.get("is_subject_excluded_purchase"):
        raise ValueError("La compra no está marcada como sujeto excluido")

    detalles = db.get_detalles_compra(compra_id) or []
    vendedor = _get_vendor(db, compra.get("vendedor_id"))
    datos_negocio = dte._load_datos_negocio() or {}

    identificacion, _ = _build_identificacion(
        db,
        compra,
        ambiente=datos_negocio.get("ambiente", "00"),
        modo_contingencia=modo_contingencia,
        tipo_contingencia=tipo_contingencia,
        motivo_contingencia=motivo_contingencia,
    )
    emisor = _build_emisor(datos_negocio)
    sujeto_excluido = _build_receptor(vendedor, datos_negocio)

    cuerpo, resumen_vals = _compute_detalles(db, compra, detalles)
    condicion_operacion = int(compra.get("condicion_operacion") or compra.get("condicionOperacion") or 1)
    pagos = _build_pagos(condicion_operacion, resumen_vals.get("total_compra", Decimal("0")))
    resumen, total_pagar = _build_resumen(resumen_vals, condicion_operacion, pagos)
    # Ajusta pagos al total a pagar para mantener consistencia
    if resumen.get("pagos"):
        for pago in resumen["pagos"]:
            pago["montoPago"] = float(d2(total_pagar))

    apendice = [
        {
            "campo": "ID_COMPRA",
            "etiqueta": "Identificador interno de compra",
            "valor": str(compra_id),
        }
    ]

    fse = {
        "identificacion": identificacion,
        "emisor": emisor,
        "sujetoExcluido": sujeto_excluido,
        "cuerpoDocumento": cuerpo,
        "resumen": resumen,
        "apendice": apendice,
    }

    return fse


def validate_fse_schema(payload: dict, schema_path: str | None = None) -> tuple[bool, list[str]]:
    """
    Validación opcional de desarrollo contra fe-fse-v1.json.
    No usar en producción; es un helper manual para pruebas rápidas.
    """

    try:
        from jsonschema import Draft7Validator
    except Exception:
        return False, ["jsonschema no disponible"]

    if schema_path is None:
        try:
            schema_path = dte.resource_path("svfe-json-schemas", "fe-fse-v1.json")
        except Exception:
            schema_path = None
    if not schema_path:
        return False, ["Ruta de schema no disponible"]
    try:
        with open(schema_path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
    except Exception as exc:  # pragma: no cover - helper de desarrollo
        return False, [f"No se pudo leer el schema: {exc}"]

    validator = Draft7Validator(schema)
    errors = [f"{e.message} @ {'/'.join(str(p) for p in e.path)}" for e in validator.iter_errors(payload)]
    return len(errors) == 0, errors
