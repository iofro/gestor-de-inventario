from decimal import Decimal as D

import json

from db import DB
from dte import generar_dte_json, FC_SCHEMA, RESOLVER, DTE_VERSIONES
from jsonschema import Draft7Validator
from utils.line_totals import compute_line_totals
from utils.monto import d2, d4, d8
import dte as dte_module
import svfe.config as svfe_config


def _setup_datos_negocio(tmp_path):
    datos = {
        "nit": "06141990011019",
        "nrc": "12345678",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "direccion": {"departamento": "06", "municipio": "10", "complemento": "Calle 1"},
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)
    svfe_config.DATOS_NEGOCIO_PATH = str(tmp_file)
    svfe_config.load_datos_negocio = lambda: datos


def test_sale_total_equals_preview():
    line1 = compute_line_totals(D('1'), D('12'), D('5'), '%')
    line2 = compute_line_totals(D('1'), D('12'), D('6'), '%')
    total = d2(line1['total_con_iva'] + line2['total_con_iva'])
    assert total == D('22.68')
    assert d2(line1['total_con_iva']) == D('11.40')
    assert d2(line2['total_con_iva']) == D('11.28')



def test_discount_amount_clamped():
    data = compute_line_totals(D('1'), D('10'), D('15'), '$')
    assert data['total_con_iva'] == D('0')
    assert data['desc_con_iva'] == D('10')


def test_save_sale_equals_preview_totals(tmp_path):
    _setup_datos_negocio(tmp_path)
    db = DB(':memory:')
    venta = {
        'fecha': '2024-01-01',
        'detalles': [
            {
                'cantidad': D('1'),
                'precio_unit_con_iva': D('12'),
                'descuento': D('5'),
                'descuento_tipo': '%',
                'tipo_fiscal': 'Venta gravada',
            },
            {
                'cantidad': D('1'),
                'precio_unit_con_iva': D('12'),
                'descuento': D('6'),
                'descuento_tipo': '%',
                'tipo_fiscal': 'Venta gravada',
            },
        ],
    }
    db.add_venta_detallada(venta)
    row = db.cursor.execute('SELECT id, total FROM ventas').fetchone()
    assert d2(D(str(row['total']))) == D('22.68')
    venta_id = row['id']
    db.cursor.execute('SELECT SUM(total) as s FROM detalles_venta WHERE venta_id=?', (venta_id,))
    sum_det = D(str(db.cursor.fetchone()['s']))
    assert d2(sum_det) == D('22.68')


def test_exenta_no_sujeta_saved_totals(tmp_path):
    _setup_datos_negocio(tmp_path)
    db = DB(':memory:')
    db.cursor.execute("INSERT INTO clientes (codigo, nombre, nit) VALUES ('C1','Cliente','06141990011019')")
    cliente_id = db.cursor.lastrowid
    venta = {
        'fecha': '2024-01-01',
        'cliente_id': cliente_id,
        'detalles': [
            {
                'cantidad': D('1'),
                'precio_unit_con_iva': D('10'),
                'descuento': D('0'),
                'descuento_tipo': '$',
                'tipo_fiscal': 'Venta exenta',
            }
        ],
    }
    db.add_venta_detallada(venta)
    venta_id = db.cursor.execute('SELECT id FROM ventas').fetchone()['id']
    det = db.cursor.execute(
        'SELECT base, iva, total FROM detalles_venta WHERE venta_id=?',
        (venta_id,),
    ).fetchone()
    assert D(str(det['iva'])) == D('0')
    assert D(str(det['base'])) == D(str(det['total']))


def test_mayorista_total_to_unit():
    total = D('100')
    qty = D('5')
    unit_price = total / qty
    calcs = compute_line_totals(qty, unit_price)
    assert calcs['total_con_iva'] == d8(total)
    assert calcs['unit_con_iva_efectivo'] == d8(unit_price)


def _create_fc_sale(db, detalles):
    db.add_vendedor('V1')
    vid = db.cursor.lastrowid
    db.add_cliente(
        'Cliente',
        '123',
        '06141990011019',
        '',
        'giro',
        '70000001',
        '',
        'C',
        '06',
        '01',
    )
    cid = db.cursor.lastrowid
    total_venta = d8(sum(d['total'] for d in detalles))
    venta_id = db.add_venta_credito_fiscal(
        cid,
        '2024-01-01',
        float(total_venta),
        '12345678',
        '06141990011019',
        'giro',
        extra={'precios_incluyen_iva': True},
    )
    for idx, det in enumerate(detalles, 1):
        db.add_producto(f'Prod{idx}', f'P{idx}', None, vid, None, 0, 0, 0, 10)
        pid = db.cursor.lastrowid
        db.add_detalle_venta(
            venta_id,
            pid,
            float(det['cantidad']),
            float(det['precio_unit_con_iva']),
            descuento=float(det['descuento']),
            descuento_tipo=det['descuento_tipo'],
            tipo_fiscal=det.get('tipo_fiscal', 'Venta gravada'),
            precio_con_iva=float(det['precio_unit_con_iva']),
            desc_con_iva=float(det['desc_con_iva']),
            base=float(det['base']),
            total=float(det['total']),
            unit_con_iva_efectivo=float(det['unit_con_iva_efectivo']),
        )
    return venta_id


def test_dte_fc_absorbs_discount_in_unit_price(tmp_path):
    _setup_datos_negocio(tmp_path)
    db = DB(':memory:')
    detalles = []
    calcs_list = []
    for desc in (D('5'), D('6')):
        calcs = compute_line_totals(D('1'), D('12'), desc, '%')
        calcs_list.append(calcs)
        detalles.append(
            {
                'cantidad': D('1'),
                'precio_unit_con_iva': D('12'),
                'descuento': desc,
                'descuento_tipo': '%',
                'desc_con_iva': calcs['desc_con_iva'],
                'base': calcs['base'],
                'total': calcs['total_con_iva'],
                'unit_con_iva_efectivo': calcs['unit_con_iva_efectivo'],
            }
        )
    venta_id = _create_fc_sale(db, detalles)
    data = generar_dte_json(db, venta_id, tipo_dte='03')
    items = data['cuerpoDocumento']
    resumen = data['resumen']
    assert all(D(str(i['montoDescu'])) == D('0') for i in items)
    for item, calcs, det in zip(items, calcs_list, detalles):
        qty = det['cantidad']
        expected_precio = d8(calcs['base'] / qty) if qty > 0 else d8(0)
        assert D(str(item['precioUni'])) == expected_precio
        assert D(str(item['ventaGravada'])) == d8(calcs['base'])
        assert D(str(item['ivaItem'])) == d8(calcs['iva'])
    assert D(str(resumen['totalPagar'])) == D('22.68')
    assert D(str(resumen['montoTotalOperacion'])) == D('22.68')
    assert D(str(resumen['totalIva'])) == D('2.61')



