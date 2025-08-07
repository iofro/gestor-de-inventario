import os
import warnings
import pytest
from PyQt5.QtWidgets import QApplication, QTableWidgetItem, QMessageBox

from sales_tab import SalesTab

warnings.filterwarnings(
    "ignore", message="Credenciales SMTP incompletas.*"
)


class FakeDB:
    def __init__(self):
        self._ventas = []
        self.detalles = {}
        self.saved = None

    def get_ventas(self):
        return self._ventas

    def get_venta_credito_fiscal(self, vid):
        return None

    def get_detalles_venta(self, vid):
        return self.detalles.get(vid, [])

    def get_trabajador(self, vid):
        return None

    def add_factura_pdf(self, *args):
        self.saved = args

    def add_ticket_pdf(self, *args):
        self.saved = args

    def get_ticket_pdf(self, vid):
        return None

    def get_factura_pdf(self, vid):
        return self.factura_path


class Manager:
    def __init__(self, db):
        self.db = db
        self._Distribuidores = []
        self._clientes = []
        self._vendedores = []


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app


def _setup_tab(tmp_path, monkeypatch=None):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10, "cliente_id": 1}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10}]
    man = Manager(db)
    man._clientes.append({"id": 1, "email": "cli@example.com", "nombre": "C"})
    if monkeypatch:
        monkeypatch.setattr(SalesTab, "load_sales", lambda self: None)
        monkeypatch.setattr(SalesTab, "_load_email_config", lambda self: None)
        monkeypatch.setattr(SalesTab, "_check_smtp_credentials", lambda self: {})
        monkeypatch.setattr(SalesTab, "show_sale", lambda self, clear=False: None)
    tab = SalesTab(man, check_smtp=False)
    tab.sales_table.setRowCount(1)
    tab.sales_table.setItem(0, 0, QTableWidgetItem("1"))
    return db, tab


def test_send_email_builds_message_and_marks_status(qt_app, tmp_path, monkeypatch):
    db, tab = _setup_tab(tmp_path, monkeypatch)
    pdf = tmp_path / "fact.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    pdf.with_suffix(".json").write_text("{}", encoding="utf-8")
    db.factura_path = str(pdf)

    tab.sales_table.selectRow(0)

    tab.email_subject_edit.setText("Subject")
    tab.email_body_edit.setText("Body")

    monkeypatch.setattr(SalesTab, "_check_smtp_credentials", lambda self: {"server": "s", "port": 25, "user": "u", "password": "p"})

    calls = {}

    def fake_send(self):
        calls.update({"to": self.to_addr, "subject": self.subject, "body": self.body, "attachments": self.attachments})
        self.finished.emit(True, "ok")

    monkeypatch.setattr("utils.email_sender.EmailSender.send", fake_send, raising=False)
    monkeypatch.setattr("utils.email_sender.EmailSender.start", lambda self: self.send())
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    tab.send_email()
    qt_app.processEvents()

    assert calls["subject"] == "Subject"
    assert calls["body"].startswith("Body")
    assert tab.status_label.text() == "Estado actual: Enviado"


def test_save_and_send_generates_files_and_registers(qt_app, tmp_path, monkeypatch):
    db, tab = _setup_tab(tmp_path, monkeypatch)
    pdf = tmp_path / "doc.pdf"

    def fake_gen(self, vid):
        pdf.write_bytes(b"%PDF")
        pdf.with_suffix(".json").write_text("{}", encoding="utf-8")
        self.manager.db.add_factura_pdf(vid, "Factura", str(pdf))
        return str(pdf)

    monkeypatch.setattr(SalesTab, "_generate_invoice_pdf", fake_gen)
    monkeypatch.setattr(SalesTab, "send_email", lambda self: None)
    monkeypatch.setattr("sales_tab.transmitir_dte", lambda *a, **k: {"estado": "recibido"})
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    tab.sales_table.selectRow(0)
    tab.save_and_send()

    assert pdf.exists()
    assert pdf.with_suffix(".json").exists()
    assert db.saved == (1, "Factura", str(pdf))
