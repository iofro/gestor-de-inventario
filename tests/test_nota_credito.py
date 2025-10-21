import fitz
from copy import deepcopy
import json
import logging
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import json
import logging
from db import DB
from dte import generar_dte_json
import nota_credito_electronica
from nota_credito_electronica import (
    generar_nce_desde_dte,
    generar_nce_desde_nota,
    _tipo_dte_str,
    inferir_tipo_por_numero_control,
)
from nota_debito_electronica import generar_nde_desde_dte
import pytest
from factura_sv import generar_nota_credito_pdf
import utils.catalogos as catalogos
from utils.fecha import fecha_ddmmaaaa, fecha_emision_hoy_str, fecha_iso
from utils.snapshot import Snapshot, SnapshotNotFoundError
from utils.nota_fallback import (
    OrigenResult,
    prepare_dte_origen,
    prevalidate_dte_origen,
)


def create_db():
    return DB(":memory:")


def _datos_negocio_base() -> dict:
    return {
        "nit": "06141407100012",
        "nrc": "1234567",
        "nombre": "Emisor Pruebas",
        "nombreComercial": "Emisor",
        "codActividad": "123456",
        "descActividad": "Venta de pruebas",
        "tipoEstablecimiento": "01",
        "telefono": "22223333",
        "correo": "emisor@example.com",
        "direccion": {
            "departamento": "05",
            "municipio": "24",
            "complemento": "Dir Emisor",
        },
    }


@pytest.fixture(autouse=True)
def _mock_geo(monkeypatch):
    monkeypatch.setattr(
        "dte.validar_dep_muni_por_catalogo",
        lambda d, m, strict=True: (str(d).zfill(2), str(m).zfill(2)),
    )


def _assert_relacionado_y_receptor(doc_rel: dict, receptor: dict) -> None:
    assert doc_rel["tipoGeneracion"] in (1, 2)
    numero_documento = doc_rel["numeroDocumento"]
    if doc_rel["tipoGeneracion"] == 2:
        assert re.match(
            r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$",
            numero_documento,
        ), numero_documento
    else:
        assert numero_documento == numero_documento.upper()

    tipo_doc = doc_rel["tipoDocumento"]
    if tipo_doc == "03":
        assert receptor.get("codActividad")
        assert receptor.get("descActividad")
    if tipo_doc == "01":
        assert receptor.get("nrc") in (None, "", "0")


def _assert_doc_rel_coincide_con_origen(doc_rel: dict, dte_origen: dict) -> None:
    ident = dte_origen.get("identificacion", {})
    uuid = str(ident.get("codigoGeneracion") or "").strip().upper()
    numero_control = str(ident.get("numeroControl") or "").strip().upper()
    expected_tipo_gen = 2 if uuid else 1
    expected_num = uuid if expected_tipo_gen == 2 else numero_control
    assert doc_rel["tipoGeneracion"] == expected_tipo_gen
    assert doc_rel["numeroDocumento"] == expected_num

    tipo_doc = _tipo_dte_str(ident.get("tipoDte"))
    if not tipo_doc:
        tipo_doc = inferir_tipo_por_numero_control(numero_control)
    if not tipo_doc:
        receptor_origen = dte_origen.get("receptor") or {}
        nrc_origen = str(receptor_origen.get("nrc") or "").strip()
        tipo_doc = "03" if nrc_origen and nrc_origen != "0" else "01"
    assert doc_rel["tipoDocumento"] == tipo_doc


@pytest.fixture(autouse=True)
def _disable_strict_snapshot(monkeypatch):
    monkeypatch.setattr("nota_credito_electronica.STRICT_SNAPSHOT_DEFAULT", False)
    monkeypatch.setattr("nota_credito_electronica.USAR_FALLBACK_JSON_DEFAULT", True)


@pytest.fixture(autouse=True)
def _mock_datos_negocio(monkeypatch):
    datos = _datos_negocio_base()
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)


def _build_base_payload() -> dict:
    codigo = "12345678-ABCD-1234-ABCD-1234567890AB"
    numero_control = "DTE-03-S001P001-000000000000123"
    return {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": codigo,
            "numeroControl": numero_control,
            "fecEmi": "2024-01-01",
            "horEmi": "10:00:00",
            "tipoModelo": 1,
            "tipoOperacion": 1,
            "tipoContingencia": None,
            "motivoContin": None,
            "ambiente": "00",
            "tipoMoneda": "USD",
        },
        "emisor": {
            "nit": "06141407100012",
            "nrc": "1234567",
            "nombre": "Emisor Pruebas",
            "nombreComercial": "Emisor",
            "codActividad": "123456",
            "descActividad": "Venta",
            "tipoEstablecimiento": "01",
            "telefono": "22223333",
            "correo": "emisor@example.com",
            "direccion": {
                "departamento": "05",
                "municipio": "24",
                "complemento": "Dir Emisor",
            },
        },
        "receptor": {
            "nombre": "Cliente Demo",
            "nit": "06141407100012",
            "nrc": "7654321",
            "codActividad": "654321",
            "descActividad": "Servicios",
            "direccion": {
                "departamento": "05",
                "municipio": "24",
                "complemento": "Dir Cliente",
            },
        },
        "documentoRelacionado": [
            {
                "tipoDocumento": "03",
                "tipoGeneracion": 2,
                "numeroDocumento": numero_control,
                "fechaEmision": "2024-01-01",
            }
        ],
        "resumen": {
            "montoTotalOperacion": 10,
            "totalGravada": 10,
            "totalNoSuj": 0,
            "totalExenta": 0,
            "condicionOperacion": 1,
        },
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "tipoItem": 1,
                "descripcion": "Servicio",
                "cantidad": 1,
                "uniMedida": 59,
                "precioUni": 10,
                "ventaGravada": 10,
                "ventaExenta": 0,
                "ventaNoSuj": 0,
                "tributos": [catalogos.TRIBUTO_IVA],
            }
        ],
    }


def _register_credit_note(db: DB, monto_venta: float = 10.0, monto_nota: float = 5.0) -> tuple[int, int]:
    db.add_vendedor("V1")
    vendedor_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vendedor_id, None, 0, 0, 0, 10)
    producto_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", monto_venta)
    db.add_detalle_venta(venta_id, producto_id, 1, monto_venta, vendedor_id=vendedor_id)
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'credito', '2024-01-05', ?, 'Ajuste')",
        (venta_id, monto_nota),
    ).lastrowid
    return venta_id, nota_id


def test_generar_nota_credito_json_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
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
    nde = generar_nde_desde_dte(db, dte_origen, detalles=None, monto=Decimal("1"))
    assert data["identificacion"]["tipoDte"] == "05"
    assert data.get("documentoRelacionado")
    doc_rel = data["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, data["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, dte_origen)
    assert doc_rel == nde["documentoRelacionado"][0]
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
        lambda: _datos_negocio_base(),
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
    dte_origen["receptor"]["codActividad"] = "654321"
    dte_origen["receptor"]["descActividad"] = "Servicios"
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), motivo="Dev")
    nde = generar_nde_desde_dte(db, dte_origen, detalles=None, monto=Decimal("1"))
    doc_rel = data["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, data["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, dte_origen)
    assert doc_rel == nde["documentoRelacionado"][0]
    receptor = data["receptor"]
    assert "-" not in receptor.get("nit", "")
    assert receptor.get("nit")
    assert receptor.get("nrc") == "123"
    assert receptor.get("nombreComercial") in {None, "Cliente"}


def test_generar_nce_desde_nota_credito_fiscal(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
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
        codActividad="654321",
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
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'credito', '2024-01-02', 10, 'Dev')",
        (venta_id,),
    ).lastrowid

    nce = generar_nce_desde_nota(db, nota_id)
    doc_rel = nce["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    assert doc_rel["fechaEmision"] == "2024-01-01"
    today_str = fecha_emision_hoy_str()
    assert nce["identificacion"]["fecEmi"] == today_str
    receptor_nota = nce["receptor"]
    assert receptor_nota["nit"] == "06141407100012"
    assert receptor_nota["nrc"] == "123"
    assert receptor_nota.get("nombreComercial") in {None, "Cliente"}


def test_generar_nce_desde_nota_regenera_dte_fecha(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
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
    cliente_id = db.add_cliente(
        "Cliente",
        "123",
        "06141407100012",
        "",
        "Servicios",
        "22223333",
        "cli@example.com",
        "Dir",
        "05",
        "24",
        codActividad="654321",
        nombreComercial="Cliente",
    )
    venta_fecha = "2024-03-15"
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        venta_fecha,
        10,
        "123",
        "06141407100012",
        "Servicios",
        descuentos=0,
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    dte_base = generar_dte_json(db, venta_id, tipo_dte="03")
    dte_alterado = deepcopy(dte_base)
    dte_alterado["identificacion"]["fecEmi"] = "2024-03-18"
    receptor_alterado = dte_alterado.setdefault("receptor", {})
    for key, value in (
        ("nombre", "Cliente"),
        ("nit", "06141407100012"),
        ("nrc", "123"),
        ("codActividad", "654321"),
        ("descActividad", "Servicios"),
    ):
        if not receptor_alterado.get(key):
            receptor_alterado[key] = value
    direccion = receptor_alterado.get("direccion") or {}
    for key, value in (
        ("departamento", "05"),
        ("municipio", "24"),
        ("complemento", "Dir"),
    ):
        if not direccion.get(key):
            direccion[key] = value
    receptor_alterado["direccion"] = direccion

    monkeypatch.setattr(
        "nota_credito_electronica.generar_dte_json",
        lambda *args, **kwargs: deepcopy(dte_alterado),
    )

    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'credito', '2024-03-20', 10, 'Dev')",
        (venta_id,),
    ).lastrowid

    fecha_envio_iso = "2024-03-18"
    db.registrar_envio_dte(
        venta_id,
        "auto",
        "procesado",
        "SELLO",
        respuesta_json=json.dumps({"fhProcesamiento": f"{fecha_envio_iso}T12:34:56"}),
    )

    nce = generar_nce_desde_nota(db, nota_id, strict_snapshot=False)
    doc_rel = nce["documentoRelacionado"][0]
    assert doc_rel["fechaEmision"] == fecha_envio_iso
    today_str = fecha_emision_hoy_str()
    assert nce["identificacion"]["fecEmi"] == today_str


def test_plan_b_nce_usa_snapshot(monkeypatch, tmp_path, caplog):
    negocio = {
        "nit": "06141407100012",
        "nrc": "1234567",
        "nombre": "Emisor Pruebas",
        "nombreComercial": "Emisor",
        "codActividad": "123456",
        "descActividad": "Venta",
        "tipoEstablecimiento": "01",
        "telefono": "22223333",
        "correo": "emisor@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir Emisor"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: negocio)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir Cliente"},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)

    db = create_db()
    venta_id, nota_id = _register_credit_note(db)
    payload = _build_base_payload()

    snapshot = Snapshot(
        uuid=payload["identificacion"]["codigoGeneracion"],
        path=str(tmp_path / "documento.json"),
        tipo_documento="03",
        fecha_emision="01/01/2024",
        payload=payload,
    )
    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda vid: snapshot if vid == venta_id else None)

    metrics_calls: list[str] = []
    monkeypatch.setattr(
        nota_credito_electronica.metrics,
        "inc",
        lambda name: metrics_calls.append(name),
    )

    caplog.set_level(logging.INFO, logger=nota_credito_electronica.logger.name)
    resultado = generar_nce_desde_nota(db, nota_id)

    assert resultado["identificacion"]["tipoDte"] == "05"
    assert "Fallback JSON activado" not in caplog.text
    assert metrics_calls.count("notes_source_used.snapshot") == 1
    assert "notes_fallback_json" not in metrics_calls


def test_plan_b_nce_json_regenera_snapshot(monkeypatch, tmp_path, caplog):
    negocio = {
        "nit": "06141407100012",
        "nrc": "1234567",
        "nombre": "Emisor Pruebas",
        "nombreComercial": "Emisor",
        "codActividad": "123456",
        "descActividad": "Venta",
        "tipoEstablecimiento": "01",
        "telefono": "22223333",
        "correo": "emisor@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir Emisor"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: negocio)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir Cliente"},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)

    db = create_db()
    venta_id, nota_id = _register_credit_note(db)
    payload = _build_base_payload()
    json_path = tmp_path / "factura.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    db.update_nota_detalles(nota_id, {"json_path": str(json_path)})
    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda vid: None)

    target_dir = tmp_path / "dtes"
    monkeypatch.setattr("paths.DTES_DIR", str(target_dir))
    monkeypatch.setattr("utils.nota_fallback.DTES_DIR", str(target_dir))

    metrics_calls: list[str] = []
    monkeypatch.setattr(
        nota_credito_electronica.metrics,
        "inc",
        lambda name: metrics_calls.append(name),
    )

    caplog.set_level(logging.INFO, logger=nota_credito_electronica.logger.name)
    generar_nce_desde_nota(db, nota_id)

    assert "Fallback JSON activado" in caplog.text
    assert "notes_source_used.json" in metrics_calls
    assert "notes_fallback_json" in metrics_calls

    detalles_row = db.cursor.execute("SELECT detalles FROM notas WHERE id=?", (nota_id,)).fetchone()
    detalles = json.loads(detalles_row["detalles"])
    assert "snapshot_conflict" in detalles
    assert detalles["snapshot_conflict"].startswith("codigoGeneracion")


def test_plan_b_nce_json_sin_documento_relacionado(monkeypatch, tmp_path, caplog):
    negocio = {
        "nit": "06141407100012",
        "nrc": "1234567",
        "nombre": "Emisor Pruebas",
        "nombreComercial": "Emisor",
        "codActividad": "123456",
        "descActividad": "Venta",
        "tipoEstablecimiento": "01",
        "telefono": "22223333",
        "correo": "emisor@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir Emisor"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: negocio)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir Cliente"},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)

    db = create_db()
    venta_id, nota_id = _register_credit_note(db)
    payload = _build_base_payload()
    payload.pop("documentoRelacionado")
    json_path = tmp_path / "factura_sin_doc_rel.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    db.update_nota_detalles(nota_id, {"json_path": str(json_path)})
    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda vid: None)

    metrics_calls: list[str] = []
    monkeypatch.setattr(
        nota_credito_electronica.metrics,
        "inc",
        lambda name: metrics_calls.append(name),
    )

    caplog.set_level(logging.INFO, logger=nota_credito_electronica.logger.name)
    data = generar_nce_desde_nota(db, nota_id)

    nde = generar_nde_desde_dte(db, payload, detalles=None, monto=Decimal("1"))
    doc_rel = data["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, data["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, payload)
    assert doc_rel == nde["documentoRelacionado"][0]
    assert "Fuente documentoRelacionado: derivado" in caplog.text
    assert "notes_source_used.json" in metrics_calls
    assert "notes_fallback_json" in metrics_calls


def test_nce_doc_rel_usa_uuid_cuando_hay_codigo_generacion():
    db = create_db()
    dte_origen = _build_base_payload()

    nce = generar_nce_desde_dte(db, dte_origen, Decimal("1"))
    nde = generar_nde_desde_dte(db, dte_origen, detalles=None, monto=Decimal("1"))

    assert len(nce["documentoRelacionado"]) == len(nde["documentoRelacionado"]) == 1
    doc_rel_nce = nce["documentoRelacionado"][0]
    doc_rel_nde = nde["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel_nce, nce["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel_nce, dte_origen)
    assert doc_rel_nce["tipoGeneracion"] == 2
    assert (
        doc_rel_nce["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"].strip().upper()
    )
    assert doc_rel_nce == doc_rel_nde
    assert nce["receptor"] == nde["receptor"]


def test_nce_receptor_hereda_nrc_y_actividad_del_origen_tipo03():
    db = create_db()
    dte_origen = _build_base_payload()
    dte_origen["receptor"]["nrc"] = "2301408"
    dte_origen["receptor"]["codActividad"] = "46484"
    dte_origen["receptor"]["descActividad"] = "Venta al por mayor"
    fuentes = {
        "nota": {"nrc": "", "codActividad": "000", "descActividad": ""},
        "venta_extra": {"codActividad": None, "descActividad": None},
        "cliente": {"codActividad": "99999", "descActividad": "Placeholder"},
    }

    resultado = generar_nce_desde_dte(db, dte_origen, Decimal("1"), receptor_fuentes=fuentes)

    receptor = resultado["receptor"]
    assert receptor["nrc"] == "2301408"
    assert receptor["codActividad"] == "46484"
    assert receptor["descActividad"] == "Venta al por mayor"


def test_nce_receptor_conserva_nit_y_actividad_del_origen_cf():
    db = create_db()
    dte_origen = _build_base_payload()
    dte_origen["receptor"]["nit"] = "000868547"
    dte_origen["receptor"]["nrc"] = "2301408"
    dte_origen["receptor"]["codActividad"] = "46484"
    dte_origen["receptor"]["descActividad"] = "Servicios medicos"

    nce = generar_nce_desde_dte(db, dte_origen, Decimal("1"))
    nde = generar_nde_desde_dte(db, dte_origen, detalles=None, monto=Decimal("1"))

    doc_rel = nce["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, nce["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, dte_origen)
    assert doc_rel["tipoGeneracion"] == 2
    assert (
        doc_rel["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"].strip().upper()
    )

    receptor = nce["receptor"]
    assert receptor["nit"] == "000868547"
    assert receptor["nrc"] == "2301408"
    assert receptor["codActividad"] == "46484"
    assert receptor["descActividad"] == "Servicios medicos"


def test_nce_requiere_actividad_con_nrc_o_tipo03():
    db = create_db()
    dte_origen = _build_base_payload()
    dte_origen["receptor"]["nrc"] = "123456-7"
    dte_origen["receptor"].pop("codActividad", None)
    dte_origen["receptor"].pop("descActividad", None)

    with pytest.raises(
        ValueError,
        match="Receptor con NRC o documento 03 requiere codActividad y descActividad válidos",
    ):
        generar_nce_desde_dte(db, dte_origen, Decimal("1"))

    dte_tipo01 = _build_base_payload()
    dte_tipo01["identificacion"]["tipoDte"] = "01"
    dte_tipo01["identificacion"]["codigoGeneracion"] = ""
    dte_tipo01["identificacion"]["numeroControl"] = "dte-01-s001p001-000000000000321"
    dte_tipo01["receptor"]["nrc"] = "7654321"
    dte_tipo01["receptor"].pop("codActividad", None)
    dte_tipo01["receptor"].pop("descActividad", None)

    with pytest.raises(
        ValueError,
        match="Receptor con NRC o documento 03 requiere codActividad y descActividad válidos",
    ):
        generar_nce_desde_dte(db, dte_tipo01, Decimal("1"))


def test_nce_unimedida_default():
    db = create_db()
    dte_origen = _build_base_payload()
    detalles = [
        {
            "numItem": 1,
            "descripcion": "Prod",
            "cantidad": 1,
            "ventaGravada": 5,
            "precio_unitario": 5,
        }
    ]

    nce = generar_nce_desde_dte(db, dte_origen, None, detalles=detalles)
    nde = generar_nde_desde_dte(db, dte_origen, detalles=detalles, monto=None)

    assert nce["documentoRelacionado"] == nde["documentoRelacionado"]
    assert nce["receptor"] == nde["receptor"]
    assert all(item["uniMedida"] == 59 for item in nce["cuerpoDocumento"])


def test_nce_receptor_actividad_numerica_a_texto():
    db = create_db()
    dte_origen = _build_base_payload()
    dte_origen["receptor"]["nrc"] = "7654321"
    dte_origen["receptor"]["codActividad"] = 123456
    dte_origen["receptor"]["descActividad"] = 98765

    resultado = generar_nce_desde_dte(db, dte_origen, Decimal("1"))

    receptor = resultado["receptor"]
    assert receptor["codActividad"] == "123456"
    assert receptor["descActividad"] == "98765"


def test_nce_log_diagnostico_incluye_ident_y_actividad(caplog):
    db = create_db()
    dte_origen = _build_base_payload()
    dte_origen["receptor"]["nit"] = "000868547"
    dte_origen["receptor"]["nrc"] = "2301408"
    dte_origen["receptor"]["codActividad"] = "46484"
    dte_origen["receptor"]["descActividad"] = "Servicios medicos"

    caplog.set_level(logging.INFO, logger=nota_credito_electronica.logger.name)

    resultado = generar_nce_desde_dte(db, dte_origen, Decimal("1"))

    doc_rel = resultado["documentoRelacionado"][0]
    receptor = resultado["receptor"]
    _assert_relacionado_y_receptor(doc_rel, receptor)

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == nota_credito_electronica.logger.name
        and record.levelno == logging.INFO
        and record.getMessage().startswith("NCE: rel=")
    ]
    assert messages, "No se registró el log diagnóstico de NCE"
    diag_msg = messages[-1]

    assert f"tipoDoc={doc_rel['tipoDocumento']}" in diag_msg
    assert f"tipoGen={doc_rel['tipoGeneracion']}" in diag_msg
    assert f"num={doc_rel['numeroDocumento']}" in diag_msg
    assert f"fecha={doc_rel['fechaEmision']}" in diag_msg
    assert f"nit={receptor.get('nit')}" in diag_msg
    assert f"nrc={receptor.get('nrc')}" in diag_msg
    assert f"codActividad={receptor.get('codActividad')}" in diag_msg
    assert f"descActividad={receptor.get('descActividad')}" in diag_msg


def test_nce_paridad_con_nde_en_relacionado_y_receptor():
    db = create_db()
    dte_origen = _build_base_payload()

    nce_uuid = generar_nce_desde_dte(db, dte_origen, Decimal("1"))
    nde_uuid = generar_nde_desde_dte(db, dte_origen, detalles=None, monto=Decimal("1"))

    assert nce_uuid["documentoRelacionado"] == nde_uuid["documentoRelacionado"]
    assert nce_uuid["receptor"] == nde_uuid["receptor"]

    dte_sin_uuid = _build_base_payload()
    dte_sin_uuid["identificacion"]["codigoGeneracion"] = ""
    dte_sin_uuid["identificacion"]["numeroControl"] = "dte-01-s001p001-000000000000654"
    dte_sin_uuid["identificacion"]["tipoDte"] = "01"

    nce_ctrl = generar_nce_desde_dte(db, dte_sin_uuid, Decimal("1"))
    nde_ctrl = generar_nde_desde_dte(db, dte_sin_uuid, detalles=None, monto=Decimal("1"))

    assert len(nce_ctrl["documentoRelacionado"]) == len(nde_ctrl["documentoRelacionado"])
    doc_ctrl_nce = nce_ctrl["documentoRelacionado"][0]
    doc_ctrl_nde = nde_ctrl["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_ctrl_nce, nce_ctrl["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_ctrl_nce, dte_sin_uuid)
    assert doc_ctrl_nce["tipoDocumento"] == doc_ctrl_nde["tipoDocumento"]
    assert doc_ctrl_nce["tipoGeneracion"] == 1
    assert doc_ctrl_nce["tipoGeneracion"] == doc_ctrl_nde["tipoGeneracion"]
    assert doc_ctrl_nce["fechaEmision"] == doc_ctrl_nde["fechaEmision"]
    assert (
        doc_ctrl_nce["numeroDocumento"]
        == doc_ctrl_nde["numeroDocumento"].strip().upper()
        == dte_sin_uuid["identificacion"]["numeroControl"].upper()
    )
    assert nce_ctrl["receptor"] == nde_ctrl["receptor"]
    assert nce_ctrl["receptor"].get("nrc") is None


def test_nce_plan_b_paridad_nde(monkeypatch, tmp_path):
    negocio = _datos_negocio_base()
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: negocio)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: negocio)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda _src: {"departamento": "05", "municipio": "24", "complemento": "Dir Cliente"},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)

    db = create_db()
    venta_id, nota_id = _register_credit_note(db)
    payload = _build_base_payload()
    payload["identificacion"]["ambiente"] = "01"
    payload["receptor"]["correo"] = "cliente@example.com"
    payload["receptor"]["telefono"] = "70000000"
    payload["receptor"]["nombreComercial"] = "Cliente Demo"
    json_path = tmp_path / "plan_b.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    db.update_nota_detalles(nota_id, {"json_path": str(json_path)})
    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda vid: None)

    calls: list[str] = []
    original_prepare = nota_credito_electronica.prepare_dte_origen
    original_prevalidate = nota_credito_electronica.prevalidate_dte_origen
    original_generar = nota_credito_electronica.generar_nce_desde_dte
    original_sanitize = nota_credito_electronica.sanitize_dte_payload
    original_rebuild = nota_credito_electronica.rebuild_snapshot_from_json

    def _wrap(name, func):
        def _wrapped(*args, **kwargs):
            calls.append(name)
            return func(*args, **kwargs)

        return _wrapped

    monkeypatch.setattr(nota_credito_electronica, "prepare_dte_origen", _wrap("prepare", original_prepare))
    monkeypatch.setattr(
        nota_credito_electronica,
        "prevalidate_dte_origen",
        _wrap("prevalidate", original_prevalidate),
    )
    monkeypatch.setattr(nota_credito_electronica, "generar_nce_desde_dte", _wrap("generar", original_generar))
    monkeypatch.setattr(nota_credito_electronica, "sanitize_dte_payload", _wrap("sanitize", original_sanitize))
    monkeypatch.setattr(
        nota_credito_electronica,
        "rebuild_snapshot_from_json",
        _wrap("rebuild", original_rebuild),
    )

    resultado = generar_nce_desde_nota(db, nota_id, ambiente="01")

    assert calls == ["prepare", "prevalidate", "generar", "sanitize", "rebuild"]
    ident = resultado["identificacion"]
    assert ident["ambiente"] == "01"
    doc_rel = resultado["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, resultado["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, payload)


def test_plan_b_nce_json_incompleto_falla(monkeypatch, tmp_path):
    payload = _build_base_payload()
    payload["emisor"].pop("nit")

    db = create_db()
    venta_id, nota_id = _register_credit_note(db)
    json_path = tmp_path / "incompleto.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    db.update_nota_detalles(nota_id, {"json_path": str(json_path)})
    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda vid: None)

    monkeypatch.setattr(
        "nota_credito_electronica.generar_dte_json",
        lambda *a, **k: {"identificacion": payload["identificacion"], "emisor": {"nrc": "123"}},
    )

    with pytest.raises(ValueError) as exc:
        generar_nce_desde_nota(db, nota_id)

    assert "Falta emisor.nit" in str(exc.value)


def test_plan_b_nce_json_conflicto(monkeypatch, tmp_path, caplog):
    negocio = {
        "nit": "06141407100012",
        "nrc": "1234567",
        "nombre": "Emisor Pruebas",
        "nombreComercial": "Emisor",
        "codActividad": "123456",
        "descActividad": "Venta",
        "tipoEstablecimiento": "01",
        "telefono": "22223333",
        "correo": "emisor@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir Emisor"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: negocio)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir Cliente"},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)

    db = create_db()
    venta_id, nota_id = _register_credit_note(db)
    payload = _build_base_payload()
    json_path = tmp_path / "conflicto.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    db.update_nota_detalles(nota_id, {"json_path": str(json_path)})
    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda vid: None)
    db.update_venta_extra(venta_id, {"codigoGeneracion": "FFFF0000-0000-0000-0000-FFFFFFFFFFFF"})

    metrics_calls: list[str] = []
    monkeypatch.setattr(
        nota_credito_electronica.metrics,
        "inc",
        lambda name: metrics_calls.append(name),
    )

    caplog.set_level(logging.INFO, logger=nota_credito_electronica.logger.name)
    generar_nce_desde_nota(db, nota_id)

    assert "notes_source_used.json" in metrics_calls
    assert "notes_fallback_json" in metrics_calls
    assert "Conflicto al regenerar snapshot" in caplog.text

    detalles_row = db.cursor.execute("SELECT detalles FROM notas WHERE id=?", (nota_id,)).fetchone()
    detalles = json.loads(detalles_row["detalles"])
    assert "snapshot_conflict" in detalles
    assert "snapshot_path" not in detalles


def test_prepare_dte_origen_completa_receptor_desde_cliente(monkeypatch):
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {
            "departamento": str(src.get("departamento", "05")).zfill(2),
            "municipio": str(src.get("municipio", "24")).zfill(2),
            "complemento": src.get("complemento", "Dir"),
        },
    )

    db = create_db()
    db.add_vendedor("V1")
    vendedor_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vendedor_id, None, 0, 0, 0, 10)
    producto_id = db.cursor.lastrowid

    db.add_cliente(
        "Cliente Demo",
        "987654-3",
        "06141407100012",
        "",
        "Servicios",
        "22223333",
        "cliente@example.com",
        "Dir Cliente",
        "05",
        "24",
        codActividad="654321",
        nombreComercial="Cliente Demo",
    )
    cliente_id = db.cursor.lastrowid

    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        10,
        "987654-3",
        "06141407100012",
        "Servicios",
    )
    db.add_detalle_venta(venta_id, producto_id, 1, 10, vendedor_id=vendedor_id)

    dte_origen = generar_dte_json(db, venta_id, tipo_dte="03")
    receptor = dte_origen.get("receptor", {})
    receptor.pop("codActividad", None)
    receptor.pop("descActividad", None)

    snapshot = Snapshot(
        uuid=dte_origen["identificacion"]["codigoGeneracion"],
        path="/tmp/in-memory.json",
        tipo_documento="03",
        fecha_emision=dte_origen["identificacion"].get("fecEmi"),
        payload=dte_origen,
    )
    monkeypatch.setattr(
        db,
        "get_snapshot_by_venta",
        lambda vid: snapshot if vid == venta_id else None,
    )

    venta = db.get_venta_by_id(venta_id)
    result = prepare_dte_origen(
        db=db,
        nota={"cliente_id": cliente_id},
        venta=venta,
        venta_id=venta_id,
        tipo_doc="03",
        ambiente="00",
        strict=False,
        usar_fallback_json=False,
        nota_id=999,
        regenerate=None,
        venta_credito_fiscal=None,
        logger=logging.getLogger("test-notas"),
    )

    receptor_result = result.data["receptor"]
    assert receptor_result["nrc"] == "987654-3"
    assert receptor_result["codActividad"] == "654321"
    assert receptor_result["descActividad"] == "Servicios"

    prevalidate_dte_origen(
        result.data,
        ambiente="00",
        nota_tipo="credito",
        logger=logging.getLogger("test-notas"),
    )


def test_prepare_dte_origen_completa_receptor_desde_venta_extra(monkeypatch):
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {
            "departamento": str(src.get("departamento", "05")).zfill(2),
            "municipio": str(src.get("municipio", "24")).zfill(2),
            "complemento": src.get("complemento", "Dir"),
        },
    )

    db = create_db()
    db.add_vendedor("V1")
    vendedor_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vendedor_id, None, 0, 0, 0, 10)
    producto_id = db.cursor.lastrowid

    db.add_cliente(
        "Cliente Demo",
        "987654-3",
        "06141407100012",
        "",
        "",
        "22223333",
        "cliente@example.com",
        "Dir Cliente",
        "05",
        "24",
        codActividad="",
        nombreComercial="Cliente Demo",
    )
    cliente_id = db.cursor.lastrowid

    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        10,
        "987654-3",
        "06141407100012",
        "",
    )
    db.add_detalle_venta(venta_id, producto_id, 1, 10, vendedor_id=vendedor_id)

    dte_origen = generar_dte_json(db, venta_id, tipo_dte="03")
    receptor = dte_origen.get("receptor", {})
    receptor.pop("codActividad", None)
    receptor.pop("descActividad", None)

    snapshot = Snapshot(
        uuid=dte_origen["identificacion"]["codigoGeneracion"],
        path="/tmp/in-memory.json",
        tipo_documento="03",
        fecha_emision=dte_origen["identificacion"].get("fecEmi"),
        payload=dte_origen,
    )
    monkeypatch.setattr(
        db,
        "get_snapshot_by_venta",
        lambda vid: snapshot if vid == venta_id else None,
    )

    db.update_venta_extra(
        venta_id,
        {
            "cliente": {
                "codActividad": "654321",
                "descActividad": "Servicios",
            }
        },
    )

    venta = db.get_venta_by_id(venta_id)
    result = prepare_dte_origen(
        db=db,
        nota={"venta_id": venta_id},
        venta=venta,
        venta_id=venta_id,
        tipo_doc="03",
        ambiente="00",
        strict=False,
        usar_fallback_json=False,
        nota_id=999,
        regenerate=None,
        venta_credito_fiscal=None,
        logger=logging.getLogger("test-notas"),
    )

    receptor_result = result.data["receptor"]
    assert receptor_result["codActividad"] == "654321"
    assert receptor_result["descActividad"] == "Servicios"


def test_generar_nce_completa_receptor_desde_credito_fiscal(monkeypatch):
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {
            "departamento": str(src.get("departamento", "05")).zfill(2),
            "municipio": str(src.get("municipio", "24")).zfill(2),
            "complemento": src.get("complemento", "Dir"),
        },
    )

    db = create_db()
    db.add_vendedor("V1")
    vendedor_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vendedor_id, None, 0, 0, 0, 10)
    producto_id = db.cursor.lastrowid

    db.add_cliente(
        "Cliente Demo",
        "987654-3",
        "06141407100012",
        "",
        "",
        "22223333",
        "cliente@example.com",
        "Dir Cliente",
        "05",
        "24",
        codActividad="",
        nombreComercial="Cliente Demo",
    )
    cliente_id = db.cursor.lastrowid

    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        10,
        "987654-3",
        "06141407100012",
        "",
        extra={
            "cliente": {
                "actividadEconomica": "CF654321",
                "actividadEconomicaDescripcion": "Servicios CF",
            }
        },
    )
    db.add_detalle_venta(venta_id, producto_id, 1, 10, vendedor_id=vendedor_id)

    dte_origen = generar_dte_json(db, venta_id, tipo_dte="03")
    receptor = dte_origen.get("receptor", {})
    receptor.pop("codActividad", None)
    receptor.pop("descActividad", None)

    snapshot = Snapshot(
        uuid=dte_origen["identificacion"]["codigoGeneracion"],
        path="/tmp/in-memory.json",
        tipo_documento="03",
        fecha_emision=dte_origen["identificacion"].get("fecEmi"),
        payload=json.loads(json.dumps(dte_origen, default=str)),
    )
    monkeypatch.setattr(
        db,
        "get_snapshot_by_venta",
        lambda vid: snapshot if vid == venta_id else None,
    )

    nota_id = db.agregar_nota("credito", venta_id, "2024-02-01", 10, "Ajuste")

    resultado = generar_nce_desde_nota(db, nota_id, ambiente="00")

    receptor_result = resultado["receptor"]
    assert receptor_result["codActividad"] == "CF654321"
    assert receptor_result["descActividad"] == "Servicios CF"


def test_generar_nce_rellena_actividad_con_metadatos(monkeypatch):
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {
            "departamento": str(src.get("departamento", "05")).zfill(2),
            "municipio": str(src.get("municipio", "24")).zfill(2),
            "complemento": src.get("complemento", "Dir"),
        },
    )

    db = create_db()
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (NULL, 'credito', '2024-02-10', 5, 'Ajuste')",
    ).lastrowid

    base_payload = _build_base_payload()
    base_payload["receptor"]["codActividad"] = None
    base_payload["receptor"]["descActividad"] = ""

    metadata = {
        "codActividad": "654321",
        "descActividad": "Servicios",
    }

    origen_info = OrigenResult(
        data=deepcopy(base_payload),
        section_sources={"receptor": "snapshot"},
        source_used="snapshot",
        snapshot=None,
        json_path=None,
        json_payload=None,
        json_used=False,
        config_used=False,
        detalles={},
        venta_extra={},
        venta_credito_fiscal=metadata,
        expected_ident={
            "codigoGeneracion": base_payload["identificacion"]["codigoGeneracion"],
            "numeroControl": base_payload["identificacion"]["numeroControl"],
        },
    )

    monkeypatch.setattr(nota_credito_electronica, "prepare_dte_origen", lambda **_: origen_info)
    monkeypatch.setattr(nota_credito_electronica, "prevalidate_dte_origen", lambda *a, **k: None)

    resultado = generar_nce_desde_nota(db, nota_id, ambiente="00")

    receptor = resultado["receptor"]
    assert receptor["codActividad"] == "654321"
    assert receptor["descActividad"] == "Servicios"


def test_generar_nce_desde_nota_prefiere_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )

    db = create_db()
    venta_id = db.add_venta("2023-08-01", 100)
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'credito', '2023-08-05', 10, 'Ajuste')",
        (venta_id,),
    ).lastrowid

    payload = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "12345678-ABCD-1234-ABCD-1234567890AB",
            "fecEmi": "2023-08-01",
            "numeroControl": "DTE-03-00100001",
        },
        "emisor": _datos_negocio_base(),
        "receptor": {
            "nombre": "Cliente Snapshot",
            "nit": "06141407100012",
            "nrc": None,
            "codActividad": "654321",
            "descActividad": "Servicios",
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
        fecha_emision="01/08/2023",
        payload=payload,
    )

    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda vid: snapshot if vid == venta_id else None)

    def _fail_generar_dte(*_args, **_kwargs):
        raise AssertionError("No se debe regenerar desde la base de datos")

    monkeypatch.setattr("nota_credito_electronica.generar_dte_json", _fail_generar_dte)
    metrics_calls = []
    monkeypatch.setattr(
        "nota_credito_electronica.metrics.inc", lambda name: metrics_calls.append(name)
    )

    nce = generar_nce_desde_nota(db, nota_id)

    receptor = nce["receptor"]
    assert receptor["nit"] == "06141407100012"
    assert receptor.get("nrc") in (None, "", "0")

    doc_rel = nce["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, receptor)
    _assert_doc_rel_coincide_con_origen(doc_rel, payload)
    assert doc_rel["fechaEmision"] == "2023-08-01"
    today_str = fecha_emision_hoy_str()
    assert nce["identificacion"]["fecEmi"] == today_str
    assert metrics_calls == ["notes_source_used.snapshot"]
    assert payload["firma"] == "SIGNATURE"


def test_generar_nce_desde_nota_snapshot_dui(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )

    db = create_db()
    venta_id = db.add_venta("2023-09-01", 40)
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'credito', '2023-09-03', 8, 'Devolución')",
        (venta_id,),
    ).lastrowid

    payload = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-DCBA-4321-DCBA-0987654321FF",
            "fecEmi": "2023-09-01",
            "numeroControl": "DTE-01-00001234",
        },
        "emisor": _datos_negocio_base(),
        "receptor": {
            "nombre": "Consumidor Final",
            "tipoDocumento": "13",
            "numDocumento": "01234567-8",
            "nit": "012345678",
            "codActividad": "654321",
            "descActividad": "Servicios",
            "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
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
        fecha_emision="01/09/2023",
        payload=payload,
    )

    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda vid: snapshot if vid == venta_id else None)
    monkeypatch.setattr(
        "nota_credito_electronica.generar_dte_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Debe usar snapshot")),
    )

    nce = generar_nce_desde_nota(db, nota_id)

    receptor = nce["receptor"]
    assert receptor["nit"] == "012345678"
    assert receptor.get("nrc") in (None, "", "0")

    doc_rel = nce["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, receptor)
    _assert_doc_rel_coincide_con_origen(doc_rel, payload)
    assert doc_rel["fechaEmision"] == "2023-09-01"
    today_str = fecha_emision_hoy_str()
    assert nce["identificacion"]["fecEmi"] == today_str


def test_generar_nce_desde_nota_strict_snapshot(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )

    db = create_db()
    venta_id = db.add_venta("2023-08-01", 50)
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, 'credito', '2023-08-05', 5, 'Ajuste')",
        (venta_id,),
    ).lastrowid

    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda _vid: None)

    with pytest.raises(SnapshotNotFoundError) as exc:
        generar_nce_desde_nota(db, nota_id, strict_snapshot=True)

    message = str(exc.value)
    assert str(venta_id) in message
    assert str(nota_id) in message


def test_generar_nce_receptor_placeholder_en_pruebas(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
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
            "numeroControl": "DTE-01-000000000001",
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
    assert "nrc" in receptor
    assert receptor["nrc"] is None
    assert receptor["correo"] == "demo@example.com"
    assert receptor["telefono"] == "00000000"
    assert receptor["direccion"]["departamento"] == "01"
    assert receptor["direccion"]["municipio"] == "01"
    assert "otrosDocumentos" not in nce


def test_generar_nce_consumidor_final_dui_en_nit(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {
            "departamento": str(src.get("departamento", "05")).zfill(2),
            "municipio": str(src.get("municipio", "24")).zfill(2),
            "complemento": src.get("complemento", "Dir"),
        },
    )

    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
            "fecEmi": "2024-01-01",
            "numeroControl": "DTE-01-000000000002",
        },
        "emisor": {},
        "receptor": {
            "nombre": "Consumidor Final",
            "tipoDocumento": "13",
            "numDocumento": "01234567-8",
        },
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
    assert receptor["nit"] == "012345678"
    assert "nrc" in receptor
    assert receptor["nrc"] is None


def test_generar_nce_receptor_incompleto_en_produccion(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
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
            "numeroControl": "DTE-01-000000000003",
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


def test_generar_nce_config_produccion_impone_ambiente(monkeypatch):
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
        "dte_api": {"prefijo_control": "DTE-01-S001P001"},
    }

    monkeypatch.setattr("dte._load_dte_api_config", lambda: {"ambiente": "produccion"})
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)

    ambientes_recibidos: list[str] = []

    def _fake_ensure_receptor(base, ambiente):
        ambientes_recibidos.append(ambiente)
        receptor = dict(base)
        receptor.setdefault("nombre", "Cliente")
        receptor.setdefault("nit", "06141407100012")
        receptor.setdefault("nrc", "1234567")
        receptor.setdefault("codActividad", "111111")
        receptor.setdefault("descActividad", "Giro")
        receptor.setdefault("tipoDocumento", "36")
        receptor.setdefault("numDocumento", "06141407100012")
        receptor.setdefault(
            "direccion",
            {"departamento": "05", "municipio": "24", "complemento": "Dir"},
        )
        return receptor

    monkeypatch.setattr(
        "nota_credito_electronica.ensure_receptor_completo", _fake_ensure_receptor
    )

    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
            "numeroControl": "DTE-01-S001P001-000000001",
            "fecEmi": "2024-01-01",
        },
        "emisor": {"nit": "06141407100012", "nrc": "1234567"},
        "receptor": {"nombre": "Cliente"},
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

    assert nce["identificacion"]["ambiente"] == "01"
    assert ambientes_recibidos == ["01"]


def test_nota_credito_total_nueve(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
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
    expected_total = dte_origen["resumen"]["montoTotalOperacion"]
    assert expected_total == Decimal("7.96")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"))
    doc_rel = data["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, data["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, dte_origen)
    assert data["resumen"]["montoTotalOperacion"] == expected_total


def test_nota_credito_precio_uni(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
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
            "precio_unitario": Decimal("7.96"),
            "ventas_gravadas": Decimal("7.96"),
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), detalles=detalles)
    doc_rel = data["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, data["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, dte_origen)
    item = data["cuerpoDocumento"][0]
    assert item["precioUni"] == Decimal("7.9600")
    iva = Decimal("7.96") * Decimal("0.13")
    iva = iva.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    expected_total = Decimal("7.96") + iva
    assert data["resumen"]["montoTotalOperacion"] == expected_total


def test_generar_nce_rechaza_monto_excedido(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
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
    db.add_cliente("Cliente", "123", "06141407100012", "", "giro", "", "cli@example.com", "Dir", "05", "24")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cliente_id)
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
        lambda: _datos_negocio_base(),
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
    db.add_cliente("Cliente", "123", "06141407100012", "", "giro", "", "cli@example.com", "Dir", "05", "24")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cliente_id)
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


def test_generar_nce_detalle_ajuste_cantidad(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
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
    venta_id = db.add_venta("2024-01-01", 50)
    db.add_detalle_venta(venta_id, pid, 5, 10, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    codigo = dte_origen["cuerpoDocumento"][0]["codigo"]
    detalles = [
        {
            "codigo": codigo,
            "descripcion": "Prod",
            "cantidad": 2,
            "precio_unitario": 10,
            "afectacion": "gravada",
            "ajusteCantidad": True,
        }
    ]
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), detalles=detalles)
    item = data["cuerpoDocumento"][0]
    assert Decimal(str(item["cantidad"])) == Decimal("2.0000")
    assert Decimal(str(item["ventaGravada"])) == Decimal("20.0000")
    assert Decimal(str(item["precioUni"])) == Decimal("10.0000")
    assert Decimal(str(data["resumen"]["montoTotalOperacion"])) == Decimal("22.60")


def test_nota_credito_un_dolar(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
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
    cliente_info = {
        "nombre": "Cliente",
        "nrc": "123",
        "nit": "06141407100012",
        "codActividad": "654321",
        "descActividad": "Servicios",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    cliente_id = db.add_cliente(
        cliente_info["nombre"],
        cliente_info["nrc"],
        cliente_info["nit"],
        "",
        cliente_info["descActividad"],
        "22223333",
        "cli@example.com",
        "Dir",
        "05",
        "24",
        codActividad=cliente_info["codActividad"],
        nombreComercial="Cliente",
    )
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        10,
        "123",
        "06141407100012",
        "Servicios",
        descuentos=0,
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    original_generar_dte = nota_credito_electronica.generar_dte_json

    def _generar_dte_enriquecido(*args, **kwargs):
        data = original_generar_dte(*args, **kwargs)
        receptor = data.setdefault("receptor", {})
        for key in ("nombre", "nit", "nrc", "codActividad", "descActividad"):
            if not receptor.get(key):
                receptor[key] = cliente_info.get(key)
        direccion = receptor.get("direccion") or {}
        for key, value in cliente_info["direccion"].items():
            if not direccion.get(key):
                direccion[key] = value
        receptor["direccion"] = direccion
        return data

    monkeypatch.setattr(
        "nota_credito_electronica.generar_dte_json", _generar_dte_enriquecido
    )
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
        lambda: _datos_negocio_base(),
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
    cliente_info = {
        "nombre": "Cliente",
        "nrc": "123",
        "nit": "06141407100012",
        "codActividad": "654321",
        "descActividad": "Servicios",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    cliente_id = db.add_cliente(
        cliente_info["nombre"],
        cliente_info["nrc"],
        cliente_info["nit"],
        "",
        cliente_info["descActividad"],
        "22223333",
        "cli@example.com",
        "Dir",
        "05",
        "24",
        codActividad=cliente_info["codActividad"],
        nombreComercial="Cliente",
    )
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        10,
        "123",
        "06141407100012",
        "Servicios",
        descuentos=0,
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    original_generar_dte = nota_credito_electronica.generar_dte_json

    def _generar_dte_enriquecido(*args, **kwargs):
        data = original_generar_dte(*args, **kwargs)
        receptor = data.setdefault("receptor", {})
        for key in ("nombre", "nit", "nrc", "codActividad", "descActividad"):
            if not receptor.get(key):
                receptor[key] = cliente_info.get(key)
        direccion = receptor.get("direccion") or {}
        for key, value in cliente_info["direccion"].items():
            if not direccion.get(key):
                direccion[key] = value
        receptor["direccion"] = direccion
        return data

    monkeypatch.setattr(
        "nota_credito_electronica.generar_dte_json", _generar_dte_enriquecido
    )
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
        "tipo": "03",
        "numero_control": "DTE-01-S001P001-000000000000001",
        "codigo_generacion": "123",
        "fecha": "2024-01-01",
    }
    codigo_generacion = "NC-TEST-1234567890"
    numero_control = "DTE-05-S001P001-000000000000001"
    sello = "S" * 40
    generar_nota_credito_pdf(
        venta,
        detalles,
        {},
        {},
        archivo=str(out),
        datos_negocio={},
        doc_relacionado=doc_rel,
        motivo="Devolución",
        codigo_generacion=codigo_generacion,
        numero_control=numero_control,
        fecha_generacion="01/02/2024, 12:00:00",
        sello_recepcion=sello,
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
    assert f"Sello Recepción: {sello}" in text


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
        codigo_generacion="NC-TEST-9876543210",
        numero_control="DTE-05-S001P001-000000000000002",
        fecha_generacion="02/02/2024, 09:30:00",
    )
    with fitz.open(out) as doc:
        lines = ''.join(p.get_text() for p in doc).splitlines()
    idx = next(i for i, ln in enumerate(lines) if ln.startswith('Dirección:'))
    assert 'La Libertad Centro' in lines[idx]
    assert 'Colonia El Centro con una avenida' in lines[idx]
    if not lines[idx].endswith('...'):
        assert idx + 1 < len(lines)
        assert lines[idx + 1].strip().startswith('realmente muy larga')


def test_nce_usa_plan_b(monkeypatch):
    db = create_db()
    venta_id, nota_id = _register_credit_note(db)
    payload = _build_base_payload()

    calls: list[str] = []

    def fake_prepare(**kwargs):
        assert kwargs["nota_id"] == nota_id
        assert kwargs["venta_id"] == venta_id
        calls.append("prepare")
        payload_copy = json.loads(json.dumps(payload))
        section_sources = {
            "emisor": "json",
            "receptor": "json",
            "documentoRelacionado": "json",
            "identificacion": "json",
            "resumen": "json",
            "cuerpoDocumento": "json",
        }
        expected_ident = {
            "codigoGeneracion": payload_copy["identificacion"]["codigoGeneracion"],
            "numeroControl": payload_copy["identificacion"]["numeroControl"],
        }
        return OrigenResult(
            data=payload_copy,
            section_sources=section_sources,
            source_used="json",
            snapshot=None,
            json_path="/tmp/dte_origen.json",
            json_payload=payload_copy,
            json_used=True,
            config_used=False,
            detalles={},
            venta_extra={},
            venta_credito_fiscal={},
            expected_ident=expected_ident,
        )

    prevalidate_calls: list[str] = []
    original_prevalidate = nota_credito_electronica.prevalidate_dte_origen

    def fake_prevalidate(data, **kwargs):
        prevalidate_calls.append("prevalidate")
        return original_prevalidate(data, **kwargs)

    rebuild_called: dict[str, bool] = {}

    def fake_rebuild(db_arg, result, **kwargs):
        rebuild_called["called"] = True
        assert result.source_used == "json"
        return {"rebuilt": True}

    monkeypatch.setattr(nota_credito_electronica, "prepare_dte_origen", fake_prepare)
    monkeypatch.setattr(nota_credito_electronica, "prevalidate_dte_origen", fake_prevalidate)
    monkeypatch.setattr(
        nota_credito_electronica, "rebuild_snapshot_from_json", fake_rebuild
    )

    resultado = generar_nce_desde_nota(db, nota_id, ambiente="00")

    assert "prepare" in calls
    assert prevalidate_calls
    assert rebuild_called.get("called") is True
    doc_rel = resultado["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, resultado["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, payload)
    for item in resultado["cuerpoDocumento"]:
        assert item["numeroDocumento"] == doc_rel["numeroDocumento"]
    assert resultado["identificacion"]["ambiente"] == "00"


def test_nce_restaurar_secciones_si_sanitize_elimina(monkeypatch, caplog):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
    )
    db = create_db()
    payload = _build_base_payload()

    def fake_sanitize(data, schema):
        sanitized = {k: v for k, v in data.items() if k not in {"receptor", "documentoRelacionado"}}
        return sanitized

    monkeypatch.setattr(nota_credito_electronica, "sanitize_dte_payload", fake_sanitize)
    caplog.set_level(logging.ERROR, logger=nota_credito_electronica.logger.name)

    resultado = generar_nce_desde_dte(db, payload, Decimal("1"))

    doc_rel = resultado["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, resultado["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, payload)
    for key in ("nombre", "nit", "direccion"):
        assert resultado["receptor"][key] == payload["receptor"][key]
    assert "sanitize_dte_payload eliminó secciones obligatorias" in caplog.text


def test_nce_sanitize_no_elimina_secciones():
    db = create_db()
    payload = _build_base_payload()
    payload["receptor"]["nit"] = "000868547"
    payload["receptor"]["nrc"] = "2301408"
    payload["receptor"]["codActividad"] = "46484"
    payload["receptor"]["descActividad"] = "Servicios medicos"

    resultado = generar_nce_desde_dte(db, payload, Decimal("1"))

    required = [
        "identificacion",
        "documentoRelacionado",
        "emisor",
        "receptor",
        "cuerpoDocumento",
        "resumen",
    ]
    for key in required:
        assert key in resultado
    assert resultado["documentoRelacionado"], "documentoRelacionado quedó vacío tras sanitize"

    doc_rel = resultado["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, resultado["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, payload)
    assert doc_rel["fechaEmision"] == fecha_iso(fecha_ddmmaaaa(payload["identificacion"]["fecEmi"]))

    receptor = resultado["receptor"]
    assert receptor["nit"] == "000868547"
    assert receptor["nrc"] == "2301408"
    assert receptor["codActividad"] == "46484"
    assert receptor["descActividad"] == "Servicios medicos"

    schema = catalogos.get_dte_schema("05")
    cleaned = nota_credito_electronica.sanitize_dte_payload(resultado, schema)
    for key in required:
        assert key in cleaned
    assert cleaned["documentoRelacionado"], "documentoRelacionado fue removido tras re-sanitize"


def test_nce_docrel_control_ccf(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: _datos_negocio_base(),
    )
    db = create_db()
    payload = _build_base_payload()
    resultado = generar_nce_desde_dte(db, payload, Decimal("1"))
    doc_rel = resultado["documentoRelacionado"][0]
    _assert_relacionado_y_receptor(doc_rel, resultado["receptor"])
    _assert_doc_rel_coincide_con_origen(doc_rel, payload)
    for item in resultado["cuerpoDocumento"]:
        assert item["numeroDocumento"] == doc_rel["numeroDocumento"]
        assert item["uniMedida"] == 59


def test_nce_sin_num_control_falla_prevalidacion():
    data = _build_base_payload()
    data["identificacion"].pop("numeroControl")
    with pytest.raises(ValueError, match="Falta numeroControl del DTE origen"):
        nota_credito_electronica.prevalidate_dte_origen(
            data,
            ambiente="00",
            nota_tipo="credito",
            logger=nota_credito_electronica.logger,
        )


def test_nce_no_regenera_ids(tmp_path):
    db = create_db()
    nota_id = db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (NULL, 'credito', '2024-01-05', 0, 'Test')"
    ).lastrowid
    payload = _build_base_payload()
    payload["identificacion"]["codigoGeneracion"] = (
        "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    )
    payload_copy = json.loads(json.dumps(payload))
    expected_ident = {
        "codigoGeneracion": "FFFFFFFF-1111-2222-3333-444444444444",
        "numeroControl": payload_copy["identificacion"]["numeroControl"],
    }
    origen = OrigenResult(
        data=payload_copy,
        section_sources={},
        source_used="json",
        snapshot=None,
        json_path=str(tmp_path / "respaldo.json"),
        json_payload=payload_copy,
        json_used=True,
        config_used=False,
        detalles={},
        venta_extra={},
        venta_credito_fiscal={},
        expected_ident=expected_ident,
    )
    resultado = nota_credito_electronica.rebuild_snapshot_from_json(
        db,
        origen,
        nota_id=nota_id,
        venta_id=None,
        logger=nota_credito_electronica.logger,
    )
    assert resultado["rebuilt"] is False
    assert "conflict" in resultado
    detalles_row = db.cursor.execute("SELECT detalles FROM notas WHERE id=?", (nota_id,)).fetchone()
    detalles = json.loads(detalles_row["detalles"])
    assert "snapshot_conflict" in detalles
    assert detalles["snapshot_conflict"].startswith("codigoGeneracion")
