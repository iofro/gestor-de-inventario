import json
import os
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext
from db import DB
import requests
from utils import jws
import auth
import json
import os
from jsonschema import validate as _jsonschema_validate
from utils import catalogos
import logging

logger = logging.getLogger(__name__)

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "datos_negocio.json")
CONFIG_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "config_negocio.json")
DEFAULT_RECEPCION_URL = "https://sandbox.dtes.mh.gob.sv/recepciondte/api/recepciondte"

# Ensure enough precision when other modules modify the global decimal context
getcontext().prec = 28


def _round(value, digits):
    """Round ``value`` to ``digits`` decimal places using HALF_UP."""
    if value is None:
        value = 0
    fmt = "0." + "0" * digits
    return float(Decimal(str(value)).quantize(Decimal(fmt), rounding=ROUND_HALF_UP))


def _load_datos_negocio():
    if os.path.exists(DATOS_NEGOCIO_PATH):
        try:
            with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def generar_numero_control(prefijo: str = "DTE-01-S001P001") -> str:
    """Crea un número de control único siguiendo el formato de Hacienda."""
    secuencia = str(uuid.uuid4().int % 10**15).zfill(15)
    return f"{prefijo}-{secuencia}"


def generar_cabecera_dte_data(modelo_facturacion: str, tipo_transmision: str) -> dict:
    """Genera los datos para la cabecera de un DTE.

    Los campos de código de generación y número de control se crean antes de
    enviar la factura. Los valores que envía Hacienda posteriormente (código de
    generación y sello recibido) se dejan en ``None``.
    """
    codigo_generacion = uuid.uuid4().hex.upper()
    numero_control = generar_numero_control()
    fecha_generacion = datetime.now().strftime("%d/%m/%Y, %I:%M %p")
    return {
        "codigo_generacion": codigo_generacion,
        "numero_control": numero_control,
        "sello_recepcion": None,
        "modelo_facturacion": modelo_facturacion,
        "tipo_transmision": tipo_transmision,
        "fecha_generacion": fecha_generacion,
    }

def generar_dte_json(
    db: DB,
    venta_id: int,
    modelo_facturacion: str = "1 - Facturación previo",
    tipo_transmision: str = "1 - Transmisión normal",
    tipo_dte: str = "01",
) -> dict:
    """Genera un diccionario DTE básico para una venta."""
    row = db.cursor.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone()
    if not row:
        raise ValueError("Venta no encontrada")
    venta = dict(row)

    detalles = db.get_detalles_venta(venta_id)
    fiscal = db.get_venta_credito_fiscal(venta_id)
    extra = {}
    raw_extra = venta.get("extra")
    if raw_extra:
        try:
            extra = json.loads(raw_extra)
        except Exception:
            extra = {}

    cliente = None
    if venta.get("cliente_id"):
        cliente = db.get_cliente(venta["cliente_id"])

    datos = _load_datos_negocio()

    codigo_generacion = uuid.uuid4().hex.upper()
    numero_control = generar_numero_control()

    fecha = venta.get("fecha") or datetime.now().strftime("%Y-%m-%d")
    hora = datetime.now().strftime("%H:%M:%S")

    identificacion = {
        "version": "1",
        "tipoDte": tipo_dte,
        "codigoGeneracion": codigo_generacion,
        "numeroControl": numero_control,
        "fecEmi": fecha,
        "horEmi": hora,
        "modeloFacturacion": modelo_facturacion,
        "tipoTransmision": tipo_transmision,
    }

    emisor = {
        "nombre": datos.get("razon_social"),
        "nit": datos.get("nit"),
        "nrc": datos.get("nrc"),
        "giro": datos.get("giro"),
        "direccion": datos.get("direccion"),
    }

    rec = cliente or {}
    receptor = {
        "nombre": rec.get("nombre"),
        "direccion": rec.get("direccion"),
        "nit": rec.get("nit"),
    }
    if fiscal:
        receptor.update({
            "nrc": fiscal.get("nrc") or rec.get("nrc"),
            "giro": fiscal.get("giro") or rec.get("giro"),
            "nit": fiscal.get("nit") or rec.get("nit"),
        })
        if fiscal.get("no_remision"):
            receptor["noRemision"] = fiscal.get("no_remision")
        if fiscal.get("orden_no"):
            receptor["ordenNo"] = fiscal.get("orden_no")

    cuerpo = []
    items_total = Decimal("0")
    for idx, d in enumerate(detalles, 1):
        try:
            cant = Decimal(str(d.get("cantidad") or 0))
        except Exception:
            cant = Decimal(0)
        try:
            price = Decimal(str(d.get("precio_unitario") or 0))
        except Exception:
            price = Decimal(0)
        cant_r = cant.quantize(Decimal("0.00000000"), rounding=ROUND_HALF_UP)
        price_r = price.quantize(Decimal("0.00000000"), rounding=ROUND_HALF_UP)
        items_total += cant_r * price_r
        cuerpo.append({
            "numItem": idx,
            "descripcion": d.get("descripcion"),
            "cantidad": float(cant_r),
            "precioUnitario": float(price_r),
        })

    total = float(items_total)
    sumas_val = fiscal.get("sumas", total) if fiscal else total
    descuentos_val = fiscal.get("descuentos", 0) if fiscal else 0
    iva_val = fiscal.get("iva") if fiscal else 0

    resumen = {
        "totalNoSuj": fiscal.get("ventas_no_sujetas") if fiscal else 0,
        "totalExenta": fiscal.get("ventas_exentas") if fiscal else 0,
        "sumas": sumas_val,
        "descuentos": descuentos_val,
        "iva": iva_val,
        "subTotal": (sumas_val - descuentos_val) + iva_val,
        "totalPagar": venta.get("total", total),
    }

    # Round resumen values to two decimals
    for k, v in resumen.items():
        resumen[k] = _round(v, 2)

    # Validate totals within tolerance
    items_total_2 = _round(items_total, 2)
    if abs(items_total_2 - resumen["sumas"]) > 0.01:
        print(
            f"Advertencia: la suma de los ítems {items_total_2:.2f} difiere del resumen {resumen['sumas']:.2f}"
        )

    calc_sub = _round(resumen["sumas"] - resumen["descuentos"] + resumen["iva"], 2)
    if abs(calc_sub - resumen["subTotal"]) > 0.01:
        print(
            f"Advertencia: el subtotal calculado {calc_sub:.2f} difiere del resumen {resumen['subTotal']:.2f}"
        )
    if abs(calc_sub - resumen["totalPagar"]) > 0.01:
        print(
            f"Advertencia: el total a pagar {resumen['totalPagar']:.2f} difiere del subtotal calculado {calc_sub:.2f}"
        )

    result = {
        "identificacion": identificacion,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": cuerpo,
        "resumen": resumen,
        "firmaElectronica": None,
        "selloRecibido": None,
    }
    if fiscal:
        result["condicionPago"] = fiscal.get("condicion_pago")

    if fiscal:
        if fiscal.get("venta_a_cuenta_de"):
            result["ventaACuentaDe"] = fiscal.get("venta_a_cuenta_de")
        if fiscal.get("documento_venta_a_cuenta"):
            result["documentoVentaACuenta"] = fiscal.get("documento_venta_a_cuenta")
    else:
        if extra.get("venta_a_cuenta_de"):
            result["ventaACuentaDe"] = extra.get("venta_a_cuenta_de")
        if extra.get("documento_venta_a_cuenta"):
            result["documentoVentaACuenta"] = extra.get("documento_venta_a_cuenta")

    return result


def validate_dte_json(data: dict) -> None:
    """Basic validation for DTE payload before signing."""
    required = ["identificacion", "emisor", "receptor", "cuerpoDocumento", "resumen"]
    for key in required:
        if key not in data:
            raise ValueError(f"Falta el campo obligatorio: {key}")

    cuerpo = data.get("cuerpoDocumento", [])
    items_total = Decimal("0")
    for item in cuerpo:
        cantidad = Decimal(str(item.get("cantidad", 0)))
        precio = Decimal(str(item.get("precioUnitario", item.get("precioUni", 0))))
        item["cantidad"] = float(cantidad.quantize(Decimal("0.00000000"), rounding=ROUND_HALF_UP))
        precio_key = "precioUnitario" if "precioUnitario" in item else "precioUni"
        item[precio_key] = float(precio.quantize(Decimal("0.00000000"), rounding=ROUND_HALF_UP))
        items_total += cantidad * precio

    resumen = data.get("resumen", {})
    for k, v in resumen.items():
        if isinstance(v, (int, float)):
            resumen[k] = _round(v, 2)
        elif isinstance(v, str):
            try:
                resumen[k] = _round(float(v), 2)
            except Exception:
                pass

    sumas = Decimal(str(resumen.get("sumas", 0)))
    descuentos = Decimal(str(resumen.get("descuentos", 0)))
    iva = Decimal(str(resumen.get("iva", 0)))
    sub_total = Decimal(str(resumen.get("subTotal", 0)))
    total = Decimal(str(resumen.get("totalPagar", 0)))

    items_total_2 = Decimal(str(_round(items_total, 2)))
    if abs(items_total_2 - sumas) > Decimal("0.01"):
        print(
            f"Advertencia: la suma de los ítems {items_total_2:.2f} difiere del resumen {sumas:.2f}"
        )

    calc_sub = sumas - descuentos + iva
    calc_sub = Decimal(str(_round(calc_sub, 2)))
    if abs(calc_sub - sub_total) > Decimal("0.01"):
        print(
            f"Advertencia: el subtotal calculado {calc_sub:.2f} difiere del resumen {sub_total:.2f}"
        )
    if abs(calc_sub - total) > Decimal("0.01"):
        print(
            f"Advertencia: el total a pagar {total:.2f} difiere del subtotal calculado {calc_sub:.2f}"
        )

    # --- Catálogo validations ---
    ident = data.get("identificacion", {})
    tipo_dte = ident.get("tipoDte")
    if tipo_dte not in catalogos.TIPOS_DTE:
        raise ValueError("Código de tipoDte inválido")

    # Modelo de facturación / tipo de operación
    modelo_val = ident.get("tipoModelo") or ident.get("modeloFacturacion")
    try:
        modelo_cod = int(str(modelo_val).split("-")[0].strip())
    except Exception:
        raise ValueError("Modelo de facturación inválido")
    if modelo_cod not in catalogos.MODELOS_FACTURACION:
        raise ValueError("Modelo de facturación inválido")
    ident["tipoModelo"] = modelo_cod

    oper_val = ident.get("tipoOperacion") or ident.get("tipoTransmision")
    try:
        oper_cod = int(str(oper_val).split("-")[0].strip())
    except Exception:
        raise ValueError("Tipo de operación inválido")
    ident["tipoOperacion"] = oper_cod

    # Validación de longitud de NIT
    for parte in ("emisor", "receptor"):
        nit = data.get(parte, {}).get("nit")
        if nit and len(nit.replace("-", "")) != catalogos.NIT_LENGTH:
            raise ValueError(f"NIT inválido en {parte}")

    # --- Schema validation ---
    schema_path = catalogos.SCHEMA_MAP.get(tipo_dte)
    if schema_path and os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        _jsonschema_validate(instance=data, schema=schema)


def generar_ticket_json(
    db: DB,
    venta_id: int,
    modelo_facturacion: str = "1 - Facturación previo",
    tipo_transmision: str = "1 - Transmisión normal",
) -> dict:
    """Genera la estructura JSON para un Ticket Electrónico."""
    return generar_dte_json(
        db,
        venta_id,
        modelo_facturacion=modelo_facturacion,
        tipo_transmision=tipo_transmision,
        tipo_dte="03",
    )


def generar_nota_credito_json(db: DB, nota_id: int) -> dict:
    """Genera la estructura JSON para una nota de crédito."""
    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")
    nota = dict(row)
    if nota.get("tipo") != "credito":
        raise ValueError("La nota indicada no es de crédito")

    venta_id = nota.get("venta_id")
    data = generar_dte_json(db, venta_id, tipo_dte="05")
    data["documentoRelacionado"] = {
        "tipoDoc": "01",
        "numeroDocumento": data["identificacion"].get("numeroControl") or venta_id,
    }

    for item in data.get("cuerpoDocumento", []):
        if isinstance(item.get("cantidad"), (int, float)):
            item["cantidad"] = -abs(item["cantidad"])
        if isinstance(item.get("precioUnitario"), (int, float)):
            item["precioUnitario"] = -abs(item["precioUnitario"])

    resumen = data.get("resumen", {})
    for k, v in resumen.items():
        if isinstance(v, (int, float)):
            resumen[k] = -abs(v)
    data["resumen"] = resumen
    return data


def _load_dte_api_config():
    """Lee configuración de URLs y ambiente desde ``config_negocio.json``."""
    try:
        with open(CONFIG_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        ambiente = data.get("ambiente", "pruebas")
        urls = data.get("recepcion_url", {})
        url = urls.get(ambiente) if isinstance(urls, dict) else urls
        return {"ambiente": ambiente, "url": url}
    except Exception:
        return {}


def _post_dte(url: str, token: str, jws_token: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"dte": jws_token}
    resp = requests.post(url, json=payload, headers=headers, timeout=20)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {"estado": "Transmitido", "sello": ""}


def transmitir_dte(
    db: DB, venta_id: int, modo: str = "normal", tipo_dte: str = "01"
) -> dict:
    """Envía un DTE a la API configurada y registra su estado.

    ``tipo_dte`` permite especificar el código del documento a transmitir,
    usando ``"01"`` para facturas y ``"03"`` para tickets.
    """
    config = _load_dte_api_config()
    if modo == "contingencia":
        db.registrar_envio_dte(venta_id, modo, "Pendiente", "")
        return {"estado": "Pendiente"}

    if tipo_dte == "03":
        dte_data = generar_ticket_json(db, venta_id)
    else:
        dte_data = generar_dte_json(db, venta_id)
    validate_dte_json(dte_data)
    url = config.get("url") or DEFAULT_RECEPCION_URL
    cert, key, phrase = jws.get_cert_config()
    signed = jws.sign_json(dte_data, cert, phrase, key)
    token = auth.get_token()

    try:
        respuesta = _post_dte(url, token, signed)
        sello = respuesta.get("sello") or respuesta.get("selloRecepcion") or ""
        estado = respuesta.get("estado") or "Transmitido"
    except Exception:
        db.registrar_envio_dte(venta_id, modo, "Rechazado", "")
        raise

    db.registrar_envio_dte(venta_id, modo, estado, sello, json.dumps(respuesta, ensure_ascii=False))
    if sello:
        db.update_venta_extra(venta_id, {"selloRecibido": sello})
    return {"estado": estado, "sello": sello}


def enviar_dte_a_hacienda(dte_json_firmado: dict) -> dict:
    """Envía un DTE firmado al entorno de pruebas de Hacienda."""
    url = "https://sandbox.dtes.mh.gob.sv/recepciondte/api/recepciondte"
    cert, key, phrase = jws.get_cert_config()
    jws_token = jws.sign_json(dte_json_firmado, cert, phrase, key)
    jwt_token = jws.create_auth_jwt("inventario", cert, phrase, key)
    respuesta = _post_dte(url, jwt_token, jws_token)
    estado = respuesta.get("estado") or respuesta.get("estadoDte") or respuesta.get("descripcionEstado")
    if estado:
        respuesta["estado"] = estado
    return respuesta


def _parse_error_response(respuesta: dict) -> str:
    """Construye un mensaje de error a partir de ``descripcionMsg`` y ``observaciones``."""
    partes = []
    desc = respuesta.get("descripcionMsg")
    if desc:
        partes.append(str(desc))
    obs = respuesta.get("observaciones")
    if isinstance(obs, dict):
        for k, v in obs.items():
            partes.append(f"{k}: {v}")
    elif isinstance(obs, list):
        partes.extend(str(o) for o in obs)
    elif obs:
        partes.append(str(obs))
    mensaje = "; ".join(partes)
    if mensaje:
        logger.error(mensaje)
    return mensaje


def _enviar_documento(db: DB, doc_id: int, data: dict, modo: str = "normal") -> dict:
    """Firma y envía ``data`` a la API de Hacienda registrando el envío."""
    config = _load_dte_api_config()
    if modo == "contingencia":
        db.registrar_envio_dte(doc_id, modo, "Pendiente", "")
        return {"estado": "Pendiente"}

    url = config.get("url") or DEFAULT_RECEPCION_URL
    cert, key, phrase = jws.get_cert_config()
    signed = jws.sign_json(data, cert, phrase, key)
    token = auth.get_token()

    try:
        respuesta = _post_dte(url, token, signed)
        sello = respuesta.get("sello") or respuesta.get("selloRecepcion") or ""
        estado = (
            respuesta.get("estado")
            or respuesta.get("estadoDte")
            or respuesta.get("descripcionEstado")
            or "Transmitido"
        )
    except Exception:
        db.registrar_envio_dte(doc_id, modo, "Rechazado", "")
        raise

    db.registrar_envio_dte(
        doc_id,
        modo,
        estado,
        sello,
        json.dumps(respuesta, ensure_ascii=False),
    )
    if estado == "Rechazado":
        respuesta["errores"] = _parse_error_response(respuesta)
    return {"estado": estado, "sello": sello}


def enviar_factura(db: DB, venta_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una factura electrónica."""
    data = generar_dte_json(db, venta_id)
    validate_dte_json(data)
    resp = _enviar_documento(db, venta_id, data, modo)
    if resp.get("sello"):
        db.update_venta_extra(venta_id, {"selloRecibido": resp["sello"]})
    return resp


def enviar_nota_credito(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de crédito."""
    data = generar_nota_credito_json(db, nota_id)
    validate_dte_json(data)
    return _enviar_documento(db, nota_id, data, modo)


def _enviar_evento(db: DB, evento_id: int, data: dict) -> dict:
    """Firma y envía un evento a Hacienda."""
    config = _load_dte_api_config()
    url = config.get("url") or DEFAULT_RECEPCION_URL
    cert, key, phrase = jws.get_cert_config()
    signed = jws.sign_json(data, cert, phrase, key)
    token = auth.get_token()

    try:
        respuesta = _post_dte(url, token, signed)
        sello = respuesta.get("sello") or respuesta.get("selloRecepcion") or ""
        estado = (
            respuesta.get("estado")
            or respuesta.get("estadoEvento")
            or respuesta.get("descripcionEstado")
            or "Transmitido"
        )
    except Exception:
        db.registrar_envio_dte(evento_id, "evento", "Rechazado", "")
        raise

    db.registrar_envio_dte(
        evento_id,
        "evento",
        estado,
        sello,
        json.dumps(respuesta, ensure_ascii=False),
    )
    if estado == "Rechazado":
        respuesta["errores"] = _parse_error_response(respuesta)
    return {"estado": estado, "sello": sello}


def enviar_evento_contingencia(db: DB, evento_id: int, data: dict) -> dict:
    """Envía un evento de contingencia."""
    return _enviar_evento(db, evento_id, data)


def enviar_evento_anulacion(db: DB, evento_id: int, data: dict) -> dict:
    """Envía un evento de anulación."""
    return _enviar_evento(db, evento_id, data)

