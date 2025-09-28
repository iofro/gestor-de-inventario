import fitz
from decimal import Decimal, ROUND_HALF_UP
from db import DB
from dte import generar_dte_json
from nota_credito_electronica import generar_nce_desde_dte, generar_nce_desde_nota
import pytest
from factura_sv import generar_nota_credito_pdf
import utils.catalogos as catalogos


def create_db():
    return DB(":memory:")


@pytest.fixture(autouse=True)
def _mock_geo(monkeypatch):
    monkeypatch.setattr(
        "dte.validar_dep_muni_por_catalogo",
        lambda d, m, strict=True: (str(d).zfill(2), str(m).zfill(2)),
    )


def test_generar_nota_credito_json_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), motivo="Dev")
    assert data["identificacion"]["tipoDte"] == "05"
    assert data.get("documentoRelacionado")
    assert data["documentoRelacionado"][0]["tipoDocumento"] == "01"
    assert (
        data["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    assert data["cuerpoDocumento"][0]["precioUni"] > 0
    assert "totalPagar" not in data["resumen"]
    assert data["resumen"]["montoTotalOperacion"] > 0
    for k in ("ivaRete1", "reteRenta", "ivaPerci1", "condicionOperacion"):
        assert k in data["resumen"]
    assert data["resumen"]["ivaPerci1"] == 0.0
    assert data["resumen"]["ivaRete1"] == 0.0
    assert data["resumen"]["reteRenta"] == 0.0
    assert data["resumen"]["condicionOperacion"] == 1


def test_generar_nota_credito_json_factura(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "0614-140710-001-2", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id, "2024-01-01", 10, "123", "06141407100012", "giro", descuentos=0
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="03")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), motivo="Dev")
    assert data["documentoRelacionado"][0]["tipoDocumento"] == "03"
    assert (
        data["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    receptor = data["receptor"]
    assert "-" not in receptor.get("nit", "")
    assert receptor.get("nit")
    assert receptor.get("nrc") == "123"
    assert receptor.get("nombreComercial") in {None, "Cliente"}


def test_generar_nce_desde_nota_credito_fiscal(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente(
        "Cliente", "123", "06141407100012", "", "giro", "22223333", "cli@example.com", "Dir", "05", "24", nombreComercial="Cliente"
    )
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        10,
        "123",
        "06141407100012",
        "giro",
        descuentos=0,
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'credito', '2024-01-02', 10, 'Dev')",
        (venta_id,),
    ).lastrowid

    nce = generar_nce_desde_nota(db, nota_id)
    doc_rel = nce["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    receptor_nota = nce["receptor"]
    assert receptor_nota["nit"] == "06141407100012"
    assert receptor_nota["nrc"] == "123"
    assert receptor_nota.get("nombreComercial") in {None, "Cliente"}


def test_generar_nce_receptor_placeholder_en_pruebas(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": str(src.get("departamento", "05")).zfill(2), "municipio": str(src.get("municipio", "24")).zfill(2), "complemento": src.get("complemento", "Dir")},
    )

    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
            "fecEmi": "2024-01-01",
        },
        "emisor": {},
        "receptor": {"nombre": "Consumidor Final"},
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "tipoItem": 1,
                "descripcion": "Servicio",
                "cantidad": 1,
                "uniMedida": 59,
                "precioUni": 1.0,
                "montoDescu": 0.0,
                "ventaGravada": 1.0,
                "ventaExenta": 0.0,
                "ventaNoSuj": 0.0,
                "tributos": [],
            }
        ],
        "resumen": {
            "totalNoSuj": 0.0,
            "totalExenta": 0.0,
            "totalGravada": 1.0,
            "subTotal": 1.0,
            "subTotalVentas": 1.0,
            "descuNoSuj": 0.0,
            "descuExenta": 0.0,
            "descuGravada": 0.0,
            "totalDescu": 0.0,
            "ivaPerci1": 0.0,
            "ivaRete1": 0.0,
            "reteRenta": 0.0,
            "condicionOperacion": 1,
            "tributos": [],
            "montoTotalOperacion": 1.0,
            "totalLetras": "UNO",
        },
    }

    nce = generar_nce_desde_dte(db, dte_origen, Decimal("1"), ambiente="00")
    receptor = nce["receptor"]
    assert receptor["nit"] == "00000000000000"
    assert receptor["nrc"] == "0"
    assert receptor["correo"] == "demo@example.com"
    assert receptor["telefono"] == "00000000"
    assert receptor["direccion"]["departamento"] == "01"
    assert receptor["direccion"]["municipio"] == "01"
    assert "otrosDocumentos" in nce


def test_generar_nce_receptor_incompleto_en_produccion(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": str(src.get("departamento", "05")).zfill(2), "municipio": str(src.get("municipio", "24")).zfill(2), "complemento": src.get("complemento", "Dir")},
    )

    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
            "fecEmi": "2024-01-01",
        },
        "emisor": {},
        "receptor": {"nombre": "Consumidor Final"},
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "tipoItem": 1,
                "descripcion": "Servicio",
                "cantidad": 1,
                "uniMedida": 59,
                "precioUni": 1.0,
                "montoDescu": 0.0,
                "ventaGravada": 1.0,
                "ventaExenta": 0.0,
                "ventaNoSuj": 0.0,
                "tributos": [],
            }
        ],
        "resumen": {
            "totalNoSuj": 0.0,
            "totalExenta": 0.0,
            "totalGravada": 1.0,
            "subTotal": 1.0,
            "subTotalVentas": 1.0,
            "descuNoSuj": 0.0,
            "descuExenta": 0.0,
            "descuGravada": 0.0,
            "totalDescu": 0.0,
            "ivaPerci1": 0.0,
            "ivaRete1": 0.0,
            "reteRenta": 0.0,
            "condicionOperacion": 1,
            "tributos": [],
            "montoTotalOperacion": 1.0,
            "totalLetras": "UNO",
        },
    }

    with pytest.raises(ValueError) as exc:
        generar_nce_desde_dte(db, dte_origen, Decimal("1"), ambiente="01")

    assert "nit" in str(exc.value)
    assert "nrc" in str(exc.value)
def test_nota_credito_total_nueve(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 9)
    db.add_detalle_venta(venta_id, pid, 1, 7.96, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    assert dte_origen["resumen"]["montoTotalOperacion"] == Decimal("9.00")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"))
    assert (
        data["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    assert data["resumen"]["montoTotalOperacion"] == 9.0


def test_nota_credito_precio_uni(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 9)
    db.add_detalle_venta(venta_id, pid, 1, 9, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    codigo = dte_origen["cuerpoDocumento"][0]["codigo"]
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "codigo": codigo,
            "ventas_gravadas": Decimal("7.96"),
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), detalles=detalles)
    assert (
        data["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    item = data["cuerpoDocumento"][0]
    assert item["precioUni"] == Decimal("7.9600")
    iva = Decimal("7.96") * Decimal("0.13")
    iva = iva.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    expected_total = Decimal("7.96") + iva
    assert data["resumen"]["montoTotalOperacion"] == expected_total


def test_generar_nce_rechaza_monto_excedido(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'credito', '2024-01-02', 15, '')",
        (venta_id,),
    ).lastrowid
    with pytest.raises(ValueError):
        generar_nce_desde_nota(db, nota_id)


def test_generar_nce_detalle_excede(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    codigo = dte_origen["cuerpoDocumento"][0]["codigo"]
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "codigo": codigo,
            "ventas_gravadas": Decimal("20"),
        }
    ]
    with pytest.raises(ValueError):
        generar_nce_desde_dte(db, dte_origen, None, detalles=detalles)


def test_nota_credito_un_dolar(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'credito', '2024-01-02', 1, '')",
        (venta_id,),
    ).lastrowid
    # El monto debe almacenarse exactamente como se ingresó
    stored = Decimal(
        str(db.cursor.execute("SELECT monto FROM notas WHERE id=?", (nota_id,)).fetchone()["monto"])
    )
    assert stored == Decimal("1")
    nce = generar_nce_desde_nota(db, nota_id)
    resumen = nce["resumen"]
    item = nce["cuerpoDocumento"][0]
    assert resumen["montoTotalOperacion"] == Decimal("1.00")
    assert item["precioUni"] == Decimal("0.8800")
    assert resumen["totalGravada"] == Decimal("0.88")
    iva = resumen["tributos"][0]["valor"] if resumen["tributos"] else Decimal("0")
    assert iva == Decimal("0.12")
    assert resumen["totalGravada"] + iva == resumen["montoTotalOperacion"]


def test_nota_credito_dos_centavos(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'credito', '2024-01-02', 0.02, '')",
        (venta_id,),
    ).lastrowid
    nce = generar_nce_desde_nota(db, nota_id)
    resumen = nce["resumen"]
    assert resumen["montoTotalOperacion"] == Decimal("0.02")
    assert resumen["totalGravada"] == Decimal("0.02")
    iva = resumen["tributos"][0]["valor"] if resumen["tributos"] else Decimal("0")
    assert iva == Decimal("0.00")
    assert resumen["totalGravada"] + iva == resumen["montoTotalOperacion"]


def _sample_data():
    venta = {
        "sumas": 10,
        "descuentos": 0,
        "subtotal": 10,
        "iva": 1.3,
        "total": 11.3,
        "ventas_exentas": 0,
        "ventas_no_sujetas": 0,
        "total_letras": "ONCE CON 30/100 DOLARES",
    }
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "precio_unitario": 10,
            "ventas_no_sujetas": 0,
            "ventas_exentas": 0,
            "ventas_gravadas": 10,
        }
    ]
    return venta, detalles


def test_nota_credito_pdf(tmp_path):
    venta, detalles = _sample_data()
    out = tmp_path / "nota.pdf"
    doc_rel = {
        "tipo": "01",
        "numero_control": "DTE-01-S001P001-000000000000001",
        "codigo_generacion": "123",
        "fecha": "2024-01-01",
    }
    generar_nota_credito_pdf(
        venta,
        detalles,
        {},
        {},
        archivo=str(out),
        datos_negocio={},
        doc_relacionado=doc_rel,
        motivo="Devolución",
    )
    assert out.exists()
    with fitz.open(out) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "DOCUMENTO TRIBUTARIO ELECTRÓNICO" in text
    assert "NOTA DE CRÉDITO (05)" in text
    assert "DTE-05-" in text
    assert "DOCUMENTO RELACIONADO" in text
    assert "Tipo: 03" in text
    assert "Código Generación: 123" in text
    assert "Motivo: Devolución" in text


def test_nota_credito_direccion(tmp_path, monkeypatch):
    monkeypatch.setattr(
        catalogos,
        "get_value",
        lambda cat, code, default=None: "La Libertad Centro" if code == "0524" else default,
    )
    venta, detalles = _sample_data()
    direccion = {
        'departamento': '05',
        'municipio': '24',
        'complemento': 'Colonia El Centro con una avenida realmente muy larga para pruebas',
    }
    out = tmp_path / 'nc_dir.pdf'
    generar_nota_credito_pdf(
        venta,
        detalles,
        {'direccion': direccion},
        {},
        archivo=str(out),
        datos_negocio={'direccion': direccion},
    )
    with fitz.open(out) as doc:
        lines = ''.join(p.get_text() for p in doc).splitlines()
    idx = next(i for i, ln in enumerate(lines) if ln.startswith('Dirección:'))
    assert 'La Libertad Centro' in lines[idx]
    assert 'realmente muy larga para pruebas' in lines[idx + 1]
