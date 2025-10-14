import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - skip when Qt is unavailable
    pytest.skip(f"PyQt5 no disponible: {exc}", allow_module_level=True)

import facturacion_tab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _patch_invoice_dirs(monkeypatch, base_path):
    mappings = {
        "CF_DIR": "cf",
        "CREDITO_DIR": "cfiscal",
        "TICKETS_DIR": "tickets",
        "NOTAS_DEBITO_DIR": "ndebito",
        "NOTAS_CREDITO_DIR": "ncredito",
        "NOTAS_REMISION_DIR": "nremision",
    }
    for attr, folder in mappings.items():
        target = base_path / folder
        target.mkdir(exist_ok=True)
        monkeypatch.setattr(facturacion_tab, attr, str(target))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])


def test_update_envio_estado_ui_updates_entry(tmp_path):
    db_path = tmp_path / "inventario.db"
    database = DB(db_path)
    venta_id = database.add_venta("2024-01-01", 10)
    database.registrar_envio_dte(
        venta_id,
        modo="normal",
        estado="Pendiente",
        sello="",
        respuesta_json={},
        codigo_generacion="ABC123",
        numero_control="DTE-001",
    )

    assert database.update_envio_estado_ui(venta_id=venta_id, estado_ui="Rechazado", estado_ui_tag="schema")

    row = database.cursor.execute(
        """
        SELECT estado_ui, estado_ui_tag, estado_ui_manual
        FROM dte_envios
        WHERE venta_id=?
        ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
        """,
        (venta_id,),
    ).fetchone()

    assert row["estado_ui"] == "Rechazado"
    assert row["estado_ui_tag"] == "schema"
    assert row["estado_ui_manual"] == 1
    assert database.update_envio_estado_ui(venta_id=9999, estado_ui="Aceptado")

    new_row = database.cursor.execute(
        """
        SELECT venta_id, estado_ui, modo, estado_ui_manual
        FROM dte_envios
        WHERE venta_id=?
        ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
        """,
        (9999,),
    ).fetchone()

    assert new_row["estado_ui"] == "Aceptado"
    assert new_row["venta_id"] == 9999
    assert new_row["modo"] == "manual"
    assert new_row["estado_ui_manual"] == 1


def test_manual_override_survives_envio_refresh(tmp_path):
    db_path = tmp_path / "refresh.db"
    database = DB(db_path)
    venta_id = database.add_venta("2024-02-01", 20)

    assert database.update_envio_estado_ui(
        venta_id=venta_id, estado_ui="Enviado", estado_ui_tag="manual"
    )

    manual_row = database.cursor.execute(
        """
        SELECT estado_ui, estado_ui_tag, estado_ui_manual
        FROM dte_envios
        WHERE venta_id=?
        ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
        """,
        (venta_id,),
    ).fetchone()
    assert manual_row["estado_ui"] == "Enviado"
    assert manual_row["estado_ui_tag"] == "manual"
    assert manual_row["estado_ui_manual"] == 1

    database.registrar_envio_dte(
        venta_id,
        modo="normal",
        estado="Pendiente",
        sello="",
        respuesta_json={"estado": "RECHAZADO"},
        codigo_generacion=None,
        numero_control=None,
    )

    latest = database.cursor.execute(
        """
        SELECT estado_ui, estado_ui_tag, estado_ui_manual
        FROM dte_envios
        WHERE venta_id=?
        ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
        """,
        (venta_id,),
    ).fetchone()
    assert latest["estado_ui"] == "Enviado"
    assert latest["estado_ui_tag"] == "manual"
    assert latest["estado_ui_manual"] == 1


def test_facturacion_tab_manual_envio_update(tmp_path, qt_app, monkeypatch):
    db_path = tmp_path / "manual.db"
    database = DB(db_path)
    venta_id = database.add_venta("2024-01-02", 5)
    database.registrar_envio_dte(
        venta_id,
        modo="normal",
        estado="Pendiente",
        sello="",
        respuesta_json={},
        codigo_generacion="XYZ789",
        numero_control="DTE-XYZ-001",
    )

    manager = SimpleNamespace(db=database, _clientes=[], _Distribuidores=[])
    _patch_invoice_dirs(monkeypatch, tmp_path)

    tab = facturacion_tab.FacturacionTab(manager)

    entry = {"venta_id": venta_id, "numero_control": "DTE-XYZ-001"}
    factura_info = {"venta_id": venta_id, "control": "DTE-XYZ-001"}
    factura_json = {
        "identificacion": {
            "numeroControl": "DTE-XYZ-001",
            "codigoGeneracion": "XYZ789",
        }
    }

    display = tab._update_invoice_envio_state(entry, factura_info, factura_json, "Enviado (observado)")
    assert display == "Enviado (observado)"

    row = database.cursor.execute(
        """
        SELECT estado_ui, estado_ui_tag, estado_ui_manual
        FROM dte_envios
        WHERE venta_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (venta_id,),
    ).fetchone()
    assert row["estado_ui"] == "Enviado"
    assert row["estado_ui_tag"] == "observado"
    assert row["estado_ui_manual"] == 1

    options = tab._get_available_envio_states()
    assert "Pendiente de envío" in options
    assert "Anulado" in options
    assert "Enviado (observado)" in options

    if hasattr(tab, "_refresh_timer"):
        tab._refresh_timer.stop()
    tab.deleteLater()


def test_manual_state_priority_over_newer_automatic(tmp_path, qt_app, monkeypatch):
    db_path = tmp_path / "priority.db"
    database = DB(db_path)
    venta_id = database.add_venta("2024-03-05", 30)

    assert database.update_envio_estado_ui(
        venta_id=venta_id,
        codigo_generacion="PRIORITY-123",
        numero_control="DTE-PRIORITY-001",
        estado_ui="Anulado",
        estado_ui_tag="usuario",
    )

    manual_row = database.cursor.execute(
        """
        SELECT estado_ui, estado_ui_tag, estado_ui_manual
        FROM dte_envios
        WHERE venta_id=?
        ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
        """,
        (venta_id,),
    ).fetchone()
    assert manual_row["estado_ui"] == "Anulado"
    assert manual_row["estado_ui_manual"] == 1

    database.cursor.execute(
        """
        INSERT INTO dte_envios (
            venta_id, modo, estado, sello, fecha_hora,
            respuesta, codigo_lote, codigo_generacion, numero_control,
            estado_ui, estado_ui_tag, estado_ui_manual
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            venta_id,
            "normal",
            "Procesado",
            "",
            datetime.now(timezone.utc).isoformat(),
            "{}",
            None,
            "PRIORITY-123",
            "DTE-PRIORITY-001",
            "Enviado",
            "hacienda",
            0,
        ),
    )
    database.conn.commit()

    latest = database.cursor.execute(
        """
        SELECT estado_ui, estado_ui_manual
        FROM dte_envios
        WHERE codigo_generacion=?
        ORDER BY id DESC LIMIT 1
        """,
        ("PRIORITY-123",),
    ).fetchone()
    assert latest["estado_ui"] == "Enviado"
    assert latest["estado_ui_manual"] == 0

    preferred = database.cursor.execute(
        """
        SELECT estado_ui, estado_ui_tag, estado, estado_ui_manual
        FROM dte_envios
        WHERE codigo_generacion=?
        ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
        """,
        ("PRIORITY-123",),
    ).fetchone()
    assert preferred["estado_ui"] == "Anulado"
    assert preferred["estado_ui_manual"] == 1

    manager = SimpleNamespace(db=database, _clientes=[], _Distribuidores=[])
    _patch_invoice_dirs(monkeypatch, tmp_path)
    tab = facturacion_tab.FacturacionTab(manager)

    display = tab._format_envio_state(
        preferred["estado_ui"], preferred["estado_ui_tag"], preferred["estado"]
    )
    assert display == "Anulado"

    if hasattr(tab, "_refresh_timer"):
        tab._refresh_timer.stop()
    tab.deleteLater()
