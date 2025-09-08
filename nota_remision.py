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
        # Para notas derivadas de factura la extensión puede omitirse
        ext = {
            "nombEntrega": "N/D",
            "docuEntrega": "ND",
            "nombRecibe": "N/D",
            "docuRecibe": "ND",
            "observaciones": "N/D",
        }
        if extension:
            ext.update({k: v for k, v in extension.items() if v not in (None, "")})
    else:
        if not (emisor and receptor and detalles):
            raise ValueError("emisor, receptor y detalles son obligatorios")
        if not detalles:
            raise ValueError("Se requiere al menos un detalle")
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

    limpiar_documentos(emisor)
    limpiar_documentos(receptor)
    limpiar_documentos(ext)

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
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": items,
        "extension": ext,
        "resumen": resumen,
        "apendice": None,
    }
    if documento_relacionado:
        data["documentoRelacionado"] = documento_relacionado

    schema = catalogos.get_dte_schema("04")
    result = sanitize_dte_payload(data, schema)
    if not documento_relacionado:
        result.pop("documentoRelacionado", None)
    return result


def generar_nota_remision_desde_db(
    db: DB, nota_id: int, *, ambiente: str = "00"
) -> dict:
    """Genera la estructura JSON para una Nota de Remisión desde la BD.

    Obtiene los datos de la nota y la venta asociada para construir la
    estructura base y delega la construcción final a :func:`generar_nota_remision`.
    """
    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")
    nota = dict(row)
    if nota.get("tipo") != "remision":
        raise ValueError("La nota indicada no es de remisión")

    import json

    detalles_raw = nota.get("detalles") or "{}"
    try:
        extra = json.loads(detalles_raw)
    except Exception:
        extra = {}

    venta_id = nota.get("venta_id")
    if venta_id:
        venta_row = db.cursor.execute(
            "SELECT cliente_id FROM ventas WHERE id=?", (venta_id,)
        ).fetchone()
        tipo_doc = "01"
        if venta_row:
            venta = dict(venta_row)
            if not db.get_venta_credito_fiscal(venta_id) and not venta.get("cliente_id"):
                tipo_doc = "03"

        from dte import generar_dte_json

        dte_origen = generar_dte_json(db, venta_id, tipo_dte=tipo_doc, ambiente=ambiente)
        extension = extra.get("extension") or {}
        return generar_nota_remision(
            db, factura=dte_origen, extension=extension, ambiente=ambiente
        )

    # Nota independiente (sin venta asociada)
    from dte import _load_datos_negocio

    detalles = extra.get("items") or []
    receptor = extra.get("receptor") or {}
    extension = extra.get("extension") or {}

    emisor = _load_datos_negocio()
    return generar_nota_remision(
        db,
        emisor=emisor,
        receptor=receptor,
        detalles=detalles,
        extension=extension,
        ambiente=ambiente,
    )


__all__ = ["generar_nota_remision", "generar_nota_remision_desde_db"]
