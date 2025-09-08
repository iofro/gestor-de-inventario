# coding: utf-8
"""Generación de Nota de Remisión Electrónica (NR).

Este módulo expone utilidades para construir la estructura JSON requerida por
el Ministerio de Hacienda de El Salvador para una Nota de Remisión (``tipoDte``
``04``).  Se proveen dos funciones de alto nivel:

* :func:`generar_nota_remision_desde_factura` crea la nota a partir de un DTE de
  origen reutilizando la información de emisor, receptor y detalles.
* :func:`generar_nota_remision_independiente` permite crear una nota sin
  documento relacionado especificando manualmente todos los datos.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from db import DB
from dte import DTE_VERSIONES, generar_cabecera_dte_data, sanitize_dte_payload
from utils import catalogos
from utils.fecha import TZ_EL_SALVADOR, fecha_emision_hoy_str
from utils.monto import d2, monto_a_texto_sv
from utils.sanitize import limpiar_documentos

Decimal_0 = Decimal("0")


def _build_items(detalles: Iterable[dict]) -> list[dict]:
    """Construye los ítems de la NR forzando todos los montos a ``0.00``.

    Además valida que ``cantidad`` sea mayor que cero y que ``uniMedida`` esté
    presente.
    """

    items: list[dict] = []
    for num, det in enumerate(detalles, 1):
        cantidad = det.get("cantidad", 1)
        if cantidad <= 0:
            raise ValueError("cantidad debe ser mayor que cero")
        if det.get("uniMedida") is None:
            raise ValueError("uniMedida requerido en el item")
        items.append(
            {
                "numItem": num,
                "tipoItem": det.get("tipoItem", 1),
                "codigo": det.get("codigo", f"NR{num:03d}"),
                "descripcion": det.get("descripcion", f"Item {num}"),
                "cantidad": cantidad,
                "uniMedida": det.get("uniMedida"),
                "precioUni": 0.0,
                "montoDescu": 0.0,
                "ventaNoSuj": d2(Decimal_0),
                "ventaExenta": d2(Decimal_0),
                "ventaGravada": d2(Decimal_0),
                "tributos": [],
                "numeroDocumento": None,
                "codTributo": None,
            }
        )
    return items


def _generar_base(
    db: DB,
    *,
    emisor: dict,
    receptor: dict,
    detalles: Iterable[dict],
    extension: Optional[dict] = None,
    documento_relacionado: Optional[dict] = None,
    ambiente: str = "00",
) -> dict:
    """Construye la estructura base común de una NR."""

    limpiar_documentos(emisor)
    limpiar_documentos(receptor)

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

    items = _build_items(detalles)

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
        "totalNoSuj": d2(Decimal_0),
        "totalExenta": d2(Decimal_0),
        "totalGravada": d2(Decimal_0),
        "subTotal": d2(Decimal_0),
        "subTotalVentas": d2(Decimal_0),
        "descuNoSuj": 0.0,
        "descuExenta": 0.0,
        "descuGravada": 0.0,
        "totalDescu": 0.0,
        "ivaPerci1": 0.0,
        "ivaRete1": 0.0,
        "reteRenta": 0.0,
        "montoTotalOperacion": d2(Decimal_0),
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


def generar_nota_remision_desde_factura(
    db: DB,
    factura: dict,
    *,
    detalles: Optional[Iterable[dict]] = None,
    extension: Optional[dict] = None,
    ambiente: str = "00",
) -> dict:
    """Genera una NR reutilizando los datos de una factura ``factura``."""

    emisor = factura.get("emisor", {})
    receptor = factura.get("receptor", {})
    detalles = detalles or factura.get("cuerpoDocumento", [])
    ident = factura.get("identificacion", {})
    doc_rel = {
        "tipoDoc": ident.get("tipoDte"),
        "numeroDocumento": ident.get("numeroControl"),
    }
    return _generar_base(
        db,
        emisor=emisor,
        receptor=receptor,
        detalles=detalles,
        extension=extension,
        documento_relacionado=doc_rel,
        ambiente=ambiente,
    )


def generar_nota_remision_independiente(
    db: DB,
    *,
    emisor: dict,
    receptor: dict,
    detalles: Iterable[dict],
    extension: Optional[dict] = None,
    ambiente: str = "00",
) -> dict:
    """Genera una NR sin documento relacionado."""

    if not (emisor and receptor and detalles):
        raise ValueError("emisor, receptor y detalles son obligatorios")

    return _generar_base(
        db,
        emisor=emisor,
        receptor=receptor,
        detalles=detalles,
        extension=extension,
        documento_relacionado=None,
        ambiente=ambiente,
    )


__all__ = [
    "generar_nota_remision_desde_factura",
    "generar_nota_remision_independiente",
]
