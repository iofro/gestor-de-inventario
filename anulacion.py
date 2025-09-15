import json
import uuid
import re
from datetime import datetime
from decimal import Decimal
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
        print(json.dumps(result, ensure_ascii=False))
        return result

    result = data if data is not None else {"estado": "Recibido", "detalle": text}
    print(json.dumps(result, ensure_ascii=False))
    return result


def build_invalidacion_json(factura: dict, ui_motivo: dict, *, ambiente: str) -> dict:
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

    nom_estable_raw = negocio.get("nombreComercial") or nombre_emisor
    nom_estable = nom_estable_raw.strip() if isinstance(nom_estable_raw, str) else None
    if nom_estable and not (3 <= len(nom_estable) <= 150):
        raise ValueError("Nombre de establecimiento inválido")
    if not nom_estable:
        nom_estable = None

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
        "codEstableMH": cod_estable_mh,
        "codEstable": cod_estable,
        "codPuntoVentaMH": cod_punto_venta_mh,
        "codPuntoVenta": cod_punto_venta,
        "telefono": telefono,
        "correo": correo,
    }

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
    monto_iva = resumen.get("totalIva")
    if monto_iva is None:
        for trib in resumen.get("tributos", []):
            if trib.get("codigo") == TRIBUTO_IVA:
                monto_iva = trib.get("valor")
                break
    monto_iva_val = None
    if monto_iva is not None:
        try:
            monto_iva_val = Decimal(str(monto_iva))
        except Exception as exc:
            raise ValueError("montoIva inválido") from exc
        if monto_iva_val < 0:
            raise ValueError("montoIva no puede ser negativo")
        monto_iva_val = float(monto_iva_val.quantize(Decimal("0.01")))

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
    elif motivo_raw is None:
        motivo_val = None
    else:
        raise ValueError("motivoAnulacion inválido")

    if tipo_anulacion == 3:
        if not motivo_val or not (5 <= len(motivo_val) <= 250):
            raise ValueError("motivoAnulacion requerido cuando tipoAnulacion es 3")
    elif motivo_val:
        if not (5 <= len(motivo_val) <= 250):
            raise ValueError("motivoAnulacion inválido")
    else:
        motivo_val = None

    codigo_generacion_r = None
    if tipo_anulacion == 2:
        codigo_generacion_r = None
    else:
        codigo_generacion_r_raw = ui_motivo.get("codigoGeneracionR")
        if not isinstance(codigo_generacion_r_raw, str) or not codigo_generacion_r_raw.strip():
            raise ValueError("codigoGeneracionR requerido para este tipo de anulación")
        codigo_generacion_r = codigo_generacion_r_raw.strip().upper()
        if not UUID36_RE.fullmatch(codigo_generacion_r):
            raise ValueError("codigoGeneracionR inválido")

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
        "telefono": tel_rec,
    }
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

