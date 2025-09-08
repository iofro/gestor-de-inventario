import pytest
from db import DB


def create_db():
    return DB(":memory:")


def test_agregar_y_obtener_notas():
    db = create_db()
    db.add_cliente("Juan", "", "", "", "", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 100, cliente_id=cliente_id)

    note_id = db.agregar_nota("credito", venta_id, "2024-01-02", 25.0, "Devolucion", {"linea": 1})
    assert isinstance(note_id, int)

    notas = db.obtener_notas_por_venta(venta_id)
    assert len(notas) == 1
    nota = notas[0]
    assert nota["tipo"] == "credito"
    assert nota["venta_id"] == venta_id
    assert nota["monto"] == 25.0
    assert nota["motivo"] == "Devolucion"
    assert nota["detalles"] == {"linea": 1}


def test_agregar_nota_remision():
    db = create_db()
    db.add_cliente("Ana", "", "", "", "", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 50, cliente_id=cliente_id)
    note_id = db.agregar_nota("remision", venta_id, "2024-01-02", 0, "Envio")
    assert isinstance(note_id, int)
    notas = db.obtener_notas_por_venta(venta_id)
    assert notas[0]["tipo"] == "remision"

def test_agregar_nota_venta_inexistente():
    db = create_db()
    with pytest.raises(ValueError):
        db.agregar_nota("debito", 999, "2024-01-03", 10, "extra")


def test_credito_no_supera_total():
    db = create_db()
    db.add_cliente("Ana", "", "", "", "", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 50, cliente_id=cliente_id)
    with pytest.raises(ValueError):
        db.agregar_nota("credito", venta_id, "2024-01-02", 60, "Dev")


def test_credito_no_supera_saldo():
    db = create_db()
    db.add_cliente("Ana", "", "", "", "", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 100, cliente_id=cliente_id)
    db.agregar_nota("credito", venta_id, "2024-01-02", 60, "Parcial")
    with pytest.raises(ValueError):
        db.agregar_nota("credito", venta_id, "2024-01-03", 50, "Resto")
