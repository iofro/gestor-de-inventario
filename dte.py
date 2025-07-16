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

def generar_dte_json(db: DB, venta_id: int) -> dict:
    """Genera un diccionario DTE básico para una venta."""
    row = db.cursor.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone()
    if not row:
        raise ValueError("Venta no encontrada")
    venta = dict(row)

    detalles = db.get_detalles_venta(venta_id)
    fiscal = db.get_venta_credito_fiscal(venta_id)

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
        "nrc": rec.get("nrc"),
        "giro": rec.get("giro"),
    }
    if fiscal:
        receptor.update({
            "nit": fiscal.get("nit") or receptor.get("nit"),
            "nrc": fiscal.get("nrc") or receptor.get("nrc"),
            "giro": fiscal.get("giro") or receptor.get("giro"),
        })

    cuerpo = []
    for idx, d in enumerate(detalles, 1):
        cuerpo.append({
            "numItem": idx,
            "descripcion": d.get("descripcion"),
            "cantidad": d.get("cantidad"),
            "precioUnitario": d.get("precio_unitario"),
        })

    total = sum(d.get("cantidad", 0) * d.get("precio_unitario", 0) for d in detalles)
    resumen = {
        "totalNoSuj": fiscal.get("ventas_no_sujetas") if fiscal else 0,
        "totalExenta": fiscal.get("ventas_exentas") if fiscal else 0,
        "subTotalVentas": fiscal.get("sumas", total) if fiscal else total,
        "iva": fiscal.get("iva") if fiscal else 0,
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
        if fiscal.get("venta_a_cuenta_de"):
            result["ventaACuentaDe"] = fiscal.get("venta_a_cuenta_de")
        if fiscal.get("documento_venta_a_cuenta"):
            result["documentoVentaACuenta"] = fiscal.get("documento_venta_a_cuenta")

    return result
