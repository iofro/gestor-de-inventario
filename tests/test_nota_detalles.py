import json
from db import DB
from nota_credito_electronica import generar_nce_desde_nota
from dte import generar_nota_debito_json

def create_db():
    return DB(":memory:")


def _prep(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )


def test_generar_nce_detalles(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "precio_unitario": 10,
            "ventas_gravadas": 10,
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo, detalles) VALUES (?,?,?,?,?,?)",
        (venta_id, "credito", "2024-01-02", 10, "Dev", json.dumps(detalles)),
    )
    nota_id = db.cursor.lastrowid
    db.conn.commit()
    data = generar_nce_desde_nota(db, nota_id)
    item = data["cuerpoDocumento"][0]
    assert item["ventaGravada"] == 10
    assert data["resumen"]["totalGravada"] == 10


def test_generar_nota_debito_detalles(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Ajuste",
            "precio_unitario": 2,
            "ventas_gravadas": 2,
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo, detalles) VALUES (?,?,?,?,?,?)",
        (venta_id, "debito", "2024-01-02", 2, "Ajuste", json.dumps(detalles)),
    )
    nota_id = db.cursor.lastrowid
    db.conn.commit()
    data = generar_nota_debito_json(db, nota_id)
    item = data["cuerpoDocumento"][0]
    assert item["ventaGravada"] == 2
    assert data["resumen"]["totalGravada"] == 2
