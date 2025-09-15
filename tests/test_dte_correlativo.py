import json
import pytest
from db import DB
import dte as dte_module
from utils.doc_generation import generate_invoice_pdf


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
        "20",
    )
    cid = db.cursor.lastrowid
    venta_id = db.add_venta(
        "2024-01-01", 13, cliente_id=cid, extra={"precios_incluyen_iva": True}
    )
    db.add_detalle_venta(venta_id, pid, 1, 13, vendedor_id=vid)
    return db, venta_id


def test_identificadores_reutilizados(tmp_path):
    _setup_datos_negocio(tmp_path)
    db, venta_id = _setup_db()

    dte1 = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    ident1 = dte1["identificacion"]
    dte2 = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    ident2 = dte2["identificacion"]

    assert ident1["numeroControl"] == ident2["numeroControl"]
    assert ident1["codigoGeneracion"] == ident2["codigoGeneracion"]


def test_generar_dte_json_correlativo_invalido(tmp_path):
    _setup_datos_negocio(tmp_path)
    db, venta_id = _setup_db()
    with pytest.raises(ValueError):
        dte_module.generar_dte_json(
            db,
            venta_id,
            tipo_dte="01",
            numero_control="DTE-01-S001P001-000000000000001",
            correlativo="x",
        )
    with pytest.raises(ValueError):
        dte_module.generar_dte_json(
            db,
            venta_id,
            tipo_dte="01",
            numero_control="DTE-01-S001P001-000000000000001",
            correlativo=0,
        )


def test_validate_dte_json_correlativo_desincronizado(tmp_path):
    _setup_datos_negocio(tmp_path)
    db, venta_id = _setup_db()
    dte = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    ident = dte["identificacion"]
    corr = int(ident["numeroControl"].split("-")[-1])
    ident["numeroControl"] = dte_module._format_numero_control("01", "001", "001", corr + 1)
    with pytest.raises(ValueError):
        dte_module.validate_dte_json(dte, db=db, correlativo=corr)


def test_validate_dte_json_corrige_numero_control_invalido(tmp_path):
    _setup_datos_negocio(tmp_path)
    db, venta_id = _setup_db()
    dte = dte_module.generar_dte_json(db, venta_id, tipo_dte="01")
    ident = dte["identificacion"]
    corr = int(ident["numeroControl"].split("-")[-1])
    ident["numeroControl"] = "INVALID"
    dte_module.validate_dte_json(dte, db=db, correlativo=corr)
    assert ident["numeroControl"] == dte_module._format_numero_control("01", "001", "001", corr)


def test_generate_invoice_pdf_correlativo_increment(tmp_path, monkeypatch):
    _setup_datos_negocio(tmp_path)

    # Preparar base de datos con dos ventas
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
        "20",
    )
    cid = db.cursor.lastrowid
    v1 = db.add_venta(
        "2024-01-01", 13, cliente_id=cid, extra={"precios_incluyen_iva": True}
    )
    db.add_detalle_venta(v1, pid, 1, 13, vendedor_id=vid)
    v2 = db.add_venta(
        "2024-01-02", 26, cliente_id=cid, extra={"precios_incluyen_iva": True}
    )
    db.add_detalle_venta(v2, pid, 2, 13, vendedor_id=vid)

    class Manager:
        def __init__(self, db):
            self.db = db
            self._Distribuidores = []
            self._clientes = []
            self._vendedores = []

    man = Manager(db)

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        from utils import docs

        return docs.get_document_paths(date, cliente, identifier, doc_type, root=tmp_path)

    def fake_pdf(*args, archivo="", **kwargs):
        with open(archivo, "wb") as fh:
            fh.write(b"pdf")

    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    monkeypatch.setattr("utils.doc_generation.generar_factura_electronica_pdf", fake_pdf)

    generate_invoice_pdf(man, v1)
    corr1 = db.cursor.execute(
        "SELECT correlativo FROM dte_correlativos WHERE tipo='01'"
    ).fetchone()["correlativo"]
    generate_invoice_pdf(man, v2)
    corr2 = db.cursor.execute(
        "SELECT correlativo FROM dte_correlativos WHERE tipo='01'"
    ).fetchone()["correlativo"]

    assert corr1 == 1
    assert corr2 == 2
