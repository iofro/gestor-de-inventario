import json
from decimal import Decimal as D

import dte as dte_module
import svfe.config as svfe_config
from db import DB
from dte import generar_dte_json


def test_resumen_venta_total_cero(tmp_path, monkeypatch):
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
    svfe_config.DATOS_NEGOCIO_PATH = str(tmp_file)
    svfe_config.load_datos_negocio = lambda: datos

    monkeypatch.setattr(dte_module, "validate_dte_json", lambda *a, **k: None)

    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123456",
        "06141990011019",
        "",
        "Cliente Giro",
        "70000001",
        "",
        "C",
        "06",
        "01",
    )
    cid = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01", 0, cliente_id=cid, extra={"precios_incluyen_iva": True}
    )
    db.add_detalle_venta(
        venta_id, pid, 1, 12, vendedor_id=vid, tipo_fiscal="venta gravada"
    )

    data = generar_dte_json(db, venta_id)
    resumen = data["resumen"]
    assert D(str(resumen["subTotalVentas"])) == D("12.00")
    assert D(str(resumen["totalPagar"])) == D("12.00")
    assert D(str(resumen["totalIva"])) == D("1.38")
