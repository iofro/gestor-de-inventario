import json
import sys
import types
from pathlib import Path

import paths


def _setup_fake_qt(monkeypatch):
    fake_pyqt = types.ModuleType("PyQt5")
    fake_qtcore = types.ModuleType("PyQt5.QtCore")
    fake_qtcore.QAbstractTableModel = object
    fake_qtcore.Qt = types.SimpleNamespace(DisplayRole=0, DecorationRole=1)
    fake_qtgui = types.ModuleType("PyQt5.QtGui")
    fake_qtgui.QColor = lambda *args, **kwargs: None
    fake_qtwidgets = types.ModuleType("PyQt5.QtWidgets")

    monkeypatch.setitem(sys.modules, "PyQt5", fake_pyqt)
    monkeypatch.setitem(sys.modules, "PyQt5.QtCore", fake_qtcore)
    monkeypatch.setitem(sys.modules, "PyQt5.QtGui", fake_qtgui)
    monkeypatch.setitem(sys.modules, "PyQt5.QtWidgets", fake_qtwidgets)


def _prepare_paths(monkeypatch, base_dir: Path):
    def fake_ensure_user_dir(*parts: str) -> Path:
        path = base_dir.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def fake_get_canonical(tipo: str) -> Path:
        return fake_ensure_user_dir(tipo.lower())

    canonical_cf = fake_get_canonical("ConsumidorFinal")
    canonical_credito = fake_get_canonical("CreditoFiscal")
    notas_credito = fake_get_canonical("NotaCredito")
    notas_debito = fake_get_canonical("NotaDebito")
    archive_cf = fake_ensure_user_dir("facturas", "consumidor_final")
    archive_credito = fake_ensure_user_dir("facturas", "credito_fiscal")
    dtes_dir = fake_ensure_user_dir("dtes")

    monkeypatch.setattr(paths, "USER_DATA_DIR", base_dir)
    monkeypatch.setattr(paths, "ensure_user_dir", fake_ensure_user_dir)
    monkeypatch.setattr(paths, "get_canonical_dte_dir", fake_get_canonical)
    monkeypatch.setattr(paths, "FACTURAS_CONSUMIDOR_FINAL_DIR", str(canonical_cf))
    monkeypatch.setattr(paths, "FACTURAS_CREDITO_FISCAL_DIR", str(canonical_credito))
    monkeypatch.setattr(paths, "FACTURAS_ARCHIVE_CF_DIR", str(archive_cf))
    monkeypatch.setattr(paths, "FACTURAS_ARCHIVE_CREDITO_DIR", str(archive_credito))
    monkeypatch.setattr(paths, "NOTAS_CREDITO_DIR", str(notas_credito))
    monkeypatch.setattr(paths, "NOTAS_DEBITO_DIR", str(notas_debito))
    monkeypatch.setattr(paths, "DTES_DIR", str(dtes_dir))
    monkeypatch.setattr(paths, "TICKETS_OUTPUT_DIR", str(fake_ensure_user_dir("tickets")))

    return {
        "credito": canonical_credito,
        "notas_credito": notas_credito,
        "notas_debito": notas_debito,
        "archive_credito": archive_credito,
        "dtes": dtes_dir,
    }


def _create_inventory_manager(monkeypatch, tmp_path, db_conn):
    _setup_fake_qt(monkeypatch)

    base_dir = tmp_path / "userdata"
    dirs = _prepare_paths(monkeypatch, base_dir)

    from inventory_manager import InventoryManager

    monkeypatch.setattr("inventory_manager.ensure_user_dir", paths.ensure_user_dir)
    monkeypatch.setattr("inventory_manager.get_canonical_dte_dir", paths.get_canonical_dte_dir)
    monkeypatch.setattr(
        "inventory_manager.FACTURAS_CREDITO_FISCAL_DIR", str(dirs["credito"])
    )
    monkeypatch.setattr(
        "inventory_manager.FACTURAS_ARCHIVE_CREDITO_DIR", str(dirs["archive_credito"])
    )
    monkeypatch.setattr("inventory_manager.NOTAS_CREDITO_DIR", str(dirs["notas_credito"]))
    monkeypatch.setattr("inventory_manager.NOTAS_DEBITO_DIR", str(dirs["notas_debito"]))
    monkeypatch.setattr("inventory_manager.DTES_DIR", str(dirs["dtes"]))

    manager = InventoryManager(db_conn)
    return manager, dirs


def _build_payload(
    *,
    tipo: str,
    fecha: str,
    numero: str,
    codigo: str,
    nombre: str,
    receptor: dict,
    resumen: dict,
    estado: str | None = "Enviado",
    sello: str | None = "S" * 40,
) -> dict:
    payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": tipo,
                "fecEmi": fecha,
                "horEmi": "10:00:00",
                "numeroControl": numero,
                "codigoGeneracion": codigo,
                "tipoOperacion": 1,
            },
            "receptor": receptor,
            "resumen": resumen,
        },
    }
    if sello:
        payload["selloRecibido"] = sello
    if estado:
        payload["respuesta"] = {"estado": estado}
    return payload


def test_get_anexo_contribuyentes_registros(monkeypatch, tmp_path, db_conn):
    manager, dirs = _create_inventory_manager(monkeypatch, tmp_path, db_conn)

    credito_dir = dirs["credito"]
    credito_dir.mkdir(parents=True, exist_ok=True)
    payload_cf = _build_payload(
        tipo="03",
        fecha="2025-10-02",
        numero="DTE-03-S001P001-000000000000123",
        codigo="CF-AAAA-1111-2222-3333-444455556666",
        nombre="Cliente Empresa",
        receptor={
            "nit": "0614-199001-101-9",
            "nrc": "1234567",
            "nombre": "Cliente Empresa",
            "tipoDocumento": "36",
            "numDocumento": "06141990011019",
        },
        resumen={
            "totalExenta": "0.00",
            "totalNoSuj": "0.00",
            "totalGravada": "100.00",
            "totalPagar": "113.00",
            "totalIva": "13.00",
        },
    )
    (credito_dir / "20251002_cf.json").write_text(json.dumps(payload_cf), encoding="utf-8")

    notas_debito_dir = dirs["notas_debito"]
    notas_debito_dir.mkdir(parents=True, exist_ok=True)
    payload_nd = _build_payload(
        tipo="05",
        fecha="2025-10-03",
        numero="DTE-05-S001P001-000000000000124",
        codigo="ND-BBBB-1111-2222-3333-444455556666",
        nombre="Persona Natural",
        receptor={
            "nombre": "Persona Natural",
            "tipoDocumento": "13",
            "numDocumento": "01234567-8",
        },
        resumen={
            "totalExenta": "5.50",
            "totalNoSuj": "0.00",
            "totalGravada": "0.00",
            "totalPagar": "5.50",
        },
        estado=None,
        sello=None,
    )
    nota_debito_path = notas_debito_dir / "20251003_nd.json"
    nota_debito_path.write_text(json.dumps(payload_nd), encoding="utf-8")
    nota_debito_path.with_suffix(".meta.json").write_text(
        json.dumps({"estadoManual": "Enviado"}), encoding="utf-8"
    )

    archive_dir = dirs["archive_credito"]
    archive_dir.mkdir(parents=True, exist_ok=True)
    payload_nc = _build_payload(
        tipo="06",
        fecha="2025-10-04",
        numero="DTE-06-S001P001-000000000000125",
        codigo="NC-CCCC-1111-2222-3333-444455556666",
        nombre="Cliente Manual",
        receptor={
            "nrc": "7654321",
            "nombre": "Cliente Manual",
            "tipoDocumento": "36",
            "numDocumento": "06141990011020",
        },
        resumen={
            "totalExenta": "0.00",
            "totalNoSuj": "2.00",
            "totalGravada": "3.00",
            "totalPagar": "5.39",
            "totalIva": "0.39",
        },
        estado="Rechazado",
    )
    nota_credito_path = archive_dir / "20251004_nc.json"
    nota_credito_path.write_text(json.dumps(payload_nc), encoding="utf-8")

    rejected_path = credito_dir / "20251005_rejected.json"
    rejected_payload = _build_payload(
        tipo="03",
        fecha="2025-10-05",
        numero="DTE-03-S001P001-000000000000126",
        codigo="CF-RECH-1111-2222-3333-444455556666",
        nombre="Rechazado",
        receptor={"nombre": "Rechazado", "tipoDocumento": "36", "numDocumento": "06141990011030"},
        resumen={"totalGravada": "10.00", "totalPagar": "11.30", "totalIva": "1.30"},
        estado="Pendiente",
    )
    rejected_path.write_text(json.dumps(rejected_payload), encoding="utf-8")
    rejected_path.with_suffix(".meta.json").write_text(
        json.dumps({"estadoManual": "Anulado"}), encoding="utf-8"
    )

    duplicate_path = dirs["dtes"] / "fcf" / "20251002_duplicate.json"
    duplicate_path.parent.mkdir(parents=True, exist_ok=True)
    duplicate_path.write_text(json.dumps(payload_cf), encoding="utf-8")

    other_period_payload = _build_payload(
        tipo="03",
        fecha="2025-09-30",
        numero="DTE-03-S001P001-000000000000200",
        codigo="CF-OLD-1111-2222-3333-444455556666",
        nombre="Otro",
        receptor={"nombre": "Otro", "tipoDocumento": "36", "numDocumento": "06141990011040"},
        resumen={"totalGravada": "1.00", "totalPagar": "1.13", "totalIva": "0.13"},
    )
    (dirs["credito"] / "20250930_old.json").write_text(
        json.dumps(other_period_payload), encoding="utf-8"
    )

    db_conn.cursor.execute("DROP TABLE IF EXISTS dte_envios")
    db_conn.cursor.execute(
        """
        CREATE TABLE dte_envios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_generacion TEXT,
            numero_control TEXT,
            estado_ui TEXT,
            estado_ui_tag TEXT,
            estado_ui_manual INTEGER DEFAULT 0
        )
        """
    )
    db_conn.cursor.execute(
        """
        INSERT INTO dte_envios (codigo_generacion, numero_control, estado_ui, estado_ui_tag, estado_ui_manual)
        VALUES (?, ?, ?, ?, 1)
        """,
        (
            "NC-CCCC-1111-2222-3333-444455556666",
            "DTE-06-S001P001-000000000000125",
            "Aceptado",
            "aceptado",
        ),
    )
    db_conn.conn.commit()

    registros = manager.get_anexo_contribuyentes_registros("202510")
    codigos = [registro.codigo_generacion for registro in registros]

    assert codigos == [
        "CF-AAAA-1111-2222-3333-444455556666",
        "ND-BBBB-1111-2222-3333-444455556666",
        "NC-CCCC-1111-2222-3333-444455556666",
    ]

    registros_map = {registro.codigo_generacion: registro for registro in registros}

    cf_registro = registros_map["CF-AAAA-1111-2222-3333-444455556666"]
    assert cf_registro.identificacion == "06141990011019"
    assert cf_registro.dui is None
    assert cf_registro.estado == "Enviado"
    assert cf_registro.total_ventas == "113.00"

    nd_registro = registros_map["ND-BBBB-1111-2222-3333-444455556666"]
    assert nd_registro.identificacion is None
    assert nd_registro.dui == "012345678"
    assert nd_registro.estado_manual == "Enviado"
    assert nd_registro.estado_fuente.startswith("meta:")
    assert nd_registro.sello_recepcion is None

    nc_registro = registros_map["NC-CCCC-1111-2222-3333-444455556666"]
    assert nc_registro.estado_manual == "Aceptado"
    assert nc_registro.estado_fuente == "db"
    assert nc_registro.total_ventas == "5.39"

    assert manager.get_anexo_contribuyentes_registros("202511") == []
