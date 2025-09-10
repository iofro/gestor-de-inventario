from decimal import Decimal
from db import DB
from dte import generar_ticket_json, generar_dte_json, recalcular_totales
from nota_credito_electronica import generar_nce_desde_dte


def test_recalcular_ticket_sin_nit_generar_nota(monkeypatch):
    # Mock dependencies for business data
    negocio_data = {
        "nit": "06142816991014",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Comercial",
        "codActividad": "12345",
        "descActividad": "Giro",
        "telefono": "12345678",
        "correo": "test@example.com",
        "direccion": {
            "departamento": "05",
            "municipio": "24",
            "complemento": "Dir",
        },
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: negocio_data)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: negocio_data)
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)

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
        "",
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

    rec = data["receptor"]
    assert "codActividad" not in rec
    assert "descActividad" not in rec
    assert "correo" not in rec
    assert "complemento" not in rec["direccion"]

    nce = generar_nce_desde_dte(db, data, Decimal("1"), motivo="Dev")
    assert nce["identificacion"]["tipoDte"] == "05"
    assert nce["documentoRelacionado"][0]["tipoDocumento"] == "01"


def test_generar_factura_cf_es_ticket_flexible(monkeypatch):
    negocio_data = {
        "nit": "06142816991014",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Comercial",
        "codActividad": "12345",
        "descActividad": "Giro",
        "telefono": "12345678",
        "correo": "test@example.com",
        "direccion": {
            "departamento": "05",
            "municipio": "24",
            "complemento": "Dir",
        },
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: negocio_data)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: negocio_data)

    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = generar_dte_json(db, venta_id, tipo_dte="01", extra={"es_ticket": True})
    rec = data["receptor"]
    assert rec == {"nombre": "Consumidor Final"}


def test_generar_ticket_cf_con_identificacion(monkeypatch):
    negocio_data = {
        "nit": "06142816991014",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Comercial",
        "codActividad": "12345",
        "descActividad": "Giro",
        "telefono": "12345678",
        "correo": "test@example.com",
        "direccion": {
            "departamento": "05",
            "municipio": "24",
            "complemento": "Dir",
        },
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: negocio_data)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: negocio_data)
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)

    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    extra = {
        "es_ticket": True,
        "receptor": {
            "tipoDocumento": "13",
            "numDocumento": "01234567-8",
            "nombre": "Héctor Rosales",
            "direccion": {
                "departamento": "05",
                "municipio": "10",
                "complemento": "Domicilio registrado.",
            },
        },
    }
    data = generar_dte_json(db, venta_id, tipo_dte="03", extra=extra)
    assert data["identificacion"]["tipoDte"] == "01"
    rec = data["receptor"]
    assert rec == {
        "tipoDocumento": "13",
        "numDocumento": "012345678",
        "nombre": "Héctor Rosales",
        "direccion": {
            "departamento": "05",
            "municipio": "10",
            "complemento": "Domicilio registrado.",
        },
    }


def test_ticket_totales_cierran(monkeypatch):
    negocio_data = {
        "nit": "06142816991014",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Comercial",
        "codActividad": "12345",
        "descActividad": "Giro",
        "telefono": "12345678",
        "correo": "test@example.com",
        "direccion": {
            "departamento": "05",
            "municipio": "24",
            "complemento": "Dir",
        },
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: negocio_data)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: negocio_data)

    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 1.13)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 1.70)
    db.add_detalle_venta(venta_id, pid, 1.5, 1.13, vendedor_id=vid)

    data = generar_dte_json(db, venta_id, tipo_dte="01", extra={"es_ticket": True})
    cambios = recalcular_totales(data)
    assert isinstance(cambios, list)
