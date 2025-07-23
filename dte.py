import json
import os
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from db import DB
import requests

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "datos_negocio.json")


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
        "tipoDte": "01",
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
        cant = Decimal(str(d.get("cantidad", 0)))
        price = Decimal(str(d.get("precio_unitario", 0)))
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


def _load_dte_api_config():
    datos = _load_datos_negocio()
    return datos.get("dte_api", {})


def _post_dte(url: str, token: str, data: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(url, json=data, headers=headers, timeout=20)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {"estado": "Transmitido", "sello": ""}


def transmitir_dte(db: DB, venta_id: int, modo: str = "normal") -> dict:
    """Envía un DTE a la API configurada y registra su estado."""
    config = _load_dte_api_config()
    if modo == "contingencia":
        db.registrar_envio_dte(venta_id, modo, "Pendiente", "")
        return {"estado": "Pendiente"}

    dte_data = generar_dte_json(db, venta_id)
    url = config.get("url")
    token = config.get("token")
    if not url:
        raise ValueError("URL de API no configurada")

    try:
        respuesta = _post_dte(url, token, dte_data)
        sello = respuesta.get("sello") or respuesta.get("selloRecepcion") or ""
        estado = respuesta.get("estado") or "Transmitido"
    except Exception:
        db.registrar_envio_dte(venta_id, modo, "Rechazado", "")
        raise

    db.registrar_envio_dte(venta_id, modo, estado, sello)
    if sello:
        db.update_venta_extra(venta_id, {"selloRecibido": sello})
    return {"estado": estado, "sello": sello}

