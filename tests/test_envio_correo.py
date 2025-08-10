import os
import smtplib
import pytest
from PyQt5.QtWidgets import QApplication, QTableWidgetItem, QMessageBox

from sales_tab import SalesTab


class FakeDB:
    def __init__(self):
        self._ventas = []
        self.detalles = {}
        self.saved = None
        self.envios = []

    def get_ventas(self):
        return self._ventas

    def get_venta_credito_fiscal(self, vid):
        return None

    def get_detalles_venta(self, vid):
        return self.detalles.get(vid, [])

    def get_trabajador(self, vid):
        return None

    def add_factura_pdf(self, vid, tipo, path):
        self.saved = (vid, tipo, path)
        self.factura_path = path

    def add_ticket_pdf(self, *args):
        self.saved = args

    def get_ticket_pdf(self, vid):
        return None

    def get_factura_pdf(self, vid):
        return self.factura_path

    def registrar_envio_dte(self, venta_id, modo, estado, sello, respuesta_json=""):
        self.envios.append(
            {"venta_id": venta_id, "modo": modo, "estado": estado, "sello": sello}
        )


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
        monkeypatch.setattr(SalesTab, "show_sale", lambda self, clear=False: None)
    tab = SalesTab(man, check_smtp=False)
    tab.sales_table.setRowCount(1)
    tab.sales_table.setItem(0, 0, QTableWidgetItem("1"))
    return db, tab


def test_transmit_success_email_fail(qt_app, tmp_path, monkeypatch):
    db, tab = _setup_tab(tmp_path, monkeypatch)
    pdf = tmp_path / "doc.pdf"

    def fake_gen(self, vid):
        pdf.write_bytes(b"%PDF")
        pdf.with_suffix(".json").write_text("{}", encoding="utf-8")
        self.manager.db.add_factura_pdf(vid, "Factura", str(pdf))
        return str(pdf)

    monkeypatch.setattr(SalesTab, "_generate_invoice_pdf", fake_gen)
    monkeypatch.setattr(
        SalesTab,
        "_check_smtp_credentials",
        lambda self: {"server": "s", "port": 25, "user": "u", "password": "p"},
    )

    def fake_transmitir(db_obj, venta_id, modo="normal", tipo_dte="01"):
        db_obj.registrar_envio_dte(venta_id, modo, "Transmitido", "S")
        return {"estado": "Transmitido"}

    monkeypatch.setattr("sales_tab.transmitir_dte", fake_transmitir)

    def fake_send(self):
        raise smtplib.SMTPException("fail")

    def fake_start(self):
        try:
            self.send()
        except smtplib.SMTPException as e:
            self.finished.emit(False, str(e))

    monkeypatch.setattr("utils.email_sender.EmailSender.send", fake_send, raising=False)
    monkeypatch.setattr("utils.email_sender.EmailSender.start", fake_start)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)

    tab.sales_table.selectRow(0)
    tab.save_and_send()
    qt_app.processEvents()

    assert db.envios and db.envios[0]["estado"] == "Transmitido"
    assert tab.status_label.text() == "Estado actual: Error"
    assert tab.retry_btn.isEnabled()
