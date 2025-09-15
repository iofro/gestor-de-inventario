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
    codigo_gen = ident.get("codigoGeneracion")
    numero_control = ident.get("numeroControl")
    fec_emi = ident.get("fecEmi")
    sello = factura.get("selloRecibido")
    if not all([codigo_gen, numero_control, fec_emi, sello]):
        raise ValueError("Factura incompleta para invalidación")

    negocio = _load_datos_negocio()
    nit = solo_digitos(negocio.get("nit", ""))
    if len(nit) not in (9, 14):
        raise ValueError("NIT del emisor inválido")

    telefono = negocio.get("telefono", "")
    correo = negocio.get("correo", "")
    if not re.fullmatch(r"[0-9+;]{8,26}", telefono or ""):
        raise ValueError("Teléfono del emisor inválido")
    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", correo or ""):
        raise ValueError("Correo del emisor inválido")

    emisor = {
        "nit": nit,
        "nombre": negocio.get("nombre"),
        "tipoEstablecimiento": str(negocio.get("tipoEstablecimiento") or "01").zfill(2),
        "nomEstablecimiento": negocio.get("nombreComercial") or negocio.get("nombre"),
        "codEstableMH": str(negocio.get("codEstableMH") or "0001").zfill(4),
        "codEstable": str(negocio.get("codEstable") or "1"),
        "codPuntoVentaMH": str(negocio.get("codPuntoVentaMH") or "0001").zfill(4),
        "codPuntoVenta": str(negocio.get("codPuntoVenta") or "1"),
        "telefono": telefono,
        "correo": correo,
    }

    receptor = factura.get("receptor") or {}
    nombre_rec = receptor.get("nombre")
    tip_doc_rec = receptor.get("tipoDocumento") or ("36" if receptor.get("nit") else None)
    num_doc_rec = receptor.get("numDocumento") or receptor.get("nit")
    if not nombre_rec or len(nombre_rec) < 5:
        raise ValueError("Nombre del receptor inválido")
    if not tip_doc_rec or not num_doc_rec or not (3 <= len(num_doc_rec) <= 20):
        raise ValueError("Documento del receptor inválido")

    resumen = factura.get("resumen") or {}
    monto_iva = resumen.get("totalIva")
    if monto_iva is None:
        for trib in resumen.get("tributos", []):
            if trib.get("codigo") == TRIBUTO_IVA:
                monto_iva = trib.get("valor")
                break
    if monto_iva is None:
        raise ValueError("montoIva no encontrado en la factura")
    tipo_dte_str = str(ident.get("tipoDte")).zfill(2)
    monto_iva = Decimal(str(monto_iva)).quantize(Decimal("0.01"))

    tipo_anulacion = str(ui_motivo.get("tipoAnulacion"))
    motivo = ui_motivo.get("motivoAnulacion", "")
    if len(motivo) < 5:
        raise ValueError("motivoAnulacion debe tener al menos 5 caracteres")

    def _val_doc(nombre, tip, num):
        if not nombre or len(nombre) < 3:
            raise ValueError("nombre inválido")
        if tip not in {"36", "13", "02", "03", "37"}:
            raise ValueError("tipo de documento inválido")
        if not (3 <= len(num or "") <= 20):
            raise ValueError("número de documento inválido")

    _val_doc(
        ui_motivo.get("nombreResponsable"),
        ui_motivo.get("tipDocResponsable"),
        ui_motivo.get("numDocResponsable"),
    )
    _val_doc(
        ui_motivo.get("nombreSolicita"),
        ui_motivo.get("tipDocSolicita"),
        ui_motivo.get("numDocSolicita"),
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
        "fecEmi": fec_emi,
        "montoIva": float(monto_iva),
        "codigoGeneracionR": None if tipo_anulacion == "2" else ui_motivo.get("codigoGeneracionR"),
        "tipoDocumento": tip_doc_rec,
        "numDocumento": num_doc_rec,
        "nombre": nombre_rec,
    }
    tel_rec = receptor.get("telefono")
    if tel_rec:
        if not re.fullmatch(r"[0-9+;]{8,50}", tel_rec):
            raise ValueError("Teléfono del receptor inválido")
        documento["telefono"] = tel_rec
    cor_rec = receptor.get("correo")
    if cor_rec:
        if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", cor_rec):
            raise ValueError("Correo del receptor inválido")
        documento["correo"] = cor_rec

    motivo_section = {
        "tipoAnulacion": int(tipo_anulacion),
        "motivoAnulacion": motivo,
        "nombreResponsable": ui_motivo.get("nombreResponsable"),
        "tipDocResponsable": ui_motivo.get("tipDocResponsable"),
        "numDocResponsable": ui_motivo.get("numDocResponsable"),
        "nombreSolicita": ui_motivo.get("nombreSolicita"),
        "tipDocSolicita": ui_motivo.get("tipDocSolicita"),
        "numDocSolicita": ui_motivo.get("numDocSolicita"),
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

