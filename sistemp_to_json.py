import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from dbfread import DBF

# Use a path relative to this script so it can be executed from
# any working directory.
BASE = (
    Path(__file__).resolve().parent
    / "sistemp"
    / "Integrasistemp"
    / "temporal"
)


def load_dbf(name):
    """Load a DBF file from the SystemP temporal directory."""

    return DBF(str(BASE / name), load=True, encoding="latin-1")


def date_to_str(value):
    if isinstance(value, date):
        return value.isoformat()
    return ""


def to_number(value):
    if value in (None, ""):
        return 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


# Productos
productos = []
codigo_to_id: dict[str, int] = {}
productos_por_id: dict[int, dict] = {}

try:
    for row in load_dbf("catalogoTemp.DBF"):
        pid = row.get("ID_ITEM")
        if pid is None:
            continue
        codigo = (row.get("COD_ITEM") or "").strip()
        producto = {
            "id": pid,
            "nombre": row.get("ITEM", ""),
            "codigo": codigo,
            "precio_compra": 0.0,
            "precio_venta_minorista": 0.0,
            "precio_venta_mayorista": 0.0,
            "stock": to_number(row.get("CANT_FIN")),
        }
        productos.append(producto)
        productos_por_id[pid] = producto
        if codigo:
            codigo_to_id[codigo] = pid
except Exception:
    pass

try:
    for row in load_dbf("utilTemp.DBF"):
        pid = row.get("ID_ITEM")
        if pid is None:
            continue
        codigo = (row.get("COD_ITEM") or "").strip()
        producto = productos_por_id.get(pid)
        if not producto:
            producto = {
                "id": pid,
                "nombre": row.get("ITEM", ""),
                "codigo": codigo,
                "precio_compra": 0.0,
                "precio_venta_minorista": 0.0,
                "precio_venta_mayorista": 0.0,
                "stock": to_number(row.get("CANT_FACT")),
            }
            productos.append(producto)
            productos_por_id[pid] = producto
        if codigo and codigo not in codigo_to_id:
            codigo_to_id[codigo] = pid
        if row.get("ITEM") and not producto.get("nombre"):
            producto["nombre"] = row.get("ITEM")
        producto["precio_compra"] = to_number(row.get("P_COSTO")) or producto.get("precio_compra", 0.0)
        if row.get("CANT_FACT") not in (None, ""):
            producto["stock"] = to_number(row.get("CANT_FACT"))
except Exception:
    pass


# Vendedores
vendedores = []
vendedor_code_to_id: dict[str, int] = {}
try:
    for row in load_dbf("vendedores_temp.DBF"):
        vid = row.get("ID_VENDEDO")
        codigo = (row.get("COD_VENDE") or "").strip()
        vendedores.append(
            {
                "id": vid,
                "codigo": codigo,
                "nombre": row.get("FULLNAME", ""),
                "descripcion": "",
            }
        )
        if codigo:
            vendedor_code_to_id[codigo] = vid
except Exception:
    pass


# Clientes
clientes = []
cliente_code_to_id: dict[str, int] = {}
try:
    for row in load_dbf("clientestemp.DBF"):
        cid = row.get("ID_FICHA")
        if cid is None:
            continue
        codigo = (row.get("COD_FICHA") or "").strip()
        clientes.append(
            {
                "id": cid,
                "codigo": codigo,
                "nombre": row.get("NOM_FICHA", ""),
            }
        )
        if codigo:
            cliente_code_to_id[codigo] = cid
except Exception:
    pass


# Ventas (agrupadas por numero de comprobante)
ventas = []
venta_meta: dict[str, dict] = {}
venta_counter = 1

def ensure_venta(numero: str, *, fecha=None, cliente_codigo=None, vendedor_codigo=None, vendedor_id=None, comision_pct=None):
    global venta_counter

    venta = venta_meta.get(numero)
    if venta:
        # Refrescar datos faltantes
        info = venta["venta"]
        if not info["fecha"] and fecha:
            info["fecha"] = date_to_str(fecha)
        if info["cliente_id"] is None and cliente_codigo:
            info["cliente_id"] = cliente_code_to_id.get(cliente_codigo)
        if info["vendedor_id"] is None:
            if vendedor_id is None and vendedor_codigo:
                vendedor_id = vendedor_code_to_id.get(vendedor_codigo)
            if vendedor_id is not None:
                info["vendedor_id"] = vendedor_id
                venta["vendedor_id"] = vendedor_id
        if venta.get("comision_pct") in (None, 0) and comision_pct not in (None, ""):
            venta["comision_pct"] = to_number(comision_pct)
        return venta

    # Crear nueva venta
    if vendedor_id is None and vendedor_codigo:
        vendedor_id = vendedor_code_to_id.get(vendedor_codigo)

    venta_dict = {
        "id": venta_counter,
        "fecha": date_to_str(fecha),
        "total": 0.0,
        "cliente_id": cliente_code_to_id.get(cliente_codigo or ""),
        "vendedor_id": vendedor_id,
        "Distribuidor_id": None,
        "extra": {"numero": numero},
    }

    ventas.append(venta_dict)
    venta_meta[numero] = {
        "venta": venta_dict,
        "comision_pct": to_number(comision_pct),
        "vendedor_id": vendedor_id,
    }
    venta_counter += 1
    return venta_meta[numero]


ventas_temp_rows = []
try:
    ventas_temp_rows = list(load_dbf("ventas_temp.DBF"))
    for row in ventas_temp_rows:
        numero = (row.get("COMPRO_NO") or "").strip()
        if not numero:
            continue
        ensure_venta(
            numero,
            fecha=row.get("F_MOV"),
            cliente_codigo=row.get("COD_FICHA"),
            vendedor_codigo=row.get("COD_VENDE"),
            vendedor_id=row.get("ID_VENDEDO"),
            comision_pct=row.get("COMISION"),
        )
except Exception:
    ventas_temp_rows = []


# Detalles de venta
detalles_venta = []
detalle_counter = 1
totales_por_venta: defaultdict[str, float] = defaultdict(float)
detalle_numeros = set()

try:
    for row in load_dbf("detaVentasTemp.DBF"):
        numero = (row.get("COMPRO_NO") or "").strip()
        if not numero:
            continue
        detalle_numeros.add(numero)
        venta = ensure_venta(
            numero,
            fecha=row.get("F_MOV"),
            cliente_codigo=row.get("COD_FICHA"),
        )
        producto_codigo = (row.get("COD_ITEM") or "").strip()
        producto_id = codigo_to_id.get(producto_codigo)
        if producto_id is None:
            # Skip detalles que no tienen un producto asociado
            continue

        cantidad = to_number(row.get("CANTIDAD"))
        precio_unit = to_number(row.get("P_UNITNETO"))
        total = to_number(row.get("TOTAL"))
        totales_por_venta[numero] += total

        comision_pct = venta.get("comision_pct", 0)
        comision = total * (comision_pct / 100.0 if comision_pct else 0)

        detalles_venta.append(
            {
                "id": detalle_counter,
                "venta_id": venta["venta"]["id"],
                "producto_id": producto_id,
                "cantidad": cantidad,
                "precio_unitario": precio_unit,
                "descuento": 0,
                "descuento_tipo": "",
                "iva": 0,
                "comision": comision,
                "iva_tipo": "",
                "tipo_fiscal": "",
                "extra": None,
                "precio_con_iva": total,
                "vendedor_id": venta.get("vendedor_id"),
            }
        )
        detalle_counter += 1
except Exception:
    pass


# Complementar detalles faltantes con ventas_temp (algunos comprobantes solo existen ahi)
for row in ventas_temp_rows:
    numero = (row.get("COMPRO_NO") or "").strip()
    if not numero or numero in detalle_numeros:
        continue
    venta = ensure_venta(
        numero,
        fecha=row.get("F_MOV"),
        cliente_codigo=row.get("COD_FICHA"),
        vendedor_codigo=row.get("COD_VENDE"),
        vendedor_id=row.get("ID_VENDEDO"),
        comision_pct=row.get("COMISION"),
    )

    producto_codigo = (row.get("COD_ITEM") or "").strip()
    producto_id = codigo_to_id.get(producto_codigo)
    if producto_id is None:
        continue

    cantidad = to_number(row.get("CANTIDAD"))
    precio_unit = to_number(row.get("P_UNITNETO"))
    total = to_number(row.get("TOTAL"))
    if not total:
        total = cantidad * precio_unit
    totales_por_venta[numero] += total

    comision_pct = venta.get("comision_pct", 0)
    comision = total * (comision_pct / 100.0 if comision_pct else 0)

    detalles_venta.append(
        {
            "id": detalle_counter,
            "venta_id": venta["venta"]["id"],
            "producto_id": producto_id,
            "cantidad": cantidad,
            "precio_unitario": precio_unit,
            "descuento": 0,
            "descuento_tipo": "",
            "iva": 0,
            "comision": comision,
            "iva_tipo": "",
            "tipo_fiscal": "",
            "extra": None,
            "precio_con_iva": total,
            "vendedor_id": venta.get("vendedor_id"),
        }
    )
    detalle_counter += 1


# Actualizar totales de venta calculados desde los detalles
for numero, total in totales_por_venta.items():
    venta = venta_meta.get(numero)
    if not venta:
        continue
    venta["venta"]["total"] = round(total, 2)


inventario = {
    "productos": productos,
    "vendedores": vendedores,
    "distribuidores": [],
    "clientes": clientes,
    "ventas": ventas,
    "compras": [],
    "movimientos": [],
    "detalles_venta": detalles_venta,
    "detalles_compra": [],
    "datos_negocio": {},
    "trabajadores": [],
    "ventas_credito_fiscal": [],
}

with open("sistemp_import.json", "w", encoding="utf-8") as f:
    json.dump(inventario, f, ensure_ascii=False, indent=2)
    print("Escrito sistemp_import.json")
