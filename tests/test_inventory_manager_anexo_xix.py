import json
import uuid
from pathlib import Path

import paths
from declaracion.anexo_xix import DTEAnulado


def _build_event_payload(*, evento_codigo: str, dte_codigo: str, numero_control: str, sello: str, fecha: str, tipo_anulacion: int, tipo_dte: str) -> dict:
    return {
        "identificacion": {
            "codigoGeneracion": evento_codigo,
            "fecAnula": fecha,
        },
        "documento": {
            "codigoGeneracion": dte_codigo,
            "numeroControl": numero_control,
            "selloRecibido": sello,
            "tipoDte": tipo_dte,
        },
        "motivo": {
            "tipoAnulacion": tipo_anulacion,
        },
    }


def _write_event(base_dir: Path, payload: dict, metadata: dict) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    with (base_dir / "documento.json").open("w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    with (base_dir / "metadata.json").open("w", encoding="utf-8") as fh:
        json.dump(metadata, fh)


def test_get_anexo_xix_registros_filters_by_period(monkeypatch, tmp_path, db_conn):
    import sys
    import types

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

    from inventory_manager import InventoryManager
    user_dir = tmp_path / "userdata"
    monkeypatch.setattr(paths, "USER_DATA_DIR", user_dir)
    monkeypatch.setattr(paths, "DTES_DIR", str(user_dir / "dtes"))

    def fake_ensure_user_dir(*parts: str) -> Path:
        path = user_dir.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(paths, "ensure_user_dir", fake_ensure_user_dir)
    monkeypatch.setattr("inventory_manager.ensure_user_dir", fake_ensure_user_dir)

    base_anulaciones = fake_ensure_user_dir("dtes", "actualizaciones", "anulacion")
    event_code = str(uuid.uuid4()).upper()
    dte_code = str(uuid.uuid4()).upper()
    numero_control = "DTE-01-S001P001-000000000000111"
    sello = "A" * 40
    payload = _build_event_payload(
        evento_codigo=event_code,
        dte_codigo=dte_code,
        numero_control=numero_control,
        sello=sello,
        fecha="2025-10-04",
        tipo_anulacion=2,
        tipo_dte="01",
    )
    metadata = {
        "respuesta": {"estado": "Aceptado"},
        "documento": {
            "codigoGeneracion": dte_code,
            "numeroControl": numero_control,
            "selloRecibido": sello,
            "tipoDte": "01",
        },
    }
    _write_event(base_anulaciones / event_code, payload, metadata)

    other_event = str(uuid.uuid4()).upper()
    other_payload = _build_event_payload(
        evento_codigo=other_event,
        dte_codigo=str(uuid.uuid4()).upper(),
        numero_control="DTE-01-S001P001-000000000000222",
        sello="B" * 40,
        fecha="2025-09-15",
        tipo_anulacion=3,
        tipo_dte="01",
    )
    other_metadata = {"respuesta": {"estado": "Procesado"}}
    _write_event(base_anulaciones / other_event, other_payload, other_metadata)

    rejected_event = str(uuid.uuid4()).upper()
    rejected_payload = _build_event_payload(
        evento_codigo=rejected_event,
        dte_codigo=str(uuid.uuid4()).upper(),
        numero_control="DTE-01-S001P001-000000000000333",
        sello="C" * 40,
        fecha="2025-10-10",
        tipo_anulacion=1,
        tipo_dte="01",
    )
    rejected_metadata = {"respuesta": {"estado": "Rechazado"}}
    _write_event(base_anulaciones / rejected_event, rejected_payload, rejected_metadata)

    manager = InventoryManager(db_conn)
    registros = manager.get_anexo_xix_registros("202510")

    assert registros == [
        DTEAnulado(
            numero_control=numero_control,
            tipo_documento="01",
            sello_recepcion=sello,
            codigo_generacion=dte_code,
            estado="A",
        )
    ]

    assert manager.get_anexo_xix_registros("202509") == [
        DTEAnulado(
            numero_control="DTE-01-S001P001-000000000000222",
            tipo_documento="01",
            sello_recepcion="B" * 40,
            codigo_generacion=other_payload["documento"]["codigoGeneracion"],
            estado="X",
        )
    ]

