import pytest

import json
from pathlib import Path
from decimal import Decimal, getcontext, setcontext

from db import DB
from dte import generar_dte_json, _write_json, money, d4


def create_db():
    return DB(":memory:")


def test_generate_invoice_pdf_error_visible(monkeypatch):
    from utils.doc_generation import generate_invoice_pdf
    class FakeDB:
        def __init__(self):
            self._ventas = [{"id": 1, "fecha": "2024-01-01", "total": 10}]
            self.detalles = {1: [{"cantidad": 1, "precio_unitario": 10}]}

        def get_ventas(self):
            return self._ventas

        def get_venta_credito_fiscal(self, vid):
            return None

        def get_detalles_venta(self, vid):
            return self.detalles.get(vid, [])

        def get_trabajador(self, vid):
            return None

        def add_factura_pdf(self, *a):
            pass

    class Manager:
        def __init__(self, db):
            self.db = db
            self._Distribuidores = []
            self._clientes = []
            self._vendedores = []

    man = Manager(FakeDB())

    def fail(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr("utils.doc_generation.generar_dte_json", fail)

    ctx = getcontext().copy()
    try:
        with pytest.raises(ValueError):
            generate_invoice_pdf(man, 1)
    finally:
        setcontext(ctx)


def test_generar_dte_json_basic(tmp_path):
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
    dte_module._load_datos_negocio = lambda: datos
    import svfe.config as svfe_config
    svfe_config.DATOS_NEGOCIO_PATH = str(tmp_file)
    svfe_config.load_datos_negocio = lambda: datos
    dte_module._load_datos_negocio = lambda: datos

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vend_id, None, 0, 0, 0, 10)
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

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="03")

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
    for key in (
        "documentoRelacionado",
        "otrosDocumentos",
        "apendice",
        "ventaTercero",
        "extension",
    ):
        assert data[key] is None


def test_generar_dte_json_usa_cod_estable_punto(tmp_path):
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
        "codEstable": "2",
        "codPuntoVenta": 5,
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

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "Cliente Giro",
        "70000001",
        "",
        "C",
        "06",
        "01",
        codActividad="99999",
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


def test_generar_dte_json_tipo_fiscal(tmp_path):
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
    dte_module._load_datos_negocio = lambda: datos

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod1", "P1", None, vend_id, None, 0, 0, 0, 10)
    prod1 = db.cursor.lastrowid
    db.add_producto("Prod2", "P2", None, vend_id, None, 0, 0, 0, 20)
    prod2 = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "Cliente Giro",
        "70000001",
        "",
        "C",
        "06",
        "01",
        codActividad="99999",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01",
        30,
        cliente_id=cliente_id,
        extra={"precios_incluyen_iva": False},
    )
    db.add_detalle_venta(
        venta_id,
        prod1,
        1,
        10,
        tipo_fiscal="venta exenta",
        vendedor_id=vend_id,
    )
    db.add_detalle_venta(
        venta_id,
        prod2,
        1,
        20,
        tipo_fiscal="venta no sujeta",
        vendedor_id=vend_id,
    )

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="03")
    items = data["cuerpoDocumento"]
    res = data["resumen"]
    D = Decimal
    assert D(str(items[0]["ventaExenta"])) == D("10")
    assert D(str(items[0]["ventaNoSuj"])) == D("0")
    assert D(str(items[0]["ventaGravada"])) == D("0")
    assert D(str(items[1]["ventaNoSuj"])) == D("20")
    assert D(str(items[1]["ventaExenta"])) == D("0")
    assert D(str(items[1]["ventaGravada"])) == D("0")
    assert D(str(res["totalExenta"])) == D("10")
    assert D(str(res["totalNoSuj"])) == D("20")
    assert D(str(res["totalGravada"])) == D("0")
    assert "ivaItem" not in items[0]
    assert "ivaItem" not in items[1]
    assert "totalIva" not in res

def test_generar_dte_json_precios_incluyen_iva_default(tmp_path):
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
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
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


def test_generar_dte_json_precios_incluyen_iva_unitario(tmp_path):
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
    venta_id = db.add_venta("2024-01-01", 13, cliente_id=cliente_id)
    db.add_detalle_venta(venta_id, pid, 1, 13, vendedor_id=vid)

    data = generar_dte_json(db, venta_id)
    item = data["cuerpoDocumento"][0]
    res = data["resumen"]
    D = Decimal
    assert D(str(item["precioUni"])) == D("13.00")
    assert D(str(item["ventaGravada"])) == D("13.00")
    assert D(str(item["ivaItem"])) == D("1.50")
    assert D(str(res["totalPagar"])) == D("13.00")
    assert D(str(res["totalGravada"])) == D("13.00")


def test_generar_dte_json_cons_final_precio_neto(tmp_path):
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
    venta_id = db.add_venta("2024-01-01", 9, cliente_id=cliente_id)
    db.add_detalle_venta(venta_id, pid, 1, 9, vendedor_id=vid)

    data = generar_dte_json(db, venta_id)
    item = data["cuerpoDocumento"][0]
    res = data["resumen"]
    D = Decimal
    assert D(str(item["precioUni"])) == D("9.00")
    assert D(str(item["ventaGravada"])) == D("9.00")
    assert D(str(item["ivaItem"])) == D("1.04")
    assert D(str(res["totalPagar"])) == D("9.00")
    assert D(str(res["totalGravada"])) == D("9.00")


def test_generar_dte_json_precios_incluyen_iva_multiple_cant(tmp_path):
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
    venta_id = db.add_venta("2024-01-01", 11, cliente_id=cliente_id)
    db.add_detalle_venta(venta_id, pid, 2, 5.5, vendedor_id=vid)

    data = generar_dte_json(db, venta_id)
    item = data["cuerpoDocumento"][0]
    res = data["resumen"]
    D = Decimal
    assert D(str(item["precioUni"])) == D("5.50")
    assert D(str(item["ventaGravada"])) == D("11.00")
    assert D(str(item["ivaItem"])) == D("1.27")
    assert D(str(res["totalPagar"])) == D("11.00")
    assert D(str(res["totalGravada"])) == D("11.00")


def test_generar_dte_json_precios_incluyen_iva_origen_neto(tmp_path):
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
    venta_id = db.add_venta("2024-01-01", 11, cliente_id=cliente_id, extra={"origen_precios": "neto"})
    db.add_detalle_venta(venta_id, pid, 2, 4.865, vendedor_id=vid)

    data = generar_dte_json(db, venta_id)
    item = data["cuerpoDocumento"][0]
    res = data["resumen"]
    D = Decimal
    assert D(str(item["precioUni"])) == D("5.50")
    assert D(str(item["ventaGravada"])) == D("11.00")
    assert D(str(item["ivaItem"])) == D("1.27")
    assert D(str(res["totalPagar"])) == D("11.00")
    assert D(str(res["totalGravada"])) == D("11.00")


@pytest.mark.parametrize("descuento", [Decimal("0.01"), Decimal("0.02")])
def test_generar_dte_json_cf_descuento_cant(tmp_path, descuento):
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
    gross_total = money(Decimal("3") * Decimal("5.5"))
    line_total_dec = d4(gross_total - descuento)
    line_total = money(gross_total - descuento)
    venta_id = db.add_venta("2024-01-01", float(line_total), cliente_id=cliente_id)
    db.add_detalle_venta(
        venta_id, pid, 3, 5.5, vendedor_id=vid, descuento=float(descuento)
    )

    data = generar_dte_json(db, venta_id)
    item = data["cuerpoDocumento"][0]
    res = data["resumen"]

    iva_item = line_total_dec - (line_total_dec / Decimal("1.13"))

    assert Decimal(str(item["precioUni"])) == Decimal("5.50")
    assert Decimal(str(item["ventaGravada"])) == line_total_dec
    assert Decimal(str(item["ivaItem"])) == money(iva_item)

    assert Decimal(str(res["subTotalVentas"])) == line_total
    assert Decimal(str(res["totalDescu"])) == money(descuento)
    assert Decimal(str(res["subTotal"])) == line_total
    assert Decimal(str(res["totalIva"])) == money(iva_item)
    assert Decimal(str(res["montoTotalOperacion"])) == line_total
    assert Decimal(str(res["totalPagar"])) == line_total
    assert res["tributos"] is None


def test_generar_dte_json_cf_descuento_pct(tmp_path):
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
    gross_total = money(Decimal("3") * Decimal("5.5"))
    descuento_pct = Decimal("10")
    desc_monto = d4(gross_total * descuento_pct / Decimal("100"))
    line_total_dec = d4(gross_total - desc_monto)
    line_total = money(gross_total - desc_monto)
    venta_id = db.add_venta("2024-01-01", float(line_total), cliente_id=cliente_id)
    db.add_detalle_venta(
        venta_id,
        pid,
        3,
        5.5,
        vendedor_id=vid,
        descuento=float(descuento_pct),
        descuento_tipo="%",
    )

    data = generar_dte_json(db, venta_id)
    item = data["cuerpoDocumento"][0]
    res = data["resumen"]

    iva_item = line_total_dec - (line_total_dec / Decimal("1.13"))

    assert Decimal(str(item["precioUni"])) == Decimal("5.50")
    assert Decimal(str(item["montoDescu"])) == desc_monto
    assert Decimal(str(item["ventaGravada"])) == line_total_dec
    assert Decimal(str(item["ivaItem"])) == money(iva_item)

    assert Decimal(str(res["subTotalVentas"])) == line_total
    assert Decimal(str(res["totalDescu"])) == money(desc_monto)
    assert Decimal(str(res["subTotal"])) == line_total
    assert Decimal(str(res["totalIva"])) == money(iva_item)
    assert Decimal(str(res["montoTotalOperacion"])) == line_total
    assert Decimal(str(res["totalPagar"])) == line_total
    assert res["tributos"] is None


@pytest.mark.parametrize("cfg, expected", [("pruebas", "00"), ("produccion", "01")])
def test_generar_dte_json_normaliza_ambiente_config(
    tmp_path, cfg, expected, monkeypatch
):
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
        "direccion": {"departamento": "06", "municipio": "10", "complemento": "Calle 1"},
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
    db.add_producto("Prod", "P1", None,  vend_id, None, 0, 0, 0, 10)
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
    db.add_producto("Prod", "P1", None,  vend_id, None, 0, 0, 0, 10)
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
    D = Decimal
    assert data["cuerpoDocumento"][0]["precioUni"] == D("1.13")
    assert data["resumen"]["totalGravada"] == 2.25


def test_dte_sum_mismatch_warning(capsys):
    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vend_id, None, 0, 0, 0, 10)
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
    import svfe.config as svfe_config

    datos = {
        "nit": "06141990011019",
        "nrc": "12345678",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "direccion": {"departamento": "06", "municipio": "10", "complemento": "Calle 1"},
    }
    datos_file = tmp_path / "datos_negocio.json"
    datos_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(datos_file)
    svfe_config.DATOS_NEGOCIO_PATH = str(datos_file)
    svfe_config.load_datos_negocio = lambda: datos
    dte_module._load_datos_negocio = lambda: datos

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
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
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
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
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
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
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
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
        "nrc": "12345678",
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
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
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
        "nrc": "12345678",
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
    db.add_producto("Prod", "P1", None,  vend_id, None, 0, 0, 0, 10)
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


def test_receptor_defaults(tmp_path):
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

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "Cliente Giro",
        "70000001",
        "",
        "C",
        "06",
        "01",
        codActividad="99999",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01",
        11.3,
        cliente_id=cliente_id,
        extra={"precios_incluyen_iva": False},
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    data = dte_module.generar_dte_json(db, venta_id)
    rec = data["receptor"]
    assert rec["codActividad"] == "99999"
    assert rec["descActividad"] == "Cliente Giro"
    assert rec["correo"] == "no-reply@example.com"


def test_credit_payment_defaults(tmp_path):
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

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
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
    extra = {
        "precios_incluyen_iva": False,
        "condicion_operacion": 2,
        "pagos": [
            {"codigo": "01", "montoPago": 11.3, "periodo": "01", "plazo": 30}
        ],
    }
    venta_id = db.add_venta("2024-01-01", 11.3, cliente_id=cliente_id, extra=extra)
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    data = dte_module.generar_dte_json(db, venta_id)
    res = data["resumen"]
    assert res["numPagoElectronico"] == ""
    pago = res["pagos"][0]
    assert pago["codigo"] == "01"
    assert pago["referencia"] == ""
    assert str(pago["periodo"]).zfill(2) == "01"
    assert str(pago["plazo"]) == "30"


def test_item_tributo_guard(tmp_path):
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

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
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
    item = data["cuerpoDocumento"][0]
    resumen = data["resumen"]
    assert item.get("codTributo") is None
    assert item.get("tributos") in (None, [])
    assert "tributos" in resumen
    assert resumen["tributos"] is None
    from decimal import Decimal as D
    assert D(str(resumen["totalIva"])) == D(str(item["ivaItem"]))


def test_consumer_invoice_preserves_tributos_in_final_json(tmp_path):
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

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
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
    data = dte_module.apply_schema_patch(data)
    schema = dte_module.catalogos.get_dte_schema("01")
    clean = dte_module.sanitize_dte_payload(data, schema)
    resumen = clean["resumen"]
    assert "tributos" in resumen
    assert resumen["tributos"] is None


def test_item_no_tributo_when_exento(tmp_path):
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

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
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
    item = data["cuerpoDocumento"][0]
    res = data["resumen"]
    item["ventaExenta"] = item["ventaGravada"]
    item["ventaGravada"] = 0
    item["codTributo"] = "20"
    item["tributos"] = ["20"]
    res["totalExenta"] = res["totalGravada"]
    res["totalGravada"] = 0
    res.pop("tributos", None)
    dte_module.validate_dte_json(data, db=db)
    item = data["cuerpoDocumento"][0]
    assert item["codTributo"] is None
    assert item.get("tributos") is None


def test_credito_fiscal_incluye_tributo(tmp_path):
    import dte as dte_module
    from utils.catalogos import TRIBUTO_IVA, TRIBUTOS

    datos = {
        "nit": "06141990011019",
        "nrc": "12345678",
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
    import svfe.config as svfe_config
    svfe_config.DATOS_NEGOCIO_PATH = str(tmp_file)
    svfe_config.load_datos_negocio = lambda: datos
    dte_module._load_datos_negocio = lambda: datos

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
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
    venta_id = db.add_venta_credito_fiscal(
        cid,
        "2024-01-01",
        10,
        "123",
        "0614-000000-102-5",
        "giro",
        sumas=10,
        descuentos=0,
        iva=0,
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="03")
    item = data["cuerpoDocumento"][0]
    resumen = data["resumen"]
    receptor = data["receptor"]
    assert item.get("codTributo") is None
    assert item["tributos"] == [TRIBUTO_IVA]
    assert "ivaItem" not in item
    assert "totalIva" not in resumen
    assert resumen["tributos"][0]["codigo"] == TRIBUTO_IVA
    assert resumen["tributos"][0]["descripcion"] == TRIBUTOS[TRIBUTO_IVA]
    assert resumen["tributos"][0]["valor"] == Decimal("1.15")
    assert receptor["nit"] == "06140000001025"
    for f in (
        "nit",
        "nrc",
        "nombre",
        "nombreComercial",
        "codActividad",
        "descActividad",
        "telefono",
        "correo",
        "direccion",
    ):
        assert f in receptor
    for f in ("noRemision", "ordenNo", "numDocumento", "tipoDocumento"):
        assert f not in receptor


def test_generar_dte_json_receptor_consumidor_final(tmp_path):
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
    cid = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01", 10, cliente_id=cid, extra={"precios_incluyen_iva": False}
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = dte_module.generar_dte_json(db, venta_id)
    receptor = data["receptor"]
    assert receptor["tipoDocumento"] == "36"
    assert receptor["numDocumento"] == "06141990011019"
    assert "nit" not in receptor
    assert "nombreComercial" not in receptor


def test_resumen_tributo_codigo_str(tmp_path):
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

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
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

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="03")
    res = data["resumen"]
    assert res["tributos"][0]["codigo"] == "20"
    assert isinstance(res["tributos"][0]["codigo"], str)


def test_generar_dte_json_cons_final_otros_tributos(tmp_path):
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
    extra = {"tributos": [{"codigo": "59", "valor": 1.0}]}
    venta_id = db.add_venta("2024-01-01", 11.0, cliente_id=cliente_id, extra=extra)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = generar_dte_json(db, venta_id)
    res = data["resumen"]
    assert res["tributos"][0]["codigo"] == "59"
    assert all(t["codigo"] != "20" for t in res["tributos"])


def test_generar_dte_json_cons_final_rechaza_iva_en_tributos(tmp_path):
    db_path = tmp_path / "db.sqlite"
    db = DB(str(db_path))
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
    extra = {"tributos": [{"codigo": "20", "valor": 1.0}]}
    venta_id = db.add_venta("2024-01-01", 11.0, cliente_id=cliente_id, extra=extra)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    with pytest.raises(ValueError):
        generar_dte_json(db, venta_id)


@pytest.mark.parametrize(
    "doc,tipo_doc",
    [
        ("06141990011019", "36"),  # NIT
        ("01234567-8", "13"),  # DUI
    ],
)
def test_generar_dte_json_cf_documento_preservado(tmp_path, doc, tipo_doc):
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

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid

    # Cliente siempre con NIT válido para DTE-03
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
    cid = db.cursor.lastrowid
    extra = {
        "precios_incluyen_iva": False,
        "receptor": {"numDocumento": doc, "tipoDocumento": tipo_doc},
    }
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cid, extra=extra)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="03")
    receptor = data["receptor"]
    assert receptor["tipoDocumento"] == tipo_doc
    assert receptor["numDocumento"] == doc.replace("-", "")


def test_generar_dte_json_dte03_descuento_colapsado(tmp_path):
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
    cid = db.cursor.lastrowid

    precio = Decimal("15.04")
    descuento = Decimal("0.75")
    total = money(precio - descuento)
    venta_id = db.add_venta(
        "2024-01-01", float(total), cliente_id=cid, extra={"precios_incluyen_iva": False}
    )
    db.add_detalle_venta(
        venta_id, pid, 1, float(precio), vendedor_id=vid, descuento=float(descuento)
    )

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="03")
    item = data["cuerpoDocumento"][0]
    res = data["resumen"]
    D = Decimal

    assert D(str(item["precioUni"])) == D("14.29")
    assert D(str(item["montoDescu"])) == D("0")
    assert D(str(res["descuGravada"])) == D("0")
    assert D(str(res["descuExenta"])) == D("0")
    assert D(str(res["descuNoSuj"])) == D("0")
    assert D(str(res["totalDescu"])) == D("0")

    assert D(str(res["subTotalVentas"])) == D("14.29")
    assert D(str(res["subTotal"])) == D("14.29")
    assert D(str(res["totalGravada"])) == D("14.29")


def test_cliente_email_alias(tmp_path):
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
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "Cliente Giro",
        "70000001",
        "cliente@example.com",
        "C",
        "06",
        "01",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01",
        11.3,
        cliente_id=cliente_id,
        extra={"precios_incluyen_iva": False},
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    data = dte_module.generar_dte_json(db, venta_id)
    assert data["receptor"]["correo"] == "cliente@example.com"
