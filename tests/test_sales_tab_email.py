import os
import warnings
import json
import pytest
from PyQt5.QtWidgets import QTableWidgetItem, QMessageBox

from sales_tab import SalesTab

warnings.filterwarnings(
    "ignore", message="Credenciales SMTP incompletas.*"
)


class FakeDB:
    def __init__(self):
        self._ventas = []
        self.detalles = {}
        self.saved = None
        self.envios = []

    def get_ventas(self):
        return self._ventas

    def get_venta_by_id(self, vid):
        return next((v for v in self._ventas if int(v["id"]) == vid), None)

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

    def registrar_envio_dte(self, *args):
        self.envios.append(args)


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
        monkeypatch.setattr(SalesTab, "_check_smtp_credentials", lambda self: {})
        monkeypatch.setattr(SalesTab, "show_sale", lambda self, clear=False: None)
    tab = SalesTab(man, check_smtp=False)
    tab.sales_table.setRowCount(1)
    tab.sales_table.setItem(0, 0, QTableWidgetItem(str(venta["id"])))
    return db, tab


def test_send_email_builds_message_and_marks_status(
    qt_app,
    pdf_json_files,
    monkeypatch,
    venta_factory,
    cliente_factory,
    producto_factory,
):
    pdf, json_path = pdf_json_files
    venta = venta_factory()
    cliente = cliente_factory(id=venta["cliente_id"])
    producto = producto_factory()
    db, tab = _setup_tab(venta, cliente, producto, monkeypatch)
    db.factura_path = str(pdf)

    tab.sales_table.selectRow(0)

    tab.email_subject_edit.setText("Subject")
    tab.email_body_edit.setText("Body")

    monkeypatch.setattr(SalesTab, "_check_smtp_credentials", lambda self: {"server": "s", "port": 25, "user": "u", "password": "p"})

    calls = {"count": 0}

    def fake_send(self):
        calls.update(
            {
                "to": self.to_addr,
                "subject": self.subject,
                "body": self.body,
                "attachments": self.attachments,
            }
        )
        calls["count"] += 1
        self.finished.emit(True, "ok")

    monkeypatch.setattr("utils.email_sender.EmailSender.send", fake_send, raising=False)
    monkeypatch.setattr("utils.email_sender.EmailSender.start", lambda self: self.send())
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    tab.send_email()
    qt_app.processEvents()

    assert calls["count"] == 1
    assert calls["subject"] == "Subject"
    assert calls["body"].startswith("Body")
    assert {os.path.basename(p) for p in calls["attachments"]} == {
        pdf.name,
        json_path.name,
    }


def test_save_invoice_generates_files_and_registers(
    qt_app,
    pdf_json_files,
    monkeypatch,
    venta_factory,
    cliente_factory,
    producto_factory,
):
    pdf, json_path = pdf_json_files
    venta = venta_factory()
    cliente = cliente_factory(id=venta["cliente_id"])
    producto = producto_factory()
    db, tab = _setup_tab(venta, cliente, producto, monkeypatch)

    def fake_gen(manager, vid):
        pdf.write_bytes(b"%PDF")
        json_path.write_text("{}", encoding="utf-8")
        manager.db.add_factura_pdf(vid, "Factura", str(pdf))
        return str(pdf)

    monkeypatch.setattr("sales_tab.generate_invoice_pdf", fake_gen)
    called = {}
    monkeypatch.setattr("dte.transmitir_dte", lambda *a, **k: called.setdefault("tx", True))
    monkeypatch.setattr(SalesTab, "send_email", lambda self: called.setdefault("email", True))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    tab.sales_table.selectRow(0)
    tab.save_invoice()

    assert pdf.exists()
    assert pdf.with_suffix(".json").exists()
    assert db.saved == (1, "Factura", str(pdf))
    assert "tx" not in called
    assert "email" not in called


def test_save_invoice_contingencia_no_transmit(
    qt_app,
    pdf_json_files,
    monkeypatch,
    venta_factory,
    cliente_factory,
    producto_factory,
):
    import dte

    pdf, json_path = pdf_json_files
    venta = venta_factory(modo_transmision="contingencia")
    cliente = cliente_factory(id=venta["cliente_id"])
    producto = producto_factory()
    db, tab = _setup_tab(venta, cliente, producto, monkeypatch)

    def fake_gen(manager, vid):
        pdf.write_bytes(b"%PDF")
        json_path.write_text("{}", encoding="utf-8")
        manager.db.add_factura_pdf(vid, "Factura", str(pdf))
        return str(pdf)

    monkeypatch.setattr("sales_tab.generate_invoice_pdf", fake_gen)
    called = {}
    monkeypatch.setattr("dte.transmitir_dte", lambda *a, **k: called.setdefault("tx", True))
    mensajes = []

    def fake_info(parent, title, text):
        mensajes.append((title, text))

    monkeypatch.setattr(QMessageBox, "information", fake_info)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    tab.sales_table.selectRow(0)
    tab.save_invoice()

    assert "tx" not in called
    assert any(
        title == "Guardar factura" and text.startswith("Factura guardado")
        for title, text in mensajes
    )


def test_save_invoice_ignores_config_transmission(
    qt_app,
    tmp_path,
    pdf_json_files,
    monkeypatch,
    venta_factory,
    cliente_factory,
    producto_factory,
):
    import dte

    pdf, json_path = pdf_json_files
    venta = venta_factory()  # sin modo_transmision
    cliente = cliente_factory(id=venta["cliente_id"])
    producto = producto_factory()
    db, tab = _setup_tab(venta, cliente, producto, monkeypatch)

    def fake_gen(manager, vid):
        pdf.write_bytes(b"%PDF")
        json_path.write_text("{}", encoding="utf-8")
        manager.db.add_factura_pdf(vid, "Factura", str(pdf))
        return str(pdf)

    monkeypatch.setattr("sales_tab.generate_invoice_pdf", fake_gen)

    datos_file = tmp_path / "datos_negocio.json"
    datos_file.write_text(
        json.dumps(
            {
                "dte_api": {
                    "modo_transmision": "2 - Contingencia",
                    "tipo_contingencia": 1,
                    "motivo_contin": "",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sales_tab.DATOS_NEGOCIO_PATH", str(datos_file))

    called = {}
    monkeypatch.setattr("dte.transmitir_dte", lambda *a, **k: called.setdefault("tx", True))

    tab.sales_table.selectRow(0)
    tab.save_invoice()

    assert "tx" not in called


def test_save_invoice_without_docs_generates_ticket(
    qt_app,
    pdf_json_files,
    monkeypatch,
    venta_factory,
    cliente_factory,
    producto_factory,
):
    pdf, json_path = pdf_json_files
    venta = venta_factory()
    cliente = cliente_factory(id=venta["cliente_id"], nit="", dui="")
    producto = producto_factory()
    db, tab = _setup_tab(venta, cliente, producto, monkeypatch)

    def fake_ticket(manager, vid):
        pdf.write_bytes(b"%PDF")
        json_path.write_text("{}", encoding="utf-8")
        manager.db.add_ticket_pdf(vid, str(pdf))
        return str(pdf)

    monkeypatch.setattr("sales_tab.generate_ticket_pdf", fake_ticket)
    monkeypatch.setattr(
        "sales_tab.generate_invoice_pdf",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no invoice")),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    tab.sales_table.selectRow(0)
    tab.save_invoice()

    assert pdf.exists()
    assert json_path.exists()
    assert db.saved == (venta["id"], str(pdf))
