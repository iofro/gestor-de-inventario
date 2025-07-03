import estado_cuenta_pdf as pdf
from db import DB


def test_estado_cuenta_pdf_incluir_pagos(tmp_path):
    db = DB(":memory:")
    db.add_cliente("C1", "", "", "", "", "", "", "", "", "")
    cid = db.cursor.lastrowid
    db.add_venta("2024-01-01", 100, cliente_id=cid)
    db.add_pago(cid, 50, "2024-01-02")
    pdf_path = tmp_path / "estado.pdf"
    pdf.generar_estado_cuenta_pdf(
        db,
        modo="cliente",
        cliente_id=cid,
        fecha_inicio="2024-01-01",
        fecha_fin="2024-12-31",
        archivo=str(pdf_path),
        incluir_pagos=True,
    )
    assert pdf_path.exists()


def test_reporte_vendedor_agrupar_factura(tmp_path):
    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_cliente("C1", "", "", "", "", "", "", "", "", "")
    cid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 20, cliente_id=cid, vendedor_id=vid)
    db.add_detalle_venta(venta_id, None, 1, 10, vendedor_id=vid)
    db.add_detalle_venta(venta_id, None, 1, 10, vendedor_id=vid)
    pdf_path = tmp_path / "vend.pdf"
    pdf.generar_reporte_vendedor_pdf(
        db,
        vid,
        "2024-01-01",
        "2024-12-31",
        archivo=str(pdf_path),
        agrupar_factura=True,
    )
    assert pdf_path.exists()

