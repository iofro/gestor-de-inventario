import json
from db import DB
import dte as dte_module


def test_cliente_nombre_comercial_en_dte(tmp_path):
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

    db = DB(":memory:")
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
        nombreComercial="Comercial XYZ",
    )
    cid = db.cursor.lastrowid
    cliente = db.get_cliente(cid)
    assert cliente["nombreComercial"] == "Comercial XYZ"

    venta_id = db.add_venta(
        "2024-01-01", 10, cliente_id=cid, extra={"precios_incluyen_iva": False}
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    assert data["receptor"]["nombreComercial"] == "Comercial XYZ"
