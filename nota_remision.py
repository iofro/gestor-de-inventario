# coding: utf-8
"""Generación de Nota de Remisión (NR) tipoDte "04".

Este módulo centraliza la creación y sanitización de las Notas de Remisión.
La estructura base contempla únicamente los campos exigidos por Hacienda y
fuerza todos los montos a ``0.00`` dado que la nota tiene carácter no
tributario.

Se soportan dos flujos de trabajo:

* **Desde factura**: a partir de un DTE existente se reutilizan emisor,
  receptor y detalles, generando automáticamente el ``documentoRelacionado``.
* **Independiente**: el llamante proporciona los datos de emisor, receptor y
  los ítems manualmente junto con la información del documento relacionado.

La función pública :func:`generar_nota_remision` retorna un ``dict`` listo para
validarse contra el esquema oficial.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from db import DB
from dte import DTE_VERSIONES, generar_cabecera_dte_data, sanitize_dte_payload
from utils import catalogos
from utils.fecha import TZ_EL_SALVADOR, fecha_emision_hoy_str
from utils.monto import monto_a_texto_sv, d2
from utils.sanitize import limpiar_documentos

Decimal_0 = Decimal("0")


def _build_items(detalles: Iterable[dict]) -> list[dict]:
    """Construye items con montos forzados a ``0.00``."""
    items: list[dict] = []
    for num, det in enumerate(detalles, 1):
        items.append(
            {
                "numItem": num,
                "tipoItem": det.get("tipoItem", 1),
                "codigo": det.get("codigo", f"NR{num:03d}"),
                "descripcion": det.get("descripcion", f"Item {num}"),
                "cantidad": det.get("cantidad", 1),
                "uniMedida": det.get("uniMedida", 59),
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


def generar_nota_remision(
    db: DB,
    factura: Optional[dict] = None,
    *,
    detalles: Optional[Iterable[dict]] = None,
    documento_relacionado: Optional[dict] = None,
    emisor: Optional[dict] = None,
    receptor: Optional[dict] = None,
    extension: Optional[dict] = None,
    ambiente: str = "00",
) -> dict:
    """Genera la estructura JSON de una Nota de Remisión."""
    if factura:
        emisor = factura.get("emisor")
        receptor = factura.get("receptor")
        detalles = detalles or factura.get("cuerpoDocumento", [])
        if documento_relacionado is None:
            ident = factura.get("identificacion", {})
            documento_relacionado = {
                "tipoDoc": ident.get("tipoDte"),
                "numeroDocumento": ident.get("numeroControl"),
            }
    else:
        if not (emisor and receptor and detalles):
            raise ValueError("emisor, receptor y detalles son obligatorios")
        if documento_relacionado is None:
            raise ValueError(
                "documento_relacionado requerido cuando no hay factura"
            )

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


__all__ = ["generar_nota_remision"]
