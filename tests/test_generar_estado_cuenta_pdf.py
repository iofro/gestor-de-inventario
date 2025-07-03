import pytest
from db import DB
from estado_cuenta_pdf import generar_estado_cuenta_pdf


def create_db():
    return DB(":memory:")


def test_generar_estado_cuenta_pdf_cliente_detalle(tmp_path):
    db = create_db()
    db.add_cliente("Juan", "", "", "", "", "", "", "", "", "")
    cid = db.cursor.lastrowid
    db.add_venta("2024-01-01", 100, cliente_id=cid)
    pdf_path = tmp_path / "cliente_detalle.pdf"
    generar_estado_cuenta_pdf(db, modo="cliente", archivo=str(pdf_path), cliente_id=cid)
    assert pdf_path.exists() and pdf_path.stat().st_size > 0


def test_generar_estado_cuenta_pdf_cliente_summary(tmp_path):
    db = create_db()
    db.add_cliente("Juan", "", "", "", "", "", "", "", "", "")
    cid = db.cursor.lastrowid
    db.add_venta("2024-01-01", 100, cliente_id=cid)
    pdf_path = tmp_path / "cliente_summary.pdf"
    generar_estado_cuenta_pdf(db, modo="cliente", archivo=str(pdf_path))
    assert pdf_path.exists() and pdf_path.stat().st_size > 0


def test_generar_estado_cuenta_pdf_vendedor_detalle(tmp_path):
    db = create_db()
    db.add_vendedor("Ana")
    vid = db.cursor.lastrowid
    db.add_venta("2024-01-01", 100, vendedor_id=vid)
    pdf_path = tmp_path / "vendedor_detalle.pdf"
    generar_estado_cuenta_pdf(db, modo="vendedor", archivo=str(pdf_path), vendedor_id=vid)
    assert pdf_path.exists() and pdf_path.stat().st_size > 0


def test_generar_estado_cuenta_pdf_vendedor_summary(tmp_path):
    db = create_db()
    db.add_vendedor("Ana")
    vid = db.cursor.lastrowid
    db.add_venta("2024-01-01", 100, vendedor_id=vid)
    pdf_path = tmp_path / "vendedor_summary.pdf"
    generar_estado_cuenta_pdf(db, modo="vendedor", archivo=str(pdf_path))
    assert pdf_path.exists() and pdf_path.stat().st_size > 0
