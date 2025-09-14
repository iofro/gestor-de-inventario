from decimal import Decimal as D
import json

import dte as dte_module
import svfe.config as svfe_config
from db import DB
from dte import generar_dte_json


def _create_sale_with_iva_items():
    """Create a basic sale with two items for DTE type 03."""
    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    # two products so we can check IVA sums across items
    db.add_producto("Prod A", "A1", None, vid, None, 0, 0, 0, 10)
    prod_a = db.cursor.lastrowid
    db.add_producto("Prod B", "B1", None, vid, None, 0, 0, 0, 20)
    prod_b = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "0614-000000-102-5",
        "",
        "giro",
        "",
        "",
        "C",
        "06",
        "01",
    )
    cid = db.cursor.lastrowid
    # total is 30 (10 + 20) before IVA, sumas 30, iva 0 (will be calculated)
    venta_id = db.add_venta_credito_fiscal(
        cid,
        "2024-01-01",
        30,
        "123",
        "0614-000000-102-5",
        "giro",
        sumas=30,
        descuentos=0,
        iva=0,
    )
    db.add_detalle_venta(venta_id, prod_a, 1, 10, vendedor_id=vid)
    db.add_detalle_venta(venta_id, prod_b, 1, 20, vendedor_id=vid)
    return db, venta_id


def test_iva_fields_in_items_and_resumen(tmp_path, monkeypatch):
    # Provide minimal datos_negocio configuration
    datos = {
        "nit": "06141990011019",
        "nrc": "12345678",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "direccion": {
            "departamento": "06",
            "municipio": "10",
            "complemento": "Calle 1",
        },
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    monkeypatch.setattr(dte_module, "DATOS_NEGOCIO_PATH", str(tmp_file))
    monkeypatch.setattr(dte_module, "_load_datos_negocio", lambda: datos)
    monkeypatch.setattr(svfe_config, "DATOS_NEGOCIO_PATH", str(tmp_file))
    monkeypatch.setattr(svfe_config, "load_datos_negocio", lambda: datos)
    monkeypatch.setattr(dte_module, "validate_dte_json", lambda *a, **k: None)

    db, venta_id = _create_sale_with_iva_items()
    data = generar_dte_json(db, venta_id, tipo_dte="03")
    # Sanitize payload to ensure IVA fields are populated as in final DTE output
    data = dte_module.sanitize_dte_payload(data)
    items = data["cuerpoDocumento"]
    resumen = data["resumen"]
    # Every item must include IVA information
    assert all("ivaItem" in item for item in items)
    total_iva_items = sum(D(str(item["ivaItem"])) for item in items)
    # resumen totalIva should match the sum of item IVA values (rounded to cents)
    assert D(str(resumen["totalIva"])) == total_iva_items.quantize(D("0.01"))
