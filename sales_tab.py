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
    QAbstractItemView,
)
from PyQt5.QtCore import Qt, QDate, QUrl
from PyQt5.QtGui import QDesktopServices
import tempfile
import os
from datetime import datetime
from factura_sv import generar_factura_electronica_pdf

class SalesTab(QWidget):
    """Simple tab to list sales and preview invoices."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.current_credito_fiscal = None
        self._setup_ui()
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
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
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
        self.sales_table.itemSelectionChanged.connect(self.show_sale)
        left_layout.addWidget(self.sales_table)

        self.new_invoice_btn = QPushButton("+ Generar nueva factura manual")
        left_layout.addWidget(self.new_invoice_btn)

        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        # Right panel
        splitter = QSplitter(Qt.Vertical)

        preview_layout = QVBoxLayout()
        self.preview_label = QLabel("Previsualización del PDF")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#DDD; padding:20px;")
        preview_layout.addWidget(self.preview_label)

        self.info_label = QLabel()
        preview_layout.addWidget(self.info_label)

        btn_layout = QHBoxLayout()
        self.btn_preview = QPushButton("Previsualizar")
        self.btn_guardar = QPushButton("Guardar PDF")
        self.btn_enviar = QPushButton("Enviar por correo")
        self.btn_imprimir = QPushButton("Imprimir PDF")
        self.btn_editar = QPushButton("Editar factura")
        btn_layout.addWidget(self.btn_preview)
        btn_layout.addWidget(self.btn_guardar)
        btn_layout.addWidget(self.btn_enviar)
        btn_layout.addWidget(self.btn_imprimir)
        btn_layout.addWidget(self.btn_editar)
        self.btn_preview.clicked.connect(self.preview_pdf)
        self.btn_guardar.clicked.connect(self.save_pdf)
        preview_layout.addLayout(btn_layout)

        preview_widget = QWidget()
        preview_widget.setLayout(preview_layout)

        status_layout = QVBoxLayout()
        self.status_label = QLabel("Estado actual: ")
        self.gen_label = QLabel("Generado: ")
        self.sent_label = QLabel("Último envío: ")
        self.email_label = QLabel("Correo destinatario: ")
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.retry_btn = QPushButton("Reintentar envío")
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.gen_label)
        status_layout.addWidget(self.sent_label)
        status_layout.addWidget(self.email_label)
        status_layout.addWidget(self.log_text)
        status_layout.addWidget(self.retry_btn)
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
            self.sales_table.setItem(row, 4, QTableWidgetItem("Pendiente"))
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
            self.log_text.clear()
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        cliente = ""
        if venta and venta.get("cliente_id"):
            cli = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
            if cli:
                cliente = cli.get("nombre", "")

        # Fetch credit-fiscal information for this sale
        self.current_credito_fiscal = self.manager.db.get_venta_credito_fiscal(venta_id)
        if self.current_credito_fiscal:
            self.info_label.setText(
                f"Factura {venta_id} - Crédito Fiscal - Cliente: {cliente}"
            )
        else:
            self.info_label.setText(f"Factura {venta_id} - Cliente: {cliente}")
        # In a real app we would load the PDF preview here

    def save_pdf(self):
        """Generate a PDF for the selected sale after user confirmation."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Guardar PDF", "Seleccione una factura primero.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())

        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Guardar PDF", "No se encontró la venta seleccionada.")
            return

        credito_info = self.manager.db.get_venta_credito_fiscal(venta_id)
        mensaje = (
            "Esta venta está registrada como crédito fiscal, ¿desea continuar?"
            if credito_info
            else "Esta venta está registrada como consumidor final, ¿desea continuar?"
        )
        reply = QMessageBox.question(self, "Guardar PDF", mensaje, QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            QMessageBox.information(
                self,
                "Guardar PDF",
                "Si desea modificar esta factura presione generar nueva factura manual",
            )
            return

        detalles = self.manager.db.get_detalles_venta(venta_id)

        # Merge venta info with credit-fiscal extra data
        venta_data = dict(venta)
        if credito_info:
            venta_data.update(credito_info)

        # Attach vendedor nombre if available
        if venta_data.get("vendedor_id"):
            trabajador = self.manager.db.get_trabajador(venta_data["vendedor_id"])
            if trabajador:
                venta_data["vendedor_nombre"] = trabajador.get("nombre", "")

        # Calculate totals per line if not provided
        sumas = 0
        ventas_exentas = 0
        ventas_no_sujetas = 0
        iva = 0
        for d in detalles:
            base = d.get("precio_unitario", 0) * d.get("cantidad", 0)
            if d.get("descuento_tipo") == "%":
                base -= base * d.get("descuento", 0) / 100
            else:
                base -= d.get("descuento", 0)
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
                sumas += base
                iva += iva_item

        subtotal = sumas + ventas_exentas + ventas_no_sujetas
        total = subtotal + iva - venta_data.get("iva_retenido", 0)
        venta_data.update({
            "sumas": sumas,
            "iva": iva,
            "ventas_exentas": ventas_exentas,
            "ventas_no_sujetas": ventas_no_sujetas,
            "subtotal": subtotal,
            "total": total,
        })

        cliente = None
        if venta.get("cliente_id"):
            cliente = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
        distribuidor = None
        if venta.get("Distribuidor_id"):
            distribuidor = next(
                (d for d in self.manager._Distribuidores if d["id"] == venta["Distribuidor_id"]),
                None,
            )

        cliente_nombre = cliente.get("nombre", "cliente") if cliente else "cliente"
        tipo = "credito fiscal" if credito_info else "consumidor final"
        filename = f"{cliente_nombre} {venta_id} {tipo}.pdf"
        generar_factura_electronica_pdf(
            venta_data,
            detalles,
            cliente or {},
            distribuidor or {},
            archivo=filename,
        )
        QMessageBox.information(self, "Guardar PDF", f"Factura guardada en {filename}")

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

        credito_info = self.manager.db.get_venta_credito_fiscal(venta_id)
        detalles = self.manager.db.get_detalles_venta(venta_id)

        venta_data = dict(venta)
        if credito_info:
            venta_data.update(credito_info)

        if venta_data.get("vendedor_id"):
            trabajador = self.manager.db.get_trabajador(venta_data["vendedor_id"])
            if trabajador:
                venta_data["vendedor_nombre"] = trabajador.get("nombre", "")

        sumas = 0
        ventas_exentas = 0
        ventas_no_sujetas = 0
        iva = 0
        for d in detalles:
            base = d.get("precio_unitario", 0) * d.get("cantidad", 0)
            if d.get("descuento_tipo") == "%":
                base -= base * d.get("descuento", 0) / 100
            else:
                base -= d.get("descuento", 0)
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
                sumas += base
                iva += iva_item

        subtotal = sumas + ventas_exentas + ventas_no_sujetas
        total = subtotal + iva - venta_data.get("iva_retenido", 0)
        venta_data.update(
            {
                "sumas": sumas,
                "iva": iva,
                "ventas_exentas": ventas_exentas,
                "ventas_no_sujetas": ventas_no_sujetas,
                "subtotal": subtotal,
                "total": total,
            }
        )

        cliente = None
        if venta.get("cliente_id"):
            cliente = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
        distribuidor = None
        if venta.get("Distribuidor_id"):
            distribuidor = next(
                (d for d in self.manager._Distribuidores if d["id"] == venta["Distribuidor_id"]),
                None,
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            temp_file = tmp.name
        generar_factura_electronica_pdf(
            venta_data,
            detalles,
            cliente or {},
            distribuidor or {},
            archivo=temp_file,
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(temp_file)))

