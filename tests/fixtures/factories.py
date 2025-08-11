import json
import pytest


@pytest.fixture
def cliente_factory(db_conn):
    def create_cliente(
        nombre="Cliente",
        codigo="",
        nit="",
        nrc="",
        giro="",
        telefono="",
        email="",
        direccion="",
        municipio="",
        departamento="",
    ):
        db_conn.add_cliente(
            nombre,
            codigo,
            nit,
            nrc,
            giro,
            telefono,
            email,
            direccion,
            municipio,
            departamento,
        )
        return db_conn.cursor.lastrowid

    return create_cliente


@pytest.fixture
def producto_factory(db_conn):
    def create_producto(
        nombre="Prod",
        codigo="P1",
        vendedor_id=None,
        distribuidor_id=None,
        precio_compra=0,
        precio_venta_minorista=0,
        precio_venta_mayorista=0,
        stock=1,
    ):
        if vendedor_id is None:
            db_conn.add_vendedor("V1")
            vendedor_id = db_conn.cursor.lastrowid
        db_conn.add_producto(
            nombre,
            codigo,
            vendedor_id,
            distribuidor_id,
            precio_compra,
            precio_venta_minorista,
            precio_venta_mayorista,
            stock,
        )
        prod_id = db_conn.cursor.lastrowid
        return prod_id, vendedor_id

    return create_producto


@pytest.fixture
def venta_factory(db_conn, cliente_factory, producto_factory):
    def create_venta(
        fecha="2024-01-01",
        total=10,
        cliente_id=None,
        vendedor_id=None,
        producto_id=None,
        cantidad=1,
        precio=10,
        detalle=True,
    ):
        if cliente_id is None:
            cliente_id = cliente_factory()
        if producto_id is None or vendedor_id is None:
            producto_id, vendedor_id = producto_factory(vendedor_id=vendedor_id)
        venta_id = db_conn.add_venta(
            fecha,
            total,
            cliente_id=cliente_id,
            vendedor_id=vendedor_id,
        )
        if detalle:
            db_conn.add_detalle_venta(
                venta_id,
                producto_id,
                cantidad,
                precio,
                vendedor_id=vendedor_id,
            )
        return venta_id

    return create_venta


@pytest.fixture
def dte_metadata_factory():
    def create_metadata(
        nombre="Cliente",
        nit="0614-987654-321-0",
        cantidad=1,
        precio=10,
        tipo="01",
    ):
        total = cantidad * precio
        return {
            "receptor": {"nombre": nombre, "nit": nit},
            "cuerpoDocumento": [{"cantidad": cantidad, "precioUnitario": precio}],
            "resumen": {"sumas": total, "iva": 0, "totalPagar": total},
            "identificacion": {"tipoDte": tipo},
        }

    return create_metadata


@pytest.fixture
def temp_pdf(tmp_path):
    def create_pdf(name="file.pdf", content=b"%PDF-1.4\n%EOF"):
        path = tmp_path / name
        path.write_bytes(content)
        return path

    return create_pdf


@pytest.fixture
def temp_json(tmp_path):
    def create_json(name="file.json", data=None):
        path = tmp_path / name
        if data is None:
            data = {}
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return create_json
