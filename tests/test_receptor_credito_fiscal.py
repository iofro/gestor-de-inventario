import json
import re
from db import DB
import dte
from svfe.generators import generar_factura_fiscal, strip_extras
import svfe.config as svfe_config


def create_db():
    return DB(":memory:")


def test_receptor_fields_credito_fiscal(tmp_path):
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
    dte.DATOS_NEGOCIO_PATH = str(tmp_file)
    svfe_config.DATOS_NEGOCIO_PATH = str(tmp_file)
    svfe_config.load_datos_negocio = lambda: datos

    db = create_db()
    payload = strip_extras(generar_factura_fiscal(db))
    payload["identificacion"]["version"] = 1
    receptor = payload["receptor"]
    receptor.pop("nombreComercial")
    receptor.update({
        "noRemision": "999",
        "ordenNo": "888",
        "numDocumento": "01234567-8",
        "tipoDocumento": "13",
    })
    dte.validate_dte_json(payload, db=db)
    receptor = payload["receptor"]
    required = {
        "nit",
        "nrc",
        "nombre",
        "codActividad",
        "descActividad",
        "nombreComercial",
        "direccion",
        "telefono",
        "correo",
    }
    assert required <= set(receptor)
    assert receptor["nombreComercial"] == receptor["nombre"]
    for key in ("noRemision", "ordenNo", "numDocumento", "tipoDocumento"):
        assert key not in receptor
    assert re.fullmatch(r"[0-9]{9}|[0-9]{14}", receptor["nit"])
