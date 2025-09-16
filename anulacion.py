import json
import os
import uuid
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests

import auth
from db import DB
from utils import jws
from utils.catalogos import TRIBUTO_IVA
from utils.sanitize import solo_digitos
from utils.fecha import TZ_EL_SALVADOR

from dte import (
    _load_datos_negocio,
    _load_dte_api_config,
    format_cliente_id_from_dui,
    detect_user_agent,
    build_auth_header,
    _parse_error_response,
    APP_VERSION,
)


UUID36_RE = re.compile(r"^[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}$")
SELLO40_RE = re.compile(r"^[A-Z0-9]{40}$")
NUM_CONTROL_RE = re.compile(r"^DTE-(0[0-9]|1[0-2])-[A-Z0-9]{8}-[0-9]{15}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TEL_EMISOR_RE = re.compile(r"^[0-9+;]{8,26}$")
TEL_RECEPTOR_RE = re.compile(r"^[0-9+;]{8,50}$")

TIPO_ESTABLECIMIENTOS = {"01", "02", "04", "07", "20"}
TIPO_DOC_CAT22 = {"36", "13", "02", "03", "37"}
TIPO_DTE_VALIDOS = {"01", "03", "04", "05", "06", "07", "08", "09", "10", "11", "14", "15"}
TIPO_ANULACION_VALIDOS = {1, 2, 3}
ACCEPTED_EVENT_STATES = {"recibido", "procesado", "aceptado"}
ACCEPTED_EVENT_STATE_ALIASES = {
    "recibida": "recibido",
    "procesada": "procesado",
    "aceptada": "aceptado",
}

ERROR_REEMPLAZO_TIPO_INDETERMINADO = (
    "No se pudo determinar el tipo del DTE de reemplazo; verifica que exista el "
    "documento.json o la respuesta almacenada."
)
ERROR_REEMPLAZO_NO_RECEPCION = (
    "El DTE de reemplazo no existe o no ha sido recepcionado por MH."
)
ERROR_REEMPLAZO_DISTINTO = (
    "El documento de reemplazo debe ser distinto al que se desea anular."
)
ERROR_REEMPLAZO_TIPO = (
    "El DTE de reemplazo debe ser del mismo tipo que el documento a invalidar."
)
ERROR_REEMPLAZO_EMISOR = (
    "El DTE de reemplazo debe pertenecer al mismo emisor que el documento a invalidar."
)
ERROR_REEMPLAZO_FECHA = (
    "El DTE de reemplazo debe tener una fecha de emisión igual o posterior al documento a invalidar."
)


def _load_json_file(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def normalize_ambiente(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in {"00", "01"}:
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits[:2] in {"00", "01"}:
        return digits[:2]
    lowered = text.lower()
    if lowered.startswith("pru") or "prue" in lowered:
        return "00"
    if lowered.startswith("pro"):
        return "01"
    if text == "0":
        return "00"
    if text == "1":
        return "01"
    return text[:2]


def _canonical_event_state(raw: str | None) -> str | None:
    if raw is None:
        return None
    estado = str(raw).strip().lower()
    if not estado:
        return None
    estado = ACCEPTED_EVENT_STATE_ALIASES.get(estado, estado)
    if estado in ACCEPTED_EVENT_STATES:
        return estado
    return None


def _normalize_documento_id(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if not text:
        return ""
    digits = solo_digitos(text)
    if digits:
        return digits
    return text


def _load_dte_json_from_venta(db: DB, venta_id: int | None) -> dict | None:
    if db is None or venta_id is None:
        return None
    try:
        db.ensure_column("ventas", "extra", "TEXT")
    except Exception:
        pass
    try:
        row = db.cursor.execute(
            "SELECT extra FROM ventas WHERE id=?",
            (venta_id,),
        ).fetchone()
    except Exception:
        row = None
    if row and row["extra"]:
        extra_raw = row["extra"]
        extra = None
        if isinstance(extra_raw, str):
            try:
                extra = json.loads(extra_raw)
            except Exception:
                extra = None
        if isinstance(extra, dict):
            for key in ("dteJsonPath", "jsonPath"):
                data = _load_json_file(extra.get(key))
                if data:
                    ident = data.get("identificacion") or {}
                    cod = str(ident.get("codigoGeneracion") or "").upper()
                    if not cod or cod == str(extra.get("codigoGeneracion", "")).upper():
                        return data
    getter = getattr(db, "get_factura_pdf", None)
    pdf_path = None
    if callable(getter):
        try:
            pdf_path = getter(venta_id)
        except Exception:
            pdf_path = None
    if pdf_path:
        json_path = os.path.splitext(pdf_path)[0] + ".json"
        data = _load_json_file(json_path)
        if data:
            ident = data.get("identificacion") or {}
            cod = str(ident.get("codigoGeneracion") or "").upper()
            if cod:
                return data
    return None


def _extract_metadata(source: dict | None) -> dict:
    metadata = {
        "tipo_dte": None,
        "fecha_emision": None,
        "ambiente": None,
        "numero_control": None,
        "emisor_nombre": None,
        "emisor_documento": None,
        "receptor_nombre": None,
        "receptor_documento": None,
        "total": None,
    }
    if not isinstance(source, dict):
        return metadata

    ident = source.get("identificacion")
    if not isinstance(ident, dict):
        ident = source.get("identificacionDocumento")
    if isinstance(ident, dict):
        tipo_val = ident.get("tipoDte") or ident.get("tipoDTE")
        if tipo_val is not None:
            metadata["tipo_dte"] = str(tipo_val).zfill(2)
        fec = ident.get("fecEmi") or ident.get("fechaEmision") or ident.get("fecha")
        if fec is not None:
            metadata["fecha_emision"] = str(fec)[:10]
        num_control = ident.get("numeroControl") or ident.get("numControl")
        if num_control is not None:
            metadata["numero_control"] = str(num_control).strip()
        amb = ident.get("ambiente")
        if amb is not None:
            metadata["ambiente"] = normalize_ambiente(amb)

    emisor = source.get("emisor")
    if not isinstance(emisor, dict):
        for key in ("emisorGenerador", "emisorResponsable", "sujetoGenerador", "transmitente"):
            cand = source.get(key)
            if isinstance(cand, dict):
                emisor = cand
                break
    if isinstance(emisor, dict):
        nombre_emisor = (
            emisor.get("nombre")
            or emisor.get("nombreComercial")
            or emisor.get("razonSocial")
        )
        if nombre_emisor:
            metadata["emisor_nombre"] = str(nombre_emisor).strip()
        doc_emisor = (
            emisor.get("nit")
            or emisor.get("numDocumento")
            or emisor.get("nrc")
            or emisor.get("dui")
        )
        if doc_emisor:
            metadata["emisor_documento"] = str(doc_emisor).strip()

    receptor = source.get("receptor")
    if not isinstance(receptor, dict):
        receptor = source.get("cliente")
    if isinstance(receptor, dict):
        nombre = receptor.get("nombre") or receptor.get("razonSocial")
        if nombre:
            metadata["receptor_nombre"] = str(nombre).strip()
        doc = (
            receptor.get("numDocumento")
            or receptor.get("nit")
            or receptor.get("dui")
            or receptor.get("nrc")
        )
        if doc:
            metadata["receptor_documento"] = str(doc).strip()

    resumen = source.get("resumen")
    if not isinstance(resumen, dict):
        resumen = source.get("totales")
    if isinstance(resumen, dict):
        for key in (
            "montoTotalOperacion",
            "totalPagar",
            "totalPagarSinRedondeo",
            "totalGeneral",
        ):
            val = resumen.get(key)
            if val is not None:
                try:
                    metadata["total"] = float(Decimal(str(val)))
                except (InvalidOperation, TypeError, ValueError):
                    continue
                else:
                    break

    if metadata["ambiente"] is None:
        amb = source.get("ambiente")
        if amb is not None:
            metadata["ambiente"] = normalize_ambiente(amb)

    return metadata


def _merge_metadata(primary: dict, secondary: dict) -> dict:
    for key, value in secondary.items():
        if key not in primary:
            primary[key] = value
            continue
        if primary[key] in (None, "") and value not in (None, ""):
            primary[key] = value
    return primary


def _parse_respuesta_documento(respuesta_raw: str | None) -> dict | None:
    if not respuesta_raw:
        return None
    try:
        data = json.loads(respuesta_raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("documento", "dte", "acuseRecibido", "acuseRecepcion"):
        doc = data.get(key)
        if isinstance(doc, dict):
            if key in {"acuseRecibido", "acuseRecepcion"}:
                inner = doc.get("documento") or doc.get("dte")
                if isinstance(inner, dict):
                    return inner
                continue
            return doc
        if isinstance(doc, str):
            try:
                parsed = json.loads(doc)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
    return None


def buscar_candidatos_reemplazo(db: DB | None, filtros: dict | None = None) -> list[dict]:
    if db is None:
        return []
    filtros = filtros or {}
    try:
        db.ensure_column("dte_envios", "respuesta", "TEXT")
        db.ensure_column("dte_envios", "codigo_generacion", "TEXT")
        db.ensure_column("dte_envios", "numero_control", "TEXT")
        db.ensure_column("dte_envios", "ambiente", "TEXT")
        db.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_dte_envios_codigo_generacion ON dte_envios(codigo_generacion)"
        )
        db.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_dte_envios_fecha_hora ON dte_envios(fecha_hora)"
        )
        db.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_dte_envios_estado ON dte_envios(estado)"
        )
        db.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_dte_envios_ambiente ON dte_envios(ambiente)"
        )
    except Exception:
        pass

    fecha_inicio = filtros.get("fecha_inicio")
    fecha_fin = filtros.get("fecha_fin")
    params: list = []
    query = [
        "SELECT id, venta_id, fecha_hora, modo, estado, TRIM(sello) AS sello,",
        "       TRIM(codigo_generacion) AS codigo_generacion, numero_control,",
        "       respuesta, ambiente",
        "  FROM dte_envios",
        " WHERE TRIM(COALESCE(codigo_generacion, '')) <> ''",
    ]
    if fecha_inicio:
        query.append("   AND date(fecha_hora) >= date(?)")
        params.append(fecha_inicio)
    if fecha_fin:
        query.append("   AND date(fecha_hora) <= date(?)")
        params.append(fecha_fin)
    query.append(" ORDER BY fecha_hora DESC, id DESC")

    try:
        rows = [dict(row) for row in db.cursor.execute("\n".join(query), params).fetchall()]
    except Exception:
        return []

    exclude_uuid = str(filtros.get("exclude_uuid") or "").strip().upper()
    ambiente_objetivo = normalize_ambiente(filtros.get("ambiente"))
    tipo_objetivo = filtros.get("tipo_dte")
    if tipo_objetivo is not None:
        tipo_objetivo = str(tipo_objetivo).zfill(2)
    receptor_docs_raw = filtros.get("receptor_documentos") or []
    receptor_docs = {
        _normalize_documento_id(val)
        for val in receptor_docs_raw
        if _normalize_documento_id(val)
    }
    recepcionado_only = bool(filtros.get("recepcionado", True))
    mismo_receptor = bool(filtros.get("mismo_receptor", True))
    search = str(filtros.get("search") or "").strip().upper()
    limit = filtros.get("limit")
    if isinstance(limit, int) and limit <= 0:
        limit = None

    results: list[dict] = []
    for row in rows:
        codigo = str(row.get("codigo_generacion") or "").strip().upper()
        if not codigo or (exclude_uuid and codigo == exclude_uuid):
            continue

        sello = str(row.get("sello") or "").strip().upper()
        sello_valido = bool(SELLO40_RE.fullmatch(sello))
        estado_canonico = _canonical_event_state(row.get("estado"))

        if recepcionado_only:
            if estado_canonico not in ACCEPTED_EVENT_STATES or not sello_valido:
                continue

        venta_id = row.get("venta_id")
        payload = _load_dte_json_from_venta(db, venta_id)
        respuesta_doc = _parse_respuesta_documento(row.get("respuesta"))
        metadata = _extract_metadata(payload)
        metadata = _merge_metadata(metadata, _extract_metadata(respuesta_doc))

        numero_control = metadata.get("numero_control") or row.get("numero_control")
        ambiente_doc = metadata.get("ambiente") or normalize_ambiente(row.get("ambiente"))
        if ambiente_objetivo and ambiente_doc:
            if ambiente_doc != ambiente_objetivo:
                continue
        elif ambiente_objetivo:
            continue

        tipo_dte = metadata.get("tipo_dte")
        tipo_indeterminado = False
        if tipo_dte is None:
            tipo_indeterminado = True
        elif tipo_objetivo and tipo_dte != tipo_objetivo:
            continue

        receptor_doc = metadata.get("receptor_documento")
        receptor_nombre = metadata.get("receptor_nombre")
        receptor_norm = _normalize_documento_id(receptor_doc)
        coincide_receptor = True
        if receptor_docs:
            coincide_receptor = receptor_norm in receptor_docs
        if mismo_receptor and receptor_docs and not coincide_receptor:
            continue

        total = metadata.get("total")
        fecha_emision = metadata.get("fecha_emision")
        fecha_sort = None
        if fecha_emision:
            try:
                fecha_sort = datetime.strptime(str(fecha_emision), "%Y-%m-%d")
            except Exception:
                fecha_sort = None
        if fecha_sort is None:
            raw_fecha = row.get("fecha_hora")
            if raw_fecha:
                try:
                    fecha_sort = datetime.fromisoformat(raw_fecha)
                except Exception:
                    fecha_sort = None
                else:
                    if not fecha_emision:
                        fecha_emision = str(raw_fecha)[:10]

        if search:
            campos = [
                codigo,
                str(numero_control or "").upper(),
                str(receptor_nombre or "").upper(),
                receptor_norm,
            ]
            if total is not None:
                campos.append(f"{total:.2f}".upper())
            if not any(search in campo for campo in campos if campo):
                continue

        estado_display = estado_canonico or (row.get("estado") or "").strip()
        seleccionable = (
            not tipo_indeterminado
            and estado_canonico in ACCEPTED_EVENT_STATES
            and sello_valido
        )

        candidato = {
            "codigo_generacion": codigo,
            "numero_control": str(numero_control or ""),
            "estado": estado_display,
            "estado_canonico": estado_canonico,
            "con_sello": sello_valido,
            "sello": sello,
            "tipo_dte": tipo_dte,
            "tipo_indeterminado": tipo_indeterminado,
            "emisor_documento": metadata.get("emisor_documento"),
            "emisor_nombre": metadata.get("emisor_nombre"),
            "receptor_nombre": receptor_nombre,
            "receptor_documento": receptor_doc,
            "coincide_receptor": coincide_receptor,
            "total": total,
            "fecha_emision": fecha_emision,
            "ambiente": ambiente_doc,
            "venta_id": venta_id,
            "seleccionable": seleccionable,
            "_sort_key": (
                fecha_sort or datetime.min,
                {
                    "aceptado": 3,
                    "procesado": 2,
                    "recibido": 1,
                }.get(estado_canonico, 0),
            ),
        }
        candidato["preselect"] = bool(
            candidato["seleccionable"]
            and candidato["coincide_receptor"]
            and (tipo_objetivo is None or candidato.get("tipo_dte") == tipo_objetivo)
        )

        results.append(candidato)
        if isinstance(limit, int) and len(results) >= limit:
            break

    results.sort(key=lambda item: item.get("_sort_key", (datetime.min, 0)), reverse=True)
    for item in results:
        item.pop("_sort_key", None)

    return results


def _ensure_replacement_document(db: DB | None, codigo: str) -> dict:
    if db is None:
        raise ValueError(ERROR_REEMPLAZO_TIPO_INDETERMINADO)

    try:
        db.ensure_column("dte_envios", "codigo_generacion", "TEXT")
        db.ensure_column("dte_envios", "numero_control", "TEXT")
        db.ensure_column("dte_envios", "respuesta", "TEXT")
        db.ensure_column("dte_envios", "ambiente", "TEXT")
    except Exception:
        pass

    codigo = (codigo or "").strip().upper()
    row = None
    try:
        row = db.cursor.execute(
            """
            SELECT venta_id, estado, TRIM(sello) AS sello, respuesta, numero_control, ambiente, fecha_hora
              FROM dte_envios
             WHERE UPPER(codigo_generacion)=?
             ORDER BY id DESC LIMIT 1
            """,
            (codigo,),
        ).fetchone()
    except Exception:
        row = None
    if row is None:
        try:
            row = db.cursor.execute(
                """
                SELECT venta_id, estado, TRIM(sello) AS sello, respuesta, numero_control, ambiente, fecha_hora
                  FROM dte_envios
                 WHERE UPPER(respuesta) LIKE ?
                 ORDER BY id DESC LIMIT 1
                """,
                (f"%{codigo}%",),
            ).fetchone()
        except Exception:
            row = None
    if row is None:
        raise ValueError(ERROR_REEMPLAZO_NO_RECEPCION)

    row_dict = dict(row)
    estado_canonico = _canonical_event_state(row_dict.get("estado"))
    sello = str(row_dict.get("sello") or "").strip().upper()
    respuesta_raw = row_dict.get("respuesta")
    if (not SELLO40_RE.fullmatch(sello)) and respuesta_raw:
        try:
            resp_json = json.loads(respuesta_raw)
        except Exception:
            resp_json = None
        else:
            if isinstance(resp_json, dict):
                sello_resp = (
                    str(
                        resp_json.get("selloRecibido")
                        or resp_json.get("selloRecepcion")
                        or resp_json.get("sello")
                        or ""
                    )
                    .strip()
                    .upper()
                )
                if SELLO40_RE.fullmatch(sello_resp):
                    sello = sello_resp
    if not SELLO40_RE.fullmatch(sello) or estado_canonico not in ACCEPTED_EVENT_STATES:
        raise ValueError(ERROR_REEMPLAZO_NO_RECEPCION)

    venta_id = row_dict.get("venta_id")
    payload = _load_dte_json_from_venta(db, venta_id)
    respuesta_doc = _parse_respuesta_documento(respuesta_raw)

    metadata = _extract_metadata(None)
    if payload:
        ident = payload.get("identificacion") or {}
        codigo_archivo = str(ident.get("codigoGeneracion") or "").strip().upper()
        if not codigo_archivo or codigo_archivo == codigo:
            metadata = _merge_metadata(metadata, _extract_metadata(payload))
    if respuesta_doc:
        metadata = _merge_metadata(metadata, _extract_metadata(respuesta_doc))

    if metadata.get("ambiente") is None:
        metadata["ambiente"] = normalize_ambiente(row_dict.get("ambiente"))
    if not metadata.get("numero_control"):
        metadata["numero_control"] = str(row_dict.get("numero_control") or "").strip()
    if not metadata.get("fecha_emision"):
        fecha_raw = row_dict.get("fecha_hora")
        if fecha_raw:
            metadata["fecha_emision"] = str(fecha_raw)[:10]

    tipo_dte = metadata.get("tipo_dte")
    if tipo_dte is None:
        raise ValueError(ERROR_REEMPLAZO_TIPO_INDETERMINADO)

    metadata.update(
        {
            "codigo_generacion": codigo,
            "estado_canonico": estado_canonico,
            "sello": sello,
        }
    )
    return metadata


def _post_invalidacion(
    url: str,
    token: str,
    evento: str,
    evento_data: dict | None = None,
    user_agent: str | None = None,
    auth: dict | None = None,
    opts: dict | None = None,
    app_version: str | None = None,
    dui: str | None = None,
    client_id: str | None = None,
) -> dict:
    token = token or ""
    pu = urlparse(url)
    assert pu.netloc in {
        "apitest.dtes.mh.gob.sv",
        "api.dtes.mh.gob.sv",
    }, f"Host inválido: {url}"
    assert pu.path.rstrip("/") == "/fesv/anulardte", f"Path inválido: {url}"

    body = {"documento": evento}
    if evento_data:
        ident = evento_data.get("identificacion", {})
        ambiente = ident.get("ambiente")
        version = ident.get("version")
        if ambiente:
            body["ambiente"] = ambiente
        if version:
            body["version"] = version

    client_id = client_id or format_cliente_id_from_dui(dui)
    ua = detect_user_agent(user_agent, opts, app_version or APP_VERSION, client_id)
    auth_headers = build_auth_header(
        auth if auth is not None else {"access_token": token},
        app_version=app_version or APP_VERSION,
        client_id=client_id,
    )
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": ua,
        **auth_headers,
    }

    try:
        print(json.dumps(body, ensure_ascii=False))
        resp = requests.post(url, headers=headers, json=body, timeout=20)
    except requests.RequestException as exc:
        return {"estado": "Error", "detalle": str(exc)}

    text = getattr(resp, "text", "")
    try:
        data = resp.json()
    except Exception:
        data = None

    if isinstance(resp.status_code, int) and resp.status_code >= 400:
        detalle = data if data is not None else text
        result = {"estado": "Rechazado", "http_status": resp.status_code, "detalle": detalle}
        if isinstance(data, dict):
            detalle_info = data.get("detalle") if isinstance(data.get("detalle"), dict) else data
            for key in ("descripcionMsg", "observaciones"):
                if key in detalle_info:
                    result[key] = detalle_info[key]
            err = _parse_error_response(result)
            if err:
                result["errores"] = err
        print(json.dumps(result, ensure_ascii=False))
        return result

    result = data if data is not None else {"estado": "Recibido", "detalle": text}
    print(json.dumps(result, ensure_ascii=False))
    return result


def build_invalidacion_json(
    factura: dict, ui_motivo: dict, *, ambiente: str, db: DB | None = None
) -> dict:
    ident = factura.get("identificacion") or {}
    codigo_gen_raw = ident.get("codigoGeneracion")
    numero_control_raw = ident.get("numeroControl")
    fec_emi = ident.get("fecEmi")
    sello_raw = factura.get("selloRecibido")
    if not all([codigo_gen_raw, numero_control_raw, fec_emi, sello_raw]):
        raise ValueError("Factura incompleta para invalidación")

    codigo_gen = str(codigo_gen_raw).strip().upper()
    if not UUID36_RE.fullmatch(codigo_gen):
        raise ValueError("codigoGeneracion de la factura inválido")
    numero_control = str(numero_control_raw).strip().upper()
    if not NUM_CONTROL_RE.fullmatch(numero_control):
        raise ValueError("numeroControl de la factura inválido")
    try:
        datetime.strptime(str(fec_emi), "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("Fecha de emisión del DTE inválida") from exc
    sello = str(sello_raw).strip().upper()
    if not SELLO40_RE.fullmatch(sello):
        raise ValueError("selloRecibido inválido")

    negocio = _load_datos_negocio() or {}
    nit = solo_digitos(negocio.get("nit", ""))
    if len(nit) not in (9, 14):
        raise ValueError("NIT del emisor inválido")

    nombre_emisor = (negocio.get("nombre") or "").strip()
    if not (3 <= len(nombre_emisor) <= 250):
        raise ValueError("Nombre del emisor inválido")

    tipo_estable = str(negocio.get("tipoEstablecimiento") or "01").zfill(2)
    if tipo_estable not in TIPO_ESTABLECIMIENTOS:
        raise ValueError("tipoEstablecimiento del emisor inválido")

    nom_estable_raw = negocio.get("nombreComercial")
    if isinstance(nom_estable_raw, str) and nom_estable_raw.strip():
        nom_estable = nom_estable_raw.strip()
    else:
        nom_estable = nombre_emisor
    if not (3 <= len(nom_estable) <= 150):
        raise ValueError("Nombre de establecimiento inválido")

    cod_estable_mh_raw = negocio.get("codEstableMH")
    cod_estable_mh = None
    if cod_estable_mh_raw not in (None, ""):
        cod_estable_mh = str(cod_estable_mh_raw).strip().zfill(4)
        if len(cod_estable_mh) != 4:
            raise ValueError("codEstableMH inválido")

    cod_estable = str(negocio.get("codEstable") or "1").strip()
    if not (1 <= len(cod_estable) <= 10):
        raise ValueError("codEstable inválido")

    cod_pv_mh_raw = negocio.get("codPuntoVentaMH")
    cod_punto_venta_mh = None
    if cod_pv_mh_raw not in (None, ""):
        cod_punto_venta_mh = str(cod_pv_mh_raw).strip().zfill(4)
        if len(cod_punto_venta_mh) != 4:
            raise ValueError("codPuntoVentaMH inválido")

    cod_punto_venta = str(negocio.get("codPuntoVenta") or "1").strip()
    if not (1 <= len(cod_punto_venta) <= 15):
        raise ValueError("codPuntoVenta inválido")

    telefono = (negocio.get("telefono") or "").strip()
    if not TEL_EMISOR_RE.fullmatch(telefono):
        raise ValueError("Teléfono del emisor inválido")

    correo = (negocio.get("correo") or "").strip()
    if not (3 <= len(correo) <= 100 and EMAIL_RE.fullmatch(correo)):
        raise ValueError("Correo del emisor inválido")

    emisor = {
        "nit": nit,
        "nombre": nombre_emisor,
        "tipoEstablecimiento": tipo_estable,
        "nomEstablecimiento": nom_estable,
        "codEstable": cod_estable,
        "codPuntoVenta": cod_punto_venta,
        "telefono": telefono,
        "correo": correo,
    }
    if cod_estable_mh is not None:
        emisor["codEstableMH"] = cod_estable_mh
    if cod_punto_venta_mh is not None:
        emisor["codPuntoVentaMH"] = cod_punto_venta_mh

    receptor = factura.get("receptor") or {}
    nombre_rec = (receptor.get("nombre") or "").strip()
    if not (5 <= len(nombre_rec) <= 200):
        raise ValueError("Nombre del receptor inválido")

    tip_doc_rec = receptor.get("tipoDocumento") or ("36" if receptor.get("nit") else None)
    tip_doc_rec = str(tip_doc_rec).zfill(2) if tip_doc_rec is not None else None
    if tip_doc_rec not in TIPO_DOC_CAT22:
        raise ValueError("Tipo de documento del receptor inválido")

    num_doc_rec = receptor.get("numDocumento") or receptor.get("nit")
    num_doc_rec = (num_doc_rec or "").strip()
    if not (3 <= len(num_doc_rec) <= 20):
        raise ValueError("Número de documento del receptor inválido")

    tel_rec_raw = receptor.get("telefono")
    tel_rec = None
    if tel_rec_raw not in (None, ""):
        tel_rec = str(tel_rec_raw).strip()
        if not TEL_RECEPTOR_RE.fullmatch(tel_rec):
            raise ValueError("Teléfono del receptor inválido")

    cor_rec_raw = receptor.get("correo")
    cor_rec = None
    if cor_rec_raw not in (None, ""):
        cor_rec = str(cor_rec_raw).strip()
        if len(cor_rec) > 100 or not EMAIL_RE.fullmatch(cor_rec):
            raise ValueError("Correo del receptor inválido")

    resumen = factura.get("resumen") or {}
    monto_iva_decimal = None
    tributos_raw = resumen.get("tributos")
    if tributos_raw in (None, []):
        tributos_list = []
    elif isinstance(tributos_raw, list):
        tributos_list = tributos_raw
    else:
        raise ValueError("Estructura de tributos inválida en el DTE original")
    if tributos_list:
        iva_sum = Decimal("0")
        iva_encontrado = False
        for trib in tributos_list:

            if trib.get("codigo") == TRIBUTO_IVA:
                valor = trib.get("valor")
                if valor is None:
                    continue
                try:
                    iva_sum += Decimal(str(valor))
                except (InvalidOperation, TypeError, ValueError) as exc:
                    raise ValueError("montoIva inválido") from exc
                iva_encontrado = True
        if iva_encontrado:
            monto_iva_decimal = iva_sum

    if monto_iva_decimal is None:
        total_iva = resumen.get("totalIva")
        if total_iva is not None:
            try:
                monto_iva_decimal = Decimal(str(total_iva))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError("montoIva inválido") from exc
    monto_iva_val = None
    if monto_iva_decimal is not None:
        if monto_iva_decimal < 0:
            raise ValueError("montoIva no puede ser negativo")
        try:
            monto_iva_decimal = monto_iva_decimal.quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise ValueError("montoIva inválido") from exc
        monto_iva_val = float(monto_iva_decimal)

    tipo_dte_raw = ident.get("tipoDte")
    tipo_dte_str = str(tipo_dte_raw).zfill(2) if tipo_dte_raw is not None else ""
    if tipo_dte_str not in TIPO_DTE_VALIDOS:
        raise ValueError("tipoDte inválido")

    tipo_anulacion_raw = ui_motivo.get("tipoAnulacion")
    try:
        tipo_anulacion = int(tipo_anulacion_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("tipoAnulacion inválido") from exc
    if tipo_anulacion not in TIPO_ANULACION_VALIDOS:
        raise ValueError("tipoAnulacion inválido")

    motivo_raw = ui_motivo.get("motivoAnulacion")
    if isinstance(motivo_raw, str):
        motivo_val = motivo_raw.strip()
        if not motivo_val:
            motivo_val = None
    elif motivo_raw is None:
        motivo_val = None
    else:
        raise ValueError("motivoAnulacion inválido")

    if tipo_anulacion == 3:
        if not motivo_val or not (5 <= len(motivo_val) <= 250):
            raise ValueError("motivoAnulacion requerido cuando tipoAnulacion es 3")
    elif motivo_val is not None and not (5 <= len(motivo_val) <= 250):
        raise ValueError("motivoAnulacion inválido")

    codigo_generacion_r = None
    if tipo_anulacion == 2:
        codigo_generacion_r = None
    else:
        codigo_generacion_r_raw = ui_motivo.get("codigoGeneracionR")
        if not isinstance(codigo_generacion_r_raw, str) or not codigo_generacion_r_raw.strip():
            raise ValueError(
                "Primero emite el DTE corregido y captura su código de generación (con sello). "
                "Ingresa ese código en 'Documento que reemplaza'."
            )
        codigo_generacion_r = codigo_generacion_r_raw.strip().upper()
        if not UUID36_RE.fullmatch(codigo_generacion_r):
            raise ValueError(
                "El código de generación debe ser un UUID de 36 caracteres en mayúsculas con guiones."
            )
        if codigo_generacion_r == codigo_gen:
            raise ValueError(ERROR_REEMPLAZO_DISTINTO)
        reemplazo = _ensure_replacement_document(db, codigo_generacion_r)
        tipo_reemplazo = reemplazo.get("tipo_dte")
        if tipo_reemplazo != tipo_dte_str:
            raise ValueError(ERROR_REEMPLAZO_TIPO)

        emisor_original_doc = None
        emisor_factura = factura.get("emisor") or {}
        for key in ("nit", "numDocumento", "nrc", "dui"):
            val = emisor_factura.get(key)
            if val:
                emisor_original_doc = str(val)
                break
        emisor_original_norm = _normalize_documento_id(emisor_original_doc)
        emisor_reemplazo_norm = _normalize_documento_id(
            reemplazo.get("emisor_documento")
        )
        if emisor_original_norm and emisor_reemplazo_norm:
            if emisor_original_norm != emisor_reemplazo_norm:
                raise ValueError(ERROR_REEMPLAZO_EMISOR)
        elif emisor_original_norm:
            raise ValueError(ERROR_REEMPLAZO_EMISOR)

        fecha_reemplazo = reemplazo.get("fecha_emision")
        if fecha_reemplazo:
            try:
                fecha_reemplazo_dt = datetime.strptime(str(fecha_reemplazo)[:10], "%Y-%m-%d")
                fecha_original_dt = datetime.strptime(str(fec_emi), "%Y-%m-%d")
            except Exception:
                fecha_reemplazo_dt = None
                fecha_original_dt = None
            if (
                fecha_reemplazo_dt is not None
                and fecha_original_dt is not None
                and fecha_reemplazo_dt < fecha_original_dt
            ):
                raise ValueError(ERROR_REEMPLAZO_FECHA)

    def _val_persona(nombre, tip, num, *, sujeto: str):
        nombre_val = (nombre or "").strip()
        if not (5 <= len(nombre_val) <= 100):
            raise ValueError(f"Nombre de {sujeto} inválido")
        tip_val = str(tip or "").zfill(2)
        if tip_val not in TIPO_DOC_CAT22:
            raise ValueError(f"Tipo de documento de {sujeto} inválido")
        num_val = (num or "").strip()
        if not (3 <= len(num_val) <= 20):
            raise ValueError(f"Número de documento de {sujeto} inválido")
        return nombre_val, tip_val, num_val

    nombre_resp, tip_resp, num_resp = _val_persona(
        ui_motivo.get("nombreResponsable"),
        ui_motivo.get("tipDocResponsable"),
        ui_motivo.get("numDocResponsable"),
        sujeto="responsable",
    )
    nombre_sol, tip_sol, num_sol = _val_persona(
        ui_motivo.get("nombreSolicita"),
        ui_motivo.get("tipDocSolicita"),
        ui_motivo.get("numDocSolicita"),
        sujeto="solicitante",
    )

    now = datetime.now(TZ_EL_SALVADOR)
    identificacion = {
        "version": 2,
        "ambiente": "01" if str(ambiente).startswith("01") else "00",
        "codigoGeneracion": str(uuid.uuid4()).upper(),
        "fecAnula": now.strftime("%Y-%m-%d"),
        "horAnula": now.strftime("%H:%M:%S"),
    }

    documento = {
        "tipoDte": tipo_dte_str,
        "codigoGeneracion": codigo_gen,
        "selloRecibido": sello,
        "numeroControl": numero_control,
        "fecEmi": str(fec_emi),
        "montoIva": monto_iva_val,
        "codigoGeneracionR": codigo_generacion_r,
        "tipoDocumento": tip_doc_rec,
        "numDocumento": num_doc_rec,
        "nombre": nombre_rec,
    }
    if tel_rec is not None:
        documento["telefono"] = tel_rec
    if cor_rec is not None:
        documento["correo"] = cor_rec

    motivo_section = {
        "tipoAnulacion": tipo_anulacion,
        "motivoAnulacion": motivo_val,
        "nombreResponsable": nombre_resp,
        "tipDocResponsable": tip_resp,
        "numDocResponsable": num_resp,
        "nombreSolicita": nombre_sol,
        "tipDocSolicita": tip_sol,
        "numDocSolicita": num_sol,
    }

    return {
        "identificacion": identificacion,
        "emisor": emisor,
        "documento": documento,
        "motivo": motivo_section,
    }


def enviar_invalidacion(db: DB, data: dict) -> dict:
    config = _load_dte_api_config()
    pu = urlparse(config["url"])
    url = f"{pu.scheme}://{pu.netloc}/fesv/anulardte"
    signed = jws.sign_json(data)
    token = auth.get_token()
    respuesta = _post_invalidacion(url, token, signed, data)
    sello = respuesta.get("sello") or respuesta.get("selloRecepcion") or ""
    estado = (
        respuesta.get("estado")
        or respuesta.get("estadoEvento")
        or respuesta.get("descripcionEstado")
        or "Transmitido"
    )
    detalle = respuesta.get("detalle")
    res = {"estado": estado, "sello": sello}
    if detalle:
        res["detalle"] = detalle
    if respuesta.get("errores"):
        res["errores"] = respuesta["errores"]
    return res

