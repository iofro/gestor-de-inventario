import json
import os
import uuid
from datetime import datetime
from db import DB

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "datos_negocio.json")


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
    for idx, d in enumerate(detalles, 1):
        cuerpo.append({
            "numItem": idx,
            "descripcion": d.get("descripcion"),
            "cantidad": d.get("cantidad"),
            "precioUnitario": d.get("precio_unitario"),
        })

    total = sum(d.get("cantidad", 0) * d.get("precio_unitario", 0) for d in detalles)
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


def generar_nota_credito_json(db: DB, nota_id: int) -> dict:
    """Genera un DTE de Nota de Crédito para la nota indicada."""
    nota_row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not nota_row:
        raise ValueError("Nota no encontrada")
    nota = dict(nota_row)
    if nota.get("tipo") != "credito":
        raise ValueError("La nota indicada no es de cr\u00e9dito")

    venta_id = nota["venta_id"]
    base = generar_dte_json(db, venta_id)

    original = base.get("identificacion", {}).copy()
    cab = generar_cabecera_dte_data("1 - Facturaci\u00f3n previo", base["identificacion"].get("tipoTransmision", ""))
    base["identificacion"].update({
        "tipoDte": "05",
        "codigoGeneracion": cab["codigo_generacion"],
        "numeroControl": cab["numero_control"],
        "fecEmi": nota.get("fecha"),
    })

    base["documentoRelacionado"] = [{
        "tipoDte": original.get("tipoDte"),
        "numeroControl": original.get("numeroControl"),
        "codigoGeneracion": original.get("codigoGeneracion"),
    }]

    for item in base.get("cuerpoDocumento", []):
        if "precioUnitario" in item and isinstance(item["precioUnitario"], (int, float)):
            item["precioUnitario"] = -abs(item["precioUnitario"])

    resumen = base.get("resumen", {})
    for k, v in resumen.items():
        if isinstance(v, (int, float)):
            resumen[k] = -abs(v)

    return base
