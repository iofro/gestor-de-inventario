import json
from decimal import Decimal as D

import dte as dte_module
from tests.test_generar_dte_json import create_db


def test_credito_fiscal_resumen_omite_total_iva(tmp_path):
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
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
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
        "2024-01-01", 5, cliente_id=cliente_id, extra={"precios_incluyen_iva": False}
    )
    db.add_detalle_venta(venta_id, pid, 1, 5, vendedor_id=vid)

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="03")
    resumen = data["resumen"]

    assert "totalIva" not in resumen
    trib = resumen["tributos"]
    assert any(
        t["codigo"] == "20" and D(str(t["valor"])) == D("0.65") for t in trib
    )
