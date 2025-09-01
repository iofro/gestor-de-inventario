from decimal import Decimal as D
import json

from db import DB
from dte import generar_dte_json
from utils.stable_json import stable_stringify


def create_db():
    return DB(":memory:")


def test_trailing_zeros_preserved(tmp_path):
    import dte as dte_module
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
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)
    dte_module._load_datos_negocio = lambda: datos
    import svfe.config as svfe_config
    svfe_config.DATOS_NEGOCIO_PATH = str(tmp_file)
    svfe_config.load_datos_negocio = lambda: datos

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 13)
    prod_id = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "giro",
        "70000001",
        "",
        "C",
        "06",
        "01",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01",
        13,
        cliente_id=cliente_id,
        extra={"precios_incluyen_iva": True},
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 13, vendedor_id=vend_id)

    data = generar_dte_json(db, venta_id)
    item = data["cuerpoDocumento"][0]
    resumen = data["resumen"]

    assert isinstance(item["precioUni"], D)
    assert isinstance(item["montoDescu"], D)
    assert isinstance(item["ivaItem"], D)
    assert isinstance(resumen["totalIva"], D)

    json_str = stable_stringify(data)
    assert "\"montoDescu\":0.0" in json_str
    assert "\"precioUni\":13.0000" in json_str
    assert "\"ivaItem\":1.50" in json_str
    assert "\"totalIva\":1.50" in json_str
