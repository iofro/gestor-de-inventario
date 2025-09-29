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

import logging

from db import DB
from dte import DTE_VERSIONES, generar_cabecera_dte_data, sanitize_dte_payload
from utils import catalogos
from utils.fecha import TZ_EL_SALVADOR, fecha_ddmmaaaa, fecha_emision_hoy_str
from utils.monto import monto_a_texto_sv, d2
from utils.snapshot import normalize_snapshot
import warnings

from utils.sanitize import limpiar_documentos, solo_digitos

Decimal_0 = Decimal("0")


logger = logging.getLogger(__name__)


def _build_items(
    detalles: Iterable[dict], numero_documento: Optional[str] = None
) -> list[dict]:
    """Construye items con montos forzados a ``0.00``.

    Además normaliza ``uniMedida`` contra el catálogo CAT-014, usando ``59``
    (Unidad) cuando el detalle no provee una unidad válida.  Si
    ``numero_documento`` se proporciona se añade a cada ítem.
    """
    items: list[dict] = []
    for num, det in enumerate(detalles, 1):
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
            "cantidad": det.get("cantidad", 1),
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
    """Sanitize and validate ``receptor`` according to tipoDocumento."""

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


def _normalizar_documento_relacionado(doc_rel: list[dict]) -> list[dict]:
    """Valida y normaliza ``documento_relacionado`` si está presente."""

    if not isinstance(doc_rel, list) or not doc_rel:
        raise ValueError("documento_relacionado debe ser una lista no vacía")
    doc = doc_rel[0] or {}
    tipo = doc.get("tipoDocumento")
    numero = doc.get("numeroDocumento")
    fecha = doc.get("fechaEmision")
    if tipo not in {"01", "03", "11"}:
        raise ValueError("tipoDocumento inválido en documento_relacionado")
    if not numero or not fecha:
        raise ValueError(
            "documento_relacionado requiere numeroDocumento y fechaEmision"
        )
    fecha_normalizada = fecha_ddmmaaaa(fecha)
    if not fecha_normalizada:
        raise ValueError("fechaEmision inválida en documento_relacionado")
    return [
        {
            "tipoDocumento": tipo,
            "tipoGeneracion": 2,
            "numeroDocumento": numero,
            "fechaEmision": fecha_normalizada,
        }
    ]


def generar_nota_remision(
    db: DB,
    factura: Optional[dict] = None,
    *,
    detalles: Optional[Iterable[dict]] = None,
    documento_relacionado: Optional[list[dict]] = None,
    emisor: Optional[dict] = None,
    receptor: Optional[dict] = None,
    extension: Optional[dict] = None,
    ambiente: str = "00",
) -> dict:
    """Genera la estructura JSON de una Nota de Remisión."""
    allowed_ext_keys = {
        "nombEntrega",
        "docuEntrega",
        "nombRecibe",
        "docuRecibe",
        "observaciones",
    }
    if factura:
        emisor = factura.get("emisor")
        receptor = factura.get("receptor") or {}
        detalles = detalles or factura.get("cuerpoDocumento", [])
        if documento_relacionado is None:
            ident = factura.get("identificacion", {})
            fecha_emision = fecha_ddmmaaaa(
                ident.get("fecEmi") or ident.get("fechaEmision")
            )
            if not fecha_emision:
                fecha_emision = fecha_ddmmaaaa(datetime.now(TZ_EL_SALVADOR))
            if fecha_emision:
                ident["fecEmi"] = fecha_emision
            codigo_generacion = ident.get("codigoGeneracion")
            numero_control = ident.get("numeroControl")
            if codigo_generacion:
                numero_documento = str(codigo_generacion).upper()
                tipo_generacion = 2
            else:
                numero_documento = str(numero_control or "").strip()
                tipo_generacion = 1
            documento_relacionado = [
                {
                    "tipoDocumento": ident.get("tipoDte"),
                    "tipoGeneracion": tipo_generacion,
                    "numeroDocumento": numero_documento,
                    "fechaEmision": fecha_emision,
                }
            ]
        # Para notas derivadas de factura la extensión puede omitirse
        ext = {
            "nombEntrega": "N/D",
            "docuEntrega": "ND",
            "nombRecibe": "N/D",
            "docuRecibe": "ND",
            "observaciones": "N/D",
        }
        if extension:
            tipo_doc_recibe = extension.pop("tipoDocRecibe", None)
            nrc_recibe = extension.pop("nrcRecibe", None)
            ext.update(
                {
                    k: v
                    for k, v in extension.items()
                    if k in allowed_ext_keys and v not in (None, "")
                }
            )
            receptor.setdefault("nombre", ext.get("nombRecibe"))
            if tipo_doc_recibe == "36":
                receptor["tipoDocumento"] = "36"
                receptor["numDocumento"] = ext.get("docuRecibe")
                if nrc_recibe:
                    receptor["nrc"] = nrc_recibe
            else:
                receptor.setdefault("tipoDocumento", "13")
                receptor.setdefault("numDocumento", ext.get("docuRecibe"))
        receptor.setdefault("bienTitulo", "01")
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
        if not str(ext.get("observaciones", "")).strip():
            raise ValueError("observaciones es obligatoria")

    ext = {k: v for k, v in ext.items() if k in allowed_ext_keys}
    limpiar_documentos(emisor)
    emisor.setdefault("tipoEstablecimiento", "01")
    receptor.setdefault("bienTitulo", "01")
    receptor = normalizar_receptor(receptor)
    for key in ("docuEntrega", "docuRecibe"):
        ext[key] = solo_digitos(ext.get(key))
        if not ext[key]:
            raise ValueError(f"{key} requerido")
    limpiar_documentos(ext)

    cabecera = generar_cabecera_dte_data(1, 1, "04", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    fecha_emision_por_defecto = fecha_ddmmaaaa(now) or fecha_emision_hoy_str(now)
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
        "fecEmi": fecha_emision_por_defecto,
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }

    if documento_relacionado:
        documento_relacionado = _normalizar_documento_relacionado(documento_relacionado)
        fecha_relacionada = documento_relacionado[0].get("fechaEmision")
        if fecha_relacionada:
            identificacion["fecEmi"] = fecha_relacionada
    numero_doc = (
        documento_relacionado[0].get("numeroDocumento")
        if documento_relacionado
        else None
    )
    items = _build_items(detalles, numero_doc)

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
    }
    if documento_relacionado:
        data["documentoRelacionado"] = documento_relacionado

    schema = catalogos.get_dte_schema("04")
    data = sanitize_dte_payload(data, schema)
    if data.get("documentoRelacionado") is None:
        data.pop("documentoRelacionado", None)
    return data


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
        venta = db.get_venta_by_id(venta_id)
        tipo_doc = "01"
        if venta and not db.get_venta_credito_fiscal(venta_id) and not venta.get(
            "cliente_id"
        ):
            tipo_doc = "03"

        from dte import generar_dte_json

        fecha_origen = None
        fecha_origen_source = None
        snapshot = db.get_snapshot_by_venta(venta_id)
        if snapshot:
            try:
                dte_origen = normalize_snapshot(snapshot.payload)
            except Exception:
                dte_origen = None
            else:
                if snapshot.fecha_emision:
                    fecha_origen = fecha_ddmmaaaa(snapshot.fecha_emision)
                    if fecha_origen:
                        fecha_origen_source = "snapshot"
        else:
            dte_origen = None

        if dte_origen is None:
            dte_origen = generar_dte_json(
                db, venta_id, tipo_dte=tipo_doc, ambiente=ambiente
            )

        if not fecha_origen and venta_id is not None:
            fecha_envio = db.get_envio_fecha_emision(venta_id)
            if fecha_envio:
                fecha_origen = fecha_envio
                fecha_origen_source = "envio"

        if not fecha_origen and venta:
            fecha_origen = fecha_ddmmaaaa(venta.get("fecha"))
            if fecha_origen:
                fecha_origen_source = "venta"

        if fecha_origen and isinstance(dte_origen, dict):
            dte_ident = dte_origen.setdefault("identificacion", {})
            if isinstance(dte_ident, dict):
                dte_ident["fecEmi"] = fecha_origen

        logger.info(
            "fecha relacionada para nota %s = %s (origen: %s)",
            nota_id,
            fecha_origen,
            fecha_origen_source or "desconocido",
        )

        extension = extra.get("extension") or {}
        return generar_nota_remision(
            db,
            factura=dte_origen,
            extension=extension,
            ambiente=ambiente,
        )

    factura = extra.get("factura")
    if factura:
        extension = extra.get("extension") or {}
        return generar_nota_remision(
            db, factura=factura, extension=extension, ambiente=ambiente
        )

    # Nota independiente (sin venta asociada)
    from dte import _load_datos_negocio

    detalles = extra.get("items") or []
    receptor = extra.get("receptor") or {}
    extension = extra.get("extension") or {}
    doc_rel = extra.get("documento_relacionado")

    emisor = _load_datos_negocio()
    return generar_nota_remision(
        db,
        emisor=emisor,
        receptor=receptor,
        detalles=detalles,
        documento_relacionado=doc_rel,
        extension=extension,
        ambiente=ambiente,
    )


__all__ = ["generar_nota_remision", "generar_nota_remision_desde_db"]
