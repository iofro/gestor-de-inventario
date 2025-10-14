import os
import json
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication, QDialog
except ImportError as exc:  # pragma: no cover - skip when Qt is unavailable
    pytest.skip(f"PyQt5 no disponible: {exc}", allow_module_level=True)

import facturacion_tab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def disable_qt_timers(monkeypatch):
    class DummyTimer:
        def __init__(self, parent=None):
            self.timeout = SimpleNamespace(connect=lambda fn: None)

        def setInterval(self, value):
            pass

        def start(self):
            pass

    monkeypatch.setattr(facturacion_tab, "QTimer", DummyTimer)
    monkeypatch.setattr(facturacion_tab.FacturacionTab, "load_invoices", lambda self: None)


def _create_sale(db, *, credito=False):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "C1", None,  vid, None, 0, 10, 10, 1)
    pid = db.cursor.lastrowid
    db.add_cliente("C", "", "", "", "", "", "c@x.com", "", "", "")
    cid = db.cursor.lastrowid
    if credito:
        venta_id = db.add_venta_credito_fiscal(
            cid,
            "2024-01-01",
            10,
            "NRC",
            "NIT",
            "Giro",
            vendedor_id=vid,
        )
    else:
        venta_id = db.add_venta("2024-01-01", 10, cliente_id=cid, vendedor_id=vid)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id, cid


def _make_tab(db, cid):
    man = SimpleNamespace(db=db, _clientes=[{"id": cid, "nombre": "C", "email": "c@x.com"}], _Distribuidores=[])
    tab = facturacion_tab.FacturacionTab(man)
    tab.table.selectRow(0)
    return tab


def test_create_ticket_saves_files(qt_app, tmp_path, monkeypatch):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab, "_selected_entry", lambda: {"row_type": "venta", "id": 1, "venta_id": venta_id}
    )

    save_path = tmp_path / "ticket.pdf"

    def fake_gen(venta, detalles, fname, dte_data=None):
        Path(fname).write_text("PDF")
        Path(fname).with_suffix(".json").write_text("{}")
    monkeypatch.setattr(facturacion_tab, "generar_ticket_personalizado", fake_gen)
    monkeypatch.setattr(facturacion_tab.QFileDialog, "getSaveFileName", lambda *a, **k: (str(save_path), None))
    monkeypatch.setattr(facturacion_tab.dte, "generar_ticket_json", lambda *a, **k: {})
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)

    tab.create_ticket()
    assert save_path.exists()
    assert save_path.with_suffix(".json").exists()


@pytest.mark.parametrize("ui_mode", ["contingencia", "normal"])
def test_create_nota_propagates_ui_mode(monkeypatch, qt_app, tmp_path, ui_mode):
    class DummyCursor:
        def execute(self, *args, **kwargs):
            return SimpleNamespace(fetchone=lambda: None)

    class DummyDB:
        def __init__(self):
            self.cursor = DummyCursor()

        def get_trabajadores(self, solo_vendedores=True):
            return []

        def get_vendedores(self, solo_vendedores=True):
            return []

        def get_vendedores_distribuidores(self):
            return []

        def get_Distribuidores(self):
            return []

        def get_clientes(self):
            return []

        def get_productos(self, **kwargs):
            return []

        def consultar_envio_dte(self, venta_id):
            return {}

        def agregar_nota(self, *args, **kwargs):
            return 42

    db = DummyDB()
    manager = SimpleNamespace(
        db=db,
        _clientes=[{"id": 1, "nombre": "Cliente", "email": "c@x.com"}],
        _Distribuidores=[],
        get_modo_transmision_actual=lambda: ui_mode,
    )

    monkeypatch.setattr(facturacion_tab.FacturacionTab, "_get_invoices_from_db", lambda self: None)
    tab = facturacion_tab.FacturacionTab(manager)
    monkeypatch.setattr(tab, "_show_pdf_preview", lambda *a, **k: None)

    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(
        facturacion_tab.QMessageBox,
        "question",
        lambda *a, **k: facturacion_tab.QMessageBox.Yes,
    )
    monkeypatch.setattr(facturacion_tab.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab, "generar_nota_credito_pdf", lambda *a, **k: None)

    pdf_path = tmp_path / "nota.pdf"
    json_note_path = tmp_path / "nota_nce.json"

    monkeypatch.setattr(
        facturacion_tab,
        "get_dte_document_paths",
        lambda *a, **k: (str(pdf_path), str(json_note_path)),
    )

    def fake_write_pdf_atomically(path, render):
        return str(pdf_path)

    monkeypatch.setattr(facturacion_tab, "write_pdf_atomically", fake_write_pdf_atomically)
    monkeypatch.setattr(
        facturacion_tab,
        "sign_and_save",
        lambda nota_json, path, return_token=True: (path, "signed-token"),
    )

    nota_stub = {
        "identificacion": {
            "tipoDte": "05",
            "codigoGeneracion": "12345678-1234-1234-1234-123456789012",
            "numeroControl": "DTE-05-001",
            "fecEmi": "2024-01-15",
        },
        "resumen": {
            "subTotalVentas": 0,
            "totalDescu": 0,
            "montoTotalOperacion": 9,
            "totalExenta": 0,
            "totalNoSuj": 0,
            "totalLetras": "NUEVE",
        },
        "cuerpoDocumento": [
            {
                "cantidad": 1,
                "descripcion": "Ajuste",
                "precioUni": 9,
                "ventaGravada": 9,
                "tributos": [],
            }
        ],
    }

    monkeypatch.setattr(
        facturacion_tab.nota_credito_electronica,
        "generar_nce_desde_dte",
        lambda *a, **k: copy.deepcopy(nota_stub),
    )

    captured: dict[str, str] = {}

    def fake_enviar(db_obj, nota_id, nota_json_arg, modo, jws_token=None):
        captured["modo"] = modo
        captured["token"] = jws_token
        return {"estado": "Pendiente"}

    monkeypatch.setattr(facturacion_tab.dte, "_enviar_documento", fake_enviar)

    factura_payload = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "abcd1234abcd1234abcd1234abcd1234",
            "numeroControl": "DTE-03-001",
            "fecEmi": "2024-01-15",
        },
        "resumen": {"montoTotalOperacion": 10, "totalPagar": 10},
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "codigo": "P1",
                "descripcion": "Producto",
                "cantidad": 1,
                "precioUni": 10,
                "ventaGravada": 10,
                "tributos": [],
            }
        ],
    }

    factura_path = tmp_path / "factura.json"
    factura_path.write_text(json.dumps(factura_payload))
    factura = {"json": str(factura_path), "venta_id": 1}

    class DummyDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec_(self):
            return QDialog.Accepted

        def get_data(self):
            return 1.0, "Motivo", [{"detalle_id": 1, "ajuste": 1.0}]

    monkeypatch.setattr(facturacion_tab, "NotaDetalleDialog", DummyDialog)

    tab.create_nota("credito", factura=factura)

    assert captured["modo"] == ui_mode
    assert captured["token"] == "signed-token"


def test_build_ticket_format_pdf_saves_alongside_invoice(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    cf_dir = tmp_path / "facturas_consumidor_final"
    cf_dir.mkdir()
    pdf_path = cf_dir / "20240101_Test.pdf"
    pdf_path.write_text("pdf")
    dte_payload = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-1234-1234-1234-123456789012",
            "numeroControl": "DTE-01-0001",
            "tipoModelo": 1,
            "tipoOperacion": 1,
            "fecEmi": "2024-01-01",
            "horEmi": "12:00:00",
        },
        "emisor": {
            "nombreComercial": "Farmacia X",
            "nit": "0614-290389-102-1",
            "nrc": "123456-7",
            "descActividad": "Farmacia",
            "direccion": {"complemento": "Av. Siempre Viva"},
        },
        "receptor": {"tipoDocumento": "37", "direccion": {"complemento": "Calle 1"}},
        "cuerpoDocumento": [
            {
                "cantidad": 1,
                "uniMedida": "59",
                "descripcion": "Acetaminofen 500mg",
                "precioUni": 2.0,
                "montoTotal": 2.0,
            }
        ],
        "resumen": {
            "totalGravada": 2.0,
            "montoTotalOperacion": 2.0,
            "totalPagar": 2.0,
            "condicionOperacion": 1,
            "pagos": [{"codigo": "01", "montoPago": 2.0}],
        },
        "selloRecibido": "ABCD1234EFGH5678IJKL9012MNOP3456QRST789",
    }
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text(json.dumps(dte_payload))
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf_path))
    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(cf_dir))

    tab = _make_tab(db, cid)
    entry = {"row_type": "venta", "venta_id": venta_id, "tipo": "Consumidor Final"}

    output = tab._build_ticket_format_pdf(entry, str(pdf_path))
    assert output is not None
    out_path = Path(output)
    assert out_path.exists()
    assert out_path.parent == cf_dir
    assert out_path.stat().st_size > 0
    stored = db.get_ticket_pdf(venta_id)
    assert stored is None
    resolved = tab._resolve_ticket_pdf(entry, str(pdf_path))
    assert resolved == str(out_path)
    tab._safe_remove(output)
    assert not out_path.exists()


def test_resolve_ticket_pdf_reuses_existing(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    existing = tmp_path / "existing.pdf"
    existing.write_text("pdf")
    db.add_ticket_pdf(venta_id, str(existing))

    tab = _make_tab(db, cid)
    entry = {"row_type": "venta", "venta_id": venta_id}

    called = {}

    def fake_build(entry_arg, base):
        called["called"] = True
        return "new"

    monkeypatch.setattr(tab, "_build_ticket_format_pdf", fake_build)

    resolved = tab._resolve_ticket_pdf(entry, None)

    assert resolved == str(existing)
    assert "called" not in called


def test_resolve_ticket_pdf_builds_when_missing(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    missing = tmp_path / "missing.pdf"
    db.add_ticket_pdf(venta_id, str(missing))

    tab = _make_tab(db, cid)
    entry = {"row_type": "venta", "venta_id": venta_id}

    generated = tmp_path / "generated.pdf"
    flags = {}

    def fake_build(entry_arg, base):
        flags["called"] = True
        return str(generated)

    monkeypatch.setattr(tab, "_build_ticket_format_pdf", fake_build)

    resolved = tab._resolve_ticket_pdf(entry, None)

    assert resolved == str(generated)
    assert flags.get("called") is True


def test_resolve_ticket_pdf_generates_once(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    cf_dir = tmp_path / "cf"
    cf_dir.mkdir()
    carta_path = cf_dir / "20240101_Test.pdf"
    carta_path.write_text("pdf")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(carta_path))

    tab = _make_tab(db, cid)
    entry = {"row_type": "venta", "venta_id": venta_id, "tipo": "Consumidor Final"}

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(cf_dir))

    def fake_ticket(venta, detalles, archivo, datos_negocio=None, dte_data=None):
        Path(archivo).write_text("ticket")

    monkeypatch.setattr(facturacion_tab, "generar_ticket_personalizado", fake_ticket)

    calls = {"count": 0}

    def fake_write(dest, render):
        calls["count"] += 1
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        render(dest_path)
        return dest_path

    monkeypatch.setattr(facturacion_tab, "write_pdf_atomically", fake_write)

    first = tab._resolve_ticket_pdf(entry, str(carta_path))
    expected = cf_dir / "20240101_Test_Ticket.pdf"
    assert first == str(expected)
    assert calls["count"] == 1
    assert expected.exists()

    second = tab._resolve_ticket_pdf(entry, str(carta_path))
    assert second == str(expected)
    assert calls["count"] == 1


def test_print_invoice_ticket_entry_allows_format_selection(
    monkeypatch, qt_app, tmp_path
):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    carta_path = tmp_path / "invoice.pdf"
    carta_path.write_text("pdf")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(carta_path))

    tab = _make_tab(db, cid)
    entry = {
        "row_type": "ticket",
        "venta_id": venta_id,
        "codigo": "01",
        "tipo": "Consumidor Final",
    }

    monkeypatch.setattr(tab, "_selected_entry", lambda: entry)

    ticket_pdf = tmp_path / "ticket.pdf"
    ticket_pdf.write_text("ticket")

    ticket_calls = []

    def fake_resolve_ticket(entry_arg, base_path):
        ticket_calls.append((entry_arg, base_path))
        return str(ticket_pdf)

    monkeypatch.setattr(tab, "_resolve_ticket_pdf", fake_resolve_ticket)

    preview_paths = []

    class DummyPreview:
        def __init__(self, path, parent=None):
            preview_paths.append(path)

        def exec_(self):
            return facturacion_tab.QDialog.Accepted

        def has_error(self):
            return False

    monkeypatch.setattr(facturacion_tab, "PdfPreviewDialog", DummyPreview)

    opened_paths = []
    monkeypatch.setattr(
        facturacion_tab,
        "open_pdf_file",
        lambda path: opened_paths.append(path) or True,
    )
    monkeypatch.setattr(
        facturacion_tab,
        "resolve_user_visible_path",
        lambda path: None,
    )

    class FakeMessageBox:
        AcceptRole = object()
        Question = object()
        Cancel = object()
        _next_choice = "carta"
        warnings = []

        def __init__(self, parent=None):
            self._carta_button = None
            self._ticket_button = None
            self._cancel_button = None
            self._clicked = None

        def setIcon(self, icon):
            pass

        def setWindowTitle(self, title):
            pass

        def setText(self, text):
            self.text = text

        def addButton(self, text_or_button, role=None):
            if text_or_button is self.Cancel:
                button = SimpleNamespace(kind="cancel")
                self._cancel_button = button
            else:
                button = SimpleNamespace(kind="text", text=text_or_button, role=role)
                if text_or_button == "Carta":
                    self._carta_button = button
                elif text_or_button == "Ticket":
                    self._ticket_button = button
            return button

        def setDefaultButton(self, button):
            self._default = button

        def exec_(self):
            choice = self.__class__._next_choice
            if choice == "ticket":
                self._clicked = self._ticket_button
            elif choice == "cancel":
                self._clicked = self._cancel_button
            else:
                self._clicked = self._carta_button
            return 0

        def clickedButton(self):
            return self._clicked

        @classmethod
        def warning(cls, *args, **kwargs):
            cls.warnings.append((args, kwargs))
            return None

    monkeypatch.setattr(facturacion_tab, "QMessageBox", FakeMessageBox)

    FakeMessageBox._next_choice = "carta"
    tab.print_invoice()

    assert preview_paths[-1] == str(carta_path)
    assert opened_paths[-1] == str(carta_path)
    assert ticket_calls == []

    FakeMessageBox._next_choice = "ticket"
    tab.print_invoice()

    assert ticket_calls == [(entry, str(carta_path))]
    assert preview_paths[-1] == str(ticket_pdf)
    assert opened_paths[-1] == str(ticket_pdf)
    assert FakeMessageBox.warnings == []


def test_print_invoice_orphan_allows_ticket_selection(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    tab = _make_tab(db, cid)

    carta_path = tmp_path / "20240101_invoice.pdf"
    carta_path.write_text("pdf")

    json_path = tmp_path / "20240101_invoice.json"
    json_payload = {
        "identificacion": {"tipoDte": "01", "numeroControl": "DTE-01-1"},
        "resumen": {"totalPagar": 10},
        "cuerpoDocumento": [],
    }
    json_path.write_text(json.dumps(json_payload))

    entry = {
        "row_type": "orphan",
        "venta_id": None,
        "codigo": "01",
        "tipo": "Consumidor Final",
        "pdf": str(carta_path),
        "json": str(json_path),
    }

    monkeypatch.setattr(tab, "_selected_entry", lambda: entry)

    ticket_pdf = tmp_path / "20240101_invoice_Ticket.pdf"
    ticket_pdf.write_text("ticket")

    ticket_calls = []

    def fake_resolve_ticket(entry_arg, base_path):
        ticket_calls.append((entry_arg, base_path))
        return str(ticket_pdf)

    monkeypatch.setattr(tab, "_resolve_ticket_pdf", fake_resolve_ticket)

    preview_paths = []

    class DummyPreview:
        def __init__(self, path, parent=None):
            preview_paths.append(path)

        def exec_(self):
            return facturacion_tab.QDialog.Accepted

        def has_error(self):
            return False

    monkeypatch.setattr(facturacion_tab, "PdfPreviewDialog", DummyPreview)

    opened_paths = []
    monkeypatch.setattr(
        facturacion_tab,
        "open_pdf_file",
        lambda path: opened_paths.append(path) or True,
    )
    monkeypatch.setattr(
        facturacion_tab,
        "resolve_user_visible_path",
        lambda path: None,
    )

    class FakeMessageBox:
        AcceptRole = object()
        Question = object()
        Cancel = object()
        _next_choice = "ticket"
        warnings = []

        def __init__(self, parent=None):
            self._carta_button = None
            self._ticket_button = None
            self._cancel_button = None
            self._clicked = None

        def setIcon(self, icon):
            pass

        def setWindowTitle(self, title):
            pass

        def setText(self, text):
            self.text = text

        def addButton(self, text_or_button, role=None):
            if text_or_button is self.Cancel:
                button = SimpleNamespace(kind="cancel")
                self._cancel_button = button
            else:
                button = SimpleNamespace(kind="text", text=text_or_button, role=role)
                if text_or_button == "Carta":
                    self._carta_button = button
                elif text_or_button == "Ticket":
                    self._ticket_button = button
            return button

        def setDefaultButton(self, button):
            self._default = button

        def exec_(self):
            choice = self.__class__._next_choice
            if choice == "ticket":
                self._clicked = self._ticket_button
            elif choice == "cancel":
                self._clicked = self._cancel_button
            else:
                self._clicked = self._carta_button
            return 0

        def clickedButton(self):
            return self._clicked

        @classmethod
        def warning(cls, *args, **kwargs):
            cls.warnings.append((args, kwargs))
            return None

    monkeypatch.setattr(facturacion_tab, "QMessageBox", FakeMessageBox)

    FakeMessageBox._next_choice = "ticket"
    tab.print_invoice()

    assert ticket_calls == [(entry, str(carta_path))]
    assert preview_paths[-1] == str(ticket_pdf)
    assert opened_paths[-1] == str(ticket_pdf)

    FakeMessageBox._next_choice = "carta"
    tab.print_invoice()

    assert preview_paths[-1] == str(carta_path)
    assert opened_paths[-1] == str(carta_path)
    assert FakeMessageBox.warnings == []


def test_print_invoice_json_only_builds_pdfs(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    tab = _make_tab(db, cid)

    json_path = tmp_path / "20240101_orphan.json"
    json_payload = {
        "identificacion": {
            "tipoDte": "01",
            "numeroControl": "DTE-01-00000001",
            "codigoGeneracion": "1234567890ABCDEF1234567890ABCDEF12345678",
            "fecEmi": "2024-01-01",
            "ambiente": "00",
        },
        "resumen": {"totalPagar": 10, "sumas": 8.85, "iva": 1.15},
        "receptor": {"nombre": "Cliente Demo", "nit": "0614-1990-0110-19"},
        "cuerpoDocumento": [
            {
                "descripcion": "Producto",
                "cantidad": 1,
                "precioUni": 8.85,
                "ventaGravada": 8.85,
                "ivaItem": 1.15,
            }
        ],
        "selloRecibido": "0" * 40,
    }
    json_path.write_text(json.dumps(json_payload))

    base_pdf = tmp_path / "20240101_orphan.pdf"
    entry = {
        "row_type": "orphan",
        "venta_id": None,
        "codigo": "01",
        "tipo": "Consumidor Final",
        "json": str(json_path),
        "pdf": str(base_pdf),
    }

    monkeypatch.setattr(tab, "_selected_entry", lambda: entry)

    invoice_called = []

    def fake_invoice_pdf(venta, detalles, cliente, distribuidor, tipo_doc, archivo, **kwargs):
        Path(archivo).write_text("pdf")
        invoice_called.append(True)

    monkeypatch.setattr(
        facturacion_tab,
        "generar_factura_electronica_pdf",
        fake_invoice_pdf,
    )

    def fake_ticket(venta, detalles, archivo, datos_negocio=None, dte_data=None):
        Path(archivo).write_text("ticket")

    monkeypatch.setattr(facturacion_tab, "generar_ticket_personalizado", fake_ticket)

    preview_paths = []

    class DummyPreview:
        def __init__(self, path, parent=None):
            preview_paths.append(path)

        def exec_(self):
            return facturacion_tab.QDialog.Accepted

        def has_error(self):
            return False

    monkeypatch.setattr(facturacion_tab, "PdfPreviewDialog", DummyPreview)

    opened_paths = []
    monkeypatch.setattr(
        facturacion_tab,
        "open_pdf_file",
        lambda path: opened_paths.append(path) or True,
    )
    monkeypatch.setattr(
        facturacion_tab,
        "resolve_user_visible_path",
        lambda path: None,
    )

    class FakeMessageBox:
        AcceptRole = object()
        Question = object()
        Cancel = object()
        _next_choice = "carta"
        warnings = []

        def __init__(self, parent=None):
            self._carta_button = None
            self._ticket_button = None
            self._cancel_button = None
            self._clicked = None

        def setIcon(self, icon):
            pass

        def setWindowTitle(self, title):
            pass

        def setText(self, text):
            self.text = text

        def addButton(self, text_or_button, role=None):
            if text_or_button is self.Cancel:
                button = SimpleNamespace(kind="cancel")
                self._cancel_button = button
            else:
                button = SimpleNamespace(kind="text", text=text_or_button, role=role)
                if text_or_button == "Carta":
                    self._carta_button = button
                elif text_or_button == "Ticket":
                    self._ticket_button = button
            return button

        def setDefaultButton(self, button):
            self._default = button

        def exec_(self):
            choice = self.__class__._next_choice
            if choice == "ticket":
                self._clicked = self._ticket_button
            elif choice == "cancel":
                self._clicked = self._cancel_button
            else:
                self._clicked = self._carta_button
            return 0

        def clickedButton(self):
            return self._clicked

        @classmethod
        def warning(cls, *args, **kwargs):
            cls.warnings.append((args, kwargs))
            return None

    monkeypatch.setattr(facturacion_tab, "QMessageBox", FakeMessageBox)

    FakeMessageBox._next_choice = "carta"
    tab.print_invoice()

    assert Path(entry["pdf"]).exists()
    assert invoice_called
    assert preview_paths[-1] == entry["pdf"]
    assert opened_paths[-1] == entry["pdf"]

    ticket_path = tmp_path / "20240101_orphan_Ticket.pdf"
    FakeMessageBox._next_choice = "ticket"
    tab.print_invoice()

    assert ticket_path.exists()
    assert preview_paths[-1] == str(ticket_path)
    assert opened_paths[-1] == str(ticket_path)
    assert FakeMessageBox.warnings == []

def test_build_ticket_format_pdf_without_base_uses_control(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db, credito=True)
    credito_dir = tmp_path / "credito"
    credito_dir.mkdir()
    json_payload = {
        "identificacion": {
            "tipoDte": "03",
            "numeroControl": "DTE-03-0001",
            "codigoGeneracion": "12345678-1234-1234-1234-123456789012",
        },
        "cuerpoDocumento": [{"cantidad": 1, "descripcion": "Item", "precioUni": 10, "montoTotal": 10}],
        "resumen": {"totalGravada": 10, "montoTotalOperacion": 10},
    }
    json_path = credito_dir / "20240101_credito.json"
    json_path.write_text(json.dumps(json_payload))
    entry = {
        "row_type": "venta",
        "venta_id": venta_id,
        "tipo": "Crédito Fiscal",
        "json": str(json_path),
    }

    tab = _make_tab(db, cid)

    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(credito_dir))
    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(tmp_path / "tickets"))

    def fake_ticket(venta, detalles, archivo, datos_negocio=None, dte_data=None):
        Path(archivo).write_text("ticket")

    monkeypatch.setattr(facturacion_tab, "generar_ticket_personalizado", fake_ticket)

    def fake_write(dest, render):
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        render(dest_path)
        return dest_path

    monkeypatch.setattr(facturacion_tab, "write_pdf_atomically", fake_write)

    output = tab._build_ticket_format_pdf(entry, None)
    expected = credito_dir / "DTE-03-0001_Ticket.pdf"
    assert output == str(expected)
    assert expected.exists()

    again = tab._build_ticket_format_pdf(entry, None)
    assert again == str(expected)
    ticket_files = list(credito_dir.glob("*_Ticket.pdf"))
    assert ticket_files == [expected]


def test_ticket_generation_preserves_qr_payload(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    cf_dir = tmp_path / "cf"
    cf_dir.mkdir()
    pdf_path = cf_dir / "20240101_Test.pdf"
    pdf_path.write_text("pdf")
    dte_payload = {
        "identificacion": {
            "tipoDte": "01",
            "numeroControl": "DTE-01-0001",
            "codigoGeneracion": "12345678-1234-1234-1234-123456789012",
        },
        "cuerpoDocumento": [{"cantidad": 1, "descripcion": "Item", "precioUni": 10, "montoTotal": 10}],
        "resumen": {"totalGravada": 10, "montoTotalOperacion": 10},
        "qrCode": "QR-DATA",
        "selloRecibido": "SELLO-DOC",
        "firmaElectronica": "FIRMA-DOC",
    }
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text(json.dumps(dte_payload))

    entry = {
        "row_type": "venta",
        "venta_id": venta_id,
        "tipo": "Consumidor Final",
        "json": str(json_path),
        "pdf": str(pdf_path),
    }

    tab = _make_tab(db, cid)

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(cf_dir))
    monkeypatch.setattr(facturacion_tab.dte, "_load_datos_negocio", lambda: {})

    payload_template = {
        "venta": {"id": venta_id},
        "detalles": ("detalle",),
        "datos_negocio": {"nombre": "Negocio"},
        "dte_data": {
            "qrCode": "QR-DATA",
            "selloRecibido": "SELLO-DOC",
            "firmaElectronica": "FIRMA-DOC",
        },
    }

    monkeypatch.setattr(
        facturacion_tab,
        "dte_to_legacy_ticket_payload",
        lambda *a, **k: payload_template,
    )

    captured = {}

    def fake_write(dest, render):
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        render(dest_path)
        return dest_path

    monkeypatch.setattr(facturacion_tab, "write_pdf_atomically", fake_write)

    def fake_ticket(venta, detalles, archivo, datos_negocio=None, dte_data=None):
        captured["venta"] = venta
        captured["detalles"] = detalles
        captured["datos_negocio"] = datos_negocio
        captured["dte_data"] = dte_data
        Path(archivo).write_text("ticket")

    monkeypatch.setattr(facturacion_tab, "generar_ticket_personalizado", fake_ticket)

    output = tab._build_ticket_format_pdf(entry, str(pdf_path))
    assert output is not None
    assert Path(output).exists()
    assert captured["dte_data"] == payload_template["dte_data"]
    assert captured["dte_data"] is not payload_template["dte_data"]
    assert captured["dte_data"]["qrCode"] == "QR-DATA"
    assert payload_template["dte_data"]["qrCode"] == "QR-DATA"
    assert isinstance(captured["detalles"], list)
    assert captured["detalles"] == ["detalle"]
    assert captured["datos_negocio"] == {"nombre": "Negocio"}


def test_print_invoice_notes_skip_format_selection(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    nota_path = tmp_path / "nota.pdf"
    nota_path.write_text("pdf")
    db.add_factura_pdf(venta_id, "Nota de crédito", str(nota_path))

    tab = _make_tab(db, cid)
    entry = {
        "row_type": "venta",
        "venta_id": venta_id,
        "codigo": "05",
        "tipo": "Nota de crédito",
    }
    monkeypatch.setattr(tab, "_selected_entry", lambda: entry)

    monkeypatch.setattr(tab, "_resolve_pdf_path", lambda e: str(nota_path))

    def fail_get_factura(vid):
        pytest.fail("get_factura_pdf no debe llamarse para notas")

    def fail_generate(vid):
        pytest.fail("_generate_invoice_pdf no debe llamarse para notas")

    monkeypatch.setattr(tab.manager.db, "get_factura_pdf", fail_get_factura)
    monkeypatch.setattr(tab, "_generate_invoice_pdf", fail_generate)

    preview_paths = []

    class DummyPreview:
        def __init__(self, path, parent=None):
            preview_paths.append(path)

        def exec_(self):
            return facturacion_tab.QDialog.Accepted

        def has_error(self):
            return False

    monkeypatch.setattr(facturacion_tab, "PdfPreviewDialog", DummyPreview)

    opened_paths = []
    monkeypatch.setattr(
        facturacion_tab,
        "open_pdf_file",
        lambda path: opened_paths.append(path) or True,
    )
    monkeypatch.setattr(
        facturacion_tab,
        "resolve_user_visible_path",
        lambda path: None,
    )

    class TrackingMessageBox:
        AcceptRole = object()
        Question = object()
        Cancel = object()
        instances = []

        def __init__(self, parent=None):
            type(self).instances.append(self)

        @classmethod
        def warning(cls, *args, **kwargs):
            return None

    monkeypatch.setattr(facturacion_tab, "QMessageBox", TrackingMessageBox)

    tab.print_invoice()

    assert preview_paths
    assert opened_paths
    assert preview_paths[-1] == str(nota_path)
    assert opened_paths[-1] == str(nota_path)
    assert TrackingMessageBox.instances == []



def test_send_selected_invoice(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf_path))

    creds_path = tmp_path / "creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "smtp_server": "s",
                "smtp_port": 25,
                "email_usuario": "u",
                "email_contrasena": "pw",
            }
        )
    )
    monkeypatch.setattr(facturacion_tab, "DATOS_NEGOCIO_PATH", str(creds_path))

    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab, "_selected_entry", lambda: {"row_type": "venta", "id": 1, "venta_id": venta_id}
    )
    monkeypatch.setattr(
        tab,
        "_selected_factura",
        lambda: {"venta_id": venta_id, "json": str(json_path), "control": "X"},
    )

    class DummyCheck:
        def __init__(self):
            self._checked = False
        def setChecked(self, v):
            self._checked = v
        def isChecked(self):
            return self._checked
    class DummyDlg:
        def __init__(self, parent=None):
            self.email_cb = DummyCheck()
            self.hacienda_cb = DummyCheck()
            self.hacienda_cb.setChecked(True)
        def exec_(self):
            return QDialog.Accepted
    monkeypatch.setattr(facturacion_tab, "SendOptionsDialog", DummyDlg)

    captured_email = {}
    class FakeSender:
        def __init__(self, server, port, user, pw, dest, subj, body, attach):
            captured_email["args"] = (server, port, user, pw, dest, subj, body, attach)
            self.finished = SimpleNamespace(connect=lambda fn: setattr(self, "_fn", fn))
        def start(self):
            if hasattr(self, "_fn"):
                self._fn(True, "ok")
    monkeypatch.setattr(facturacion_tab, "EmailSender", FakeSender)

    captured_post = {}
    def fake_post(url, token, jws, data):
        captured_post["args"] = (url, token, jws)
        return {"estado": "PROCESADO", "sello": "SELLO"}
    monkeypatch.setattr("dte._post_dte", fake_post)
    captured_transmit = {}

    def fake_transmitir(db_, vid, modo="normal", tipo_dte="01"):
        fake_post("http://example.com", "TOKEN", "SIGNED", {})
        captured_transmit["args"] = (db_, vid, modo, tipo_dte)
        return {
            "estado": "PROCESADO",
            "selloRecibido": "SELLO-DOC",
            "identificacion": {"codigoGeneracion": "ABC123"},
        }
    monkeypatch.setattr(facturacion_tab, "transmitir_dte", fake_transmitir)

    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)

    tab.send_selected_invoice()
    assert pdf_path in map(Path, captured_email["args"][7])
    assert json_path in map(Path, captured_email["args"][7])
    assert captured_post["args"] == ("http://example.com", "TOKEN", "SIGNED")
    assert captured_transmit["args"][3] == "01"


def test_send_selected_invoice_allows_email_when_procesado(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf_path))

    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab,
        "_selected_entry",
        lambda: {"row_type": "venta", "id": 1, "venta_id": venta_id},
    )
    monkeypatch.setattr(
        tab,
        "_selected_factura",
        lambda: {"venta_id": venta_id, "json": str(json_path), "control": "X"},
    )

    class DummyCheck:
        def __init__(self):
            self._checked = False

        def setChecked(self, value):
            self._checked = value

        def isChecked(self):
            return self._checked

    class DummyDlg:
        def __init__(self, parent=None):
            self.email_cb = DummyCheck()
            self.hacienda_cb = DummyCheck()

        def exec_(self):
            return QDialog.Accepted

    monkeypatch.setattr(facturacion_tab, "SendOptionsDialog", DummyDlg)

    warnings = []

    def fake_warning(*args, **kwargs):
        warnings.append(args)

    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", fake_warning)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)

    called = {}

    def fake_send_invoice_email(self, venta, **kwargs):
        called["args"] = (venta, kwargs)

    monkeypatch.setattr(
        facturacion_tab.FacturacionTab,
        "_send_invoice_email",
        fake_send_invoice_email,
    )

    def fake_transmitir(db_, vid, modo="normal", tipo_dte="01"):
        return {
            "estado": "PROCESADO",
            "selloRecibido": "SELLO-DOC",
            "identificacion": {"codigoGeneracion": "ABC123"},
        }

    monkeypatch.setattr(facturacion_tab, "transmitir_dte", fake_transmitir)

    tab.send_selected_invoice()

    assert called["args"][0] == venta_id
    assert called["args"][1]["expected_codigo"] == "ABC123"
    assert called["args"][1]["expected_sello"] == "SELLO-DOC"
    assert warnings == []


def test_send_selected_invoice_credito_fiscal(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db, credito=True)
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")
    db.add_factura_pdf(venta_id, "Crédito Fiscal", str(pdf_path))

    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab,
        "_selected_entry",
        lambda: {
            "row_type": "venta",
            "id": 1,
            "venta_id": venta_id,
            "tipo": "Crédito Fiscal",
        },
    )
    monkeypatch.setattr(
        tab,
        "_selected_factura",
        lambda: {"venta_id": venta_id, "json": str(json_path), "control": "X"},
    )

    class DummyCheck:
        def __init__(self, checked=False):
            self._checked = checked

        def setChecked(self, v):
            self._checked = v

        def isChecked(self):
            return self._checked

    class DummyDlg:
        def __init__(self, parent=None):
            self.email_cb = DummyCheck(False)
            self.hacienda_cb = DummyCheck(True)

        def exec_(self):
            return QDialog.Accepted

    monkeypatch.setattr(facturacion_tab, "SendOptionsDialog", DummyDlg)

    captured_tipo = {}

    def fake_transmitir(db_, vid, modo="normal", tipo_dte="01"):
        captured_tipo["tipo"] = tipo_dte
        return {"estado": "Transmitido"}

    monkeypatch.setattr(facturacion_tab, "transmitir_dte", fake_transmitir)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)

    tab.send_selected_invoice()

    assert captured_tipo["tipo"] == "03"


def test_determine_tipo_dte_uses_tipo_tokens(monkeypatch, qt_app):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    tab = _make_tab(db, cid)
    monkeypatch.setattr(tab.manager.db, "get_venta_credito_fiscal", lambda *_: None)

    entry = {"row_type": "venta", "venta_id": venta_id, "tipo": "Factura CCF"}

    assert tab._determine_tipo_dte(entry) == "03"


def test_determine_tipo_dte_uses_json_hint(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    tab = _make_tab(db, cid)
    monkeypatch.setattr(tab.manager.db, "get_venta_credito_fiscal", lambda *_: None)

    json_path = tmp_path / "preview.json"
    json_path.write_text(json.dumps({"identificacion": {"tipoDte": "03"}}))

    entry = {
        "row_type": "venta",
        "venta_id": venta_id,
        "tipo": "Nota de crédito",
        "json": str(json_path),
    }

    assert tab._determine_tipo_dte(entry) == "03"


def test_determine_tipo_dte_skips_nota_credito(monkeypatch, qt_app):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    tab = _make_tab(db, cid)
    monkeypatch.setattr(tab.manager.db, "get_venta_credito_fiscal", lambda *_: None)

    entry = {"row_type": "venta", "venta_id": venta_id, "tipo": "Nota de crédito"}

    assert tab._determine_tipo_dte(entry) == "01"


def test_delete_invoice_removes_all(qt_app, tmp_path, monkeypatch):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)

    pdf = tmp_path / "f.pdf"
    pdf.write_text("p")
    js = pdf.with_suffix(".json")
    js.write_text(
        json.dumps({"identificacion": {"numeroControl": "DTE-01-S001P001-000000000000005"}})
    )
    jws = pdf.with_suffix(".jws")
    jws.write_text("TOKEN")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf))

    base_dte = Path(facturacion_tab.__file__).with_name("dtes")
    dte_dir = base_dte / "tmp_test" / "abc"
    dte_dir.mkdir(parents=True, exist_ok=True)
    dte_json = dte_dir / js.name
    dte_json.write_text(
        json.dumps({"identificacion": {"numeroControl": "DTE-01-S001P001-000000000000005"}})
    )
    (dte_dir / f"{js.stem}_estado.json").write_text(json.dumps({"estado": "aceptado"}))

    db.set_dte_correlativo("01", "001", "001", 5)
    monkeypatch.setattr(facturacion_tab.FacturacionTab, "load_invoices", lambda self: None)
    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab,
        "_selected_entry",
        lambda: {"row_type": "venta", "id": 1, "venta_id": venta_id, "json": str(dte_json)},
    )

    monkeypatch.setattr(
        facturacion_tab.QMessageBox,
        "question",
        lambda *a, **k: facturacion_tab.QMessageBox.Yes,
    )
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)

    tab.delete_invoice()

    assert not pdf.exists()
    assert not js.exists()
    assert not jws.exists()
    assert not dte_dir.exists()
    assert db.get_venta_by_id(venta_id) is None
    assert db.get_dte_correlativo("01", "001", "001") == 4


def test_delete_orphan_invoice_removes_files(qt_app, tmp_path, monkeypatch):
    db = DB(":memory:")
    base = "20240101_Test"

    cf_dir = tmp_path / "facturas_consumidor_final"
    credito_dir = tmp_path / "facturas_credito_fiscal"
    tickets_dir = tmp_path / "tickets"
    dtes_dir = tmp_path / "dtes"
    fallidos_dir = tmp_path / "dte_fallidos"
    pendientes_dir = tmp_path / "dtes_pendientes"
    for d in [cf_dir, credito_dir, tickets_dir, dtes_dir, fallidos_dir, pendientes_dir]:
        d.mkdir(parents=True, exist_ok=True)

    pdf = cf_dir / f"{base}.pdf"
    js = cf_dir / f"{base}.json"
    jws = cf_dir / f"{base}.jws"
    pdf.write_text("p")
    js.write_text("{}")
    jws.write_text("sig")

    (dtes_dir / f"{base}.pdf").write_text("p")
    (dtes_dir / f"{base}.json").write_text("{}")
    (dtes_dir / f"{base}.jws").write_text("sig")

    db.cursor.execute(
        "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, '')",
        (None, "Consumidor Final", str(pdf)),
    )
    db.conn.commit()

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(cf_dir))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(credito_dir))
    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(tickets_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_DEBITO_DIR", str(tmp_path / "notas_debito"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_CREDITO_DIR", str(tmp_path / "notas_credito"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_REMISION_DIR", str(tmp_path / "notas_remision"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])
    monkeypatch.setattr(
        facturacion_tab,
        "INVOICE_DIRS",
        [
            str(cf_dir),
            str(credito_dir),
            str(tickets_dir),
            str(dtes_dir),
            str(fallidos_dir),
            str(pendientes_dir),
        ],
    )
    monkeypatch.setattr(facturacion_tab.FacturacionTab, "load_invoices", lambda self: None)

    tab = facturacion_tab.FacturacionTab(SimpleNamespace(db=db, _clientes=[], _Distribuidores=[]))
    monkeypatch.setattr(
        tab,
        "_selected_entry",
        lambda: {"row_type": "orphan", "pdf": str(pdf), "json": str(js)},
    )

    warn_called = False

    def fake_warning(*a, **k):
        nonlocal warn_called
        warn_called = True

    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", fake_warning)
    monkeypatch.setattr(
        facturacion_tab.QMessageBox, "question", lambda *a, **k: facturacion_tab.QMessageBox.Yes
    )
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)

    tab.delete_invoice()

    assert not warn_called
    assert not pdf.exists()
    assert not js.exists()
    assert not jws.exists()
    assert not (dtes_dir / f"{base}.pdf").exists()
    assert not (dtes_dir / f"{base}.json").exists()
    assert not (dtes_dir / f"{base}.jws").exists()
    db.cursor.execute("SELECT COUNT(*) FROM facturas_pdf")
    assert db.cursor.fetchone()[0] == 0


def test_rejected_invoice_without_revert_keeps_correlativo(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db, credito=True)
    correlativo = 404
    db.set_dte_correlativo("03", "001", "001", correlativo)

    control = f"DTE-03-S001P001-{correlativo:015d}"
    factura_json = tmp_path / "factura.json"
    factura_json.write_text(json.dumps({"identificacion": {"numeroControl": control}}))

    tab = _make_tab(db, cid)

    class RejectDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec_(self):
            return QDialog.Rejected

    monkeypatch.setattr(facturacion_tab, "DTERechazadoDialog", RejectDialog)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)

    archive_called = False

    def fake_archive(self, entry, factura):
        nonlocal archive_called
        archive_called = True

    monkeypatch.setattr(facturacion_tab.FacturacionTab, "_archive_rejected_invoice", fake_archive)

    resp = {
        "identificacion": {
            "numeroControl": control,
            "tipoDte": "03",
        }
    }
    entry = {"row_type": "venta", "venta_id": venta_id, "name": control, "control": control}
    factura = {"json": str(factura_json), "control": control}

    tab._handle_hacienda_rejection(resp, tipo_dte="03", entry=entry, factura=factura)

    assert db.get_dte_correlativo("03", "001", "001") == 404
    assert db.get_venta_by_id(venta_id) is not None
    assert not archive_called


def test_rejected_invoice_with_revert_rolls_back_correlativo(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db, credito=True)
    correlativo = 404
    db.set_dte_correlativo("03", "001", "001", correlativo)

    control = f"DTE-03-S001P001-{correlativo:015d}"
    factura_json = tmp_path / "factura.json"
    factura_json.write_text(json.dumps({"identificacion": {"numeroControl": control}}))

    tab = _make_tab(db, cid)

    class AcceptDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec_(self):
            return QDialog.Accepted

    monkeypatch.setattr(facturacion_tab, "DTERechazadoDialog", AcceptDialog)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)

    archive_called = False

    def fake_archive(self, entry, factura):
        nonlocal archive_called
        archive_called = True
        self.manager.db.delete_venta(entry["venta_id"])

    monkeypatch.setattr(facturacion_tab.FacturacionTab, "_archive_rejected_invoice", fake_archive)

    resp = {
        "identificacion": {
            "numeroControl": control,
            "tipoDte": "03",
        }
    }
    entry = {"row_type": "venta", "venta_id": venta_id, "name": control, "control": control}
    factura = {"json": str(factura_json), "control": control}

    tab._handle_hacienda_rejection(resp, tipo_dte="03", entry=entry, factura=factura)

    assert archive_called
    assert db.get_dte_correlativo("03", "001", "001") == 403
    assert db.get_venta_by_id(venta_id) is None
