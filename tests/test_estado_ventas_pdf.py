import fitz
from db import DB
from estado_ventas_pdf import generar_estado_ventas_pdf


def test_generar_estado_ventas_pdf(tmp_path):
    db = DB(":memory:")
    # Crear vendedor y cliente
    db.add_vendedor("Juan", codigo="V1")
    vendedor_id = db.cursor.lastrowid
    db.add_cliente("Cliente", "", "", "12345678-9", "", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    # Crear producto
    db.add_producto("Prod", "P1", vendedor_id, None, 0, 0, 0, 10)
    producto_id = db.cursor.lastrowid
    # Registrar venta y detalle
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cliente_id, vendedor_id=vendedor_id)
    db.add_detalle_venta(venta_id, producto_id, 2, 5, comision=1, vendedor_id=vendedor_id)

    # Construir datos para el reporte
    row = db.cursor.execute(
        """
        SELECT c.nombre AS c_nombre, c.dui AS c_dui, v.id AS venta_id, v.total AS valor_fact,
               v.fecha AS facturo, p.nombre AS item, dv.cantidad, dv.precio_unitario,
               dv.cantidad * dv.precio_unitario AS total, dv.comision
        FROM ventas v
        JOIN clientes c ON v.cliente_id=c.id
        JOIN detalles_venta dv ON dv.venta_id=v.id
        JOIN productos p ON p.id=dv.producto_id
        WHERE v.vendedor_id=?
        """,
        (vendedor_id,),
    ).fetchone()

    porc = f"{row['comision'] / row['total'] * 100:.2f}%" if row['total'] else "0%"
    ventas_por_cliente = [
        {
            "nombre": row["c_nombre"],
            "dui": row["c_dui"],
            "ventas": [
                {
                    "comprobante": str(row["venta_id"]),
                    "valor_fact": row["valor_fact"],
                    "facturo": row["facturo"],
                    "item": row["item"],
                    "cantidad": row["cantidad"],
                    "p_unitario": row["precio_unitario"],
                    "total": row["total"],
                    "porc_comision": porc,
                    "comision": row["comision"],
                }
            ],
        }
    ]

    out = tmp_path / "estado_ventas.pdf"
    generar_estado_ventas_pdf(
        {"nombre": "Juan", "codigo": "V1"},
        "2024-01-01",
        "2024-01-31",
        ventas_por_cliente,
        archivo=str(out),
        datos_negocio={},
    )
    assert out.exists()

    with fitz.open(out) as doc:
        text = "\n".join(p.get_text() for p in doc)
    assert "CLIENTE: Cliente" in text
    assert "Prod" in text
    assert "10.00" in text
    assert "1.00" in text
