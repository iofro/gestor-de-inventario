import fitz
import json
from copy import deepcopy
from decimal import Decimal
import pytest
from db import DB
from nota_debito_electronica import generar_nde_desde_dte, generar_nde_desde_nota
from dte import generar_dte_json
from nota_remision import generar_nota_remision_desde_db, generar_nota_remision
from factura_sv import generar_nota_debito_pdf, generar_nota_remision_pdf
from utils.snapshot import Snapshot, SnapshotNotFoundError
import utils.catalogos as catalogos


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


def _doc_rel():
    return [
        {
            "tipoDocumento": "01",
            "tipoGeneracion": 2,
            "numeroDocumento": "12345678-ABCD-1234-ABCD-1234567890AB",
            "fechaEmision": "2024-01-01",
        }
    ]


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
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="03")
    data = generar_nde_desde_dte(db, dte_origen, None, 10, "Ajuste")
    assert data["identificacion"]["tipoDte"] == "06"
    assert data["resumen"]["montoTotalOperacion"] > 0
    doc_rel = data["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    assert doc_rel["tipoGeneracion"] == 2
    assert doc_rel["fechaEmision"]
    assert (
        doc_rel["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    assert doc_rel["numeroDocumento"] != data["identificacion"].get("numeroControl")
    assert "-" not in data["emisor"].get("nit", "")


def test_generar_nde_desde_nota_credito_fiscal(monkeypatch):
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
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "06141407100012",
        "",
        "giro",
        "22223333",
        "cli@example.com",
        "Dir",
        "05",
        "24",
        nombreComercial="Cliente",
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
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'debito', '2024-01-02', 10, 'Ajuste')",
        (venta_id,),
    ).lastrowid

    nde = generar_nde_desde_nota(db, nota_id)
    doc_rel = nde["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    receptor = nde["receptor"]
    assert receptor["nit"] == "06141407100012"
    assert receptor["nrc"] == "123"
    assert receptor.get("nombreComercial") in {None, "Cliente"}


def test_generar_nde_desde_nota_regenera_dte_fecha(monkeypatch):
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
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_fecha = "2024-04-10"
    venta_id = db.add_venta(venta_fecha, 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    dte_base = generar_dte_json(db, venta_id, tipo_dte="01")
    dte_alterado = deepcopy(dte_base)
    dte_alterado["identificacion"]["fecEmi"] = "2024-04-12"

    monkeypatch.setattr(
        "nota_debito_electronica.generar_dte_json",
        lambda *args, **kwargs: deepcopy(dte_alterado),
    )

    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'debito', '2024-04-15', 10, 'Ajuste')",
        (venta_id,),
    ).lastrowid

    fecha_envio = "2024-04-12"
    db.registrar_envio_dte(
        venta_id,
        "auto",
        "procesado",
        "SELLO",
        respuesta_json=json.dumps({"fhProcesamiento": f"{fecha_envio}T08:15:00"}),
    )

    nde = generar_nde_desde_nota(db, nota_id, strict_snapshot=False)
    doc_rel = nde["documentoRelacionado"][0]
    assert doc_rel["fechaEmision"] == fecha_envio


def test_generar_nde_desde_nota_prefiere_snapshot(monkeypatch, tmp_path):
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
    db.add_cliente("Cliente", "123", "06141407100012", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2023-08-01",
        100,
        "123",
        "06141407100012",
        "giro",
        descuentos=0,
    )
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'debito', '2023-08-05', 10, 'Ajuste')",
        (venta_id,),
    ).lastrowid

    payload = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "12345678-ABCD-1234-ABCD-1234567890AB",
            "fecEmi": "2023-08-01",
            "numeroControl": "DTE-03-00100001",
        },
        "emisor": {"nombre": "Emisor"},
        "receptor": {
            "nombre": "Cliente Snapshot",
            "nit": "0614-140710-001-2",
            "nrc": None,
            "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
        },
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "tipoItem": 1,
                "descripcion": "Producto",
                "cantidad": 1,
                "uniMedida": 59,
                "precioUni": 100,
                "montoDescu": 0,
                "ventaGravada": 100,
                "ventaExenta": 0,
                "ventaNoSuj": 0,
                "tributos": [catalogos.TRIBUTO_IVA],
            }
        ],
        "resumen": {
            "totalGravada": 100,
            "totalExenta": 0,
            "totalNoSuj": 0,
            "montoTotalOperacion": 100,
        },
        "firma": "SIGNATURE",
    }
    snapshot = Snapshot(
        uuid=payload["identificacion"]["codigoGeneracion"],
        path=str(tmp_path / "documento.json"),
        tipo_documento="03",
        fecha_emision="2023-08-01",
        payload=payload,
    )

    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda vid: snapshot if vid == venta_id else None)

    def _fail_generar_dte(*_args, **_kwargs):
        raise AssertionError("No se debe regenerar desde la base de datos")

    monkeypatch.setattr("nota_debito_electronica.generar_dte_json", _fail_generar_dte)
    metrics_calls = []
    monkeypatch.setattr(
        "nota_debito_electronica.metrics.inc", lambda name: metrics_calls.append(name)
    )

    nde = generar_nde_desde_nota(db, nota_id)

    receptor = nde["receptor"]
    assert receptor["nit"] == "06141407100012"
    assert receptor["nrc"] is None

    doc_rel = nde["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    assert doc_rel["tipoGeneracion"] == 2
    assert (
        doc_rel["numeroDocumento"]
        == payload["identificacion"]["codigoGeneracion"].upper()
    )
    assert doc_rel["fechaEmision"] == "2023-08-01"
    assert metrics_calls == ["notes_source_used.snapshot"]
    assert payload["firma"] == "SIGNATURE"


def test_generar_nde_desde_nota_snapshot_dui(monkeypatch, tmp_path):
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
    venta_id = db.add_venta("2023-09-01", 40)
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'debito', '2023-09-03', 8, 'Ajuste')",
        (venta_id,),
    ).lastrowid

    payload = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "87654321-ABCD-4321-ABCD-112233445566",
            "fecEmi": "2023-09-01",
            "numeroControl": "DTE-01-00004567",
        },
        "emisor": {"nombre": "Emisor"},
        "receptor": {
            "nombre": "Consumidor Final",
            "tipoDocumento": "13",
            "numDocumento": "12345678-9",
        },
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "tipoItem": 1,
                "descripcion": "Servicio",
                "cantidad": 1,
                "uniMedida": 59,
                "precioUni": 40,
                "montoDescu": 0,
                "ventaGravada": 40,
                "ventaExenta": 0,
                "ventaNoSuj": 0,
                "tributos": [catalogos.TRIBUTO_IVA],
            }
        ],
        "resumen": {
            "totalGravada": 40,
            "totalExenta": 0,
            "totalNoSuj": 0,
            "montoTotalOperacion": 40,
        },
        "firma": "ORIGINAL-FIRMA",
    }

    snapshot = Snapshot(
        uuid=payload["identificacion"]["codigoGeneracion"],
        path=str(tmp_path / "documento.json"),
        tipo_documento="01",
        fecha_emision="2023-09-01",
        payload=payload,
    )

    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda vid: snapshot if vid == venta_id else None)
    monkeypatch.setattr(
        "nota_debito_electronica.generar_dte_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Debe usar snapshot")),
    )

    nde = generar_nde_desde_nota(db, nota_id)

    receptor = nde["receptor"]
    assert receptor["nit"] == "123456789"
    assert receptor["nrc"] is None

    doc_rel = nde["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "01"
    assert doc_rel["tipoGeneracion"] == 2
    assert doc_rel["numeroDocumento"] == payload["identificacion"]["codigoGeneracion"].upper()
    assert doc_rel["fechaEmision"] == "2023-09-01"


def test_generar_nde_desde_nota_strict_snapshot(monkeypatch):
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
    db.add_cliente("Cliente", "123", "06141407100012", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2023-08-01",
        50,
        "123",
        "06141407100012",
        "giro",
        descuentos=0,
    )
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'debito', '2023-08-05', 5, 'Ajuste')",
        (venta_id,),
    ).lastrowid

    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda _vid: None)

    with pytest.raises(SnapshotNotFoundError) as exc:
        generar_nde_desde_nota(db, nota_id, strict_snapshot=True)

    message = str(exc.value)
    assert str(venta_id) in message
    assert str(nota_id) in message


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
    assert data["receptor"]["nit"] == "00000000000000"
    assert data["receptor"]["correo"] == "demo@example.com"
    assert "otrosDocumentos" not in data


def test_generar_nde_receptor_placeholder_en_pruebas(monkeypatch):
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

    nde = generar_nde_desde_dte(db, dte_origen, None, 1.0, "Ajuste", ambiente="00")
    receptor = nde["receptor"]
    assert receptor["nit"] == "00000000000000"
    assert receptor["nrc"] == "0"
    assert receptor["telefono"] == "00000000"
    assert receptor["direccion"]["departamento"] == "01"


def test_generar_nde_receptor_incompleto_en_produccion(monkeypatch):
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
        generar_nde_desde_dte(db, dte_origen, None, 1.0, "Ajuste", ambiente="01")

    assert "nit" in str(exc.value)
    assert "nrc" in str(exc.value)


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
        "identificacion": {"tipoDte": "01", "codigoGeneracion": "UUID", "fecEmi": "2024-01-01"},
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
    db.add_cliente("Cliente", "1234567", "06141407100012", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(cliente_id, "2024-01-01", 10, "1234567", "06141407100012", "giro", descuentos=0)
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
    assert data["documentoRelacionado"][0]["tipoDocumento"] == "01"
    assert data["extension"]["nombEntrega"] == "Juan"


def test_nota_debito_pdf(tmp_path):
    venta, detalles = _sample_data()
    out = tmp_path / "nota.pdf"
    doc_rel = {
        "tipo": "01",
        "numero_control": "DTE-01-S001P001-000000000000001",
        "codigo_generacion": "abc",
        "fecha": "2024-01-01",
    }
    generar_nota_debito_pdf(
        venta,
        detalles,
        {},
        {},
        archivo=str(out),
        datos_negocio={},
        doc_relacionado=doc_rel,
        motivo="Intereses",
    )
    assert out.exists()
    with fitz.open(out) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "DOCUMENTO TRIBUTARIO ELECTRÓNICO" in text
    assert "NOTA DE DÉBITO (06)" in text
    assert "DTE-06-" in text
    assert "DOCUMENTO RELACIONADO" in text
    assert "Código Generación: abc" in text
    assert "Motivo: Intereses" in text


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
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "cliente@example.com",
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
    assert "numeroDocumento" not in data["cuerpoDocumento"][0]
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
    extra = {
        "items": detalles,
        "receptor": receptor,
        "extension": extension,
        "documento_relacionado": _doc_rel(),
    }
    nota_id = db.agregar_nota("remision", None, "2024-01-01", 0, "Envio", detalles=extra)
    data = generar_nota_remision_desde_db(db, nota_id)
    assert data["receptor"]["nombre"] == "Cliente"
    assert data["documentoRelacionado"]


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
            "codigoGeneracion": "DTE-03-XYZ-000000000000001",
            "fecEmi": "2024-01-01",
        },
        "emisor": datos,
        "receptor": {
            "tipoDocumento": "36",
            "numDocumento": "0614-140710-001-2",
            "nrc": "1234567",
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
    doc_rel = data["documentoRelacionado"][0]
    assert doc_rel["numeroDocumento"] == "DTE-03-XYZ-000000000000001"
    assert data["receptor"]["nombre"] == "Cliente"
