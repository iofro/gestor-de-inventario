# coding: utf-8
"""Generación de Nota de Remisión Electrónica (NR).

Este módulo expone utilidades para construir la estructura JSON requerida por
el Ministerio de Hacienda de El Salvador para una Nota de Remisión (``tipoDte``
``04``).  Se proveen dos funciones de alto nivel:

* :func:`generar_nota_remision_desde_factura` crea la nota a partir de un DTE de
  origen reutilizando la información de emisor, receptor y detalles.
* :func:`generar_nota_remision_independiente` permite crear una nota
  especificando manualmente todos los datos, incluido su documento
  relacionado.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from db import DB
from dte import DTE_VERSIONES, generar_cabecera_dte_data, sanitize_dte_payload
from utils import catalogos
from utils.fecha import TZ_EL_SALVADOR, fecha_emision_hoy_str, normalizar_fecha_iso
from utils.monto import d2, monto_a_texto_sv
import warnings

from utils.sanitize import limpiar_documentos, solo_digitos

Decimal_0 = Decimal("0")


def _build_items(
    detalles: Iterable[dict], numero_documento: Optional[str] = None
) -> list[dict]:
    """Construye los ítems de la NR forzando todos los montos a ``0.00``.

    Además valida que ``cantidad`` sea mayor que cero y normaliza
    ``uniMedida`` contra el catálogo CAT-014.  Si el ítem no provee una unidad
    válida se utiliza por defecto ``59`` (Unidad).  Si
    ``numero_documento`` se proporciona se agrega a cada ítem.
    """

    items: list[dict] = []
    for num, det in enumerate(detalles, 1):
        cantidad = det.get("cantidad", 1)
        if cantidad <= 0:
            raise ValueError("cantidad debe ser mayor que cero")
        uni = det.get("uniMedida", 59)
        try:
            uni = int(uni)
        except Exception:
            uni = 59
        if uni not in catalogos.UNIDADES_MEDIDA_PERMITIDAS:
            uni = 59
        item = {
            "numItem": num,
            "tipoItem": det.get("tipoItem", 1),
            "codigo": det.get("codigo", f"NR{num:03d}"),
            "descripcion": det.get("descripcion", f"Item {num}"),
            "cantidad": cantidad,
            "uniMedida": uni,
            "precioUni": 0.0,
            "montoDescu": 0.0,
            "ventaNoSuj": d2(Decimal_0),
            "ventaExenta": d2(Decimal_0),
            "ventaGravada": d2(Decimal_0),
            "tributos": None,
            "codTributo": None,
        }
        if numero_documento:
            item["numeroDocumento"] = numero_documento
        items.append(item)
    return items


def normalizar_receptor(receptor: dict) -> dict:
    """Sanitize and validate ``receptor`` fields according to its document type."""

    if not receptor or not receptor.get("tipoDocumento"):
        raise ValueError("receptor requiere tipoDocumento y numDocumento")

    limpiar_documentos(receptor)
    tipo = receptor.get("tipoDocumento")
    num = solo_digitos(receptor.get("numDocumento"))
    if not num:
        raise ValueError("receptor requiere numDocumento")
    receptor["numDocumento"] = num

    nrc_raw = receptor.get("nrc")
    if nrc_raw is not None:
        nrc = solo_digitos(nrc_raw)
        if nrc:
            receptor["nrc"] = nrc
        else:
            receptor.pop("nrc", None)

    if tipo == "13":
        if len(num) != 9:
            raise ValueError("DUI debe tener 9 dígitos (sin guiones)")
        if nrc_raw:
            warnings.warn(
                "Se removió NRC porque el documento es DUI", UserWarning
            )
        receptor.pop("nrc", None)
    elif tipo == "36":
        if len(num) != 14:
            raise ValueError("NIT debe tener 14 dígitos (sin guiones)")
        nrc = receptor.get("nrc")
        if not nrc or len(nrc) not in (6, 7):
            raise ValueError("NRC requerido (6–7 dígitos)")
    elif tipo in {"37", "03", "02"}:
        receptor.pop("nrc", None)
    else:
        raise ValueError("tipoDocumento inválido en receptor")
    # Campos adicionales requeridos para receptores
    for campo in ("codActividad", "descActividad", "telefono", "correo"):
        if not receptor.get(campo):
            raise ValueError(f"receptor requiere {campo}")

    direccion = receptor.get("direccion") or {}
    if not direccion.get("complemento"):
        raise ValueError("receptor requiere direccion.complemento")

    receptor.setdefault("nombreComercial", None)
    return receptor


def _generar_base(
    db: DB,
    *,
    emisor: dict,
    receptor: dict,
    detalles: Iterable[dict],
    extension: Optional[dict] = None,
    documento_relacionado: Optional[list[dict]] = None,
    ambiente: str = "00",
) -> dict:
    """Construye la estructura base común de una NR."""
    if not documento_relacionado:
        raise ValueError("documento_relacionado es obligatorio")

    limpiar_documentos(emisor)
    emisor.setdefault("tipoEstablecimiento", "01")
    receptor.setdefault("bienTitulo", "01")
    receptor = normalizar_receptor(receptor)

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

    numero_doc = documento_relacionado[0].get("numeroDocumento")
    items = _build_items(detalles, numero_doc)

    ext = {
        "nombEntrega": "N/D",
        "docuEntrega": "ND",
        "nombRecibe": "N/D",
        "docuRecibe": "ND",
        "observaciones": "N/D",
    }
    if extension:
        ext.update({k: v for k, v in extension.items() if v not in (None, "")})
    for key in ("docuEntrega", "docuRecibe"):
        ext[key] = solo_digitos(ext.get(key))
        if not ext[key]:
            raise ValueError(f"{key} requerido")
    limpiar_documentos(ext)

    resumen = {
        "totalNoSuj": d2(Decimal_0),
        "totalExenta": d2(Decimal_0),
        "totalGravada": d2(Decimal_0),
        "subTotal": d2(Decimal_0),
        "subTotalVentas": d2(Decimal_0),
        "porcentajeDescuento": d2(Decimal_0),
        "totalDescu": d2(Decimal_0),
        "descuNoSuj": d2(Decimal_0),
        "descuExenta": d2(Decimal_0),
        "descuGravada": d2(Decimal_0),
        "tributos": None,
        "montoTotalOperacion": d2(Decimal_0),
        "totalLetras": monto_a_texto_sv(0.0),
    }

    data = {
        "identificacion": identificacion,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": items,
        "extension": ext,
        "resumen": resumen,
        "apendice": None,
        "documentoRelacionado": documento_relacionado,
    }

    schema = catalogos.get_dte_schema("04")
    return sanitize_dte_payload(data, schema)


def generar_nota_remision_desde_factura(
    db: DB,
    factura: dict,
    *,
    detalles: Optional[Iterable[dict]] = None,
    extension: Optional[dict] = None,
    ambiente: str = "00",
    fecha_origen: Optional[str] = None,
) -> dict:
    """Genera una NR reutilizando los datos de una factura ``factura``."""

    emisor = factura.get("emisor", {})
    receptor = factura.get("receptor", {})
    receptor.setdefault("bienTitulo", "01")
    detalles = detalles or factura.get("cuerpoDocumento", [])
    ident = factura.get("identificacion") or {}
    if not isinstance(ident, dict):
        ident = {}
        factura["identificacion"] = ident
    fecha_emision = None
    if fecha_origen:
        fecha_normalizada = normalizar_fecha_iso(fecha_origen)
        if fecha_normalizada:
            fecha_emision = fecha_normalizada
            ident["fecEmi"] = fecha_emision
    if not fecha_emision:
        fecha_normalizada = normalizar_fecha_iso(ident.get("fecEmi"))
        if fecha_normalizada:
            fecha_emision = fecha_normalizada
            ident["fecEmi"] = fecha_emision
        else:
            fecha_emision = ident.get("fecEmi")
    doc_rel = [
        {
            "tipoDocumento": ident.get("tipoDte"),
            "tipoGeneracion": 2,
            "numeroDocumento": ident.get("codigoGeneracion"),
            "fechaEmision": fecha_emision,
        }
    ]
    ext = extension.copy() if extension else None
    if ext:
        tipo_doc = ext.pop("tipoDocRecibe", None)
        nrc_recibe = ext.pop("nrcRecibe", None)
        if tipo_doc:
            receptor["tipoDocumento"] = tipo_doc
            doc_recibe = ext.get("docuRecibe")
            if doc_recibe:
                receptor["numDocumento"] = doc_recibe
        if nrc_recibe:
            receptor["nrc"] = nrc_recibe
    return _generar_base(
        db,
        emisor=emisor,
        receptor=receptor,
        detalles=detalles,
        extension=ext,
        documento_relacionado=doc_rel,
        ambiente=ambiente,
    )


def generar_nota_remision_independiente(
    db: DB,
    *,
    emisor: dict,
    receptor: dict,
    detalles: Iterable[dict],
    documento_relacionado: list[dict],
    extension: Optional[dict] = None,
    ambiente: str = "00",
) -> dict:
    """Genera una NR independiente especificando su documento relacionado."""

    if not (emisor and receptor and detalles and documento_relacionado):
        raise ValueError(
            "emisor, receptor, detalles y documento_relacionado son obligatorios"
        )
    if not extension:
        raise ValueError("extension es obligatoria")
    required_ext = [
        "nombEntrega",
        "docuEntrega",
        "nombRecibe",
        "docuRecibe",
        "observaciones",
    ]
    missing = [k for k in required_ext if not extension.get(k)]
    if missing:
        raise ValueError(
            "Faltan campos obligatorios en extension: " + ", ".join(missing)
        )
    ext = {k: extension.get(k) for k in required_ext}
    if not str(ext.get("observaciones", "")).strip():
        raise ValueError("observaciones es obligatoria")

    return _generar_base(
        db,
        emisor=emisor,
        receptor=receptor,
        detalles=detalles,
        extension=ext,
        documento_relacionado=documento_relacionado,
        ambiente=ambiente,
    )


__all__ = [
    "generar_nota_remision_desde_factura",
    "generar_nota_remision_independiente",
]
