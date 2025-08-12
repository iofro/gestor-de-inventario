import os
import smtplib
import pytest
from PyQt5.QtWidgets import QTableWidgetItem, QMessageBox

from sales_tab import SalesTab


class DummySignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, cb):
        self._callbacks.append(cb)

    def emit(self, *args, **kwargs):
        for cb in list(self._callbacks):
            cb(*args, **kwargs)


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
    

def _setup_tab(venta, cliente, producto, monkeypatch=None):
    db = FakeDB()
    db._ventas.append(venta)
    db.detalles[venta["id"]] = [{**producto, "cantidad": 1, "precio_unitario": 10}]
    man = Manager(db)
    man._clientes.append(cliente)
    if monkeypatch:
        monkeypatch.setattr(SalesTab, "load_sales", lambda self: None)
        monkeypatch.setattr(SalesTab, "_load_email_config", lambda self: None)
        monkeypatch.setattr(SalesTab, "show_sale", lambda self, clear=False: None)
    tab = SalesTab(man, check_smtp=False)
    tab.sales_table.setRowCount(1)
    tab.sales_table.setItem(0, 0, QTableWidgetItem(str(venta["id"])))
    return db, tab


def test_transmit_success_email_fail(
    qt_app,
    pdf_json_files,
    monkeypatch,
    venta_factory,
    cliente_factory,
    producto_factory,
):
    pdf, _json = pdf_json_files
    venta = venta_factory()
    cliente = cliente_factory(id=venta["cliente_id"])
    producto = producto_factory()
    db, tab = _setup_tab(venta, cliente, producto, monkeypatch)

    def fake_gen(manager, vid, p=pdf):
        manager.db.add_factura_pdf(vid, "Factura", str(p))
        return str(p)

    monkeypatch.setattr("sales_tab.generate_invoice_pdf", fake_gen)
    monkeypatch.setattr(
        SalesTab,
        "_check_smtp_credentials",
        lambda self: {"server": "s", "port": 25, "user": "u", "password": "p"},
    )

    def fake_transmitir(db_obj, venta_id, modo="normal", tipo_dte="01"):
        db_obj.registrar_envio_dte(venta_id, modo, "Transmitido", "S")
        return {"estado": "Transmitido"}

    monkeypatch.setattr("sales_tab.transmitir_dte", fake_transmitir)

    init_calls = []

    def fake_init(self, server, port, user, password, to_addr, subject, body, attachments):
        init_calls.append(to_addr)
        self.to_addr = to_addr
        self.subject = subject
        self.attachments = attachments if isinstance(attachments, list) else [attachments]
        self.finished = DummySignal()

    monkeypatch.setattr("utils.email_sender.EmailSender.__init__", fake_init, raising=False)

    send_called = {}

    def fake_send(self):
        send_called["called"] = True
        raise smtplib.SMTPException("fail")

    def fake_start(self):
        try:
            self.send()
        except smtplib.SMTPException as e:
            self.finished.emit(False, str(e))

    monkeypatch.setattr("utils.email_sender.EmailSender.send", fake_send, raising=False)
    monkeypatch.setattr("utils.email_sender.EmailSender.start", fake_start)

    smtp_calls = []

    class DummySMTP:
        def __init__(self, *a, **k):
            smtp_calls.append((a, k))

    monkeypatch.setattr(smtplib, "SMTP", DummySMTP)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)

    tab.sales_table.selectRow(0)
    tab.save_and_send()
    qt_app.processEvents()

    assert send_called.get("called")
    assert db.envios and db.envios[0]["estado"] == "Transmitido"
    assert pdf.exists()
    assert len(init_calls) == 1
    assert not smtp_calls


def test_email_exitoso(
    qt_app,
    pdf_json_files,
    monkeypatch,
    venta_factory,
    cliente_factory,
    producto_factory,
):
    pdf, _json = pdf_json_files
    venta = venta_factory()
    cliente = cliente_factory(id=venta["cliente_id"])
    producto = producto_factory()
    db, tab = _setup_tab(venta, cliente, producto, monkeypatch)
    tab.email_subject_edit.setText("Factura enviada")

    def fake_gen(manager, vid, p=pdf):
        manager.db.add_factura_pdf(vid, "Factura", str(p))
        return str(p)

    monkeypatch.setattr("sales_tab.generate_invoice_pdf", fake_gen)
    monkeypatch.setattr(
        SalesTab,
        "_check_smtp_credentials",
        lambda self: {"server": "s", "port": 25, "user": "u", "password": "p"},
    )

    monkeypatch.setattr(
        "sales_tab.transmitir_dte",
        lambda db_obj, venta_id, modo="normal", tipo_dte="01": {"estado": "Transmitido"},
    )

    captured = {}

    init_calls = []

    def fake_init(self, server, port, user, password, to_addr, subject, body, attachments):
        init_calls.append(to_addr)
        self.to_addr = to_addr
        self.subject = subject
        self.attachments = attachments if isinstance(attachments, list) else [attachments]
        self.finished = DummySignal()

    monkeypatch.setattr("utils.email_sender.EmailSender.__init__", fake_init, raising=False)

    def fake_send(self):
        captured["to"] = self.to_addr
        captured["subject"] = self.subject
        captured["attachments"] = list(self.attachments)
        self.finished.emit(True, "ok")

    def fake_start(self):
        self.send()

    monkeypatch.setattr("utils.email_sender.EmailSender.send", fake_send, raising=False)
    monkeypatch.setattr("utils.email_sender.EmailSender.start", fake_start)

    smtp_calls = []

    class DummySMTP:
        def __init__(self, *a, **k):
            smtp_calls.append((a, k))

    monkeypatch.setattr(smtplib, "SMTP", DummySMTP)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)

    tab.sales_table.selectRow(0)
    tab.save_and_send()
    qt_app.processEvents()

    assert captured["to"] == "cli@example.com"
    assert captured["subject"] == "Factura enviada"
    assert {os.path.basename(p) for p in captured["attachments"]} == {
        pdf.name,
        pdf.with_suffix(".json").name,
    }
    assert db.saved == (1, "Factura", str(pdf))
    assert len(init_calls) == 1
    assert not smtp_calls


def test_transmit_fail_no_email(
    qt_app,
    pdf_json_files,
    monkeypatch,
    venta_factory,
    cliente_factory,
    producto_factory,
):
    pdf, _json = pdf_json_files
    venta = venta_factory()
    cliente = cliente_factory(id=venta["cliente_id"])
    producto = producto_factory()
    db, tab = _setup_tab(venta, cliente, producto, monkeypatch)

    def fake_gen(manager, vid, p=pdf):
        manager.db.add_factura_pdf(vid, "Factura", str(p))
        return str(p)

    monkeypatch.setattr("sales_tab.generate_invoice_pdf", fake_gen)
    monkeypatch.setattr(
        "sales_tab.transmitir_dte", lambda *a, **k: {"estado": "error"}
    )

    called = {}

    def fake_send(self):
        called["called"] = True

    monkeypatch.setattr(SalesTab, "send_email", fake_send)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    tab.sales_table.selectRow(0)
    tab.save_and_send()

    assert "called" not in called

