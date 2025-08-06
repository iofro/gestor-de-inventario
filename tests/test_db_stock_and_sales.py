import pytest

from db import DB


def test_aumentar_stock_increments_product_stock():
    db = DB(':memory:')
    # Insert a product with initial stock 10
    db.add_producto(
        nombre='Prod',
        codigo='P1',
        vendedor_id=None,
        Distribuidor_id=None,
        precio_compra=1.0,
        precio_venta_minorista=2.0,
        precio_venta_mayorista=3.0,
        stock=10,
    )
    product_id = db.cursor.lastrowid

    db.aumentar_stock(product_id, 5)

    db.cursor.execute('SELECT stock FROM productos WHERE id=?', (product_id,))
    assert db.cursor.fetchone()['stock'] == 15


def test_registrar_venta_detallada_creates_records():
    db = DB(':memory:')
    # Prepare product
    db.add_producto(
        nombre='Prod',
        codigo='P1',
        vendedor_id=None,
        Distribuidor_id=None,
        precio_compra=1.0,
        precio_venta_minorista=2.0,
        precio_venta_mayorista=3.0,
        stock=10,
    )
    product_id = db.cursor.lastrowid

    venta_data = {
        'fecha': '2024-01-01',
        'total': 20,
        'detalles': [
            {
                'producto_id': product_id,
                'cantidad': 2,
                'precio_unitario': 10,
            }
        ],
    }
    db.add_venta_detallada(venta_data)

    db.cursor.execute('SELECT id, total FROM ventas')
    ventas = db.cursor.fetchall()
    assert len(ventas) == 1
    venta_id = ventas[0]['id']
    assert ventas[0]['total'] == 20

    db.cursor.execute('SELECT venta_id, producto_id, cantidad, precio_unitario FROM detalles_venta')
    detalles = db.cursor.fetchall()
    assert len(detalles) == 1
    detalle = detalles[0]
    assert detalle['venta_id'] == venta_id
    assert detalle['producto_id'] == product_id
    assert detalle['cantidad'] == 2
    assert detalle['precio_unitario'] == 10
