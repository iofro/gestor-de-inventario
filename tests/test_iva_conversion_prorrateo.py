from decimal import Decimal
from utils.monto import to_base_iva, d8
from nota_credito_electronica import generar_nce_desde_dte
from db import DB
from dte import generar_dte_json
import pytest


def create_db():
    return DB(":memory:")


@pytest.fixture(autouse=True)
def _mock_geo(monkeypatch):
    monkeypatch.setattr(
        "dte.validar_dep_muni_por_catalogo",
        lambda d, m, strict=True: (str(d).zfill(2), str(m).zfill(2)),
    )


def test_to_base_iva_splits_total():
    base, iva = to_base_iva(113)
    assert base == d8("100")
    assert iva == d8("13")


def test_prorrateo_porcentaje(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 100)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 100)
    db.add_detalle_venta(venta_id, pid, 1, 100, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("0.1"))
    assert (
        data["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    assert data["resumen"]["montoTotalOperacion"] == 10.0

