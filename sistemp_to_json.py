import json
from dbfread import DBF
from datetime import date
from pathlib import Path

BASE = Path('sistemp/Integrasistemp/temporal')

# Helpers
def load_dbf(name):
    return DBF(str(BASE / name), load=True, encoding='latin-1')

def date_to_str(d):
    if isinstance(d, date):
        return d.isoformat()
    return ''

# Productos
productos = []
codigo_to_id = {}
try:
    for row in load_dbf('utilTemp.DBF'):
        pid = row.get('ID_ITEM')
        codigo = row.get('COD_ITEM') or ''
        productos.append({
            'id': pid,
            'nombre': row.get('ITEM', ''),
            'codigo': codigo,
            'precio_compra': row.get('P_COSTO', 0) or 0,
            'precio_venta_minorista': 0,
            'precio_venta_mayorista': 0,
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
try:
    for row in load_dbf('clientestemp.DBF'):
        cid = row.get('ID_FICHA')
        cod = row.get('COD_FICHA', '')
        clientes.append({
            'id': cid,
            'codigo': cod,
            'nombre': row.get('NOM_FICHA', '')
        })
        cliente_code_to_id[cod] = cid
except Exception:
    pass

# Ventas
ventas = []
venta_num_to_id = {}
try:
    for row in load_dbf('ventas_temp.DBF'):
        vid = row.get('ID_MOV')
        ventas.append({
            'id': vid,
            'fecha': date_to_str(row.get('F_MOV')),
            'total': row.get('TOTAL_MOV', 0) or 0,
            'cliente_id': cliente_code_to_id.get(row.get('COD_FICHA')),
            'vendedor_id': None,
            'Distribuidor_id': None,
            'extra': None,
        })
        venta_num_to_id[row.get('COMPRO_NO')] = vid
except Exception:
    pass

# Detalles de venta
# Map COMPRO_NO -> venta_id from ventas_temp
# Map COD_ITEM -> producto_id from productos

detalles_venta = []
try:
    for row in load_dbf('detaVentasTemp.DBF'):
        venta_id = venta_num_to_id.get(row.get('COMPRO_NO'))
        producto_id = codigo_to_id.get(row.get('COD_ITEM'))
        detalles_venta.append({
            'id': None,
            'venta_id': venta_id,
            'producto_id': producto_id,
            'cantidad': row.get('CANTIDAD', 0) or 0,
            'precio_unitario': row.get('P_UNITNETO', 0) or 0,
            'descuento': 0,
            'descuento_tipo': '',
            'iva': 0,
            'comision': 0,
            'iva_tipo': '',
            'tipo_fiscal': '',
            'extra': None,
            'precio_con_iva': row.get('TOTAL', 0) or 0,
            'vendedor_id': None,
        })
except Exception:
    pass

# Compose final structure
inventario = {
    'productos': productos,
    'vendedores': vendedores,
    'Distribuidores': [],
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
