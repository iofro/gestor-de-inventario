from decimal import Decimal
import pytest
from db import DB
from dte import generar_ticket_json, recalcular_totales
from nota_credito_electronica import generar_nce_desde_dte


@pytest.fixture(autouse=True)
def _mock_geo(monkeypatch):
    monkeypatch.setattr(
        "dte.validar_dep_muni_por_catalogo",
        lambda d, m, strict=True: (str(d).zfill(2), str(m).zfill(2)),
    )


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

    assert data["identificacion"]["tipoDte"] == "01"
    assert "extra" not in data
    rec = data["receptor"]
    assert rec["nombre"] == "Cliente"
    assert rec["tipoDocumento"]
    assert rec["numDocumento"]

    nce = generar_nce_desde_dte(db, data, Decimal("1"), motivo="Dev")
    assert nce["identificacion"]["tipoDte"] == "05"
    assert nce["documentoRelacionado"][0]["tipoDocumento"] == "01"
    assert (
        nce["documentoRelacionado"][0]["numeroDocumento"]
        == data["identificacion"]["numeroControl"]
    )
    assert "nit" not in nce["receptor"]


def test_generar_ticket_con_receptor_valido(monkeypatch):
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
    db.add_cliente(
        "Cliente",
        "1234567",
        "06142816991014",
        "",
        "",
        "22223333",
        "cli@example.com",
        "Colonia ABC",
        "05",
        "24",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cliente_id)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = generar_ticket_json(db, venta_id)
    recalcular_totales(data)

    assert data["identificacion"]["tipoDte"] == "01"
    assert "extra" not in data
    assert data["receptor"] is not None
    assert data["receptor"].get("direccion", {}).get("complemento") == "Colonia ABC"
    rec = data["receptor"]
    assert "nit" not in rec
    assert "nombreComercial" not in rec
