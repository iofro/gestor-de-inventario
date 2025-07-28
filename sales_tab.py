from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QLabel,
    QSplitter,
    QDateEdit,
    QTextEdit,
    QMessageBox,
    QFileDialog,
    QAbstractItemView,

    QHeaderView,
    QSizePolicy,

    QInputDialog,
    QDialog,

)
from PyQt5.QtCore import Qt, QDate, QUrl, QThread, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QPixmap
from datetime import datetime
from factura_sv import generar_factura_electronica_pdf
from utils.monto import monto_a_texto_sv
from utils.docs import get_document_paths, build_invoice_json
from dte import generar_ticket_json
from utils.jws import get_cert_config, sign_and_save
from ticket_pdf import generar_ticket_personalizado
from dialogs import ManualInvoiceDialog
import tempfile
import subprocess
import shutil
import os
import json
import uuid
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "datos_negocio.json")

CF_DIR = os.path.join(os.path.dirname(__file__), "facturas_consumidor_final")
CREDITO_DIR = os.path.join(os.path.dirname(__file__), "facturas_credito_fiscal")
TICKETS_DIR = os.path.join(os.path.dirname(__file__), "tickets")


class EmailSender(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, server, port, user, password, to_addr, subject, body, attachments):
        super().__init__()
        self.server = server
        self.port = port
        self.user = user
        self.password = password
        self.to_addr = to_addr
        self.subject = subject
        self.body = body
        if isinstance(attachments, str):
            self.attachments = [attachments]
        else:
            self.attachments = attachments or []

    def run(self):
        try:
            msg = MIMEMultipart()
            msg["From"] = self.user
            msg["To"] = self.to_addr
            msg["Subject"] = self.subject
            msg.attach(MIMEText(self.body or "", "plain"))

            for path in self.attachments:
                with open(path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{os.path.basename(path)}"',
                )
                msg.attach(part)

            smtp = smtplib.SMTP(self.server, int(self.port))
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(msg)
            smtp.quit()
            self.finished.emit(True, "Correo enviado correctamente")
        except Exception as e:
            self.finished.emit(False, str(e))


class SalesTab(QWidget):
    """Simple tab to list sales and preview invoices."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.current_credito_fiscal = None
        self.preview_pdf_file = None
        self.preview_image_file = None
        self.email_subject = ""
        self.email_body = ""
        self.email_thread = None
        self._setup_ui()
        self._load_email_config()
        self.load_sales()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)

        # Left panel
        left_layout = QVBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar número o cliente")
        self.search_bar.textChanged.connect(self.load_sales)
        left_layout.addWidget(self.search_bar)

        filter_layout = QHBoxLayout()
        self.date_from = QDateEdit(QDate.currentDate().addYears(-2))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_from.dateChanged.connect(self.load_sales)
        self.date_to.dateChanged.connect(self.load_sales)
        filter_layout.addWidget(self.date_from)
        filter_layout.addWidget(self.date_to)
        left_layout.addLayout(filter_layout)

        self.client_filter = QLineEdit()
        self.client_filter.setPlaceholderText("Cliente")
        self.client_filter.textChanged.connect(self.load_sales)
        left_layout.addWidget(self.client_filter)

        self.sales_table = QTableWidget(0, 5)
        self.sales_table.setHorizontalHeaderLabels([
            "Nº Factura", "Cliente", "Fecha", "Total", "Estado"
        ])
        self.sales_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sales_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sales_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sales_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.sales_table.itemSelectionChanged.connect(self.show_sale)
        left_layout.addWidget(self.sales_table)

        self.new_invoice_btn = QPushButton("+ Generar nueva factura manual")
        self.new_invoice_btn.clicked.connect(self.generate_manual_invoice)
        left_layout.addWidget(self.new_invoice_btn)

        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        # Right panel
        splitter = QSplitter(Qt.Vertical)

        preview_layout = QVBoxLayout()
        self.preview_label = QLabel("Previsualización del PDF")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#DDD; padding:20px;")
        # Avoid stretching the image so the aspect ratio of the PDF is preserved
        self.preview_label.setScaledContents(False)
        preview_layout.addWidget(self.preview_label)

        self.info_label = QLabel()
        preview_layout.addWidget(self.info_label)

        btn_layout = QHBoxLayout()
        self.btn_guardar = QPushButton("Guardar factura")
        self.btn_enviar = QPushButton("Enviar por correo")
        self.btn_enviar_ticket = QPushButton("Enviar ticket")
        self.btn_ticket = QPushButton("Ticket")
        btn_layout.addWidget(self.btn_guardar)
        btn_layout.addWidget(self.btn_enviar)
        btn_layout.addWidget(self.btn_enviar_ticket)
        btn_layout.addWidget(self.btn_ticket)
        self.btn_guardar.clicked.connect(self.save_pdf)
        self.btn_enviar.clicked.connect(self.send_email)
        self.btn_enviar_ticket.clicked.connect(self.send_ticket_email)
        self.btn_ticket.clicked.connect(self.save_ticket)
        preview_layout.addLayout(btn_layout)

        preview_widget = QWidget()
        preview_widget.setLayout(preview_layout)

        status_layout = QVBoxLayout()
        self.status_label = QLabel("Estado actual: ")
        self.gen_label = QLabel("Generado: ")
        self.sent_label = QLabel("Último envío: ")
        self.email_label = QLabel("Correo destinatario: ")
        self.email_subject_edit = QLineEdit()
        self.email_body_edit = QTextEdit()
        self.retry_btn = QPushButton("Reintentar envío")
        self.config_email_btn = QPushButton("Configurar correo")
        self.email_subject_edit.textChanged.connect(lambda t: setattr(self, "email_subject", t))
        self.email_body_edit.textChanged.connect(lambda: setattr(self, "email_body", self.email_body_edit.toPlainText()))
        self.retry_btn.clicked.connect(self.send_email)
        self.config_email_btn.clicked.connect(self.configure_email)
        self.retry_btn.setEnabled(False)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.gen_label)
        status_layout.addWidget(self.sent_label)
        status_layout.addWidget(self.email_label)
        status_layout.addWidget(QLabel("Asunto:"))
        status_layout.addWidget(self.email_subject_edit)
        status_layout.addWidget(QLabel("Mensaje:"))
        status_layout.addWidget(self.email_body_edit)
        btns_layout = QHBoxLayout()
        btns_layout.addWidget(self.retry_btn)
        btns_layout.addWidget(self.config_email_btn)
        status_layout.addLayout(btns_layout)
        status_widget = QWidget()
        status_widget.setLayout(status_layout)

        splitter.addWidget(preview_widget)
        splitter.addWidget(status_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(left_widget)
        main_layout.addWidget(splitter)
        main_layout.setStretch(0, 2)
        main_layout.setStretch(1, 3)

    def load_sales(self):
        ventas = self.manager.db.get_ventas()
        search = self.search_bar.text().lower()
        cliente_filter = self.client_filter.text().lower()
        d_from = self.date_from.date().toPyDate()
        d_to = self.date_to.date().toPyDate()
        rows = []
        for v in ventas:
            fecha = v.get("fecha")
            try:
                fdate = datetime.strptime(fecha, "%Y-%m-%d %H:%M:%S").date()
            except ValueError:
                try:
                    fdate = datetime.strptime(fecha, "%Y-%m-%d").date()
                except ValueError:
                    fdate = None
            if fdate and (fdate < d_from or fdate > d_to):
                continue
            cliente = ""
            if v.get("cliente_id"):
                cli = next((c for c in self.manager._clientes if c["id"] == v["cliente_id"]), None)
                if cli:
                    cliente = cli.get("nombre", "")
            if cliente_filter and cliente_filter not in cliente.lower():
                continue
            if search and search not in str(v.get("id")).lower() and search not in cliente.lower():
                continue
            rows.append((v, cliente))

        self.sales_table.setRowCount(len(rows))
        for row, (venta, cli) in enumerate(rows):
            self.sales_table.setItem(row, 0, QTableWidgetItem(str(venta.get("id"))))
            self.sales_table.setItem(row, 1, QTableWidgetItem(cli))
            self.sales_table.setItem(row, 2, QTableWidgetItem(venta.get("fecha", "")))
            self.sales_table.setItem(row, 3, QTableWidgetItem(f"${venta.get('total', 0):.2f}"))
            estado = venta.get("estado", "Pendiente")
            self.sales_table.setItem(row, 4, QTableWidgetItem(estado))
        if rows:
            self.sales_table.selectRow(0)
        else:
            self.show_sale(clear=True)

    def show_sale(self, clear=False):
        if clear or self.sales_table.currentRow() < 0:
            self.preview_label.setText("Previsualización del PDF")
            self.info_label.setText("")
            self.status_label.setText("Estado actual: ")
            self.gen_label.setText("Generado: ")
            self.sent_label.setText("Último envío: ")
            self.email_label.setText("Correo destinatario: ")
            self.email_subject_edit.clear()
            self.email_body_edit.clear()
            self._clear_preview_files()
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        cliente = ""
        cliente_email = ""
        if venta and venta.get("cliente_id"):
            cli = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
            if cli:
                cliente = cli.get("nombre", "")
                cliente_email = cli.get("email", "")

        # Fetch credit-fiscal information for this sale
        self.current_credito_fiscal = self.manager.db.get_venta_credito_fiscal(venta_id)
        if self.current_credito_fiscal:
            self.info_label.setText(
                f"Factura {venta_id} - Crédito Fiscal - Cliente: {cliente}"
            )
        else:
            self.info_label.setText(f"Factura {venta_id} - Cliente: {cliente}")
        # Generate and display preview image for the selected invoice
        self.email_label.setText(f"Correo destinatario: {cliente_email}")
        self._update_preview(venta_id)
        self._update_email_preview()

    def _clear_preview_files(self):
        """Remove temporary preview image without deleting stored PDFs."""
        if self.preview_image_file and os.path.exists(self.preview_image_file):
            try:
                os.remove(self.preview_image_file)
            except OSError:
                pass
        self.preview_pdf_file = None
        self.preview_image_file = None

    def _update_email_preview(self):
        self.email_subject_edit.setText(self.email_subject)
        self.email_body_edit.setPlainText(self.email_body)

    def edit_email(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Editar correo")
        layout = QVBoxLayout(dialog)
        subject_edit = QLineEdit(self.email_subject)
        body_edit = QTextEdit()
        body_edit.setPlainText(self.email_body)
        layout.addWidget(QLabel("Asunto:"))
        layout.addWidget(subject_edit)
        layout.addWidget(QLabel("Cuerpo:"))
        layout.addWidget(body_edit)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("Aceptar")
        cancel_btn = QPushButton("Cancelar")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)
        if dialog.exec_() == QDialog.Accepted:
            self.email_subject = subject_edit.text()
            self.email_body = body_edit.toPlainText()
            self._update_email_preview()

    def configure_email(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Configurar correo")
        layout = QVBoxLayout(dialog)
        subject_edit = QLineEdit(self.email_subject)
        body_edit = QTextEdit()
        body_edit.setPlainText(self.email_body)
        layout.addWidget(QLabel("Asunto por defecto:"))
        layout.addWidget(subject_edit)
        layout.addWidget(QLabel("Mensaje por defecto:"))
        layout.addWidget(body_edit)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("Guardar")
        cancel_btn = QPushButton("Cancelar")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)
        if dialog.exec_() == QDialog.Accepted:
            self.email_subject = subject_edit.text()
            self.email_body = body_edit.toPlainText()
            self._save_email_config()
            self._update_email_preview()

    def _load_email_config(self):
        path = DATOS_NEGOCIO_PATH
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.email_subject = data.get("default_email_subject", "")
                self.email_body = data.get("default_email_body", "")
            except Exception:
                pass
        self._update_email_preview()

    def _save_email_config(self):
        path = DATOS_NEGOCIO_PATH
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["default_email_subject"] = self.email_subject
        data["default_email_body"] = self.email_body
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _check_smtp_credentials(self):
        """Warn user if SMTP settings are incomplete when the tab is opened."""
        path = DATOS_NEGOCIO_PATH
        if not os.path.exists(path):
            QMessageBox.warning(
                self,
                "Configuración de correo",
                "Credenciales SMTP incompletas. Configure sus datos en la opción 'Configuración de correo'.",
            )
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            QMessageBox.warning(
                self,
                "Configuración de correo",
                "Credenciales SMTP incompletas. Configure sus datos en la opción 'Configuración de correo'.",
            )
            return

        server = data.get("smtp_server")
        port = data.get("smtp_port")
        user = data.get("email_usuario") or data.get("email")
        password = os.getenv("INVENTARIO_EMAIL_PASSWORD")

        if not data.get("email_usuario") and user:
            data["email_usuario"] = user
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        if not all([server, port, user, password]):
            QMessageBox.warning(
                self,
                "Configuración de correo",
                "Credenciales SMTP incompletas. Configure sus datos en la opción 'Configuración de correo'.",
            )

    def _update_preview(self, venta_id):
        """Generate PDF preview image for the given sale ID and display it."""
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            self.preview_label.setText("Previsualización del PDF")
            return

        self._clear_preview_files()

        pdf_path = self.manager.db.get_factura_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            pdf_path = self._generate_invoice_pdf(venta_id)
            if not pdf_path:
                self.preview_label.setText("No se pudo generar previsualización")
                return

        prefix = tempfile.mktemp()
        try:
            png_path = prefix + ".png"
            if shutil.which("pdftoppm"):
                subprocess.run([
                    "pdftoppm",
                    "-png",
                    "-singlefile",
                    pdf_path,
                    prefix,
                ], check=True)
            else:
                import fitz

                doc = fitz.open(pdf_path)
                page = doc.load_page(0)
                pix = page.get_pixmap()
                pix.save(png_path)

            self.preview_pdf_file = pdf_path
            self.preview_image_file = png_path
            pixmap = QPixmap(png_path)
            if pixmap.isNull():
                raise RuntimeError("failed to load image")
            # Scale down a bit but keep the PDF aspect ratio intact
            scaled = pixmap.scaled(
                int(self.preview_label.width() * 0.9),
                int(self.preview_label.height() * 0.9),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled)
            self.preview_label.setText("")
        except Exception:
            self.preview_label.setText("No se pudo generar previsualización")
            self._clear_preview_files()

    def _generate_invoice_pdf(self, venta_id):
        """Generate and store the invoice PDF for the given sale."""
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            return None

        credito_info = self.manager.db.get_venta_credito_fiscal(venta_id)
        detalles = self.manager.db.get_detalles_venta(venta_id)

        venta_data = dict(venta)
        if credito_info:
            venta_data.update(credito_info)

        if venta_data.get("vendedor_id"):
            trabajador = self.manager.db.get_trabajador(venta_data["vendedor_id"])
            if trabajador:
                venta_data["vendedor_nombre"] = trabajador.get("nombre", "")

        sumas = descuentos = 0
        ventas_exentas = ventas_no_sujetas = iva = 0
        for d in detalles:
            base_total = d.get("precio_unitario", 0) * d.get("cantidad", 0)
            desc = d.get("descuento", 0)
            if d.get("descuento_tipo") == "%":
                desc = base_total * d.get("descuento", 0) / 100
            base = base_total - desc
            iva_item = d.get("iva", 0)
            tipo = d.get("tipo_fiscal", "").lower()
            if tipo == "venta exenta":
                d["ventas_exentas"] = base
                ventas_exentas += base
            elif tipo == "venta no sujeta":
                d["ventas_no_sujetas"] = base
                ventas_no_sujetas += base
            else:
                d["ventas_gravadas"] = base
                sumas += base_total
                descuentos += desc
                iva += iva_item

        subtotal = (sumas - descuentos) + iva
        total = subtotal + ventas_exentas + ventas_no_sujetas
        venta_data.update(
            {
                "sumas": sumas,
                "descuentos": descuentos,
                "iva": iva,
                "ventas_exentas": ventas_exentas,
                "ventas_no_sujetas": ventas_no_sujetas,
                "subtotal": subtotal,
                "total": total,
            }
        )
        if not venta_data.get("total_letras"):
            try:
                venta_data["total_letras"] = monto_a_texto_sv(total)
            except Exception:
                venta_data["total_letras"] = ""

        cliente = None
        if venta.get("cliente_id"):
            cliente = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
        distribuidor = None
        if venta.get("Distribuidor_id"):
            distribuidor = next(
                (d for d in self.manager._Distribuidores if d["id"] == venta["Distribuidor_id"]),
                None,
            )

        extra = venta_data.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        if not venta_data.get("venta_a_cuenta_de"):
            venta_data["venta_a_cuenta_de"] = extra.get("venta_a_cuenta_de", "")
        if not venta_data.get("documento_venta_a_cuenta"):
            venta_data["documento_venta_a_cuenta"] = extra.get("documento_venta_a_cuenta", "")
        dte_json = extra.get("dteJson") or extra.get("dte_json") or {}
        ident = dte_json.get("identificacion", {})
        codigo_generacion = venta_data.get("codigo_generacion") or ident.get("codigoGeneracion", "")
        numero_control = venta_data.get("numero_control") or dte_json.get("numeroControl", "")
        sello_recepcion = venta_data.get("sello_recepcion") or extra.get("selloRecibido", "")
        modelo_facturacion = venta_data.get("modelo_facturacion") or ident.get("modeloFacturacion", "")
        if not modelo_facturacion:
            modelo_facturacion = "1 - Facturación previo"
        tipo_transmision = venta_data.get("tipo_transmision") or ident.get("tipoTransmision", "")
        if not tipo_transmision:
            tipo_transmision = "1 - Transmisión normal"
        fecha_generacion = venta_data.get("fecha_generacion") or ident.get("fecGeneracion", "")

        if tipo_transmision.startswith("1") and not sello_recepcion:
            sello_recepcion = f"SELLO-{uuid.uuid4().hex[:8]}"
            venta_data["sello_recepcion"] = sello_recepcion
        venta_data["tipo_transmision"] = tipo_transmision

        tipo_doc = "Crédito Fiscal" if credito_info else "Consumidor Final"
        doc_key = "CreditoFiscal" if credito_info else "ConsumidorFinal"
        cliente_nombre = cliente.get("nombre") if cliente else ""
        file_path, json_path = get_document_paths(
            venta_data.get("fecha"), cliente_nombre, numero_control or venta_id, doc_key
        )

        generar_factura_electronica_pdf(
            venta_data,
            detalles,
            cliente or {},
            distribuidor or {},
            tipo_doc,
            archivo=file_path,
            codigo_generacion=codigo_generacion,
            numero_control=numero_control,
            sello_recepcion=sello_recepcion,
            modelo_facturacion=modelo_facturacion,
            tipo_transmision=tipo_transmision,
            fecha_generacion=fecha_generacion,
        )
        json_data = build_invoice_json(venta_data, cliente or {}, detalles)
        with open(json_path, 'w', encoding='utf-8') as fh:
            json.dump(json_data, fh, ensure_ascii=False, indent=2)
        if tipo_transmision.startswith("2"):
            self.manager.db.add_dte_pendiente(venta_id, json_data, tipo_transmision)
        if not os.path.exists(json_path):
            raise IOError(f"No se pudo guardar JSON en {json_path}")
        cert_path, cert_pass = get_cert_config(DATOS_NEGOCIO_PATH)
        if cert_path:
            try:
                sign_and_save(json_data, json_path, cert_path, cert_pass)
            except Exception:
                pass
        self.manager.db.add_factura_pdf(venta_id, tipo_doc, file_path)
        return file_path

    def _generate_ticket_pdf(self, venta_id):
        """Generate and store the ticket PDF for the given sale."""
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            return None

        detalles = self.manager.db.get_detalles_venta(venta_id)
        extra = {}
        raw_extra = venta.get("extra") if venta else None
        if raw_extra:
            try:
                extra = json.loads(raw_extra)
            except Exception:
                extra = {}

        cliente = None
        if venta.get("cliente_id"):
            cliente = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
        cliente_nombre = cliente.get("nombre") if cliente else ""

        filename, json_path = get_document_paths(
            venta.get("fecha"), cliente_nombre, venta_id, "Ticket"
        )

        generar_ticket_personalizado(venta, detalles, filename, dte_data=extra)
        if hasattr(self.manager.db, "cursor"):
            ticket_json = generar_ticket_json(self.manager.db, venta_id)
        else:
            ticket_json = {"venta": venta, "detalles": detalles}
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(ticket_json, fh, ensure_ascii=False, indent=2)
        if not os.path.exists(json_path):
            raise IOError(f"No se pudo guardar JSON en {json_path}")
        cert_path, cert_pass = get_cert_config(DATOS_NEGOCIO_PATH)
        if cert_path:
            try:
                sign_and_save(ticket_json, json_path, cert_path, cert_pass)
            except Exception:
                pass
        self.manager.db.add_ticket_pdf(venta_id, filename)
        return filename

    def save_pdf(self):
        """Generate a PDF for the selected sale after user confirmation."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Guardar factura", "Seleccione una factura primero.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())

        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Guardar factura", "No se encontró la venta seleccionada.")
            return

        credito_info = self.manager.db.get_venta_credito_fiscal(venta_id)
        mensaje = (
            "Esta venta está registrada como crédito fiscal, ¿desea continuar?"
            if credito_info
            else "Esta venta está registrada como consumidor final, ¿desea continuar?"
        )
        reply = QMessageBox.question(self, "Guardar factura", mensaje, QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            QMessageBox.information(
                self,
                "Guardar factura",
                "Si desea modificar esta factura presione generar nueva factura manual",
            )
            return
        file_path = self._generate_invoice_pdf(venta_id)
        if file_path:
            QMessageBox.information(self, "Guardar factura", f"Factura guardada en {file_path}")

    def save_ticket(self):
        """Generate a simple ticket PDF for the selected sale."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Ticket", "Seleccione una factura primero.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Ticket", "No se encontró la venta seleccionada.")
            return

        detalles = self.manager.db.get_detalles_venta(venta_id)
        extra = {}
        raw_extra = venta.get("extra") if venta else None
        if raw_extra:
            try:
                extra = json.loads(raw_extra)
            except Exception:
                extra = {}
        cliente = None
        if venta.get("cliente_id"):
            cliente = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
        cliente_nombre = cliente.get("nombre") if cliente else ""
        filename, json_path = get_document_paths(
            venta.get("fecha"), cliente_nombre, venta_id, "Ticket"
        )
        generar_ticket_personalizado(venta, detalles, filename, dte_data=extra)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump({"venta": venta, "detalles": detalles}, fh, ensure_ascii=False, indent=2)
        if not os.path.exists(json_path):
            raise IOError(f"No se pudo guardar JSON en {json_path}")
        cert_path, cert_pass = get_cert_config(DATOS_NEGOCIO_PATH)
        if cert_path:
            try:
                sign_and_save({"venta": venta, "detalles": detalles}, json_path, cert_path, cert_pass)
            except Exception:
                pass
        self.manager.db.add_ticket_pdf(venta_id, filename)
        QMessageBox.information(self, "Ticket", f"Ticket guardado en {filename}")

    def preview_pdf(self):
        """Generate a temporary PDF and open it with the default viewer."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Previsualizar", "Seleccione una factura primero.")

            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Previsualizar", "No se encontró la venta seleccionada.")

            return

        pdf_path = self.manager.db.get_factura_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            pdf_path = self._generate_invoice_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "Previsualizar", "No se pudo generar el PDF.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(pdf_path)))

    def print_pdf(self):
        """Print the selected sale by first generating a temporary PDF."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Imprimir", "Seleccione una factura primero.")
            return
        # Reuse preview_pdf to generate the file
        self.preview_pdf()

    def send_email(self):
        """Send the selected invoice via email in a background thread."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Enviar por correo", "No has seleccionado ninguna venta.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Enviar por correo", "No se encontró la venta seleccionada.")
            return

        cliente_email = ""
        if venta.get("cliente_id"):
            cli = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
            if cli:
                cliente_email = cli.get("email", "")
        if not cliente_email:
            QMessageBox.warning(self, "Enviar por correo", "El cliente no tiene correo registrado.")
            return

        subject = self.email_subject_edit.text().strip()
        body = self.email_body_edit.toPlainText()

        pdf_path = self.manager.db.get_factura_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            pdf_path = self._generate_invoice_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "Enviar por correo", "No se pudo generar el PDF.")
            return
        json_path = os.path.splitext(pdf_path)[0] + ".json"
        if not os.path.exists(json_path):
            # regenerate files to ensure JSON exists
            pdf_path = self._generate_invoice_pdf(venta_id)
            json_path = os.path.splitext(pdf_path)[0] + ".json"
            if not os.path.exists(json_path):
                QMessageBox.warning(self, "Enviar por correo", "No se encontró el JSON firmado.")
                return

        creds = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    creds = json.load(f)
            except Exception:
                creds = {}
        server = creds.get("smtp_server")
        port = creds.get("smtp_port")
        user = creds.get("email_usuario")
        password = os.getenv("INVENTARIO_EMAIL_PASSWORD")
        if not all([server, port, user, password]):
            QMessageBox.warning(self, "Enviar por correo", "Credenciales SMTP incompletas.")
            return

        body += (
            "\n\nSe adjuntan la representaci\u00f3n gr\u00e1fica en PDF y el documento firmado en formato JSON."
        )
        self.status_label.setText("Estado actual: Enviando...")
        self.retry_btn.setEnabled(False)
        self.btn_enviar.setEnabled(False)

        self.email_thread = EmailSender(
            server,
            port,
            user,
            password,
            cliente_email,
            subject,
            body,
            [pdf_path, json_path],
        )
        self.email_thread.finished.connect(self._on_email_sent)
        self.email_thread.start()

    def _on_email_sent(self, success, message):
        self.btn_enviar.setEnabled(True)
        if success:
            self.status_label.setText("Estado actual: Enviado")
            self.sent_label.setText("Último envío: " + datetime.now().strftime("%Y-%m-%d %H:%M"))
            QMessageBox.information(self, "Enviar por correo", message)
            self.retry_btn.setEnabled(False)
        else:
            self.status_label.setText("Estado actual: Error")
            QMessageBox.critical(self, "Enviar por correo", message)
            self.retry_btn.setEnabled(True)
        self.email_thread = None

    def send_ticket_email(self):
        """Send the selected ticket via email in a background thread."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Enviar ticket", "No has seleccionado ninguna venta.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Enviar ticket", "No se encontró la venta seleccionada.")
            return

        cliente_email = ""
        if venta.get("cliente_id"):
            cli = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
            if cli:
                cliente_email = cli.get("email", "")
        if not cliente_email:
            QMessageBox.warning(self, "Enviar ticket", "El cliente no tiene correo registrado.")
            return

        subject = self.email_subject_edit.text().strip()
        body = self.email_body_edit.toPlainText()

        pdf_path = self.manager.db.get_ticket_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            pdf_path = self._generate_ticket_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "Enviar ticket", "No se pudo generar el ticket.")
            return
        json_path = os.path.splitext(pdf_path)[0] + ".json"
        if not os.path.exists(json_path):
            pdf_path = self._generate_ticket_pdf(venta_id)
            json_path = os.path.splitext(pdf_path)[0] + ".json"
            if not os.path.exists(json_path):
                QMessageBox.warning(self, "Enviar ticket", "No se encontró el JSON firmado.")
                return

        creds = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    creds = json.load(f)
            except Exception:
                creds = {}
        server = creds.get("smtp_server")
        port = creds.get("smtp_port")
        user = creds.get("email_usuario")
        password = os.getenv("INVENTARIO_EMAIL_PASSWORD")
        if not all([server, port, user, password]):
            QMessageBox.warning(self, "Enviar ticket", "Credenciales SMTP incompletas.")
            return

        body += (
            "\n\nSe adjuntan la representaci\u00f3n gr\u00e1fica en PDF y el documento firmado en formato JSON."
        )
        self.status_label.setText("Estado actual: Enviando...")
        self.retry_btn.setEnabled(False)
        self.btn_enviar_ticket.setEnabled(False)

        self.email_thread = EmailSender(
            server,
            port,
            user,
            password,
            cliente_email,
            subject,
            body,
            [pdf_path, json_path],
        )
        self.email_thread.finished.connect(self._on_ticket_sent)
        self.email_thread.start()

    def _on_ticket_sent(self, success, message):
        self.btn_enviar_ticket.setEnabled(True)
        if success:
            self.status_label.setText("Estado actual: Enviado")
            self.sent_label.setText("Último envío: " + datetime.now().strftime("%Y-%m-%d %H:%M"))
            QMessageBox.information(self, "Enviar ticket", message)
            self.retry_btn.setEnabled(False)
        else:
            self.status_label.setText("Estado actual: Error")
            QMessageBox.critical(self, "Enviar ticket", message)
            self.retry_btn.setEnabled(True)
        self.email_thread = None

    def generate_manual_invoice(self):
        """Open dialog to create an invoice manually and preview the PDF."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(
                self,
                "Factura manual",
                "No has seleccionado ninguna venta",
            )
            return
        tipo, ok = QInputDialog.getItem(
            self,
            "Tipo de factura",
            "¿Qué tipo de factura desea generar?",
            ["Consumidor final", "Crédito fiscal"],
            0,
            False,
        )
        if not ok:
            return
        dialog = ManualInvoiceDialog(self)
        if tipo == "Crédito fiscal":
            dialog.type_combo.setCurrentIndex(1)
        else:
            dialog.type_combo.setCurrentIndex(0)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            venta = {k: v for k, v in data.items() if k not in {"cliente", "detalles", "tipo"}}
            detalles = data.get("detalles", [])
            cliente = data.get("cliente", {})
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                temp_file = tmp.name
            generar_factura_electronica_pdf(
                venta,
                detalles,
                cliente,
                {},
                tipo.title(),
                archivo=temp_file,
                codigo_generacion=venta.get("codigo_generacion", ""),
                numero_control=venta.get("numero_control", ""),
                sello_recepcion=venta.get("sello_recepcion", ""),
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(temp_file)))


