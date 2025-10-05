import pytest

import json
from pathlib import Path
from decimal import Decimal, getcontext, setcontext, InvalidOperation, ROUND_HALF_UP

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

def test_venta_vs_dte_precision(tmp_path):
    """Temporal test para depuración manual de cálculos POS vs DTE.

    Se crea una venta con múltiples descuentos y diferentes tipos de
    impuestos. El objetivo es simplemente ejecutar ``log_venta_vs_dte`` y
    revisar manualmente los resultados en el log. No se realizan aserciones.
    """

    import dte as dte_module
    import svfe.config as svfe_config
    from utils.doc_generation import log_venta_vs_dte

    ctx = getcontext().copy()
    getcontext().prec = 8
    getcontext().traps[InvalidOperation] = False
    try:
        datos = {
            "nit": "06141990011019",
            "nrc": "1234567",
            "dui": "01234567-8",
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

        db = create_db()
        db.add_vendedor("V1")
        vend_id = db.cursor.lastrowid

        def add_prod(nombre: str, codigo: str) -> int:
            db.add_producto(nombre, codigo, None, vend_id, None, 0, 0, 0, 10)
            return db.cursor.lastrowid

        prod_a = add_prod("A-001", "A-001")
        prod_b = add_prod("B-002", "B-002")
        prod_c = add_prod("C-003", "C-003")
        prod_d = add_prod("D-004", "D-004")
        prod_e = add_prod("E-005", "E-005")

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
        cliente_id = db.cursor.lastrowid

        total = 111.97
        venta_id = db.add_venta_credito_fiscal(
            cliente_id,
            "2024-05-01",
            total,
            "1234567",
            "06141990011019",
            "Comercio",
            extra={
                "precios_incluyen_iva": True,
                "descuento_global": 0.57,
                "pagos": [{"codigo": "01", "montoPago": 111.97}],
            },
        )

        db.add_detalle_venta(
            venta_id,
            prod_a,
            3.75,
            12.9875,
            descuento=7.75,
            descuento_tipo="%",
            tipo_fiscal="venta gravada",
            vendedor_id=vend_id,
        )
        db.add_detalle_venta(
            venta_id,
            prod_b,
            2.20,
            8.3333,
            descuento=1.2345,
            descuento_tipo="",
            tipo_fiscal="venta gravada",
            vendedor_id=vend_id,
        )
        db.add_detalle_venta(
            venta_id,
            prod_c,
            4.15,
            5.1709,
            tipo_fiscal="venta exenta",
            vendedor_id=vend_id,
        )
        db.add_detalle_venta(
            venta_id,
            prod_d,
            6.40,
            0.9917,
            descuento=12.5,
            descuento_tipo="%",
            tipo_fiscal="venta no sujeta",
            vendedor_id=vend_id,
        )
        db.add_detalle_venta(
            venta_id,
            prod_e,
            1.33,
            18.1701,
            descuento=2.75,
            descuento_tipo="%",
            tipo_fiscal="venta gravada",
            vendedor_id=vend_id,
        )

        class Manager:
            def __init__(self, db):
                self.db = db
                self._Distribuidores = []
                self._clientes = []
                self._vendedores = []

        manager = Manager(db)
        try:
            log_venta_vs_dte(manager, venta_id)
        except Exception:
            pass
    finally:
        setcontext(ctx)


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
        "23",
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

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
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
    assert "ivaItem" not in item
    assert D(str(res["totalGravada"])) == D("8.85")
    assert "totalIva" not in res


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
    assert D(str(res["totalPagar"])) == D("13.00")
    assert D(str(res["totalGravada"])) == D("13.00")
    assert "ivaItem" not in item


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
    assert D(str(res["totalPagar"])) == D("9.00")
    assert D(str(res["totalGravada"])) == D("9.00")
    assert "ivaItem" not in item


def test_generar_dte_json_asigna_nombre_consumidor_final(tmp_path):
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
        "direccion": {
            "departamento": "06",
            "municipio": "10",
            "complemento": "Calle 1",
        },
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    original_path = dte_module.DATOS_NEGOCIO_PATH
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)
    original_loader = dte_module._load_datos_negocio
    original_svfe_path = svfe_config.DATOS_NEGOCIO_PATH
    original_svfe_loader = svfe_config.load_datos_negocio
    svfe_config.DATOS_NEGOCIO_PATH = str(tmp_file)
    dte_module._load_datos_negocio = lambda: datos
    svfe_config.load_datos_negocio = lambda: datos

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01",
        10,
        extra={
            "precios_incluyen_iva": False,
            "es_ticket": True,
            "receptor": {
                "direccion": {
                    "departamento": "06",
                    "municipio": "23",
                    "complemento": "San Salvador",
                }
            },
        },
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vid)

    try:
        data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    finally:
        dte_module.DATOS_NEGOCIO_PATH = original_path
        dte_module._load_datos_negocio = original_loader
        svfe_config.DATOS_NEGOCIO_PATH = original_svfe_path
        svfe_config.load_datos_negocio = original_svfe_loader

    assert data["receptor"]["nombre"] == "Consumidor Final"


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
    assert D(str(res["totalPagar"])) == D("11.00")
    assert D(str(res["totalGravada"])) == D("11.00")
    assert "ivaItem" not in item


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
    assert D(str(res["totalPagar"])) == D("11.00")
    assert D(str(res["totalGravada"])) == D("11.00")
    assert "ivaItem" not in item


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
    assert "ivaItem" not in item

    assert Decimal(str(res["subTotalVentas"])) == line_total
    assert Decimal(str(res["totalDescu"])) == money(descuento)
    assert Decimal(str(res["subTotal"])) == line_total
    assert Decimal(str(res["montoTotalOperacion"])) == line_total
    assert Decimal(str(res["totalPagar"])) == line_total
    assert "totalIva" not in res
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
    assert "ivaItem" not in item

    assert Decimal(str(res["subTotalVentas"])) == line_total
    assert Decimal(str(res["totalDescu"])) == money(desc_monto)
    assert Decimal(str(res["subTotal"])) == line_total
    assert Decimal(str(res["montoTotalOperacion"])) == line_total
    assert Decimal(str(res["totalPagar"])) == line_total
    assert "totalIva" not in res
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

    data = generar_dte_json(db, venta_id, tipo_dte="01")
    assert data["identificacion"]["tipoDte"] == "01"


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


def test_generar_dte_json_config_produccion_impone_ambiente(tmp_path, monkeypatch):
    import dte as dte_module
    import svfe.config as svfe_config

    datos = {
        "nit": "06141990011019",
        "nrc": "123456",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "direccion": {"departamento": "06", "municipio": "23", "complemento": "Calle 1"},
        "dte_api": {"prefijo_control": "S001P001"},
    }
    datos_file = tmp_path / "datos_negocio.json"
    datos_file.write_text(json.dumps(datos))
    monkeypatch.setattr(dte_module, "DATOS_NEGOCIO_PATH", str(datos_file), raising=False)
    monkeypatch.setattr(dte_module, "_load_datos_negocio", lambda: datos)
    monkeypatch.setattr(svfe_config, "DATOS_NEGOCIO_PATH", str(datos_file), raising=False)
    monkeypatch.setattr(svfe_config, "load_datos_negocio", lambda: datos)
    monkeypatch.setattr(
        dte_module,
        "_load_dte_api_config",
        lambda: {"ambiente": "produccion", "url": "https://api.example.com/fesv"},
    )

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "700001",
        "06141990011019",
        "",
        "giro",
        "22223333",
        "",
        "C",
        "06",
        "23",
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01",
        5,
        cliente_id=cliente_id,
        extra={"precios_incluyen_iva": False, "ambiente": "00"},
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 5, vendedor_id=vend_id)

    data = dte_module.generar_dte_json(db, venta_id, ambiente="pruebas")
    assert data["identificacion"]["ambiente"] == "01"


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


def test_generar_dte_json_resumen_fc_descuentos_mixtos(tmp_path):
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
        "direccion": {
            "departamento": "06",
            "municipio": "10",
            "complemento": "Calle 1",
        },
    }
    datos_file = tmp_path / "datos_negocio.json"
    datos_file.write_text(json.dumps(datos))
    original_path = dte_module.DATOS_NEGOCIO_PATH
    original_svfe_path = svfe_config.DATOS_NEGOCIO_PATH
    dte_module.DATOS_NEGOCIO_PATH = str(datos_file)
    svfe_config.DATOS_NEGOCIO_PATH = str(datos_file)

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid

    def add_prod(nombre: str, codigo: str) -> int:
        db.add_producto(nombre, codigo, None, vid, None, 0, 0, 0, 10)
        return db.cursor.lastrowid

    pid_grav_1 = add_prod("Prod Grav 1", "PG1")
    pid_grav_2 = add_prod("Prod Grav 2", "PG2")
    pid_exe = add_prod("Prod Exe", "PE")
    pid_nos = add_prod("Prod NoS", "PN")

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
        "23",
    )
    cliente_id = db.cursor.lastrowid

    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        0,
        "123",
        "06141990011019",
        "giro",
        sumas=0,
        descuentos=0,
        iva=0,
        extra={
            "descu_gravada": "1.00",
            "descu_exenta": "0.50",
            "descu_no_suj": "0.30",
        },
    )

    db.add_detalle_venta(
        venta_id,
        pid_grav_1,
        1,
        16,
        descuento=1,
        descuento_tipo="$",
        tipo_fiscal="gravada",
        precio_con_iva=16,
    )
    db.add_detalle_venta(
        venta_id,
        pid_grav_2,
        1,
        15.4,
        descuento=1,
        descuento_tipo="$",
        tipo_fiscal="gravada",
        precio_con_iva=15.4,
    )
    db.add_detalle_venta(
        venta_id,
        pid_exe,
        1,
        15.4,
        descuento=1,
        descuento_tipo="$",
        tipo_fiscal="exenta",
        precio_con_iva=15.4,
    )
    db.add_detalle_venta(
        venta_id,
        pid_nos,
        1,
        15.4,
        descuento=1,
        descuento_tipo="$",
        tipo_fiscal="no_sujeta",
        precio_con_iva=15.4,
    )

    try:
        data = generar_dte_json(db, venta_id, tipo_dte="03")
    finally:
        dte_module.DATOS_NEGOCIO_PATH = original_path
        svfe_config.DATOS_NEGOCIO_PATH = original_svfe_path

    resumen = data["resumen"]
    cuerpo = data["cuerpoDocumento"]

    q8 = Decimal("0.00000001")
    base_grav_1 = ((Decimal("16") - Decimal("1")) / Decimal("1.13")).quantize(
        q8, rounding=ROUND_HALF_UP
    )
    base_grav_2 = ((Decimal("15.4") - Decimal("1")) / Decimal("1.13")).quantize(
        q8, rounding=ROUND_HALF_UP
    )
    expected_total_gravada = money(base_grav_1 + base_grav_2)
    expected_total_exenta = money(Decimal("15.4") - Decimal("1"))
    expected_total_no_suj = money(Decimal("15.4") - Decimal("1"))
    expected_total_no_gravado = money(Decimal("0"))
    expected_sub_total_ventas = money(
        expected_total_gravada
        + expected_total_exenta
        + expected_total_no_suj
        + expected_total_no_gravado
    )
    expected_descuentos = money(Decimal("0"))
    expected_sub_total = money(expected_sub_total_ventas - expected_descuentos)
    expected_iva = money(expected_total_gravada * Decimal("0.13"))
    expected_monto_total = money(expected_sub_total + expected_iva)
    expected_total_pagar = expected_monto_total

    total_gravada = Decimal(str(resumen.get("totalGravada", 0)))
    total_exenta = Decimal(str(resumen.get("totalExenta", 0)))
    total_no_suj = Decimal(str(resumen.get("totalNoSuj", 0)))
    total_no_gravado = Decimal(str(resumen.get("totalNoGravado", 0)))
    sub_total_ventas = Decimal(str(resumen.get("subTotalVentas", 0)))

    assert total_gravada == expected_total_gravada
    assert total_exenta == expected_total_exenta
    assert total_no_suj == expected_total_no_suj
    assert total_no_gravado == expected_total_no_gravado
    assert sub_total_ventas == expected_sub_total_ventas

    descu_no_suj = Decimal(str(resumen.get("descuNoSuj", 0)))
    descu_exenta = Decimal(str(resumen.get("descuExenta", 0)))
    descu_gravada = Decimal(str(resumen.get("descuGravada", 0)))
    total_descuentos = money(descu_no_suj + descu_exenta + descu_gravada)

    assert descu_no_suj == Decimal("0")
    assert descu_exenta == Decimal("0")
    assert descu_gravada == Decimal("0")
    assert total_descuentos == expected_descuentos
    assert Decimal(str(resumen.get("totalDescu", 0))) == expected_descuentos

    sub_total = Decimal(str(resumen.get("subTotal", 0)))
    assert sub_total == expected_sub_total

    tributos = resumen.get("tributos") or []
    assert tributos and [t.get("codigo") for t in tributos] == ["20"]
    iva_total = money(Decimal(str(tributos[0]["valor"])))
    assert iva_total == expected_iva

    monto_total_operacion = Decimal(str(resumen.get("montoTotalOperacion", 0)))
    assert monto_total_operacion == expected_monto_total

    total_pagar = Decimal(str(resumen.get("totalPagar", 0)))
    assert total_pagar == expected_total_pagar

    tg8 = sum(Decimal(str(item.get("ventaGravada") or 0)) for item in cuerpo)
    te8 = sum(Decimal(str(item.get("ventaExenta") or 0)) for item in cuerpo)
    tns8 = sum(Decimal(str(item.get("ventaNoSuj") or 0)) for item in cuerpo)
    tng8 = sum(Decimal(str(item.get("noGravado") or 0)) for item in cuerpo)

    assert total_gravada == money(tg8)
    assert total_exenta == money(te8)
    assert total_no_suj == money(tns8)
    assert total_no_gravado == money(tng8)

    iva_resumen = Decimal(str(tributos[0]["valor"])) if tributos else Decimal("0")
    assert iva_resumen == money(tg8 * Decimal("0.13"))

    for item in cuerpo:
        venta_gravada_item = Decimal(str(item.get("ventaGravada") or 0))
        venta_exenta_item = Decimal(str(item.get("ventaExenta") or 0))
        venta_no_suj_item = Decimal(str(item.get("ventaNoSuj") or 0))
        venta_no_grav_item = Decimal(str(item.get("noGravado") or 0))
        cantidad_item = Decimal(str(item.get("cantidad") or 0))
        precio_unit = Decimal(str(item.get("precioUni") or 0))
        monto_desc = Decimal(str(item.get("montoDescu") or 0))

        assert monto_desc == Decimal("0")

        if cantidad_item > 0:
            if venta_gravada_item > 0:
                expected_unit = (venta_gravada_item / cantidad_item).quantize(
                    q8, rounding=ROUND_HALF_UP
                )
                assert precio_unit == expected_unit
                assert item.get("tributos") == ["20"]
            else:
                base_val = (
                    venta_exenta_item
                    or venta_no_suj_item
                    or venta_no_grav_item
                    or Decimal("0")
                )
                if base_val:
                    expected_unit = (base_val / cantidad_item).quantize(
                        q8, rounding=ROUND_HALF_UP
                    )
                    assert precio_unit == expected_unit
                assert item.get("tributos") is None
        else:
            assert precio_unit == Decimal("0")

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
        "23",
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
    assert direccion["municipio"] == "23"
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
    assert rec["correo"] is None


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
    assert "ivaItem" not in item
    assert "totalIva" not in resumen


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

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
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

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
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

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    receptor = data["receptor"]
    assert receptor["tipoDocumento"] == tipo_doc
    assert receptor["numDocumento"] == doc


def test_generar_dte_json_dui_invalid_length(tmp_path):
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

    doc = "0123456-7"  # 8 dígitos luego de remover el guion
    extra = {
        "precios_incluyen_iva": False,
        "receptor": {"numDocumento": doc, "tipoDocumento": "13"},
    }
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cid, extra=extra)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    assert isinstance(data.get("receptor"), dict)


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

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
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


def test_generar_dte_json_dte03_iva_incluido_descuentos(tmp_path):
    import dte as dte_module
    from decimal import Decimal as D

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
    db.add_producto("Prod1", "P1", None, vid, None, 0, 0, 0, 10)
    p1 = db.cursor.lastrowid
    db.add_producto("Prod2", "P2", None, vid, None, 0, 0, 0, 10)
    p2 = db.cursor.lastrowid
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

    pf1_bruto = d4(D("3") * D("4.03"))
    desc1 = d4(pf1_bruto * D("5") / D("100"))
    pf1_net = d4(pf1_bruto - desc1)
    pf2_bruto = d4(D("2") * D("10.50"))
    desc2 = D("1.00")
    pf2_net = d4(pf2_bruto - desc2)
    total_pf = money(pf1_net + pf2_net)

    venta_id = db.add_venta_credito_fiscal(
        cid,
        "2024-01-01",
        float(total_pf),
        "12345678",
        "06141990011019",
        "giro",
        extra={"precios_incluyen_iva": True},
    )
    db.add_detalle_venta(
        venta_id,
        p1,
        3,
        4.03,
        descuento=5,
        descuento_tipo="%",
        vendedor_id=vid,
    )
    db.add_detalle_venta(
        venta_id,
        p2,
        2,
        10.50,
        descuento=1,
        vendedor_id=vid,
    )

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    items = data["cuerpoDocumento"]
    resumen = data["resumen"]

    assert all(D(str(i["montoDescu"])) == D("0") for i in items)
    pf_sum = money(
        sum(D(str(i["precioUni"])) * D(str(i["cantidad"])) for i in items)
    )
    assert pf_sum == D(str(resumen["montoTotalOperacion"]))
    assert pf_sum == total_pf


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


def test_generar_dte_json_total_venta_cero(tmp_path):
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
    dte_module._load_datos_negocio = lambda: {**datos, "nrc": "1234567"}

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
    venta_id = db.add_venta("2024-01-01", 0, cliente_id=cliente_id)
    db.add_detalle_venta(venta_id, pid, 1, 13, vendedor_id=vid)

    data = generar_dte_json(db, venta_id)
    item = data["cuerpoDocumento"][0]
    res = data["resumen"]
    D = Decimal
    assert D(str(res["totalPagar"])) == D("13.00")
    assert D(str(res["subTotalVentas"])) == D("13.00")
    assert D(str(item["ventaGravada"])) == D("13.00")
    assert "totalIva" not in res
    assert "ivaItem" not in item


def test_generar_dte_json_sets_venta_tercero_from_extra(monkeypatch):
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
        "direccion": {
            "departamento": "06",
            "municipio": "10",
            "complemento": "Calle 1",
        },
    }

    monkeypatch.setattr(dte_module, "_load_datos_negocio", lambda: datos)
    monkeypatch.setattr(svfe_config, "load_datos_negocio", lambda: datos)

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid

    extra = {
        "venta_a_cuenta_de": "Tercero Ejemplo",
        "documento_venta_a_cuenta": "0614-1990-0110-19",
        "receptor": {
            "tipoDocumento": "36",
            "numDocumento": "06141990011019",
            "nrc": "1234567",
            "nombre": "Consumidor Demo",
            "direccion": {
                "departamento": "06",
                "municipio": "23",
                "complemento": "San Salvador",
            }
        },
    }
    venta_id = db.add_venta("2024-06-01", 10, extra=extra)
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    assert data["ventaTercero"] == {
        "nombre": "Tercero Ejemplo",
        "nit": "06141990011019",
    }


def test_generar_dte_json_sets_venta_tercero_credito_fiscal(monkeypatch):
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
        "direccion": {
            "departamento": "06",
            "municipio": "10",
            "complemento": "Calle 1",
        },
    }

    monkeypatch.setattr(dte_module, "_load_datos_negocio", lambda: datos)
    monkeypatch.setattr(svfe_config, "load_datos_negocio", lambda: datos)

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid

    db.add_cliente(
        "Cliente FC",
        "1234567",
        "06141990011019",
        "",
        "Comercio",
        "22223333",
        "cli@example.com",
        "San Salvador",
        "06",
        "23",
    )
    cliente_id = db.cursor.lastrowid

    venta_id = db.add_venta_credito_fiscal(
        cliente_id=cliente_id,
        fecha="2024-06-02",
        total=11.3,
        nrc="1234567",
        nit="06141990011019",
        giro="Comercio",
        venta_a_cuenta_de="Distribuidor XYZ",
        documento_venta_a_cuenta="00798935-2",
        sumas=10.0,
        descuentos=0.0,
        iva=1.3,
        subtotal=11.3,
        ventas_exentas=0.0,
        ventas_no_sujetas=0.0,
    )

    db.add_detalle_venta(
        venta_id,
        prod_id,
        1,
        10,
        tipo_fiscal="venta gravada",
        vendedor_id=vend_id,
    )

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="03")
    assert data["ventaTercero"] == {
        "nombre": "Distribuidor XYZ",
        "nit": "007989352",
    }


def test_generar_dte_json_credito_fiscal_autofills_remision(monkeypatch):
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
        "direccion": {
            "departamento": "06",
            "municipio": "10",
            "complemento": "Calle 1",
        },
    }

    monkeypatch.setattr(dte_module, "_load_datos_negocio", lambda: datos)
    monkeypatch.setattr(svfe_config, "load_datos_negocio", lambda: datos)

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid

    db.add_cliente(
        "Cliente FC",
        "1234567",
        "06141990011019",
        "",
        "Comercio",
        "22223333",
        "cli@example.com",
        "San Salvador",
        "06",
        "23",
    )
    cliente_id = db.cursor.lastrowid

    venta_id = db.add_venta_credito_fiscal(
        cliente_id=cliente_id,
        fecha="2024-06-02",
        total=11.3,
        nrc="1234567",
        nit="06141990011019",
        giro="Comercio",
        sumas=10.0,
        descuentos=0.0,
        iva=1.3,
        subtotal=11.3,
        ventas_exentas=0.0,
        ventas_no_sujetas=0.0,
    )

    db.add_detalle_venta(
        venta_id,
        prod_id,
        1,
        10,
        tipo_fiscal="venta gravada",
        vendedor_id=vend_id,
    )

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="03")
    numero_control = data["identificacion"]["numeroControl"]
    correlativo_segment = numero_control.rsplit("-", 1)[-1]
    expected = correlativo_segment[-4:]

    receptor = data["receptor"]
    assert receptor["noRemision"] == expected
    assert receptor["ordenNo"] == expected


def test_generar_dte_json_ignores_invalid_venta_tercero_doc(monkeypatch):
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
        "direccion": {
            "departamento": "06",
            "municipio": "10",
            "complemento": "Calle 1",
        },
    }

    monkeypatch.setattr(dte_module, "_load_datos_negocio", lambda: datos)
    monkeypatch.setattr(svfe_config, "load_datos_negocio", lambda: datos)

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid

    extra = {
        "venta_a_cuenta_de": "Nombre Incompleto",
        "documento_venta_a_cuenta": "ABC123",
        "receptor": {
            "tipoDocumento": "36",
            "numDocumento": "06141990011019",
            "nrc": "1234567",
            "nombre": "Consumidor Demo",
            "direccion": {
                "departamento": "06",
                "municipio": "23",
                "complemento": "San Salvador",
            }
        },
    }
    venta_id = db.add_venta("2024-06-03", 10, extra=extra)
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    data = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    assert data["ventaTercero"] is None

