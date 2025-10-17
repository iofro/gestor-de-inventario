from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import paths
from declaracion.anexo_consumidor_final import VentaCF, on_click_generar_consumidor_final


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
        if tipo == "ConsumidorFinal":
            return fake_ensure_user_dir("facturas_consumidor_final")
        return fake_ensure_user_dir(tipo)

    canonical_cf = fake_get_canonical("ConsumidorFinal")
    archive_cf = fake_ensure_user_dir("facturas", "consumidor_final")
    tickets_dir = fake_ensure_user_dir("tickets")
    dtes_dir = fake_ensure_user_dir("dtes")

    monkeypatch.setattr(paths, "USER_DATA_DIR", base_dir)
    monkeypatch.setattr(paths, "ensure_user_dir", fake_ensure_user_dir)
    monkeypatch.setattr(paths, "DTES_DIR", str(dtes_dir))
    monkeypatch.setattr(paths, "TICKETS_OUTPUT_DIR", str(tickets_dir))
    monkeypatch.setattr(paths, "FACTURAS_CONSUMIDOR_FINAL_DIR", str(canonical_cf))
    monkeypatch.setattr(paths, "FACTURAS_ARCHIVE_CF_DIR", str(archive_cf))
    monkeypatch.setattr(paths, "get_canonical_dte_dir", fake_get_canonical)

    return fake_ensure_user_dir, fake_get_canonical, {
        "canonical_cf": canonical_cf,
        "archive_cf": archive_cf,
        "tickets": tickets_dir,
        "dtes": dtes_dir,
    }


def _create_inventory_manager(monkeypatch, tmp_path, db_conn):
    _setup_fake_qt(monkeypatch)

    base_dir = tmp_path / "userdata"
    fake_ensure_user_dir, fake_get_canonical, dirs = _prepare_paths(monkeypatch, base_dir)

    from inventory_manager import InventoryManager  # patched PyQt & paths in place

    monkeypatch.setattr("inventory_manager.ensure_user_dir", fake_ensure_user_dir)
    monkeypatch.setattr("inventory_manager.get_canonical_dte_dir", fake_get_canonical)
    monkeypatch.setattr(
        "inventory_manager.FACTURAS_CONSUMIDOR_FINAL_DIR", str(dirs["canonical_cf"])
    )
    monkeypatch.setattr(
        "inventory_manager.FACTURAS_ARCHIVE_CF_DIR", str(dirs["archive_cf"])
    )
    monkeypatch.setattr("inventory_manager.TICKETS_OUTPUT_DIR", str(dirs["tickets"]))
    monkeypatch.setattr("inventory_manager.DTES_DIR", str(dirs["dtes"]))

    manager = InventoryManager(db_conn)
    return manager, dirs


def test_get_anexo_consumidor_final_registros_reads_json(monkeypatch, tmp_path, db_conn):
    manager, dirs = _create_inventory_manager(monkeypatch, tmp_path, db_conn)

    cf_dir = dirs["canonical_cf"]
    payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-10-02",
                "horEmi": "13:45:30",
                "numeroControl": "DTE-01-S001P001-000000000000789",
                "codigoGeneracion": "ABCDEF12-3456-7890-ABCD-EF1234567890",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "2.00",
                "totalNoGravado": "0.50",
                "totalNoSuj": "0.50",
                "totalGravada": "10.00",
                "totalPagar": "13.00",
            },
        },
        "selloRecibido": "A" * 40,
        "respuesta": {"estado": "Enviado"},
    }

    json_path = cf_dir / "20251002_cliente_DTE-01.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    enviado_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-10-02",
                "horEmi": "07:30:00",
                "numeroControl": "DTE-01-S001P001-000000000000456",
                "codigoGeneracion": "EEEFFF00-1111-2222-3333-444455556666",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "0.25",
                "totalNoGravado": "0.25",
                "totalNoSuj": "0.25",
                "totalGravada": "5.00",
                "totalPagar": "5.75",
            },
        },
        "respuesta": {"estado": "Enviado"},
    }

    enviado_json = cf_dir / "20251002_cliente_envio.json"
    enviado_json.write_text(json.dumps(enviado_payload), encoding="utf-8")

    backup_dir = cf_dir / "copia de seguridad"
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / json_path.name).write_text(json.dumps(payload), encoding="utf-8")

    archive_dir = dirs["archive_cf"]
    archive_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "02",
                "fecEmi": "2025-10-01",
                "horEmi": "09:00:00",
                "numeroControl": "ARCHIVE-CF-0001",
                "codigoGeneracion": "B1B1B1B1-0000-1111-2222-333344445555",
                "tipoOperacion": 2,
            },
            "resumen": {
                "totalExenta": "1.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "5.00",
                "totalPagar": "6.00",
                "tipoIngreso": "2",
            },
        },
        "respuesta": {"estado": "Enviado"},
    }

    archive_json = archive_dir / "20251001_archive.json"
    archive_json.write_text(json.dumps(archive_payload), encoding="utf-8")

    tickets_dir = dirs["tickets"] / "consumidor_final"
    tickets_dir.mkdir(parents=True, exist_ok=True)
    ticket_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "10",
                "fecEmi": "2025-10-03",
                "horEmi": "08:00",
                "numeroControl": "TICKET-CF-0001",
                "codigoGeneracion": "C1C1C1C1-AAAA-BBBB-CCCC-DDDDEEEEFFFF",
                "tipoOperacion": 3,
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "20.00",
                "totalPagar": "20.00",
            },
        },
        "selloRecibido": "C" * 40,
        "respuesta": {"estado": "Enviado"},
    }

    ticket_json = tickets_dir / "20251003_ticket.json"
    ticket_json.write_text(json.dumps(ticket_payload), encoding="utf-8")

    dtes_dir = dirs["dtes"]
    dtes_fcf_dir = dtes_dir / "fcf"
    dtes_fcf_dir.mkdir(parents=True, exist_ok=True)
    dtes_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "11",
                "fecEmi": "2025-10-04",
                "horEmi": "10:30:15",
                "numeroControl": "DTES-CF-0001",
                "codigoGeneracion": "D1D1D1D1-AAAA-BBBB-CCCC-111122223333",
                "tipoOperacion": 4,
            },
            "resumen": {
                "totalExenta": "0.50",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.50",
                "totalGravada": "15.00",
                "totalPagar": "16.00",
            },
        },
        "respuesta": {"estado": "Enviado"},
    }

    dtes_json = dtes_fcf_dir / "20251004_dtes.json"
    dtes_json.write_text(json.dumps(dtes_payload), encoding="utf-8")

    anulado_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-10-06",
                "horEmi": "09:00:00",
                "numeroControl": "ANULADO-MANUAL-0001",
                "codigoGeneracion": "0A0A0A0A-1111-2222-3333-444455556666",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "3.00",
                "totalPagar": "3.00",
            },
        },
        "respuesta": {"estado": "recibido"},
    }

    anulado_json = cf_dir / "20251006_anulado.json"
    anulado_json.write_text(json.dumps(anulado_payload), encoding="utf-8")
    anulado_meta = anulado_json.with_suffix(".meta.json")
    anulado_meta.write_text(
        json.dumps({"estadoManual": "Anulado", "anulado": True}),
        encoding="utf-8",
    )

    meta_only_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-10-06",
                "horEmi": "09:30:00",
                "numeroControl": "ANULADO-META-0002",
                "codigoGeneracion": "0B0B0B0B-1111-2222-3333-444455556666",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "4.00",
                "totalPagar": "4.00",
            },
        },
        "respuesta": {"estado": "procesado"},
    }

    meta_only_json = cf_dir / "20251006_anulado_meta_only.json"
    meta_only_json.write_text(json.dumps(meta_only_payload), encoding="utf-8")
    meta_only_meta = meta_only_json.with_suffix(".meta.json")
    meta_only_meta.write_text(json.dumps({"anulado": True}), encoding="utf-8")

    duplicate_json = dtes_dir / "20251003_ticket_duplicate.json"
    duplicate_json.write_text(json.dumps(ticket_payload), encoding="utf-8")

    other_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-09-30",
                "codigoGeneracion": "FF001122-3344-5566-7788-99AABBCCDDEE",
            }
        },
        "selloRecibido": "B" * 40,
        "respuesta": {"estado": "enviado"},
    }
    (cf_dir / "20250930_old.json").write_text(json.dumps(other_payload), encoding="utf-8")

    manual_meta_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-10-05",
                "horEmi": "06:30:00",
                "numeroControl": "MANUAL-META-0001",
                "codigoGeneracion": "E1E1E1E1-AAAA-BBBB-CCCC-777788889999",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "8.00",
                "totalPagar": "8.00",
            },
        },
    }

    manual_meta_json = cf_dir / "20251005_manual_meta.json"
    manual_meta_json.write_text(json.dumps(manual_meta_payload), encoding="utf-8")
    manual_meta_file = manual_meta_json.with_suffix(".meta.json")
    manual_meta_file.write_text(json.dumps({"estadoManual": "Enviado"}), encoding="utf-8")

    db_manual_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-10-05",
                "horEmi": "12:30:00",
                "numeroControl": "MANUAL-DB-0002",
                "codigoGeneracion": "F1F1F1F1-AAAA-BBBB-CCCC-000011112222",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "12.00",
                "totalPagar": "12.00",
            },
        },
    }

    db_manual_json = cf_dir / "20251005_manual_db.json"
    db_manual_json.write_text(json.dumps(db_manual_payload), encoding="utf-8")

    credito_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "03",
                "fecEmi": "2025-10-07",
                "horEmi": "09:00:00",
                "numeroControl": "CF-0003",
                "codigoGeneracion": "G1G1G1G1-AAAA-BBBB-CCCC-333344445555",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "18.00",
                "totalPagar": "18.00",
            },
        },
        "respuesta": {"estado": "Aceptado"},
    }

    credito_json = cf_dir / "20251007_credito_fiscal.json"
    credito_json.write_text(json.dumps(credito_payload), encoding="utf-8")

    nota_debito_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "05",
                "fecEmi": "2025-10-08",
                "horEmi": "14:00:00",
                "numeroControl": "ND-0005",
                "codigoGeneracion": "H1H1H1H1-AAAA-BBBB-CCCC-555566667777",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "9.50",
                "totalPagar": "9.50",
            },
        },
        "respuesta": {"estado": "Enviado"},
    }

    nota_debito_json = cf_dir / "20251008_nota_debito.json"
    nota_debito_json.write_text(json.dumps(nota_debito_payload), encoding="utf-8")

    nota_credito_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "06",
                "fecEmi": "2025-10-09",
                "horEmi": "11:15:00",
                "numeroControl": "NC-0006",
                "codigoGeneracion": "I1I1I1I1-AAAA-BBBB-CCCC-999900001111",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "-4.00",
                "totalPagar": "-4.00",
            },
        },
        "respuesta": {"estado": "procesado"},
    }

    nota_credito_json = cf_dir / "20251009_nota_credito.json"
    nota_credito_json.write_text(json.dumps(nota_credito_payload), encoding="utf-8")

    db_conn.cursor.execute("DROP TABLE IF EXISTS dte_envios")
    db_conn.cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dte_envios (
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
        INSERT INTO dte_envios (
            codigo_generacion, numero_control, estado_ui, estado_ui_tag, estado_ui_manual
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            "F1F1F1F1-AAAA-BBBB-CCCC-000011112222",
            "MANUAL-DB-0002",
            "Aceptado",
            "aceptado",
            1,
        ),
    )
    db_conn.conn.commit()

    registros_octubre = manager.get_anexo_consumidor_final_registros("202510")
    assert [r.numero_doc_del for r in registros_octubre] == [
        "B1B1B1B1-0000-1111-2222-333344445555",
        "EEEFFF00-1111-2222-3333-444455556666",
        "ABCDEF12-3456-7890-ABCD-EF1234567890",
        "C1C1C1C1-AAAA-BBBB-CCCC-DDDDEEEEFFFF",
        "D1D1D1D1-AAAA-BBBB-CCCC-111122223333",
        "E1E1E1E1-AAAA-BBBB-CCCC-777788889999",
        "F1F1F1F1-AAAA-BBBB-CCCC-000011112222",
    ]

    registros_map = {registro.numero_doc_del: registro for registro in registros_octubre}

    assert "0A0A0A0A-1111-2222-3333-444455556666" not in registros_map
    assert "0B0B0B0B-1111-2222-3333-444455556666" not in registros_map

    registro_enviado = registros_map["EEEFFF00-1111-2222-3333-444455556666"]
    assert registro_enviado.fecha == "02/10/2025"
    assert registro_enviado.ventas_gravadas_locales == "5.00"
    assert registro_enviado.total_ventas == "5.75"

    registro = registros_map["ABCDEF12-3456-7890-ABCD-EF1234567890"]
    assert registro.fecha == "02/10/2025"
    assert registro.tipo == "01"
    assert registro.ventas_gravadas_locales == "10.00"
    assert registro.ventas_exentas == "2.00"
    assert registro.internas_exentas_ns == "0.50"
    assert registro.ventas_no_sujetas == "0.50"
    assert registro.total_ventas == "13.00"
    assert registro.tipo_operacion == "1"
    assert registro.tipo_ingreso == "0"
    assert Path(registro.json_path) == json_path

    registro_archive = registros_map["B1B1B1B1-0000-1111-2222-333344445555"]
    assert registro_archive.fecha == "01/10/2025"
    assert registro_archive.tipo == "02"
    assert registro_archive.total_ventas == "6.00"
    assert registro_archive.tipo_ingreso == "2"
    assert Path(registro_archive.json_path) == archive_json

    registro_ticket = registros_map["C1C1C1C1-AAAA-BBBB-CCCC-DDDDEEEEFFFF"]
    assert registro_ticket.tipo == "10"
    assert registro_ticket.total_ventas == "20.00"
    assert Path(registro_ticket.json_path) == ticket_json

    registro_dtes = registros_map["D1D1D1D1-AAAA-BBBB-CCCC-111122223333"]
    assert registro_dtes.tipo == "11"
    assert registro_dtes.total_ventas == "16.00"
    assert Path(registro_dtes.json_path) == dtes_json

    registro_manual_meta = registros_map["E1E1E1E1-AAAA-BBBB-CCCC-777788889999"]
    assert registro_manual_meta.total_ventas == "8.00"
    assert getattr(registro_manual_meta, "estado_manual", None) == "Enviado"
    assert getattr(registro_manual_meta, "estado", None) == "Enviado"
    assert Path(registro_manual_meta.json_path) == manual_meta_json

    registro_manual_db = registros_map["F1F1F1F1-AAAA-BBBB-CCCC-000011112222"]
    assert registro_manual_db.total_ventas == "12.00"
    assert getattr(registro_manual_db, "estado_manual", None) == "Aceptado"
    assert getattr(registro_manual_db, "estado", None) == "Aceptado"
    assert Path(registro_manual_db.json_path) == db_manual_json

    assert "G1G1G1G1-AAAA-BBBB-CCCC-333344445555" not in registros_map
    assert "H1H1H1H1-AAAA-BBBB-CCCC-555566667777" not in registros_map
    assert "I1I1I1I1-AAAA-BBBB-CCCC-999900001111" not in registros_map

    registros_septiembre = manager.get_anexo_consumidor_final_registros("202509")
    assert len(registros_septiembre) == 1
    sept = registros_septiembre[0]
    assert sept.numero_doc_del == "FF001122-3344-5566-7788-99AABBCCDDEE"
    assert sept.total_ventas == "0.00"


def test_get_anexo_consumidor_final_registros_accepts_weird_hour(
    monkeypatch, tmp_path, db_conn
):
    manager, dirs = _create_inventory_manager(monkeypatch, tmp_path, db_conn)

    cf_dir = dirs["canonical_cf"]
    payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-10-02",
                "horEmi": "07.30.00",
                "numeroControl": "DTE-01-S001P001-000000000000999",
                "codigoGeneracion": "ABC12345-6789-4321-BCDE-FEDCBA987654",
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "4.00",
                "totalPagar": "4.00",
            },
        },
        "selloRecibido": "D" * 40,
        "respuesta": {"estado": "Enviado"},
    }

    json_path = cf_dir / "20251002_weird_time.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    registros = manager.get_anexo_consumidor_final_registros("202510")
    assert len(registros) == 1
    registro = registros[0]
    assert registro.numero_doc_del == "ABC12345-6789-4321-BCDE-FEDCBA987654"
    assert registro.total_ventas == "4.00"
    assert registro.fecha == "02/10/2025"


def test_get_anexo_consumidor_final_registros_accepts_manual_variants(
    monkeypatch, tmp_path, db_conn
):
    manager, dirs = _create_inventory_manager(monkeypatch, tmp_path, db_conn)

    cf_dir = dirs["canonical_cf"]

    meta_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-10-05",
                "horEmi": "09:15:00",
                "numeroControl": "MANUAL-META-0001",
                "codigoGeneracion": "ACCEPT-META-1111-2222-3333-444455556666",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "5.00",
                "totalPagar": "5.00",
            },
        },
        "respuesta": {"estado": "Pendiente"},
    }

    meta_json = cf_dir / "20251005_manual_meta.json"
    meta_json.write_text(json.dumps(meta_payload), encoding="utf-8")
    meta_json.with_suffix(".meta.json").write_text(
        json.dumps({"estadoManual": "Aceptado Manual"}),
        encoding="utf-8",
    )

    db_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-10-06",
                "horEmi": "08:00:00",
                "numeroControl": "MANUAL-DB-0001",
                "codigoGeneracion": "ACCEPT-DB-AAAA-BBBB-CCCC-DDDDEEEEFFFF",
                "tipoOperacion": 1,
            },
            "resumen": {
                "totalExenta": "0.00",
                "totalNoGravado": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "7.00",
                "totalPagar": "7.00",
            },
        },
        "respuesta": {"estado": "Pendiente"},
    }

    db_json = cf_dir / "20251006_manual_db.json"
    db_json.write_text(json.dumps(db_payload), encoding="utf-8")

    db_conn.cursor.execute("DROP TABLE IF EXISTS dte_envios")
    db_conn.cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dte_envios (
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
        INSERT INTO dte_envios (
            codigo_generacion, numero_control, estado_ui, estado_ui_tag, estado_ui_manual
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            "ACCEPT-DB-AAAA-BBBB-CCCC-DDDDEEEEFFFF",
            "MANUAL-DB-0001",
            "Enviado Manual",
            "enviado-manual",
            1,
        ),
    )
    db_conn.conn.commit()

    registros = manager.get_anexo_consumidor_final_registros("202510")
    assert [r.numero_doc_del for r in registros] == [
        "ACCEPT-META-1111-2222-3333-444455556666",
        "ACCEPT-DB-AAAA-BBBB-CCCC-DDDDEEEEFFFF",
    ]

    registros_map = {registro.numero_doc_del: registro for registro in registros}

    meta_registro = registros_map["ACCEPT-META-1111-2222-3333-444455556666"]
    assert getattr(meta_registro, "estado_manual", None) == "Aceptado Manual"
    assert getattr(meta_registro, "estado", None) == "Aceptado Manual"

    db_registro = registros_map["ACCEPT-DB-AAAA-BBBB-CCCC-DDDDEEEEFFFF"]
    assert getattr(db_registro, "estado_manual", None) == "Enviado Manual"
    assert getattr(db_registro, "estado", None) == "Enviado Manual"


def test_get_anexo_consumidor_final_registros_prioritizes_manual_state(
    monkeypatch, tmp_path, db_conn
):
    manager, dirs = _create_inventory_manager(monkeypatch, tmp_path, db_conn)

    cf_dir = dirs["canonical_cf"]

    manual_accept_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-11-01",
                "horEmi": "08:00:00",
                "numeroControl": "MANUAL-OK-0001",
                "codigoGeneracion": "MANUAL-OK-1111-2222-3333-444455556666",
            },
            "resumen": {"totalGravada": "5.00", "totalPagar": "5.00"},
        },
        "respuesta": {"estado": "Rechazado"},
    }

    manual_accept_json = cf_dir / "20251101_manual_accept.json"
    manual_accept_json.write_text(json.dumps(manual_accept_payload), encoding="utf-8")
    manual_accept_json.with_suffix(".meta.json").write_text(
        json.dumps({"estadoManual": "Aceptado"}),
        encoding="utf-8",
    )

    manual_reject_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-11-02",
                "horEmi": "09:00:00",
                "numeroControl": "MANUAL-BAD-0001",
                "codigoGeneracion": "MANUAL-BAD-AAAA-BBBB-CCCC-DDDDEEEEFFFF",
            },
            "resumen": {"totalGravada": "6.00", "totalPagar": "6.00"},
        },
        "respuesta": {"estado": "Aceptado"},
    }

    manual_reject_json = cf_dir / "20251102_manual_reject.json"
    manual_reject_json.write_text(json.dumps(manual_reject_payload), encoding="utf-8")
    manual_reject_json.with_suffix(".meta.json").write_text(
        json.dumps({"estadoManual": "Rechazado"}),
        encoding="utf-8",
    )

    automatic_payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "01",
                "fecEmi": "2025-11-03",
                "horEmi": "10:00:00",
                "numeroControl": "AUTO-OK-0001",
                "codigoGeneracion": "AUTO-OK-1111-AAAA-BBBB-CCCCDDDDEEEE",
            },
            "resumen": {"totalGravada": "7.00", "totalPagar": "7.00"},
        },
        "respuesta": {"estado": "Enviado"},
    }

    auto_json = cf_dir / "20251103_auto.json"
    auto_json.write_text(json.dumps(automatic_payload), encoding="utf-8")

    registros = manager.get_anexo_consumidor_final_registros("202511")
    codigos = [registro.numero_doc_del for registro in registros]

    assert codigos == [
        "MANUAL-OK-1111-2222-3333-444455556666",
        "AUTO-OK-1111-AAAA-BBBB-CCCCDDDDEEEE",
    ]

    registros_map = {registro.numero_doc_del: registro for registro in registros}
    assert registros_map["MANUAL-OK-1111-2222-3333-444455556666"].tipo == "01"
    assert registros_map["AUTO-OK-1111-AAAA-BBBB-CCCCDDDDEEEE"].tipo == "01"


def test_on_click_generar_consumidor_final_requires_registros(tmp_path):
    resultado = on_click_generar_consumidor_final(str(tmp_path), "202510", [])
    assert resultado["success"] is False
    assert "No hay ventas" in resultado["message"]


def test_on_click_generar_consumidor_final_reports_count(tmp_path):
    registro = VentaCF(
        fecha="01/10/2025",
        clase="4",
        tipo="01",
        numero_doc_del="ABCDEF12-3456-7890-ABCD-EF1234567890",
        numero_doc_al="ABCDEF12-3456-7890-ABCD-EF1234567890",
        ventas_gravadas_locales="10.00",
        total_ventas="10.00",
        tipo_operacion="1",
        tipo_ingreso="0",
    )

    resultado = on_click_generar_consumidor_final(
        str(tmp_path),
        "202510",
        [registro],
    )

    assert resultado["success"] is True
    assert resultado.get("count") == 1
    assert "1 DTE" in resultado["message"]
    csv_path = resultado["paths"]["csv"]
    xlsx_path = resultado["paths"]["xlsx"]
    assert csv_path.exists()
    assert xlsx_path.exists()
