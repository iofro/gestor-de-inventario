import fitz
from copy import deepcopy
import json
from decimal import Decimal, ROUND_HALF_UP
from db import DB
from dte import generar_dte_json
from nota_credito_electronica import generar_nce_desde_dte, generar_nce_desde_nota
import pytest
from factura_sv import generar_nota_credito_pdf
import utils.catalogos as catalogos
from utils.fecha import fecha_emision_hoy_str
from utils.snapshot import Snapshot, SnapshotNotFoundError


def create_db():
    return DB(":memory:")


@pytest.fixture(autouse=True)
def _mock_geo(monkeypatch):
    monkeypatch.setattr(
        "dte.validar_dep_muni_por_catalogo",
        lambda d, m, strict=True: (str(d).zfill(2), str(m).zfill(2)),
    )


@pytest.fixture(autouse=True)
def _disable_strict_snapshot(monkeypatch):
    monkeypatch.setattr("nota_credito_electronica.STRICT_SNAPSHOT_DEFAULT", False)


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
    venta_fecha = "2024-03-15"
    venta_id = db.add_venta(venta_fecha, 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    dte_base = generar_dte_json(db, venta_id, tipo_dte="01")
    dte_alterado = deepcopy(dte_base)
    dte_alterado["identificacion"]["fecEmi"] = "2024-03-18"

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


def test_generar_nce_desde_nota_prefiere_snapshot(monkeypatch, tmp_path):
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
    assert receptor["nrc"] is None

    doc_rel = nce["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    assert doc_rel["tipoGeneracion"] == 2
    assert (
        doc_rel["numeroDocumento"]
        == payload["identificacion"]["codigoGeneracion"].upper()
    )
    assert doc_rel["fechaEmision"] == "2023-08-01"
    today_str = fecha_emision_hoy_str()
    assert nce["identificacion"]["fecEmi"] == today_str
    assert metrics_calls == ["notes_source_used.snapshot"]
    assert payload["firma"] == "SIGNATURE"


def test_generar_nce_desde_nota_snapshot_dui(monkeypatch, tmp_path):
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
        "emisor": {"nombre": "Emisor"},
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
    assert receptor["nrc"] is None

    doc_rel = nce["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "01"
    assert doc_rel["tipoGeneracion"] == 2
    assert doc_rel["numeroDocumento"] == payload["identificacion"]["codigoGeneracion"].upper()
    assert doc_rel["fechaEmision"] == "2023-09-01"
    today_str = fecha_emision_hoy_str()
    assert nce["identificacion"]["fecEmi"] == today_str


def test_generar_nce_desde_nota_strict_snapshot(monkeypatch):
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
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
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
    expected_total = dte_origen["resumen"]["montoTotalOperacion"]
    assert expected_total == Decimal("7.96")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"))
    assert (
        data["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    assert data["resumen"]["montoTotalOperacion"] == expected_total


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
            "precio_unitario": Decimal("7.96"),
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
        "tipo": "03",
        "numero_control": "DTE-01-S001P001-000000000000001",
        "codigo_generacion": "123",
        "fecha": "2024-01-01",
    }
    codigo_generacion = "NC-TEST-1234567890"
    numero_control = "DTE-05-S001P001-000000000000001"
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
        codigo_generacion="NC-TEST-9876543210",
        numero_control="DTE-05-S001P001-000000000000002",
        fecha_generacion="02/02/2024, 09:30:00",
    )
    with fitz.open(out) as doc:
        lines = ''.join(p.get_text() for p in doc).splitlines()
    idx = next(i for i, ln in enumerate(lines) if ln.startswith('Dirección:'))
    assert 'La Libertad Centro' in lines[idx]
    assert 'Colonia El Centro con una avenida' in lines[idx]
    assert lines[idx].endswith('...')
