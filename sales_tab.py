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
    QScrollArea,

    QInputDialog,
    QDialog,
    QCheckBox,
    QComboBox,
)
from PyQt5.QtCore import Qt, QDate, QUrl, QSize
from PyQt5.QtGui import QDesktopServices, QPixmap
from datetime import datetime, date, timedelta
from factura_sv import generar_factura_electronica_pdf
from utils.email_sender import EmailSender
from utils.email_builder import build_email
from dialogs import ManualInvoiceDialog
from utils.doc_generation import generate_invoice_pdf, generate_ticket_pdf
import tempfile
import subprocess
import shutil
import os
import json
import warnings
from paths import DATOS_NEGOCIO_PATH

CF_DIR = os.path.join(os.path.dirname(__file__), "facturas_consumidor_final")
CREDITO_DIR = os.path.join(os.path.dirname(__file__), "facturas_credito_fiscal")
TICKETS_DIR = os.path.join(os.path.dirname(__file__), "tickets")

class SalesTab(QWidget):
    """Simple tab to list sales and preview invoices."""

    def __init__(self, manager, parent=None, check_smtp=True):
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
        if check_smtp:
            self._check_smtp_credentials()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)

        # Left panel
        left_layout = QVBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar número o cliente")
        self.search_bar.textChanged.connect(self.load_sales)
        left_layout.addWidget(self.search_bar)

        filter_layout = QHBoxLayout()
        self.date_filter_cb = QCheckBox("Filtrar por fecha")
        self.quick_range = QComboBox()
        self.quick_range.addItems(["Personalizado", "Esta semana", "Este mes", "Este año"])
        self.date_from = QDateEdit(QDate.currentDate().addYears(-2))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.quick_range.setEnabled(False)
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)
        self.date_filter_cb.toggled.connect(self._toggle_date_filter)
        self.quick_range.currentIndexChanged.connect(self._apply_quick_range)
        self.date_from.dateChanged.connect(self.load_sales)
        self.date_to.dateChanged.connect(self.load_sales)
        for w in [self.date_filter_cb, self.quick_range, QLabel("Desde"), self.date_from,
                  QLabel("Hasta"), self.date_to]:
            filter_layout.addWidget(w)
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

        self.btn_estado = QPushButton("Estado")
        self.btn_estado.clicked.connect(self.show_sale_details)
        left_layout.addWidget(self.btn_estado)

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
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setScaledContents(True)
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setWidget(self.preview_label)
        preview_layout.addWidget(preview_scroll)

        self.info_label = QLabel()
        preview_layout.addWidget(self.info_label)

        btn_layout = QHBoxLayout()
        self.btn_guardar = QPushButton("Guardar factura")
        btn_layout.addWidget(self.btn_guardar)
        self.btn_guardar.clicked.connect(self.save_invoice)
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
        self.config_email_btn = QPushButton("Configurar correo")
        self.email_subject_edit.textChanged.connect(lambda t: setattr(self, "email_subject", t))
        self.email_body_edit.textChanged.connect(lambda: setattr(self, "email_body", self.email_body_edit.toPlainText()))
        self.config_email_btn.clicked.connect(self.configure_email)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.gen_label)
        status_layout.addWidget(self.sent_label)
        status_layout.addWidget(self.email_label)
        status_layout.addWidget(QLabel("Asunto:"))
        status_layout.addWidget(self.email_subject_edit)
        status_layout.addWidget(QLabel("Mensaje:"))
        status_layout.addWidget(self.email_body_edit)
        status_layout.addWidget(self.config_email_btn)
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

    def _toggle_date_filter(self, checked):
        self.quick_range.setEnabled(checked)
        custom = self.quick_range.currentIndex() == 0
        self.date_from.setEnabled(checked and custom)
        self.date_to.setEnabled(checked and custom)
        if checked:
            self._apply_quick_range()
        else:
            self.load_sales()

    def _apply_quick_range(self):
        if not self.date_filter_cb.isChecked():
            return
        option = self.quick_range.currentText()
        today = date.today()
        if option == "Esta semana":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            self.date_from.setDate(QDate(start))
            self.date_to.setDate(QDate(end))
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        elif option == "Este mes":
            start = today.replace(day=1)
            if today.month == 12:
                end = date(today.year, 12, 31)
            else:
                end = date(today.year, today.month + 1, 1) - timedelta(days=1)
            self.date_from.setDate(QDate(start))
            self.date_to.setDate(QDate(end))
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        elif option == "Este año":
            start = date(today.year, 1, 1)
            end = date(today.year, 12, 31)
            self.date_from.setDate(QDate(start))
            self.date_to.setDate(QDate(end))
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        else:
            self.date_from.setEnabled(True)
            self.date_to.setEnabled(True)
        self.load_sales()

    def load_sales(self):
        ventas = self.manager.db.get_ventas(sincronizada=1)
        search = self.search_bar.text().lower()
        cliente_filter = self.client_filter.text().lower()
        if self.date_filter_cb.isChecked():
            d_from = self.date_from.date().toPyDate()
            d_to = self.date_to.date().toPyDate()
        else:
            d_from = d_to = None
        rows = []
        for v in ventas:
            fecha = v.get("fecha")
            fdate = None
            if isinstance(fecha, str):
                try:
                    fdate = datetime.strptime(fecha, "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    try:
                        fdate = datetime.strptime(fecha, "%Y-%m-%d")
                    except (ValueError, TypeError):
                        fdate = None
            else:
                # fecha no es una cadena o está ausente
                fdate = None
            if self.date_filter_cb.isChecked() and fdate and (
                (d_from and fdate.date() < d_from) or (d_to and fdate.date() > d_to)
            ):
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
            rows.append((v, cliente, fdate))

        rows.sort(key=lambda x: x[2] or datetime.min, reverse=True)

        self.sales_table.setRowCount(len(rows))
        for row, (venta, cli, _) in enumerate(rows):
            self.sales_table.setItem(row, 0, QTableWidgetItem(str(venta.get("id"))))
            self.sales_table.setItem(row, 1, QTableWidgetItem(cli))
            self.sales_table.setItem(row, 2, QTableWidgetItem(venta.get("fecha", "")))
            self.sales_table.setItem(row, 3, QTableWidgetItem(f"${venta.get('total', 0):.2f}"))
            estado = venta.get("estado", "Pendiente")
            self.sales_table.setItem(row, 4, QTableWidgetItem(estado))
        self.sales_table.clearSelection()
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
        if not self.current_credito_fiscal and not venta.get("cliente_id"):
            self.info_label.setText(f"Ticket {venta_id}")
        elif self.current_credito_fiscal:
            self.info_label.setText(
                f"Factura {venta_id} - Crédito Fiscal - Cliente: {cliente}"
            )
        else:
            self.info_label.setText(f"Factura {venta_id} - Cliente: {cliente}")
        # Generate and display preview image for the selected invoice
        self.email_label.setText(f"Correo destinatario: {cliente_email}")
        self._update_preview(venta_id)
        self._update_email_preview()

    def show_sale_details(self):
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Estado", "Seleccione una venta")
            return
        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Estado", "No se encontró la venta seleccionada")
            return
        detalles = self.manager.db.get_detalles_venta(venta_id)
        from dialogs import VentaDetalleDialog
        dialog = VentaDetalleDialog(venta, detalles, self)
        dialog.exec_()

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
        """Check for SMTP data and warn if any are missing.

        Returns a dict with the credentials if complete, otherwise ``None``.
        """
        path = DATOS_NEGOCIO_PATH
        headless = os.environ.get("QT_QPA_PLATFORM") in {"offscreen", "minimal"}
        msg = (
            "Credenciales SMTP incompletas. Configure sus datos en la opción 'Configuración de correo'."
        )

        suppress = os.environ.get("INVENTARIO_SUPPRESS_SMTP_WARNING")

        def warn():
            if headless:
                warnings.warn(msg)
            else:
                QMessageBox.warning(self, "Configuración de correo", msg)

        if not os.path.exists(path):
            if not suppress:
                warn()
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            if not suppress:
                warn()
            return None

        server = data.get("smtp_server")
        port = data.get("smtp_port")
        user = data.get("email_usuario") or data.get("email")
        password = os.getenv("INVENTARIO_EMAIL_PASSWORD") or data.get("email_contrasena")

        if not data.get("email_usuario") and user:
            data["email_usuario"] = user
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        if not all([server, port, user, password]):
            if not suppress:
                warn()
            return None

        return {
            "server": server,
            "port": port,
            "user": user,
            "password": password,
        }
    def _update_preview(self, venta_id):
        """Generate PDF preview image for the given sale ID and display it."""
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            self.preview_label.setText("Previsualización del PDF")
            return

        self._clear_preview_files()

        is_ticket = not venta.get("cliente_id") and not self.manager.db.get_venta_credito_fiscal(venta_id)
        if is_ticket:
            pdf_path = self.manager.db.get_ticket_pdf(venta_id)
        else:
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            self.preview_label.setText("Documento no guardado")
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
            # Scale to fixed dimensions while preserving the PDF aspect ratio
            scaled = pixmap.scaled(
                600,
                800,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled)
            self.preview_label.setText("")
        except Exception:
            self.preview_label.setText("No se pudo generar previsualización")
            self._clear_preview_files()

    def _generate_invoice_pdf(self, venta_id):
        return generate_invoice_pdf(self.manager, venta_id)

    def _generate_ticket_pdf(self, venta_id):
        return generate_ticket_pdf(self.manager, venta_id)

    def save_invoice(self):
        """Generate and store the document for the selected sale."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Guardar factura", "Seleccione una venta primero.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = self.manager.db.get_venta_by_id(venta_id)
        if not venta or int(venta.get("id", 0)) != venta_id:
            QMessageBox.warning(self, "Guardar factura", "No se encontró la venta seleccionada.")
            return
        credito_info = self.manager.db.get_venta_credito_fiscal(venta_id)
        doc_type = "Factura"
        if not credito_info and not venta.get("cliente_id"):
            box = QMessageBox(self)
            box.setWindowTitle("Tipo de documento")
            box.setText("¿Desea generar ticket o factura de consumidor final?")
            ticket_btn = box.addButton("Ticket", QMessageBox.AcceptRole)
            factura_btn = box.addButton("Factura", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec_()
            clicked = box.clickedButton()
            if clicked == ticket_btn:
                file_path = self._generate_ticket_pdf(venta_id)
                doc_type = "Ticket"
            elif clicked == factura_btn:
                try:
                    file_path = self._generate_invoice_pdf(venta_id)
                except ValueError as e:
                    QMessageBox.warning(self, "Guardar factura", str(e))
                    return
            else:
                return
        else:
            try:
                file_path = self._generate_invoice_pdf(venta_id)
            except ValueError as e:
                QMessageBox.warning(self, "Guardar factura", str(e))
                return
        if not file_path:
            QMessageBox.warning(self, "Guardar factura", "No se pudo generar el documento.")
            return
        QMessageBox.information(self, "Guardar factura", f"{doc_type} guardado en {file_path}")

    def save_ticket(self):
        """Generate a simple ticket PDF for the selected sale."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Ticket", "Seleccione una factura primero.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        file_path = self._generate_ticket_pdf(venta_id)
        if file_path:
            QMessageBox.information(self, "Ticket", f"Ticket guardado en {file_path}")
        else:
            QMessageBox.warning(self, "Ticket", "No se pudo generar el ticket.")

    def preview_pdf(self):
        """Open the saved PDF for the selected sale."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Previsualizar", "Seleccione una factura primero.")

            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Previsualizar", "No se encontró la venta seleccionada.")

            return

        is_ticket = not venta.get("cliente_id") and not self.manager.db.get_venta_credito_fiscal(venta_id)
        if is_ticket:
            pdf_path = self.manager.db.get_ticket_pdf(venta_id)
        else:
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(
                self, "Previsualizar", "No hay PDF guardado para esta venta."
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(pdf_path)))

    def print_pdf(self):
        """Print the selected sale using the saved PDF."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Imprimir", "Seleccione una factura primero.")
            return
        # Reuse preview_pdf to open the file
        self.preview_pdf()

    def send_email(self):
        """Send the selected document via email in a background thread."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Enviar por correo", "No has seleccionado ninguna venta.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = self.manager.db.get_venta_by_id(venta_id)
        if not venta or int(venta.get("id", 0)) != venta_id:
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

        dte_meta = {
            "subject": self.email_subject_edit.text(),
            "body": self.email_body_edit.toPlainText(),
        }

        credito_info = self.manager.db.get_venta_credito_fiscal(venta_id)
        if credito_info or venta.get("cliente_id"):
            doc_type = "factura"
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._generate_invoice_pdf(venta_id)
        else:
            doc_type = "ticket"
            pdf_path = self.manager.db.get_ticket_pdf(venta_id)
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._generate_ticket_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "Enviar por correo", "No se pudo generar el documento.")
            return
        json_path = os.path.splitext(pdf_path)[0] + ".json"
        if not os.path.exists(json_path):
            if doc_type == "ticket":
                pdf_path = self._generate_ticket_pdf(venta_id)
            else:
                pdf_path = self._generate_invoice_pdf(venta_id)
            json_path = os.path.splitext(pdf_path)[0] + ".json"
            if not os.path.exists(json_path):
                QMessageBox.warning(self, "Enviar por correo", "No se encontró el JSON firmado.")
                return

        creds = self._check_smtp_credentials()
        if not creds:
            return
        server = creds["server"]
        port = creds["port"]
        user = creds["user"]
        password = creds["password"]

        email_data = build_email(
            cliente_email,
            dte_meta,
            pdf_path,
            json_path,
        )

        self.status_label.setText("Estado actual: Enviando...")

        self.email_thread = EmailSender(
            server,
            port,
            user,
            password,
            email_data["to"],
            email_data["subject"],
            email_data["body"],
            email_data["attachments"],
        )
        self.email_thread.finished.connect(self._on_email_sent)
        self.email_thread.start()

    def _on_email_sent(self, success, message):
        if success:
            self.status_label.setText("Estado actual: Enviado")
            self.sent_label.setText("Último envío: " + datetime.now().strftime("%Y-%m-%d %H:%M"))
            QMessageBox.information(self, "Enviar por correo", message)
        else:
            self.status_label.setText("Estado actual: Error")
            QMessageBox.critical(self, "Enviar por correo", message)
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
        tipo = "Consumidor final"
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
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


