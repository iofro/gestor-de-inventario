from decimal import Decimal

import dte as dte_module
from svfe import config as svfe_config


NEGOCIO_BASE = {
    "nit": "06141990011019",
    "nrc": "1234567",
    "nombre": "Mi Negocio",
    "nombreComercial": "Mi Negocio",
    "cod_giro": "123456",
    "descActividad": "Comercio",
    "telefono": "22222222",
    "correo": "test@example.com",
    "direccion": {
        "departamento": "06",
        "municipio": "23",
        "complemento": "Calle 1",
    },
    "dte_api": {"prefijo_control": "DTE-01-S001P001"},
}


def _configure_negocio(monkeypatch):
    monkeypatch.setattr(dte_module, "_load_datos_negocio", lambda: NEGOCIO_BASE)
    monkeypatch.setattr(dte_module, "get_default_modo_transmision", lambda: "normal")
    monkeypatch.setattr(svfe_config, "load_datos_negocio", lambda: NEGOCIO_BASE)


def test_cf_extra_without_iva(db_conn, monkeypatch):
    _configure_negocio(monkeypatch)

    db_conn.add_producto("Exento", "E01", "SKU-E01", None, None, 0, 0, 0, 0)
    prod_exento = db_conn.cursor.lastrowid
    db_conn.add_producto("No Sujeto", "NS01", "SKU-NS01", None, None, 0, 0, 0, 0)
    prod_no_suj = db_conn.cursor.lastrowid

    db_conn.add_cliente(
        nombre="Consumidor Final",
        nrc="",
        nit="",
        dui="01234567-8",
        giro="",
        telefono="",
        email="",
        direccion="San Salvador",
        departamento="06",
        municipio="23",
    )
    cliente_id = db_conn.cursor.lastrowid

    extra = {
        "sumas": 0,
        "descuentos": 0,
        "iva": 0,
        "subtotal": 0,
        "ventas_exentas": 50,
        "ventas_no_sujetas": 25,
        "no_gravado": 0,
        "precios_incluyen_iva": True,
    }

    venta_id = db_conn.add_venta("2024-01-01", 75, cliente_id=cliente_id, extra=extra)

    db_conn.add_detalle_venta(
        venta_id,
        prod_exento,
        1,
        50,
        iva=0,
        tipo_fiscal="venta exenta",
        precio_con_iva=50,
        base=50,
        total=50,
    )
    db_conn.add_detalle_venta(
        venta_id,
        prod_no_suj,
        1,
        25,
        iva=0,
        tipo_fiscal="venta no sujeta",
        precio_con_iva=25,
        base=25,
        total=25,
    )

    data = dte_module.generar_dte_json(db_conn, venta_id, tipo_dte="01")
    resumen = data["resumen"]

    assert resumen.get("tributos") in (None, [])
    assert resumen["montoTotalOperacion"] == resumen["totalPagar"]

    for item in data["cuerpoDocumento"]:
        tributos = item.get("tributos") or []
        assert all(t != dte_module.TRIBUTO_IVA for t in tributos)
        no_gravado = Decimal(str(item.get("noGravado") or 0))
        if no_gravado > 0:
            assert not tributos


def test_cf_only_no_gravada(db_conn, monkeypatch):
    _configure_negocio(monkeypatch)

    db_conn.add_producto("Servicio No Gravado", "NG01", "SKU-NG01", None, None, 0, 0, 0, 0)
    prod_no_grav = db_conn.cursor.lastrowid

    db_conn.add_cliente(
        nombre="Cliente No Gravado",
        nrc="",
        nit="",
        dui="01234567-8",
        giro="",
        telefono="",
        email="",
        direccion="San Salvador",
        departamento="06",
        municipio="23",
    )
    cliente_id = db_conn.cursor.lastrowid

    extra = {
        "sumas": 0,
        "descuentos": 0,
        "iva": 0,
        "subtotal": 0,
        "ventas_exentas": 0,
        "ventas_no_sujetas": 0,
        "no_gravado": 80,
        "precios_incluyen_iva": True,
    }

    venta_id = db_conn.add_venta("2024-01-05", 80, cliente_id=cliente_id, extra=extra)

    db_conn.add_detalle_venta(
        venta_id,
        prod_no_grav,
        1,
        80,
        iva=0,
        tipo_fiscal="no gravada",
        precio_con_iva=80,
        base=80,
        total=80,
    )

    data = dte_module.generar_dte_json(db_conn, venta_id, tipo_dte="01")
    resumen = data["resumen"]

    assert resumen.get("tributos") in (None, [])
    assert resumen["montoTotalOperacion"] == resumen["totalPagar"]
    assert Decimal(str(resumen["montoTotalOperacion"])) == Decimal("80")

    for item in data["cuerpoDocumento"]:
        tributos = item.get("tributos") or []
        assert not tributos
        assert Decimal(str(item.get("noGravado") or 0)) == Decimal("80")
        assert Decimal(str(item.get("ventaGravada") or 0)) == Decimal("0")


def test_credito_mixto_includes_iva_only_for_gravadas(db_conn, monkeypatch):
    _configure_negocio(monkeypatch)

    db_conn.add_cliente(
        nombre="Cliente CF",
        nrc="",
        nit="06141990011019",
        dui="",
        giro="Comercio",
        telefono="22223333",
        email="cli@example.com",
        direccion="San Salvador",
        departamento="06",
        municipio="23",
    )
    cliente_id = db_conn.cursor.lastrowid

    db_conn.add_producto("Gravado", "G01", "SKU-G01", None, None, 0, 0, 0, 0)
    prod_grav = db_conn.cursor.lastrowid
    db_conn.add_producto("Exento", "E02", "SKU-E02", None, None, 0, 0, 0, 0)
    prod_exento = db_conn.cursor.lastrowid
    db_conn.add_producto("No Gravado", "NG02", "SKU-NG02", None, None, 0, 0, 0, 0)
    prod_no_grav = db_conn.cursor.lastrowid

    extra = {
        "sumas": 100,
        "descuentos": 0,
        "iva": 13,
        "subtotal": 113,
        "ventas_exentas": 40,
        "ventas_no_sujetas": 0,
        "no_gravado": 20,
        "precios_incluyen_iva": True,
    }

    venta_id = db_conn.add_venta_credito_fiscal(
        cliente_id=cliente_id,
        fecha="2024-02-01",
        total=173,
        nrc="1234567",
        nit="06141990011019",
        giro="Comercio",
        sumas=extra["sumas"],
        descuentos=extra["descuentos"],
        iva=extra["iva"],
        subtotal=extra["subtotal"],
        ventas_exentas=extra["ventas_exentas"],
        ventas_no_sujetas=extra["ventas_no_sujetas"],
        total_letras="CIENTO SETENTA Y TRES",
        extra=extra,
    )

    db_conn.add_detalle_venta(
        venta_id,
        prod_grav,
        1,
        100,
        iva=13,
        tipo_fiscal="venta gravada",
        precio_con_iva=113,
        base=100,
        total=113,
    )
    db_conn.add_detalle_venta(
        venta_id,
        prod_exento,
        1,
        40,
        iva=0,
        tipo_fiscal="venta exenta",
        precio_con_iva=40,
        base=40,
        total=40,
    )
    db_conn.add_detalle_venta(
        venta_id,
        prod_no_grav,
        1,
        20,
        iva=0,
        tipo_fiscal="no gravada",
        precio_con_iva=20,
        base=20,
        total=20,
    )

    data = dte_module.generar_dte_json(db_conn, venta_id, tipo_dte="03")
    resumen = data["resumen"]

    tributos_resumen = resumen.get("tributos") or []
    assert any(t.get("codigo") == dte_module.TRIBUTO_IVA for t in tributos_resumen)

    cuerpo = data["cuerpoDocumento"]
    grav_item = next(i for i in cuerpo if Decimal(str(i.get("ventaGravada", 0))) > 0)
    exento_item = next(i for i in cuerpo if Decimal(str(i.get("ventaExenta", 0))) > 0)
    no_grav_item = next(i for i in cuerpo if Decimal(str(i.get("noGravado", 0))) > 0)

    grav_tributos = grav_item.get("tributos") or []
    assert dte_module.TRIBUTO_IVA in grav_tributos
    assert grav_item.get("tributos") == [dte_module.TRIBUTO_IVA] or all(
        code == dte_module.TRIBUTO_IVA or code in dte_module.TRIBUTOS_PERMITIDOS_ITEM
        for code in grav_tributos
    )

    assert "tributos" not in exento_item
    assert "tributos" not in no_grav_item
