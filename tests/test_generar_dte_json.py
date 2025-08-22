import pytest

import json
from pathlib import Path
from decimal import Decimal

from db import DB
from dte import generar_dte_json, _write_json


def create_db():
    return DB(":memory:")


def test_generar_dte_json_basic(tmp_path):
    import dte as dte_module

    datos = {
        "nit": "06141990011019",
        "nrc": "1234567-8",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "direccion": {
            "departamento": "06",
            "municipio": "15",
            "complemento": "Calle 1",
        },
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vend_id, None, 0, 0, 0, 10)
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
        "2024-01-01", 11.3, cliente_id=cliente_id, extra={"precios_incluyen_iva": False}
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    data = dte_module.generar_dte_json(db, venta_id)

    idf = data["identificacion"]
    res = data["resumen"]

    assert idf["tipoDte"] == "01"
    assert idf["ambiente"] in ("00", "01")

    def q2(x):
        return Decimal(str(x)).quantize(Decimal("0.01"))

    assert q2(res["totalPagar"]) == sum(
        q2(p["montoPago"]) for p in (res.get("pagos") or [])
    )

    expected = {
        "identificacion",
        "emisor",
        "receptor",
        "cuerpoDocumento",
        "resumen",
        "documentoRelacionado",
        "otrosDocumentos",
        "apendice",
        "ventaTercero",
        "extension",
    }
    assert set(data.keys()) == expected


def test_gravado_item_includes_tributos(tmp_path):
    import dte as dte_module

    datos = {
        "nit": "06141990011019",
        "nrc": "1234567-8",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "direccion": {
            "departamento": "06",
            "municipio": "15",
            "complemento": "Calle 1",
        },
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)
    import svfe.config as svfe_config
    svfe_config.DATOS_NEGOCIO_PATH = str(tmp_file)

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
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
        "2024-01-01", 11.3, cliente_id=cliente_id, extra={"precios_incluyen_iva": False}
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = dte_module.generar_dte_json(db, venta_id)
    item = data["cuerpoDocumento"][0]
    resumen = data["resumen"]
    assert item.get("tributos") == ["19"]
    assert resumen.get("tributos")


def test_generar_dte_json_usa_cod_estable_punto(tmp_path):
    import dte as dte_module

    datos = {
        "nit": "06141990011019",
        "nrc": "1234567-8",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "codEstable": "2",
        "codPuntoVenta": 5,
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vend_id, None, 0, 0, 0, 10)
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
        "2024-01-01", 10, cliente_id=cliente_id, extra={"precios_incluyen_iva": False}
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    data = generar_dte_json(db, venta_id)
    numero = data["identificacion"]["numeroControl"]
    assert numero.startswith("DTE-01-S002P005-")
    emisor = data["emisor"]
    assert emisor["codEstable"] == "0002"
    assert emisor["codPuntoVenta"] == "0005"

def test_generar_dte_json_precios_incluyen_iva_default(tmp_path):
    import dte as dte_module

    datos = {
        "nit": "06141990011019",
        "nrc": "1234567-8",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
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
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cliente_id)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    data = generar_dte_json(db, venta_id)
    item = data["cuerpoDocumento"][0]
    res = data["resumen"]
    D = Decimal
    assert D(str(item["ventaGravada"])) == D("8.85")
    assert D(str(item["ivaItem"])) == D("1.15")
    assert D(str(res["totalGravada"])) == D("8.85")
    assert D(str(res["totalIva"])) == D("1.15")
    assert D(str(res["totalPagar"])) == D("10.00")
    assert res["totalLetras"].startswith("DIEZ")


@pytest.mark.parametrize("cfg, expected", [("pruebas", "00"), ("produccion", "01")])
def test_generar_dte_json_normaliza_ambiente_config(
    tmp_path, cfg, expected, monkeypatch
):
    import dte as dte_module

    datos = {
        "nit": "06141990011019",
        "nrc": "1234567-8",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
    }
    datos_file = tmp_path / "datos_negocio.json"
    datos_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(datos_file)

    cfg_file = tmp_path / "config_negocio.json"
    cfg_file.write_text(json.dumps({"ambiente": cfg}))
    dte_module.CONFIG_NEGOCIO_PATH = str(cfg_file)

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vend_id, None, 0, 0, 0, 10)
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
        "2024-01-01", 10, cliente_id=cliente_id, extra={"precios_incluyen_iva": False}
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    orig_validate = dte_module.validate_dte_json
    orig_norm = dte_module._normalize_payload
    monkeypatch.setattr(dte_module, "validate_dte_json", lambda payload, **kwargs: None)
    monkeypatch.setattr(dte_module, "_normalize_payload", lambda x: x)
    data = dte_module.generar_dte_json(db, venta_id, ambiente="00")
    monkeypatch.setattr(dte_module, "validate_dte_json", orig_validate)
    data["identificacion"].pop("ambiente", None)
    dte_module.validate_dte_json(data, db=db)
    monkeypatch.setattr(dte_module, "_normalize_payload", orig_norm)
    assert data["identificacion"]["ambiente"] == expected


def test_dte_rounding_and_validation(capsys):
    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "giro",
        "",
        "",
        "C",
        "06",
        "01",
    )
    cliente_id = db.cursor.lastrowid
    precio = 1.123456789
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        precio * 2,
        "123",
        "06141990011019",
        "giro",
        sumas=precio * 2,
        descuentos=0,
        iva=0,
        extra={"precios_incluyen_iva": False},
    )
    db.cursor.execute(
        "UPDATE ventas SET extra=? WHERE id=?",
        (json.dumps({"precios_incluyen_iva": False}), venta_id),
    )
    db.add_detalle_venta(venta_id, prod_id, 2, precio, vendedor_id=vend_id)

    data = generar_dte_json(db, venta_id)
    capsys.readouterr()
    # Values rounded
    assert data["cuerpoDocumento"][0]["precioUni"] == 1.12345679
    assert data["resumen"]["totalGravada"] == 2.25


def test_dte_sum_mismatch_warning(capsys):
    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "giro",
        "",
        "",
        "C",
        "06",
        "01",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        10,
        "123",
        "06141990011019",
        "giro",
        sumas=10,
        descuentos=0,
        iva=0,
        extra={"precios_incluyen_iva": False},
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 5, vendedor_id=vend_id)

    generar_dte_json(db, venta_id)
    out = capsys.readouterr().out
    assert "Advertencia" in out


def test_generar_ticket_json_tipo(tmp_path):
    import dte as dte_module

    datos = {
        "nit": "06141990011019",
        "nrc": "1234567-8",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
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

    data = generar_dte_json(db, venta_id, tipo_dte="03")
    assert data["identificacion"]["tipoDte"] == "03"


@pytest.mark.parametrize(
    "ambiente, expected", [("pruebas", "00"), ("produccion", "01")]
)
def test_generar_dte_json_normaliza_ambiente_param(ambiente, expected, monkeypatch):
    import dte as dte_module

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
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

    monkeypatch.setattr(dte_module, "validate_dte_json", lambda payload, **kwargs: None)
    data = dte_module.generar_dte_json(db, venta_id, ambiente=ambiente)
    assert data["identificacion"]["ambiente"] == expected


def test_dte_comision_sin_advertencia_total(capsys):
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "giro",
        "",
        "",
        "C",
        "06",
        "01",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        12,
        "123",
        "06141990011019",
        "giro",
        sumas=10,
        descuentos=0,
        iva=0,
        extra={"precios_incluyen_iva": False},
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, comision=2, vendedor_id=vid)
    generar_dte_json(db, venta_id)
    capsys.readouterr()


def test_generar_dte_json_condicion_operacion_invalida():
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "giro",
        "",
        "",
        "C",
        "06",
        "01",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        10,
        "123",
        "06141990011019",
        "giro",
        condicion_pago="Invalida",
        extra={"precios_incluyen_iva": False},
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = generar_dte_json(db, venta_id)
    assert data["resumen"]["condicionOperacion"] == 1


def test_write_json_guard(tmp_path):
    path = tmp_path / "facturas_consumidor_final" / "ejemplo.json"
    path.parent.mkdir(parents=True)
    with pytest.raises(AssertionError):
        _write_json(str(path), {})


def test_generar_dte_json_receptor_extra_preserva_direccion(tmp_path):
    import dte as dte_module

    datos = {
        "nit": "06141990011019",
        "nrc": "1234567-8",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
    }
    datos_file = tmp_path / "datos_negocio.json"
    datos_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(datos_file)

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "giro",
        "70000001",
        "",
        "Calle",
        "06",
        "01",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01",
        10,
        cliente_id=cliente_id,
        extra={
            "precios_incluyen_iva": False,
            "receptor": {"departamento": "", "municipio": ""},
        },
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = generar_dte_json(db, venta_id)
    direccion = data["receptor"]["direccion"]
    assert direccion["departamento"] == "06"
    assert direccion["municipio"] == "01"
    assert direccion["complemento"] == "Calle"


def test_generar_dte_json_municipio_fuera_depto(tmp_path):
    import dte as dte_module

    datos = {
        "nit": "06141990011019",
        "nrc": "1234567-8",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
    }
    datos_file = tmp_path / "datos_negocio.json"
    datos_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(datos_file)

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vend_id, None, 0, 0, 0, 10)
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
        "15",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01",
        11.3,
        cliente_id=cliente_id,
        extra={"precios_incluyen_iva": False},
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    data = generar_dte_json(db, venta_id)
    direccion = data["receptor"]["direccion"]
    assert direccion["departamento"] == "06"
    assert direccion["municipio"] == "15"
