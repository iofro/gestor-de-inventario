from db import DB
from ticket_pdf import generar_ticket_pdf, generar_ticket_personalizado
import fitz


def test_ticket_path_storage(tmp_path):
    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 50)
    path = tmp_path / "ticket.pdf"
    path.write_text("data")
    db.add_ticket_pdf(venta_id, str(path))
    assert db.get_ticket_pdf(venta_id) == str(path)


def test_add_nota_and_retrieve(tmp_path):
    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 100)
    db.add_nota(venta_id, "credito", "2024-01-02", 10.0, "devolucion")
    notas = db.get_notas_by_venta(venta_id)
    assert len(notas) == 1
    n = notas[0]
    assert n["tipo"] == "credito"
    assert n["monto"] == 10.0


def test_generar_ticket_pdf(tmp_path):
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10}
    detalles = [{"descripcion": "Prod", "cantidad": 1, "precio_unitario": 10}]
    archivo = tmp_path / "ticket.pdf"
    generar_ticket_pdf(venta, detalles, str(archivo))
    assert archivo.exists()
    assert archivo.stat().st_size > 0



def test_generar_ticket_pdf_header(tmp_path):
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10}
    detalles = [{"descripcion": "Prod", "cantidad": 1, "precio_unitario": 10}]
    datos = {"nombre_comercial": "MI NEGOCIO"}
    archivo = tmp_path / "ticket.pdf"
    generar_ticket_pdf(venta, detalles, str(archivo), datos_negocio=datos)
    assert archivo.exists()
    with fitz.open(archivo) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "MI NEGOCIO" in text


def test_generar_ticket_personalizado_missing(tmp_path):
    venta = {"id": 1, "total": 10}
    detalles = []
    archivo = tmp_path / "ticket_pers.pdf"
    generar_ticket_personalizado(venta, detalles, str(archivo), datos_negocio={}, dte_data={})
    assert archivo.exists()
    with fitz.open(archivo) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "falta" in text
