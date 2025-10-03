import pytest

from db import DB


def test_aumentar_stock_increments_product_stock():
    db = DB(':memory:')
    # Insert a product with initial stock 10
    db.add_producto(
        nombre='Prod',
        codigo='P1',
        sku=None,
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
        sku=None,
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


def test_delete_sale_restores_inventory():
    db = DB(':memory:')
    db.add_producto(
        nombre='Prod',
        codigo='P1',
        sku=None,
        vendedor_id=None,
        Distribuidor_id=None,
        precio_compra=1.0,
        precio_venta_minorista=2.0,
        precio_venta_mayorista=3.0,
        stock=0,
    )
    product_id = db.cursor.lastrowid

    compra_id = db.add_compra_detallada({
        'fecha': '2024-01-01',
        'producto_id': product_id,
        'cantidad': 10,
        'precio_unitario': 1.0,
        'total': 10,
    })
    db.add_detalle_compra(compra_id, product_id, 10, 1.0)
    db.actualizar_stock_producto(product_id)

    db.cursor.execute('SELECT id FROM detalles_compra WHERE compra_id=?', (compra_id,))
    lote_id = db.cursor.fetchone()['id']

    venta_id = db.add_venta('2024-01-02', 20)
    db.add_detalle_venta(
        venta_id,
        product_id,
        4,
        5.0,
        tipo_fiscal='Gravada',
        extra={'lote_id': lote_id},
    )

    db.disminuir_stock_lote(lote_id, 4)
    db.actualizar_stock_producto(product_id)

    db.cursor.execute('SELECT cantidad FROM detalles_compra WHERE id=?', (lote_id,))
    assert db.cursor.fetchone()['cantidad'] == 6
    db.cursor.execute('SELECT stock FROM productos WHERE id=?', (product_id,))
    assert db.cursor.fetchone()['stock'] == 6

    assert db.delete_venta(venta_id)

    db.cursor.execute('SELECT cantidad FROM detalles_compra WHERE id=?', (lote_id,))
    assert db.cursor.fetchone()['cantidad'] == 10
    db.cursor.execute('SELECT stock FROM productos WHERE id=?', (product_id,))
    assert db.cursor.fetchone()['stock'] == 10


def test_delete_sale_without_lote_info_restores_product_stock():
    db = DB(':memory:')
    db.add_producto(
        nombre='Prod',
        codigo='P1',
        sku=None,
        vendedor_id=None,
        Distribuidor_id=None,
        precio_compra=1.0,
        precio_venta_minorista=2.0,
        precio_venta_mayorista=3.0,
        stock=8,
    )
    product_id = db.cursor.lastrowid

    venta_id = db.add_venta('2024-01-02', 15)
    db.add_detalle_venta(
        venta_id,
        product_id,
        3,
        5.0,
        tipo_fiscal='Gravada',
        extra=None,
    )

    # Simula la reducción de stock que ocurre al registrar la venta
    db.cursor.execute('UPDATE productos SET stock = stock - 3 WHERE id=?', (product_id,))
    db.conn.commit()

    db.cursor.execute('SELECT stock FROM productos WHERE id=?', (product_id,))
    assert db.cursor.fetchone()['stock'] == 5

    assert db.delete_venta(venta_id)

    db.cursor.execute('SELECT stock FROM productos WHERE id=?', (product_id,))
    assert db.cursor.fetchone()['stock'] == 8
