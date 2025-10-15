import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest


qt_module = types.ModuleType("PyQt5")
qtwidgets = types.ModuleType("PyQt5.QtWidgets")
qtcore = types.ModuleType("PyQt5.QtCore")
qtgui = types.ModuleType("PyQt5.QtGui")
dialogs_pkg = types.ModuleType("dialogs")
dialogs_pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "dialogs")]
anular_stub = types.ModuleType("dialogs.anular_factura_dialog")
anular_stub.AnularFacturaDialog = type("AnularFacturaDialog", (), {})


class _Base:
    def __init__(self, *args, **kwargs):
        pass


class _Button:
    def __init__(self, *args, **kwargs):
        pass

    def setText(self, *args, **kwargs):
        pass

    def setEnabled(self, *args, **kwargs):
        pass

    def clicked(self, *args, **kwargs):
        class _Signal:
            def connect(self, *a, **k):
                pass

        return _Signal()


class _DialogButtonBox(_Base):
    Ok = 1
    Cancel = 2
    ActionRole = 3

    def button(self, *args, **kwargs):
        return _Button()

    def addButton(self, *args, **kwargs):
        return _Button()

    def accepted(self):
        class _Signal:
            def connect(self, *a, **k):
                pass

        return _Signal()


for name in [
    "QDialog",
    "QTableWidget",
    "QTableWidgetItem",
    "QLabel",
    "QHeaderView",
    "QAbstractItemView",
    "QMessageBox",
    "QComboBox",
    "QFormLayout",
    "QPushButton",
    "QTabWidget",
    "QWidget",
    "QTreeWidget",
    "QTreeWidgetItem",
]:
    setattr(qtwidgets, name, type(name, (_Base,), {}))

qtwidgets.QDialogButtonBox = _DialogButtonBox
qtwidgets.QAbstractItemView.NoSelection = 0
qtwidgets.QAbstractItemView.NoEditTriggers = 1
qtwidgets.QHeaderView.ResizeToContents = 0
qtwidgets.QHeaderView.Stretch = 1


class _TreeWidgetItem(_Base):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._children = []

    def addChild(self, item):
        self._children.append(item)

    def childCount(self):
        return len(self._children)


class _TreeHeader:
    def setSectionResizeMode(self, *args, **kwargs):
        pass


class _TreeWidget(_Base):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._root = _TreeWidgetItem()

    def setColumnCount(self, *args, **kwargs):
        pass

    def setHeaderLabels(self, *args, **kwargs):
        pass

    def header(self):
        return _TreeHeader()

    def setAlternatingRowColors(self, *args, **kwargs):
        pass

    def setUniformRowHeights(self, *args, **kwargs):
        pass

    def setSelectionMode(self, *args, **kwargs):
        pass

    def setEditTriggers(self, *args, **kwargs):
        pass

    def setFocusPolicy(self, *args, **kwargs):
        pass

    def invisibleRootItem(self):
        return self._root

    def topLevelItemCount(self):
        return len(self._root._children)

    def expandToDepth(self, *args, **kwargs):
        pass


qtwidgets.QTreeWidgetItem = _TreeWidgetItem
qtwidgets.QTreeWidget = _TreeWidget


class _VBoxLayout(_Base):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def addWidget(self, *args, **kwargs):
        pass

    def addLayout(self, *args, **kwargs):
        pass

    def addStretch(self, *args, **kwargs):
        pass

    def setContentsMargins(self, *args, **kwargs):
        pass

    def setSpacing(self, *args, **kwargs):
        pass


qtwidgets.QVBoxLayout = _VBoxLayout


class _Qt:
    KeepAspectRatio = 0
    SmoothTransformation = 0
    NoFocus = 0


class _QUrl:
    @staticmethod
    def fromLocalFile(path):
        return path


class _QDesktopServices:
    @staticmethod
    def openUrl(*args, **kwargs):
        pass


qtcore.Qt = _Qt()
qtcore.QUrl = _QUrl
qtgui.QDesktopServices = _QDesktopServices

sys.modules["PyQt5"] = qt_module
sys.modules["PyQt5.QtWidgets"] = qtwidgets
sys.modules["PyQt5.QtCore"] = qtcore
sys.modules["PyQt5.QtGui"] = qtgui
sys.modules["dialogs"] = dialogs_pkg
sys.modules["dialogs.anular_factura_dialog"] = anular_stub

MODULE_PATH = Path(__file__).resolve().parents[1] / "dialogs" / "invoice_detail_dialog.py"
spec = importlib.util.spec_from_file_location("invoice_detail_dialog_module", MODULE_PATH)
invoice_detail_dialog = importlib.util.module_from_spec(spec)
invoice_detail_dialog.__package__ = "dialogs"
assert spec.loader is not None
spec.loader.exec_module(invoice_detail_dialog)
sys.modules["dialogs.invoice_detail_dialog"] = invoice_detail_dialog
setattr(dialogs_pkg, "invoice_detail_dialog", invoice_detail_dialog)
InvoiceDetailDialog = invoice_detail_dialog.InvoiceDetailDialog
normalize_items = invoice_detail_dialog._normalize_invoice_items
normalize_summary = invoice_detail_dialog._normalize_invoice_summary


def _make_dialog():
    dialog = InvoiceDetailDialog.__new__(InvoiceDetailDialog)
    dialog.factura = {}
    dialog.numero_control = None
    dialog.venta_id = None
    dialog._pdf_path = None
    dialog._json_path = None
    dialog._source_pdf_path = None
    dialog._source_json_path = None
    dialog._open_button = None
    dialog.factura = {}
    return dialog


def test_sync_standard_paths_consumidor_final(tmp_path, monkeypatch):
    dialog = _make_dialog()
    dialog.factura = {
        "identificacion": {
            "tipoDte": "01",
            "numeroControl": "ABC123",
            "fecEmi": "2024-05-01",
        },
        "receptor": {"nombre": "Cliente Demo"},
    }
    dialog.venta_id = 10
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    pdf_source = custom_dir / "factura.pdf"
    json_source = custom_dir / "factura.json"
    pdf_source.write_bytes(b"pdf-bytes")
    json_source.write_text("{}", encoding="utf-8")
    dialog._pdf_path = str(pdf_source)
    dialog._json_path = str(json_source)

    target_dir = tmp_path / "target"
    expected_pdf = target_dir / "expected.pdf"
    expected_json = target_dir / "expected.json"

    def fake_get_document_paths(fecha, cliente, numero_control, doc_type, root=None):
        assert doc_type == "ConsumidorFinal"
        expected_pdf.parent.mkdir(parents=True, exist_ok=True)
        return str(expected_pdf), str(expected_json)

    monkeypatch.setattr(
        "dialogs.invoice_detail_dialog.get_document_paths", fake_get_document_paths
    )
    monkeypatch.setattr(
        "dialogs.invoice_detail_dialog.get_dte_document_paths",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call")),
    )

    dialog._sync_standard_paths()

    assert expected_pdf.exists()
    assert expected_json.exists()
    assert dialog._pdf_path == str(expected_pdf)
    assert dialog._json_path == str(expected_json)
    assert expected_pdf.read_bytes() == b"pdf-bytes"
    assert expected_json.read_text(encoding="utf-8") == "{}"


def test_sync_standard_paths_nota_credito(tmp_path, monkeypatch):
    dialog = _make_dialog()
    dialog.factura = {
        "identificacion": {
            "tipoDte": "05",
            "numeroControl": "DTE-05-1",
            "fecEmi": "2024-06-01",
        },
        "receptor": {"nombreComercial": "Cliente"},
    }
    dialog.numero_control = "DTE-05-1"
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    pdf_source = custom_dir / "nota.pdf"
    json_source = custom_dir / "nota.json"
    pdf_source.write_bytes(b"nota")
    json_source.write_text("{\"nota\": true}", encoding="utf-8")
    dialog._pdf_path = str(pdf_source)
    dialog._json_path = None

    target_dir = tmp_path / "target"
    expected_pdf = target_dir / "nota.pdf"
    expected_json = target_dir / "nota.json"

    def fake_get_dte_paths(fecha, cliente, numero_control, doc_type, root=None):
        assert doc_type == "NotaCredito"
        expected_pdf.parent.mkdir(parents=True, exist_ok=True)
        return str(expected_pdf), str(expected_json)

    monkeypatch.setattr(
        "dialogs.invoice_detail_dialog.get_dte_document_paths", fake_get_dte_paths
    )
    monkeypatch.setattr(
        "dialogs.invoice_detail_dialog.get_document_paths",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call")),
    )

    dialog._sync_standard_paths()

    assert expected_pdf.exists()
    assert expected_json.exists()
    assert dialog._pdf_path == str(expected_pdf)
    assert dialog._json_path == str(expected_json)
    assert expected_json.read_text(encoding="utf-8") == "{\"nota\": true}"


def test_determine_file_path_accepts_pathlike(tmp_path):
    dialog = _make_dialog()
    pdf_path = tmp_path / "nota.pdf"
    pdf_path.write_text("pdf", encoding="utf-8")
    dialog._pdf_path = pdf_path
    dialog._json_path = None

    class DummyButton:
        def __init__(self):
            self.enabled = None

        def setEnabled(self, value):
            self.enabled = value

    button = DummyButton()
    dialog._open_button = button

    assert dialog._determine_file_path() == os.fspath(pdf_path)

    dialog._update_open_button_state()
    assert dialog._open_button.enabled is True


def test_open_file_location_regenerates_and_opens_canonical(tmp_path, monkeypatch):
    dialog = _make_dialog()
    dialog.factura = {
        "identificacion": {
            "tipoDte": "01",
            "numeroControl": "CTRL-001",
            "fecEmi": "2024-07-01",
        },
        "receptor": {"nombre": "Cliente"},
    }
    dialog.venta_id = 42

    class FakeButton:
        def __init__(self):
            self.enabled = None

        def setEnabled(self, value):
            self.enabled = value

    button = FakeButton()
    dialog._open_button = button

    canonical_dir = tmp_path / "facturas_consumidor_final"
    expected_pdf = canonical_dir / "canon.pdf"
    expected_json = canonical_dir / "canon.json"

    def fake_get_document_paths(fecha, cliente, numero_control, doc_type, root=None):
        expected_pdf.parent.mkdir(parents=True, exist_ok=True)
        return str(expected_pdf), str(expected_json)

    monkeypatch.setattr(
        "dialogs.invoice_detail_dialog.get_document_paths", fake_get_document_paths
    )
    monkeypatch.setattr(
        "dialogs.invoice_detail_dialog.get_dte_document_paths",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call")),
    )

    class FakeDB:
        def get_factura_pdf(self, venta_id):
            return None

    class FakeParent:
        def __init__(self):
            self.manager = types.SimpleNamespace(db=FakeDB())

        def _generate_invoice_pdf(self, venta_id):
            expected_pdf.parent.mkdir(parents=True, exist_ok=True)
            expected_pdf.write_text("pdf", encoding="utf-8")
            expected_json.write_text("{}", encoding="utf-8")
            return str(expected_pdf)

    parent = FakeParent()
    dialog.parent = lambda: parent

    opened = []

    def fake_open(url):
        opened.append(url)

    monkeypatch.setattr(invoice_detail_dialog.QDesktopServices, "openUrl", fake_open)

    dialog._pdf_path = None
    dialog._json_path = None

    dialog._open_file_location()

    assert opened == [str(canonical_dir)]
    assert dialog._pdf_path == str(expected_pdf)
    assert dialog._json_path == str(expected_json)
    assert dialog._open_button.enabled is True


def test_open_file_location_prefers_existing_original_path(tmp_path, monkeypatch):
    dialog = _make_dialog()

    class FakeButton:
        def __init__(self):
            self.enabled = None

        def setEnabled(self, value):
            self.enabled = value

    dialog._open_button = FakeButton()

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy_pdf = legacy_dir / "legacy.pdf"
    legacy_pdf.write_text("legacy", encoding="utf-8")

    canonical_dir = tmp_path / "canonical"
    canonical_pdf = canonical_dir / "canonical.pdf"

    dialog._source_pdf_path = str(legacy_pdf)
    dialog._pdf_path = str(canonical_pdf)
    dialog._json_path = None
    dialog._source_json_path = None

    opened = []

    def fake_open(url):
        opened.append(url)

    monkeypatch.setattr(invoice_detail_dialog.QDesktopServices, "openUrl", fake_open)

    dialog._update_open_button_state()
    dialog._open_file_location()

    assert opened == [str(legacy_dir)]
    assert dialog._open_button.enabled is True


def test_sync_standard_paths_updates_db_and_reuses_canonical(tmp_path, monkeypatch):
    dialog = _make_dialog()
    dialog.factura = {
        "identificacion": {
            "tipoDte": "01",
            "numeroControl": "CTRL-002",
            "fecEmi": "2024-08-01",
        },
        "receptor": {"nombre": "Cliente"},
    }
    dialog.venta_id = 77

    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    pdf_source = custom_dir / "factura.pdf"
    json_source = custom_dir / "factura.json"
    pdf_source.write_bytes(b"pdf")
    json_source.write_text("{}", encoding="utf-8")

    canonical_dir = tmp_path / "canonical"
    expected_pdf = canonical_dir / "canon.pdf"
    expected_json = canonical_dir / "canon.json"

    def fake_get_document_paths(fecha, cliente, numero_control, doc_type, root=None):
        assert doc_type == "ConsumidorFinal"
        expected_pdf.parent.mkdir(parents=True, exist_ok=True)
        return str(expected_pdf), str(expected_json)

    monkeypatch.setattr(
        "dialogs.invoice_detail_dialog.get_document_paths", fake_get_document_paths
    )
    monkeypatch.setattr(
        "dialogs.invoice_detail_dialog.get_dte_document_paths",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call")),
    )

    class RecordingDB:
        def __init__(self):
            self.paths = {}
            self.updated = []

        def update_factura_pdf_path(self, venta_id, ruta):
            self.updated.append((venta_id, ruta))
            self.paths[venta_id] = ruta

        def get_factura_pdf(self, venta_id):
            return self.paths.get(venta_id)

    db = RecordingDB()
    db.paths[dialog.venta_id] = str(pdf_source)

    class FakeParent:
        def __init__(self, database):
            self.manager = types.SimpleNamespace(db=database)

    parent = FakeParent(db)

    dialog.parent = lambda: parent
    dialog._pdf_path = str(pdf_source)
    dialog._json_path = str(json_source)

    dialog._sync_standard_paths()

    assert expected_pdf.exists()
    assert expected_json.exists()
    assert dialog._pdf_path == str(expected_pdf)
    assert dialog._json_path == str(expected_json)
    assert db.updated == [(dialog.venta_id, str(expected_pdf))]
    assert db.get_factura_pdf(dialog.venta_id) == str(expected_pdf)
    dialog2 = _make_dialog()
    dialog2.factura = dialog.factura
    dialog2.venta_id = dialog.venta_id
    dialog2.parent = lambda: parent
    dialog2._pdf_path = None
    dialog2._json_path = None

    refreshed = dialog2._refresh_invoice_files()

    assert refreshed == str(expected_pdf)
    assert dialog2._pdf_path == str(expected_pdf)
    assert dialog2._json_path == str(expected_json)
    assert db.updated == [(dialog.venta_id, str(expected_pdf))]


@pytest.mark.parametrize("tipo", ["04", "05", "06"])
def test_metadata_tab_includes_note_payloads(tipo):
    dialog = _make_dialog()
    dialog.factura = {
        "identificacion": {
            "tipoDte": tipo,
            "numeroControl": "NC-0001",
        },
        "resumen": {"montoTotalOperacion": 12.34},
    }

    info_widget = dialog._build_metadata_tab()

    assert info_widget is not None


def test_normalize_items_handles_stringified_payload():
    raw = json.dumps(
        {
            "1": {
                "descripcion": "Prod",
                "cantidad": "2",
                "precioUni": "1.50",
                "ventaGravada": "3.00",
            }
        }
    )
    items = normalize_items(raw)
    assert len(items) == 1
    assert items[0]["descripcion"] == "Prod"


def test_normalize_items_recurses_nested_sequences():
    raw = {"item": [{"descripcion": "A", "cantidad": 1}]}
    items = normalize_items(raw)
    assert len(items) == 1
    assert items[0]["descripcion"] == "A"


def test_normalize_summary_accepts_json_string():
    summary = normalize_summary('{"totalGravada": "5", "totalPagar": "5"}')
    assert summary["totalGravada"] == "5"
    assert summary["totalPagar"] == "5"
