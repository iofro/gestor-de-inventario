from decimal import Decimal
from db import DB
from dte import generar_ticket_json, recalcular_totales
from nota_credito_electronica import generar_nce_desde_dte


def test_recalcular_ticket_sin_nit_generar_nota(monkeypatch):
    # Mock dependencies for business data and validation
    datos = {
        "nit": "06141990011019",
        "nrc": "12345678",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    monkeypatch.setattr("dte.recalcular_totales", lambda *a, **k: [])

    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "",  # NIT vacío para simular ticket sin NIT
        "",
        "giro",
        "",
        "",
        "",
        "06",
        "01",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cliente_id)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = generar_ticket_json(db, venta_id)
    # No debe lanzar error al recalcular totales aunque no haya NIT
    recalcular_totales(data)

    nce = generar_nce_desde_dte(db, data, Decimal("1"), motivo="Dev")
    assert nce["identificacion"]["tipoDte"] == "05"
    assert nce["documentoRelacionado"][0]["tipoDocumento"] == "03"


def test_generar_ticket_json_dui_auto_tipo(monkeypatch):
    datos = {
        "nit": "06141990011019",
        "nrc": "12345678",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    monkeypatch.setattr("dte.recalcular_totales", lambda *a, **k: [])

    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "",  # sin NIT
        "",
        "giro",
        "",
        "",
        "",
        "06",
        "01",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cliente_id)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    db.update_venta_extra(venta_id, {"receptor": {"numDocumento": "01234567-8"}})

    data = generar_ticket_json(db, venta_id)
    assert data["receptor"]["tipoDocumento"] == "13"
