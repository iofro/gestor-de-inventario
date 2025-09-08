import fitz
from decimal import Decimal
from db import DB
from nota_debito_electronica import generar_nde_desde_dte
from dte import generar_dte_json
from nota_remision import generar_nota_remision_desde_db, generar_nota_remision
from factura_sv import generar_nota_debito_pdf, generar_nota_remision_pdf


def create_db():
    return DB(":memory:")


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


def test_generar_nota_debito_json_ticket(tmp_path, monkeypatch):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "1234567", "06141407100012", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(cliente_id, "2024-01-01", 10, "1234567", "06141407100012", "giro", descuentos=0)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    data = generar_nde_desde_dte(db, dte_origen, None, 10, "Ajuste")
    assert data["identificacion"]["tipoDte"] == "06"
    assert data["resumen"]["montoTotalOperacion"] > 0
    doc_rel = data["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    assert doc_rel["tipoGeneracion"] == 2
    assert doc_rel["fechaEmision"]
    assert doc_rel["numeroDocumento"] != data["identificacion"].get("numeroControl")
    assert "-" not in data["emisor"].get("nit", "")


def test_generar_nde_consumidor_final_sin_nit(monkeypatch):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    db = create_db()
    dte_origen = {
        "identificacion": {"tipoDte": "01", "codigoGeneracion": "UUID", "fecEmi": "2024-01-01"},
        "emisor": {},
        "receptor": {"nombre": "Consumidor Final"},
        "resumen": {
            "montoTotalOperacion": 10,
            "totalGravada": 10,
            "totalExenta": 0,
            "totalNoSuj": 0,
        },
    }
    data = generar_nde_desde_dte(db, dte_origen, None, 10, "Ajuste")
    assert data["identificacion"]["tipoDte"] == "06"


def test_generar_nde_ticket_minimo(monkeypatch):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    db = create_db()
    dte_origen = {
        "identificacion": {"tipoDte": "03", "codigoGeneracion": "UUID", "fecEmi": "2024-01-01"},
        "emisor": {},
        "receptor": {},
        "resumen": {
            "montoTotalOperacion": 5,
            "totalGravada": 5,
            "totalExenta": 0,
            "totalNoSuj": 0,
        },
    }
    data = generar_nde_desde_dte(db, dte_origen, None, 5, "Ajuste")
    assert data["identificacion"]["tipoDte"] == "06"


def test_generar_nde_conserva_total(monkeypatch):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "UUID",
            "fecEmi": "2024-01-01",
        },
        "emisor": {},
        "receptor": {"nombre": "Consumidor Final"},
        "resumen": {
            "montoTotalOperacion": 11.3,
            "totalGravada": 10,
            "totalExenta": 0,
            "totalNoSuj": 0,
        },
    }
    data = generar_nde_desde_dte(db, dte_origen, None, 1, "Ajuste")
    assert data["resumen"]["montoTotalOperacion"] == Decimal("1.00")


def test_generar_nota_remision_factura(tmp_path, monkeypatch):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "06141407100012", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(cliente_id, "2024-01-01", 10, "123", "06141407100012", "giro", descuentos=0)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    extra = {"extension": extension}
    nota_id = db.agregar_nota(
        "remision", venta_id, "2024-01-02", 0, "Envio", detalles=extra
    )

    data = generar_nota_remision_desde_db(db, nota_id)
    assert data["identificacion"]["tipoDte"] == "04"
    assert data["documentoRelacionado"]["tipoDoc"] == "01"
    assert data["extension"]["nombEntrega"] == "Juan"


def test_nota_debito_pdf(tmp_path):
    venta, detalles = _sample_data()
    out = tmp_path / "nota.pdf"
    generar_nota_debito_pdf(venta, detalles, {}, {}, archivo=str(out), datos_negocio={})
    assert out.exists()
    with fitz.open(out) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "DOCUMENTO TRIBUTARIO ELECTRÓNICO" in text
    assert "NOTA DE DÉBITO" in text
    assert "Código Generación:" in text
    assert "Número Control:" in text
    assert "Sello Recepción:" in text
    assert "Tipo Modelo:" in text
    assert "Tipo Operación:" in text
    assert "Fecha Generación:" in text


def test_nota_remision_pdf(tmp_path):
    venta, detalles = _sample_data()
    out = tmp_path / "nota.pdf"
    generar_nota_remision_pdf(venta, detalles, {}, {}, archivo=str(out), datos_negocio={})
    assert out.exists()
    with fitz.open(out) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "NOTA DE REMISI" in text


def test_generar_nota_remision_sin_documento_relacionado(monkeypatch):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    db = create_db()
    receptor = {
        "nombre": "Cliente",
        "tipoDocumento": "13",
        "numDocumento": "12345678-9",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    detalles = [
        {"codigo": "P1", "descripcion": "Prod", "cantidad": 1},
    ]
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    data = generar_nota_remision(
        db,
        emisor=datos,
        receptor=receptor,
        detalles=detalles,
        extension=extension,
    )
    assert "documentoRelacionado" not in data
    assert str(data["resumen"]["montoTotalOperacion"]) == "0.00"


def test_generar_nota_remision_desde_db_independiente(monkeypatch):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    db = create_db()
    receptor = {
        "nombre": "Cliente",
        "tipoDocumento": "13",
        "numDocumento": "12345678-9",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    detalles = [
        {"codigo": "P1", "descripcion": "Prod", "cantidad": 1},
    ]
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    extra = {"items": detalles, "receptor": receptor, "extension": extension}
    nota_id = db.agregar_nota("remision", None, "2024-01-01", 0, "Envio", detalles=extra)
    data = generar_nota_remision_desde_db(db, nota_id)
    assert data["receptor"]["nombre"] == "Cliente"
    assert "documentoRelacionado" not in data


def test_generar_nota_remision_desde_db_factura_sin_venta(monkeypatch):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    db = create_db()
    factura = {
        "identificacion": {
            "tipoDte": "03",
            "numeroControl": "DTE-03-XYZ-000000000000001",
        },
        "emisor": datos,
        "receptor": {
            "tipoDocumento": "36",
            "numDocumento": "1234 567-8",
            "nombre": "Cliente",
        },
        "cuerpoDocumento": [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}],
    }
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    extra = {"extension": extension, "factura": factura}
    nota_id = db.agregar_nota("remision", None, "2024-01-02", 0, "Envio", detalles=extra)
    data = generar_nota_remision_desde_db(db, nota_id)
    doc_rel = data["documentoRelacionado"]
    assert doc_rel["numeroDocumento"] == "DTE-03-XYZ-000000000000001"
    assert data["receptor"]["nombre"] == "Cliente"
