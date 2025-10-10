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
import json
import re
from typing import Iterable, Optional

import logging

from db import DB
from dte import (
    DTE_VERSIONES,
    generar_cabecera_dte_data,
    sanitize_dte_payload,
    normalize_uuid_v4_upper,
    resolve_ambiente,
    _map_estado_hacienda,
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
from utils.identificacion import is_valid_nit

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


def _normalize_tipo_dte(value) -> Optional[str]:
    """Normaliza ``value`` a un código de tipo DTE de dos dígitos."""

    if value is None:
        return None
    if isinstance(value, int):
        candidate = f"{value:02d}"
    else:
        value_str = str(value).strip()
        if not value_str:
            return None
        if value_str.isdigit():
            candidate = f"{int(value_str):02d}"
        else:
            candidate = value_str
    candidate = candidate.zfill(2) if candidate.isdigit() else candidate
    if candidate in _TIPOS_DTE_VALIDOS:
        return candidate
    return None


def _build_documento_relacionado_desde_dte(
    factura: dict, *, tipo_documento_hint: Optional[str] = None
) -> list[dict]:
    """Construye ``documentoRelacionado`` preservando el tipo del DTE origen."""

    ident = factura.get("identificacion") or {}
    tipo_origen = _normalize_tipo_dte(ident.get("tipoDte"))
    hint_norm = _normalize_tipo_dte(tipo_documento_hint)
    if tipo_origen:
        tipo_doc = tipo_origen
        tipo_source = "tipoDte"
    elif hint_norm:
        tipo_doc = hint_norm
        tipo_source = "hint"
    else:
        receptor = factura.get("receptor") or {}
        nrc = solo_digitos(receptor.get("nrc"))
        tipo_doc = "03" if nrc else "01"
        tipo_source = "receptor.nrc"

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "NR documentoRelacionado: tipo_origen=%s → tipo_doc_rel=%s (source=%s)",
            tipo_origen if tipo_origen is not None else ident.get("tipoDte"),
            tipo_doc,
            tipo_source,
        )

    fecha_emision = fecha_ddmmaaaa(ident.get("fecEmi") or ident.get("fechaEmision"))
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
            "tipoDocumento": tipo_doc,
            "tipoGeneracion": tipo_generacion,
            "numeroDocumento": numero_documento,
            "fechaEmision": fecha_iso(fecha_emision),
        }
    ]
    if codigo_generacion:
        documento_relacionado[0]["codigoGeneracion"] = numero_documento
    return documento_relacionado


def _fetch_envio_estado_ui(
    db: DB, *, codigo: Optional[str], numero: Optional[str]
) -> Optional[str]:
    """Obtiene ``estado_ui`` (o equivalente) de ``dte_envios`` para NR."""

    for column, definition in (
        ("codigo_generacion", "TEXT"),
        ("numero_control", "TEXT"),
        ("estado_ui", "TEXT"),
        ("estado", "TEXT"),
        ("respuesta", "TEXT"),
    ):
        db.ensure_column("dte_envios", column, definition)

    cur = db.cursor
    row = None
    row_source = None
    codigo = (codigo or "").strip()
    numero = (numero or "").strip()
    if codigo:
        row = cur.execute(
            """
            SELECT id, estado_ui, estado, respuesta
            FROM dte_envios
            WHERE codigo_generacion IS NOT NULL AND codigo_generacion = ?
            ORDER BY id DESC LIMIT 1
            """,
            (codigo,),
        ).fetchone()
        if row is not None:
            row_source = "codigo"
    if row is None and numero:
        row = cur.execute(
            """
            SELECT id, estado_ui, estado, respuesta
            FROM dte_envios
            WHERE numero_control IS NOT NULL AND numero_control = ?
            ORDER BY id DESC LIMIT 1
            """,
            (numero,),
        ).fetchone()
        if row is not None:
            row_source = "numero"

    if row is None:
        token = codigo or numero
        if token:
            patterns: list[str] = []
            if codigo:
                patterns.append(f'%"codigoGeneracion":"{codigo}"%')
                patterns.append(f'%"codigoGeneracion":"{codigo}%')
            if numero:
                patterns.append(f'%"numeroControl":"{numero}"%')
                patterns.append(f'%"numeroControl":"{numero}%')
            patterns.append(f"%{token}%")
            for pattern in patterns:
                row = cur.execute(
                    """
                    SELECT id, estado_ui, estado, respuesta
                    FROM dte_envios
                    WHERE respuesta LIKE ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (pattern,),
                ).fetchone()
                if row is not None:
                    row_source = "respuesta"
                    break

    if row is None:
        logger.debug(
            "NR relacionado: sin coincidencia para codigo=%s numero=%s", codigo, numero
        )
        return None

    try:
        row_id = row["id"]
        estado_ui = (row["estado_ui"] or "").strip()
        estado_raw = (row["estado"] or "").strip()
        respuesta_raw = row["respuesta"] or ""
    except Exception:
        row_id = row[0]
        estado_ui = (row[1] or "").strip()
        estado_raw = (row[2] or "").strip()
        respuesta_raw = row[3] or ""

    if estado_ui:
        logger.debug(
            "NR relacionado: estado_ui=%s obtenido por %s (id=%s)",
            estado_ui,
            row_source,
            row_id,
        )
        return estado_ui

    try:
        respuesta_json = json.loads(respuesta_raw) if respuesta_raw else {}
    except Exception:
        respuesta_json = {}

    if respuesta_json:
        try:
            estado_map = _map_estado_hacienda(respuesta_json)
        except Exception:
            estado_map = {}
        ui = (estado_map.get("ui") or "").strip() if isinstance(estado_map, dict) else ""
        if ui:
            if not estado_ui and row_id is not None:
                try:
                    cur.execute(
                        "UPDATE dte_envios SET estado_ui = ? WHERE id = ?",
                        (ui, row_id),
                    )
                    db.conn.commit()
                    logger.info(
                        "NR relacionado: backfill estado_ui=%s por JSON (id=%s, fuente=%s)",
                        ui,
                        row_id,
                        row_source,
                    )
                except Exception:
                    logger.exception(
                        "NR relacionado: fallo backfill estado_ui=%s id=%s", ui, row_id
                    )
            logger.debug(
                "NR relacionado: ui derivado de JSON=%s (id=%s, fuente=%s)",
                ui,
                row_id,
                row_source,
            )
            return ui

    estado_up = estado_raw.upper()
    ui = None
    if "ACEPT" in estado_up:
        ui = "Aceptado"
    elif any(token in estado_up for token in ("PROCES", "RECIB", "TRANSMIT")):
        ui = "Enviado"
    elif "RECHAZ" in estado_up:
        ui = "Rechazado"

    if ui and not estado_ui and row_id is not None:
        try:
            cur.execute(
                "UPDATE dte_envios SET estado_ui = ? WHERE id = ?",
                (ui, row_id),
            )
            db.conn.commit()
            logger.info(
                "NR relacionado: backfill estado_ui=%s por estado (id=%s, fuente=%s)",
                ui,
                row_id,
                row_source,
            )
        except Exception:
            logger.exception(
                "NR relacionado: fallo backfill estado_ui=%s id=%s", ui, row_id
            )

    if ui:
        logger.debug(
            "NR relacionado: ui derivado de estado=%s (id=%s, fuente=%s)",
            ui,
            row_id,
            row_source,
        )
    else:
        logger.debug(
            "NR relacionado: sin ui derivado (id=%s, fuente=%s)", row_id, row_source
        )
    return ui


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

    nrc_raw = receptor.get("nrc")
    if nrc_raw is not None:
        nrc = solo_digitos(nrc_raw)
        if nrc:
            receptor["nrc"] = nrc
        else:
            receptor["nrc"] = None

    if tipo == "13":
        if len(num) != 9:
            raise ValueError("DUI debe tener 9 dígitos (sin guiones)")
        receptor["numDocumento"] = f"{num[:8]}-{num[-1]}"
        if nrc_raw:
            warnings.warn(
                "Se forzó NRC=null porque el documento es DUI", UserWarning
            )
        receptor["nrc"] = None
    elif tipo == "36":
        if not is_valid_nit(num):
            raise ValueError("NIT debe tener 9 o 14 dígitos (sin guiones)")
        nrc = receptor.get("nrc")
        if not nrc or len(nrc) not in (6, 7):
            raise ValueError("NRC requerido (6–7 dígitos)")
    elif tipo in {"37", "03", "02"}:
        receptor["nrc"] = None
    else:
        raise ValueError("tipoDocumento inválido en receptor")
    # Campos adicionales requeridos para receptores
    for campo in ("telefono", "correo"):
        if not receptor.get(campo):
            raise ValueError(f"receptor requiere {campo}")

    for campo in ("codActividad", "descActividad"):
        value = receptor.get(campo)
        if value is None:
            receptor[campo] = None
        else:
            receptor[campo] = str(value).strip() or None

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
    codigo_generacion = (doc.get("codigoGeneracion") or "").strip().upper()
    numero_documento = (doc.get("numeroDocumento") or "").strip().upper()

    codigo_consulta: Optional[str] = None
    numero_consulta: Optional[str] = None
    if tipo_generacion == 2:
        codigo_consulta = codigo_generacion or numero_documento or None
    elif tipo_generacion == 1:
        numero_consulta = numero_documento or None
        if codigo_generacion:
            codigo_consulta = codigo_generacion
    else:
        if codigo_generacion:
            codigo_consulta = codigo_generacion
        if not codigo_consulta and numero_documento:
            numero_consulta = numero_documento or None

    estado_ui = _fetch_envio_estado_ui(
        db, codigo=codigo_consulta, numero=numero_consulta
    )

    if estado_ui is None:
        raise ValueError(
            "El documento relacionado aún no ha sido recepcionado por MH (sin registro local)"
        )

    if estado_ui == "Rechazado":
        raise ValueError("El documento relacionado fue RECHAZADO por MH")

    if estado_ui not in _ESTADOS_REL_PERMITIDOS:
        raise ValueError(
            "El documento relacionado aún no ha sido recepcionado por MH"
        )


def generar_nota_remision(
    db: DB,
    factura: Optional[dict] = None,
    *,
    detalles: Optional[Iterable[dict]] = None,
    documento_relacionado: Optional[list[dict]] = None,
    tipo_documento_relacionado_hint: Optional[str] = None,
    verificar_documento_relacionado: bool = True,
    emisor: Optional[dict] = None,
    receptor: Optional[dict] = None,
    extension: Optional[dict] = None,
    ambiente: str = "00",
    fecha_documento_relacionado: Optional[str] = None,
) -> dict:
    """Genera la estructura JSON de una Nota de Remisión."""
    ambiente = resolve_ambiente(ambiente)
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
        if isinstance(receptor, dict):
            if not receptor.get("tipoDocumento"):
                doc_val = solo_digitos(receptor.get("numDocumento"))
                nit_val = solo_digitos(receptor.get("nit"))
                candidato = doc_val or nit_val
                if candidato:
                    if len(candidato) == 14:
                        receptor["tipoDocumento"] = "36"
                        receptor.setdefault("numDocumento", candidato)
                    elif len(candidato) == 9:
                        receptor["tipoDocumento"] = "13"
                        receptor.setdefault("numDocumento", candidato)
            if receptor.get("nrc"):
                nrc_val = solo_digitos(receptor.get("nrc"))
                receptor["nrc"] = nrc_val or receptor.get("nrc")
            if not receptor.get("telefono"):
                receptor["telefono"] = "00000000"
            if not receptor.get("correo"):
                receptor["correo"] = "no-reply@example.com"
        detalles = detalles or factura.get("cuerpoDocumento", [])
        if documento_relacionado is None:
            documento_relacionado = _build_documento_relacionado_desde_dte(
                factura, tipo_documento_hint=tipo_documento_relacionado_hint
            )
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
        if verificar_documento_relacionado:
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
    ambiente = resolve_ambiente(ambiente)
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
        credito_fiscal = bool(db.get_venta_credito_fiscal(venta_id)) if venta else False
        tipo_doc = "03" if credito_fiscal else "01"
        tipo_doc_source = "venta_credito_fiscal" if credito_fiscal else "consumidor_final"
        logger.debug(
            "NR base: venta_id=%s tipo_doc_hint=%s (source=%s)",
            venta_id,
            tipo_doc,
            tipo_doc_source,
        )

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
                tipo_snapshot = _normalize_tipo_dte(
                    (dte_origen.get("identificacion") or {}).get("tipoDte")
                )
                if tipo_snapshot:
                    tipo_doc = tipo_snapshot
                    tipo_doc_source = "snapshot"
                    logger.debug(
                        "NR base: venta_id=%s tipo_doc_hint actualizado a %s por snapshot",
                        venta_id,
                        tipo_doc,
                    )
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

        if venta_id and isinstance(dte_origen, dict):
            ident_origen = dte_origen.get("identificacion") or {}
            codigo_origen = (ident_origen.get("codigoGeneracion") or "").strip().upper()
            numero_ctrl_origen = (ident_origen.get("numeroControl") or "").strip().upper()
            if codigo_origen or numero_ctrl_origen:
                try:
                    db.ensure_column("dte_envios", "codigo_generacion", "TEXT")
                    db.ensure_column("dte_envios", "numero_control", "TEXT")
                    db.cursor.execute(
                        """
                        UPDATE dte_envios
                        SET codigo_generacion = CASE
                                WHEN (codigo_generacion IS NULL OR codigo_generacion = '') AND ? IS NOT NULL THEN ?
                                ELSE codigo_generacion
                            END,
                            numero_control = CASE
                                WHEN (numero_control IS NULL OR numero_control = '') AND ? IS NOT NULL THEN ?
                                ELSE numero_control
                            END
                        WHERE venta_id = ?
                        """,
                        (
                            codigo_origen or None,
                            codigo_origen or None,
                            numero_ctrl_origen or None,
                            numero_ctrl_origen or None,
                            venta_id,
                        ),
                    )
                    db.conn.commit()
                except Exception:
                    logger.debug(
                        "NR base: no se pudo actualizar dte_envios con código del documento", exc_info=True
                    )

        tipo_final = _normalize_tipo_dte(
            (dte_origen.get("identificacion") or {}).get("tipoDte")
        )
        if tipo_final and tipo_final != tipo_doc:
            logger.debug(
                "NR base: venta_id=%s tipo_doc_hint ajustado a %s por DTE origen",
                venta_id,
                tipo_final,
            )
            tipo_doc = tipo_final

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
            tipo_documento_relacionado_hint=tipo_doc,
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
            verificar_documento_relacionado=False,
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
        verificar_documento_relacionado=False,
    )


__all__ = ["generar_nota_remision", "generar_nota_remision_desde_db"]
