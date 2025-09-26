"""Utilities to render DTE tickets as thermal PDFs.

This module now renders tickets using HTML templates targeted at 58 mm
thermal printers.  The templates live under :mod:`templates/` and share a
common CSS stylesheet that enforces the typography, spacing and layout
guidelines required for 203 dpi printers.
"""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import os
import sys

import qrcode
from jinja2 import Environment, FileSystemLoader, select_autoescape

# --- Bootstrap DLLs GTK/Pango/Cairo en Windows ---
if sys.platform.startswith("win"):
    here = os.path.dirname(__file__)
    # 1) Ruta local dentro del repo: repo_root/gtk3/bin
    repo_bin = os.path.abspath(os.path.join(here, "..", "gtk3", "bin"))
    if os.path.isdir(repo_bin):
        try:
            os.add_dll_directory(repo_bin)  # Python 3.8+
        except Exception:
            pass
    # 2) (Opcional) override por variable de entorno
    gtk_bin = os.environ.get("GTK_BIN")
    if gtk_bin and os.path.isdir(gtk_bin):
        try:
            os.add_dll_directory(gtk_bin)
        except Exception:
            pass
# --- Fin bootstrap ---

_HTML = _CSS = None
_weasy_error = None


def _ensure_weasyprint() -> None:
    """Import WeasyPrint de forma diferida y controlar errores de dependencias."""

    global _HTML, _CSS, _weasy_error
    if _HTML and _CSS:
        return
    try:
        from weasyprint import HTML as __HTML, CSS as __CSS

        _HTML, _CSS = __HTML, __CSS
        _weasy_error = None
    except Exception as e:  # pragma: no cover - depende de entorno externo
        _weasy_error = e
        raise RuntimeError(
            "WeasyPrint no está disponible. Instala las dependencias nativas (GTK/Pango/Cairo) "
            "y el paquete Python WeasyPrint. Detalle: " + str(e)
        )


def _base_templates_dir() -> Path:
    """Return the base path where templates live, supporting PyInstaller."""

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "templates"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent.parent / "templates"

from factura_sv import build_qr_url
from utils.catalogos import (
    CAT_DEPTOS,
    CAT_MUNI44,
    CAT_MUNI44_BY_DEPTO,
    CONDICION_OPERACION,
    DTE_TIPOS,
    FORMA_PAGO,
    MODELO,
    OPERACION,
    PLAZO,
    TIPO_DOC_REC,
)

try:  # pragma: no cover - defensive import for optional data
    from dte import _DEPARTAMENTOS as DTE_DEPARTAMENTOS
    from dte import _MUNICIPIOS_POR_DEPTO as DTE_MUNICIPIOS
except Exception:  # pragma: no cover - fallback when running minimal envs
    DTE_DEPARTAMENTOS = {}
    DTE_MUNICIPIOS = {}


TEMPLATES_DIR = _base_templates_dir()
CSS_PATH = TEMPLATES_DIR / "ticket-58mm.css"


def render_ticket_html_to_pdf(html_str: str, css_path: str, out_path: str) -> str:
    """Render *html_str* + *css_path* to *out_path* using WeasyPrint."""

    _ensure_weasyprint()
    html = _HTML(string=html_str, base_url=str(TEMPLATES_DIR))
    stylesheet = _CSS(filename=str(css_path))
    html.write_pdf(str(out_path), stylesheets=[stylesheet])
    return out_path


# ---------------------------------------------------------------------------
# Formatting helpers used inside the renderer


def _to_decimal(value: Any) -> Decimal:
    """Return ``value`` as :class:`~decimal.Decimal`.

    ``value`` can be an int, float, Decimal or string.  Missing values are
    treated as ``Decimal('0')``.  This helper makes the rest of the code more
    robust when dealing with different numeric types coming from JSON.
    """

    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def money(value: Any) -> str:
    """Format ``value`` as a monetary string with two decimals."""

    q = Decimal("0.01")
    return f"{_to_decimal(value).quantize(q, rounding=ROUND_HALF_UP):,.2f}"


def q(value: Any) -> str:
    """Format a quantity removing trailing zeros."""

    d = _to_decimal(value)
    s = f"{d.normalize():f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


PAGO_LABELS = {code.zfill(2): value.upper() for code, value in FORMA_PAGO.items()}

FISCAL_SUMMARY_LABELS = [
    ("totalGravada", "Ventas gravadas"),
    ("totalExenta", "Ventas exentas"),
    ("totalNoSuj", "Ventas no sujetas"),
    ("iva", "IVA débito fiscal"),
    ("ivaRete1", "IVA retenido"),
    ("ivaPercibido", "IVA percibido"),
    ("reteRenta", "Retención renta"),
]


def document_title_label(ident: Mapping[str, Any] | None) -> str:
    """Return an uppercased label describing the DTE document type."""

    tipo_dte = ""
    if ident and isinstance(ident, Mapping):
        tipo_dte = str(ident.get("tipoDte") or "").zfill(2)

    if tipo_dte == "01":
        return "CONSUMIDOR FINAL"
    if tipo_dte == "03":
        return "CRÉDITO FISCAL"

    label = DTE_TIPOS.get(tipo_dte)
    if label:
        return label.upper()
    return "FACTURA"


# ---------------------------------------------------------------------------
# Internal structures used to build the template context


@dataclass
class ItemRow:
    descripcion: str
    cantidad: str
    precio_unitario: str
    subtotal: str
    iva: str | None = None
    descuentos: str | None = None


def _map_modelo(code: Any) -> str:
    try:
        value = MODELO.get(int(code))
    except Exception:
        value = None
    if value:
        return value.title()
    return str(code or "")


def _map_operacion(code: Any) -> str:
    try:
        value = OPERACION.get(int(code))
    except Exception:
        value = None
    if value:
        return value.title()
    return str(code or "")


def _format_address(data: Mapping[str, Any]) -> str:
    if not isinstance(data, Mapping):
        return ""
    complemento = str(data.get("complemento") or "").strip()
    dep_raw = data.get("departamento")
    muni_raw = data.get("municipio")
    dep_code = f"{dep_raw}".zfill(2) if dep_raw is not None else None
    muni_code = f"{muni_raw}".zfill(2) if muni_raw is not None else None

    dep_name = (
        DTE_DEPARTAMENTOS.get(dep_code)
        or CAT_DEPTOS.get(dep_code)
        or ""
    )
    muni_name = ""
    if dep_code and muni_code:
        try:
            muni_name = DTE_MUNICIPIOS.get(dep_code, {}).get(muni_code, "")
        except AttributeError:
            muni_name = ""
        if not muni_name:
            muni_name = CAT_MUNI44_BY_DEPTO.get(dep_code, {}).get(muni_code, "")
        if not muni_name:
            muni_map = CAT_MUNI44.get(muni_code) or {}
            if muni_map:
                muni_name = next(iter(muni_map.values()))

    parts = [p for p in (complemento, muni_name, dep_name) if p]
    return ", ".join(parts)


def _format_document_meta(ident: Mapping[str, Any]) -> List[Dict[str, str]]:
    meta: List[Dict[str, str]] = []

    numero_control = ident.get("numeroControl")
    if numero_control:
        meta.append({"label": "Número de control", "value": str(numero_control)})

    codigo_generacion = ident.get("codigoGeneracion")
    if codigo_generacion:
        meta.append({"label": "Código de generación", "value": str(codigo_generacion)})

    modelo = ident.get("tipoModelo")
    if modelo:
        meta.append({"label": "Modelo", "value": _map_modelo(modelo)})

    operacion = ident.get("tipoOperacion")
    if operacion:
        meta.append({"label": "Operación", "value": _map_operacion(operacion)})

    fecha = ident.get("fecEmi")
    hora = ident.get("horEmi")
    if fecha or hora:
        value = " ".join(v for v in (str(fecha or "").strip(), str(hora or "").strip()) if v)
        if value:
            meta.append({"label": "Fecha y hora", "value": value})

    return meta


def _format_receptor(receptor: Mapping[str, Any]) -> Dict[str, Any]:
    documento_codigo = str(receptor.get("tipoDocumento") or receptor.get("tipoDoc") or "").zfill(2)
    documento_label = TIPO_DOC_REC.get(documento_codigo) if documento_codigo else None
    documento_numero = (
        receptor.get("numDocumento")
        or receptor.get("numeroDocumento")
        or receptor.get("nit")
        or receptor.get("dui")
    )

    return {
        "nombre": (receptor.get("nombre") or receptor.get("razonSocial") or "").strip(),
        "documento_label": documento_label,
        "documento_numero": str(documento_numero or "").strip(),
        "nit": str(receptor.get("nit") or "").strip(),
        "nrc": str(receptor.get("nrc") or "").strip(),
        "direccion": _format_address(receptor.get("direccion", {})),
        "correo": str(receptor.get("correo") or receptor.get("email") or "").strip(),
        "telefono": str(receptor.get("telefono") or "").strip(),
        "giro": str(receptor.get("descActividad") or receptor.get("giro") or "").strip(),
    }


def _format_emisor(emisor: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "nombre": (emisor.get("nombreComercial") or emisor.get("nombre") or "").strip(),
        "razon_social": (emisor.get("nombre") or emisor.get("razonSocial") or "").strip(),
        "nit": str(emisor.get("nit") or "").strip(),
        "nrc": str(emisor.get("nrc") or "").strip(),
        "giro": str(emisor.get("descActividad") or emisor.get("actividad") or "").strip(),
        "direccion": _format_address(emisor.get("direccion", {})),
        "telefono": str(emisor.get("telefono") or "").strip(),
        "email": str(emisor.get("correo") or emisor.get("email") or "").strip(),
        "logo_url": str(emisor.get("logoUrl") or emisor.get("logo") or "").strip() or None,
    }


def _calculate_item_total(entry: Mapping[str, Any]) -> Decimal:
    total_candidates = (
        entry.get("montoTotal"),
        entry.get("ventaGravada"),
        entry.get("ventaExenta"),
        entry.get("ventaNoSuj"),
        entry.get("montoTotalOperacion"),
        entry.get("subTotal"),
        entry.get("ventas_gravadas"),
        entry.get("ventas_exentas"),
        entry.get("ventas_no_sujetas"),
    )
    for candidate in total_candidates:
        if candidate is not None:
            value = _to_decimal(candidate)
            if value != 0:
                return value

    qty = _to_decimal(entry.get("cantidad") or entry.get("cantidadUniMedida") or entry.get("uniCantidad"))
    unit = _to_decimal(
        entry.get("precio_unitario")
        or entry.get("precioUnitario")
        or entry.get("precioUnit")
        or entry.get("precioUni")
        or entry.get("precio")
    )
    return (qty * unit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _extract_iva(entry: Mapping[str, Any]) -> Decimal:
    tributos = entry.get("tributos")
    if isinstance(tributos, Sequence):
        total = Decimal("0")
        for trib in tributos:
            if not isinstance(trib, Mapping):
                continue
            valor = trib.get("valor") or trib.get("monto") or trib.get("importe")
            if valor is not None:
                total += _to_decimal(valor)
        if total != 0:
            return total

    iva = entry.get("iva") or entry.get("montoIva") or entry.get("ivaItem")
    if iva is not None:
        return _to_decimal(iva)

    return Decimal("0")


def _format_items(items: Iterable[Mapping[str, Any]]) -> List[ItemRow]:
    formatted: List[ItemRow] = []
    for entry in items or []:
        descripcion = str(
            entry.get("descripcion")
            or entry.get("nombre")
            or entry.get("detalle")
            or ""
        ).strip()

        cantidad = q(entry.get("cantidad") or entry.get("cantidadUniMedida") or entry.get("uniCantidad") or 0)
        unit_price = money(
            entry.get("precio_unitario")
            or entry.get("precioUnitario")
            or entry.get("precioUnit")
            or entry.get("precioUni")
            or entry.get("precio")
            or entry.get("valorUni")
            or 0
        )
        subtotal = money(_calculate_item_total(entry))
        iva_value = _extract_iva(entry)
        iva = money(iva_value) if iva_value else None

        descuentos = entry.get("montoDescu") or entry.get("descuento")
        if descuentos:
            descuentos = money(descuentos)
        else:
            descuentos = None

        formatted.append(
            ItemRow(
                descripcion=descripcion or "—",
                cantidad=cantidad,
                precio_unitario=unit_price,
                subtotal=subtotal,
                iva=iva,
                descuentos=descuentos,
            )
        )

    return formatted


def _format_totals(resumen: Mapping[str, Any]) -> tuple[List[Dict[str, str]], Dict[str, str] | None]:
    if not isinstance(resumen, Mapping):
        return [], None

    totals: List[Dict[str, str]] = []
    labels = [
        ("totalGravada", "Ventas gravadas"),
        ("totalExenta", "Ventas exentas"),
        ("totalNoSuj", "Ventas no sujetas"),
        ("subTotalVentas", "Subtotal ventas"),
        ("totalDescu", "Descuentos"),
        ("iva", "IVA"),
        ("ivaRete1", "IVA retenido"),
        ("ivaPercibido", "IVA percibido"),
        ("reteRenta", "Retención renta"),
        ("montoTotalOperacion", "Monto total operación"),
        ("saldoAFavor", "Saldo a favor"),
    ]

    seen = set()
    for key, label in labels:
        if key in seen:
            continue
        value = resumen.get(key)
        if value in (None, "", 0, 0.0):
            continue
        totals.append({"label": label, "value": money(value)})
        seen.add(key)

    total_pagar_candidates = (
        resumen.get("totalPagar"),
        resumen.get("totalPagarSinRedondeo"),
        resumen.get("montoTotalPagar"),
    )
    total_pagar_value = None
    for candidate in total_pagar_candidates:
        if candidate is not None:
            total_pagar_value = candidate
            break

    total_to_pay = None
    if total_pagar_value is not None:
        total_to_pay = {"label": "Total a pagar", "value": money(total_pagar_value)}

    return totals, total_to_pay


def _format_condicion_operacion(resumen: Mapping[str, Any]) -> str | None:
    if not isinstance(resumen, Mapping):
        return None
    value = resumen.get("condicionOperacion")
    if value is None:
        return None
    try:
        value = int(value)
    except Exception:
        return None
    label = CONDICION_OPERACION.get(value)
    if not label:
        return None
    return label.title()


def _format_pagos(resumen: Mapping[str, Any]) -> List[Dict[str, str]]:
    pagos = resumen.get("pagos") if isinstance(resumen, Mapping) else None
    formatted: List[Dict[str, str]] = []
    if not isinstance(pagos, Sequence):
        return formatted

    for pago in pagos:
        if not isinstance(pago, Mapping):
            continue
        codigo = str(pago.get("codigo") or pago.get("formaPago") or "").zfill(2)
        label = PAGO_LABELS.get(codigo, "Otro")
        monto = pago.get("montoPago") or pago.get("valor") or pago.get("monto")
        detalle: List[str] = []

        plazo = pago.get("plazo") or pago.get("plazoPago")
        if plazo not in (None, "", 0, 0.0):
            detalle.append(f"Plazo: {q(plazo)}")

        periodo = pago.get("periodo")
        if periodo not in (None, "", 0, 0.0):
            periodo_code = str(periodo).zfill(2)
            periodo_label = PLAZO.get(periodo_code)
            if periodo_label:
                detalle.append(f"Periodo: {periodo_label}")
            else:
                detalle.append(f"Periodo: {periodo}")

        referencia = pago.get("referencia") or pago.get("numeroDocumento")
        if referencia:
            detalle.append(f"Ref: {referencia}")
        detail_text = " · ".join(detalle).strip()
        formatted.append(
            {
                "label": label,
                "amount": money(monto or 0),
                "detail": detail_text or None,
            }
        )
    return formatted


def _format_fiscal_summary(resumen: Mapping[str, Any]) -> List[Dict[str, str]]:
    if not isinstance(resumen, Mapping):
        return []

    summary: List[Dict[str, str]] = []
    for key, label in FISCAL_SUMMARY_LABELS:
        value = resumen.get(key)
        summary.append({"label": label, "amount": money(value)})

    return summary


def _qr_data_uri(qr_url: str | None) -> str | None:
    if not qr_url:
        return None

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=1,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@lru_cache(maxsize=1)
def _jinja_env() -> Environment:
    loader = FileSystemLoader(str(TEMPLATES_DIR))
    return Environment(loader=loader, autoescape=select_autoescape(["html", "xml"]))


def _select_template_name(ident: Mapping[str, Any]) -> str:
    tipo_dte = str(ident.get("tipoDte") or "").zfill(2)
    if tipo_dte == "01":
        return "ticket-consumidor-final-58mm.html"
    if tipo_dte == "03":
        return "ticket-credito-fiscal-58mm.html"
    return "ticket-normal-58mm.html"


def _collect_footer_notes(payload: Mapping[str, Any], accepted: bool) -> List[str]:
    notes: List[str] = []
    if accepted:
        notes.append("Documento validado por el Ministerio de Hacienda")
    if payload.get("selloRecibido") or payload.get("acuseRecibo"):
        notes.append("Sello de recepción disponible")
    return notes


# ---------------------------------------------------------------------------
# Public API


def render_ticket_pdf(
    payload: Dict[str, Any],
    accepted: bool,
    sello: str | None = None,
) -> bytes:
    """Render ``payload`` into a thermal ticket PDF."""

    ident = payload.get("identificacion", {}) or {}
    emisor = payload.get("emisor", {}) or {}
    receptor = payload.get("receptor", {}) or {}
    resumen = payload.get("resumen", {}) or {}
    items = payload.get("cuerpoDocumento", []) or []

    env = _jinja_env()
    template_name = _select_template_name(ident)
    template = env.get_template(template_name)

    document_label = document_title_label(ident)
    qr_url = build_qr_url(payload) if payload else None
    qr_image = _qr_data_uri(qr_url)

    totals, total_to_pay = _format_totals(resumen)
    pagos = _format_pagos(resumen)
    condicion_operacion = _format_condicion_operacion(resumen)

    condicion_operacion_raw = None
    if isinstance(resumen, Mapping):
        condicion_operacion_raw = resumen.get("condicionOperacion")
    is_credit_operation = False
    try:
        is_credit_operation = int(condicion_operacion_raw) == 2
    except Exception:
        is_credit_operation = False

    context = {
        "title": "Documento Tributario Electrónico",
        "document_label": document_label,
        "emisor": _format_emisor(emisor),
        "receptor": _format_receptor(receptor),
        "document_meta": _format_document_meta(ident),
        "items": _format_items(items),
        "totals": totals,
        "total_to_pay": total_to_pay,
        "pagos": pagos,
        "condicion_operacion": condicion_operacion,
        "fiscal_summary": _format_fiscal_summary(resumen),
        "show_payments_block": bool(pagos) or is_credit_operation,
        "is_credit_operation": is_credit_operation,
        "qr_url": qr_url,
        "qr_image": qr_image,
        "accepted": accepted,
        "sello": sello,
        "firma": payload.get("firmaElectronica"),
        "footer_notes": _collect_footer_notes(payload, accepted),
    }

    html = template.render(**context)
    _ensure_weasyprint()
    stylesheets = [_CSS(filename=str(CSS_PATH))]
    pdf_bytes = _HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf(
        stylesheets=stylesheets
    )
    return pdf_bytes

