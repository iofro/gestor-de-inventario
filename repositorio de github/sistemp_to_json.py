import json
from datetime import date
from pathlib import Path
from typing import Any, Dict

from dbfread import DBF

try:
    from pgdumplib import load as load_pg_dump
except Exception:  # pragma: no cover - optional dependency
    load_pg_dump = None

# Use a path relative to this script so it can be executed from
# any working directory.
BASE = (
    Path(__file__).resolve().parent
    / "sistemp"
    / "Integrasistemp"
    / "temporal"
)

BACKUP_PATH = BASE.parent.parent / "stacatalina.backup"


# Helpers
def load_dbf(name: str) -> DBF:
    return DBF(str(BASE / name), load=True, encoding="latin-1")


def date_to_str(d: Any) -> str:
    if isinstance(d, date):
        return d.isoformat()
    return ""


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("latin-1", "ignore")
    if isinstance(value, str):
        value = value.replace("\r\n", " ").replace("\n", " ").replace("\t", " ")
        return value.strip()
    return str(value)


def load_client_metadata() -> Dict[str, Dict[str, Any]]:
    """Return extra client metadata sourced from the PostgreSQL backup."""

    if not BACKUP_PATH.exists() or load_pg_dump is None:
        return {}

    try:
        dump = load_pg_dump(str(BACKUP_PATH))
    except Exception:
        return {}

    deptos = {}
    municipios = {}
    try:
        deptos = {
            int(row[0]): _clean_str(row[1])
            for row in dump.table_data("public", "deptos")
        }
        municipios = {
            int(row[1]): {
                "nombre": _clean_str(row[2]),
                "departamento_id": int(row[0]),
            }
            for row in dump.table_data("public", "municipios")
        }
    except Exception:
        deptos = {}
        municipios = {}

    emails = {}
    try:
        for row in dump.table_data("public", "emails"):
            email = _clean_str(row[2])
            ficha_id = _clean_str(row[1])
            if ficha_id and email:
                emails.setdefault(ficha_id, []).append(email)
    except Exception:
        emails = {}

    columns = [
        "cod_ficha",
        "direccion",
        "dui",
        "excluido",
        "giro",
        "id_ficha",
        "id_munici",
        "nacionali",
        "nit",
        "nom_ficha",
        "nrc",
        "otros",
        "ret_iva",
        "telefono",
        "proveedor",
        "cliente",
    ]

    metadata: Dict[str, Dict[str, Any]] = {}

    try:
        for row in dump.table_data("public", "fichas"):
            data = {columns[idx]: row[idx] for idx in range(len(columns))}
            codigo = _clean_str(data.get("cod_ficha"))
            if not codigo:
                continue

            municipio_id_raw = _clean_str(data.get("id_munici"))
            try:
                municipio_id = int(municipio_id_raw) if municipio_id_raw else None
            except ValueError:
                municipio_id = None

            municipio_info = municipios.get(municipio_id or -1)
            departamento_id = municipio_info.get("departamento_id") if municipio_info else None

            ficha_id = _clean_str(data.get("id_ficha"))
            correo = emails.get(ficha_id, [])

            if codigo in {"N/A", "*NULO*"}:
                continue

            metadata[codigo] = {
                "nombre": _clean_str(data.get("nom_ficha")),
                "direccion": _clean_str(data.get("direccion")),
                "dui": _clean_str(data.get("dui")),
                "giro": _clean_str(data.get("giro")),
                "nit": _clean_str(data.get("nit")),
                "nrc": _clean_str(data.get("nrc")),
                "telefono": _clean_str(data.get("telefono")),
                "otros": _clean_str(data.get("otros")),
                "departamento": f"{departamento_id:02d}" if isinstance(departamento_id, int) and departamento_id > 0 else "",
                "municipio": str(municipio_id) if isinstance(municipio_id, int) and municipio_id > 0 else "",
                "email": correo[0] if correo else "",
            }
    except Exception:
        return {}

    return metadata

# Productos
productos = []
codigo_to_id = {}
try:
    for row in load_dbf('utilTemp.DBF'):
        pid = row.get('ID_ITEM')
        codigo = row.get('COD_ITEM') or ''
        precio_venta = row.get('T_VENTA', 0) or 0
        # Algunos artículos tienen valores flotantes con muchos decimales,
        # por lo que redondeamos a 4 cifras para mantener un formato estable
        # en el archivo exportado.
        if isinstance(precio_venta, float):
            precio_venta = round(precio_venta, 4)

        productos.append({
            'id': pid,
            'nombre': row.get('ITEM', ''),
            'codigo': codigo,
            'precio_compra': row.get('P_COSTO', 0) or 0,
            'precio_venta_minorista': precio_venta,
            'precio_venta_mayorista': precio_venta,
            'stock': row.get('CANT_FACT', 0) or 0,
        })
        codigo_to_id[codigo] = pid
except Exception:
    pass

# Vendedores
vendedores = []
try:
    for row in load_dbf('vendedores_temp.DBF'):
        vendedores.append({
            'id': row.get('ID_VENDEDO'),
            'codigo': row.get('COD_VENDE', ''),
            'nombre': row.get('FULLNAME', ''),
            'descripcion': ''
        })
except Exception:
    pass

# Clientes
clientes = []
cliente_code_to_id = {}
cliente_metadata = load_client_metadata()
try:
    for row in load_dbf('clientestemp.DBF'):
        cid = row.get('ID_FICHA')
        cod = (row.get('COD_FICHA') or '').strip()
        nombre = row.get('NOM_FICHA', '')
        data = {
            'id': cid,
            'codigo': cod,
            'nombre': nombre,
        }

        meta = cliente_metadata.get(cod)
        if meta:
            if meta.get('nombre'):
                data['nombre'] = meta['nombre']
            if meta.get('nit'):
                data['nit'] = meta['nit']
            if meta.get('dui'):
                data['dui'] = meta['dui']
            if meta.get('direccion'):
                data['direccion'] = meta['direccion']
            if meta.get('telefono'):
                data['telefono'] = meta['telefono']
            if meta.get('giro'):
                data['giro'] = meta['giro']
            if meta.get('nrc'):
                data['nrc'] = meta['nrc']
            if meta.get('departamento'):
                data['departamento'] = meta['departamento']
            if meta.get('municipio'):
                data['municipio'] = meta['municipio']
            if meta.get('email'):
                data['email'] = meta['email']
            if meta.get('otros'):
                data['otros'] = meta['otros']

        clientes.append(data)
        cliente_code_to_id[cod] = cid
except Exception:
    pass

# Ventas
ventas = []
venta_num_to_id = {}
venta_info = {}
try:
    for row in load_dbf('ventas_temp.DBF'):
        vid = row.get('ID_MOV')
        vendedor_id = row.get('ID_VENDEDO')
        pct = row.get('COMISION', 0) or 0
        ventas.append({
            'id': vid,
            'fecha': date_to_str(row.get('F_MOV')),
            'total': row.get('TOTAL_MOV', 0) or 0,
            'cliente_id': cliente_code_to_id.get(row.get('COD_FICHA')),
            'vendedor_id': vendedor_id,
            'Distribuidor_id': None,
            'extra': None,
        })
        venta_num_to_id[row.get('COMPRO_NO')] = vid
        venta_info[row.get('COMPRO_NO')] = (vendedor_id, pct)
except Exception:
    pass

# Detalles de venta
# Map COMPRO_NO -> venta_id from ventas_temp
# Map COD_ITEM -> producto_id from productos

detalles_venta = []
try:
    for row in load_dbf('detaVentasTemp.DBF'):
        venta_no = row.get('COMPRO_NO')
        venta_id = venta_num_to_id.get(venta_no)
        producto_id = codigo_to_id.get(row.get('COD_ITEM'))
        vendedor_id, pct = venta_info.get(venta_no, (None, 0))
        cantidad = row.get('CANTIDAD', 0) or 0
        precio_unit = row.get('P_UNITNETO', 0) or 0
        total = cantidad * precio_unit
        comision = total * (pct / 100)
        detalles_venta.append({
            'id': None,
            'venta_id': venta_id,
            'producto_id': producto_id,
            'cantidad': cantidad,
            'precio_unitario': precio_unit,
            'descuento': 0,
            'descuento_tipo': '',
            'iva': 0,
            'comision': comision,
            'iva_tipo': '',
            'tipo_fiscal': '',
            'extra': None,
            'precio_con_iva': row.get('TOTAL', 0) or 0,
            'vendedor_id': vendedor_id,
        })
except Exception:
    pass

# Compose final structure
inventario = {
    'productos': productos,
    'vendedores': vendedores,
    'distribuidores': [],
    'clientes': clientes,
    'ventas': ventas,
    'compras': [],
    'movimientos': [],
    'detalles_venta': detalles_venta,
    'detalles_compra': [],
    'datos_negocio': {},
    'trabajadores': [],
    'ventas_credito_fiscal': []
}

with open('sistemp_import.json', 'w', encoding='utf-8') as f:
    json.dump(inventario, f, ensure_ascii=False, indent=2)
    print('Escrito sistemp_import.json')
