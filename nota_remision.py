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
import re
from typing import Iterable, Optional

import logging

from db import DB
from dte import (
    DTE_VERSIONES,
    generar_cabecera_dte_data,
    sanitize_dte_payload,
    normalize_uuid_v4_upper,
)
from utils import catalogos
from utils.fecha import (
    TZ_EL_SALVADOR,
    fecha_ddmmaaaa,
    fecha_emision_hoy_str,
    fecha_iso,
)
from utils.monto import monto_a_texto_sv, d2
from utils.snapshot import normalize_snapshot
import warnings

from utils.sanitize import limpiar_documentos, solo_digitos

Decimal_0 = Decimal("0")


_RE_NUM_CONTROL = re.compile(r"^DTE-(\d{2})-S\d{3}P\d{3}-\d{15}$", re.IGNORECASE)


def _tipos_dte_validos() -> set[str]:
    """Obtiene el conjunto de tipos de DTE válidos desde el catálogo."""

    tipos: set[str] = set()
    for key in catalogos.DTE_TIPOS.keys():
        if isinstance(key, int):
            tipos.add(f"{key:02d}")
            continue
        key_str = str(key).strip()
        if key_str.isdigit():
            try:
                tipos.add(f"{int(key_str):02d}")
            except Exception:
                tipos.add(key_str)
        elif key_str:
            tipos.add(key_str)
    return tipos


_TIPOS_DTE_VALIDOS = _tipos_dte_validos()
_ESTADOS_REL_PERMITIDOS = {"Enviado", "Aceptado"}


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
    """Valida y normaliza ``documento_relacionado`` respetando el número original."""

    if not isinstance(doc_rel, list) or not doc_rel:
        raise ValueError("documento_relacionado debe ser una lista no vacía")

    raw = doc_rel[0] or {}
    tipo_raw = raw.get("tipoDocumento")
    if isinstance(tipo_raw, int):
        tipo = f"{tipo_raw:02d}"
    elif isinstance(tipo_raw, str):
        tipo_str = tipo_raw.strip()
        if tipo_str.isdigit() and len(tipo_str) <= 2:
            tipo = f"{int(tipo_str):02d}"
        else:
            tipo = tipo_str or None
    else:
        tipo = None

    if tipo not in _TIPOS_DTE_VALIDOS:
        raise ValueError("tipoDocumento inválido en documento_relacionado")

    numero = raw.get("numeroDocumento")
    codigo_generacion = raw.get("codigoGeneracion")
    if codigo_generacion:
        codigo_generacion_str = str(codigo_generacion).strip()
        if not codigo_generacion_str:
            raise ValueError("codigoGeneracion inválido en documento_relacionado")
        try:
            codigo_generacion = normalize_uuid_v4_upper(codigo_generacion_str)
        except Exception:
            codigo_generacion = codigo_generacion_str.upper()
        numero = codigo_generacion
    if not numero:
        raise ValueError(
            "documento_relacionado requiere numeroDocumento y fechaEmision"
        )
    numero = str(numero).strip()

    fecha = raw.get("fechaEmision")
    fecha_normalizada = fecha_ddmmaaaa(fecha)
    if not fecha_normalizada:
        raise ValueError("fechaEmision inválida en documento_relacionado")

    tipo_generacion = raw.get("tipoGeneracion")
    if isinstance(tipo_generacion, str) and tipo_generacion.isdigit():
        tipo_generacion = int(tipo_generacion)
    if tipo_generacion not in {1, 2}:
        if codigo_generacion:
            tipo_generacion = 2
        elif _RE_NUM_CONTROL.fullmatch(numero):
            tipo_generacion = 1
        else:
            try:
                numero = normalize_uuid_v4_upper(numero)
            except Exception:
                tipo_generacion = 1
            else:
                tipo_generacion = 2

    if tipo_generacion == 2:
        try:
            numero_documento = normalize_uuid_v4_upper(numero)
        except Exception:
            numero_documento = str(numero).strip().upper()
            if not numero_documento:
                raise ValueError(
                    "numeroDocumento inválido para tipoGeneracion=2"
                )
    else:
        if not _RE_NUM_CONTROL.fullmatch(numero):
            raise ValueError(
                "numeroDocumento inválido para tipoGeneracion=1"
            )
        numero_documento = numero.upper()
        if tipo_generacion == 1:
            match = _RE_NUM_CONTROL.fullmatch(numero_documento)
            if match:
                tipo_from_num = match.group(1)
                if tipo_from_num != tipo:
                    raise ValueError(
                        "tipoDocumento no coincide con el prefijo de numeroDocumento"
                    )

    resultado = {
        "tipoDocumento": tipo,
        "tipoGeneracion": tipo_generacion,
        "numeroDocumento": numero_documento,
        "fechaEmision": fecha_iso(fecha_normalizada),
    }
    if codigo_generacion:
        resultado["codigoGeneracion"] = codigo_generacion

    return [resultado]


def _verificar_documento_relacionado_recepcionado(db: DB, doc_rel: list[dict]) -> None:
    """Valida que el documento relacionado tenga estado recepcionado localmente."""

    if not doc_rel:
        return

    doc = doc_rel[0]
    tipo_generacion = doc.get("tipoGeneracion")
    codigo_generacion = doc.get("codigoGeneracion")
    numero_documento = doc.get("numeroDocumento")

    codigo_consulta = None
    numero_consulta = None
    if tipo_generacion == 2:
        codigo_consulta = (codigo_generacion or numero_documento or "").strip().upper()
    elif tipo_generacion == 1:
        numero_consulta = (numero_documento or "").strip().upper()
        if codigo_generacion:
            codigo_consulta = str(codigo_generacion).strip().upper()
    else:
        if codigo_generacion:
            codigo_consulta = str(codigo_generacion).strip().upper()
        if not codigo_consulta and numero_documento:
            numero_consulta = str(numero_documento).strip().upper()

    for column, definition in (
        ("codigo_lote", "TEXT"),
        ("codigo_generacion", "TEXT"),
        ("numero_control", "TEXT"),
        ("estado_ui", "TEXT"),
        ("estado_ui_tag", "TEXT"),
    ):
        db.ensure_column("dte_envios", column, definition)

    row = None
    if codigo_consulta:
        row = db.cursor.execute(
            """
            SELECT estado_ui FROM dte_envios
            WHERE codigo_generacion IS NOT NULL AND codigo_generacion = ?
            ORDER BY id DESC LIMIT 1
            """,
            (codigo_consulta,),
        ).fetchone()
    if row is None and numero_consulta:
        row = db.cursor.execute(
            """
            SELECT estado_ui FROM dte_envios
            WHERE numero_control IS NOT NULL AND numero_control = ?
            ORDER BY id DESC LIMIT 1
            """,
            (numero_consulta,),
        ).fetchone()

    if row is None:
        raise ValueError(
            "El documento relacionado aún no ha sido recepcionado por MH (sin registro local)"
        )

    try:
        estado_ui = row["estado_ui"]
    except Exception:
        estado_ui = row[0] if row else None

    if (estado_ui or "").strip() not in _ESTADOS_REL_PERMITIDOS:
        raise ValueError(
            "El documento relacionado aún no ha sido recepcionado por MH"
        )


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
    fecha_documento_relacionado: Optional[str] = None,
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
                    "fechaEmision": fecha_iso(fecha_emision),
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
    fec_emi_hoy_iso = fecha_iso(fecha_emision_por_defecto)
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
        "fecEmi": fec_emi_hoy_iso,
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }
    # NOTAS (04/05/06):
    # - identificacion.fecEmi = hoy (se reafirma en enviar_* y _enviar_documento).
    # - documentoRelacionado[].fechaEmision = fecha histórica del DTE base.
    #   Nunca copiar la histórica hacia fecEmi.

    if documento_relacionado:
        documento_relacionado = _normalizar_documento_relacionado(documento_relacionado)
        _verificar_documento_relacionado_recepcionado(db, documento_relacionado)
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
        if fecha_documento_relacionado:
            fecha_doc = fecha_ddmmaaaa(fecha_documento_relacionado)
            if fecha_doc:
                documento_relacionado[0]["fechaEmision"] = fecha_iso(fecha_doc)
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
            fecha_documento_relacionado=fecha_origen,
        )

    factura = extra.get("factura")
    if factura:
        extension = extra.get("extension") or {}
        return generar_nota_remision(
            db,
            factura=factura,
            extension=extension,
            ambiente=ambiente,
            fecha_documento_relacionado=extra.get("fecha_documento_relacionado"),
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
        fecha_documento_relacionado=extra.get("fecha_documento_relacionado"),
    )


__all__ = ["generar_nota_remision", "generar_nota_remision_desde_db"]
