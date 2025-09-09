import json
from db import DB
import dte as dte_module


def _setup_datos_negocio(tmp_path):
    datos = {
        "nit": "06141990011019",
        "nrc": "12345678",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "codActividad": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "direccion": {"departamento": "06", "municipio": "10", "complemento": "Calle 1"},
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)
    dte_module._load_datos_negocio = lambda: datos
    import svfe.config as svfe_config

    svfe_config.DATOS_NEGOCIO_PATH = str(tmp_file)
    svfe_config.load_datos_negocio = lambda: datos
    return datos


def _setup_db():
    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 13)
    pid = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "1234567",
        "06141990011019",
        "",
        "giro",
        "70000001",
        "",
        "C",
        "06",
        "01",
    )
    cid = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01", 13, cliente_id=cid, extra={"precios_incluyen_iva": True}
    )
    db.add_detalle_venta(venta_id, pid, 1, 13, vendedor_id=vid)
    return db, venta_id


def test_correlativo_incrementa_secuencialmente(tmp_path):
    _setup_datos_negocio(tmp_path)
    db, venta_id = _setup_db()

    dte1 = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    dte2 = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    dte3 = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")

    n1 = dte1["identificacion"]["numeroControl"]
    n2 = dte2["identificacion"]["numeroControl"]
    n3 = dte3["identificacion"]["numeroControl"]

    assert n1.endswith("000000000000001")
    assert n2.endswith("000000000000002")
    assert n3.endswith("000000000000003")
