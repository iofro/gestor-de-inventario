from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QLineEdit,
    QDateEdit,
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QComboBox,
)
from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QPixmap
import os

from ticket_pdf import generar_ticket_personalizado
from factura_sv import generar_factura_electronica_pdf
from utils.monto import monto_a_texto_sv
from utils.docs import get_document_paths, build_invoice_json
import tempfile
import subprocess
import shutil

# Directory where debit notes will be stored
NOTAS_DEBITO_DIR = os.path.join(os.path.dirname(__file__), "notas_debito")
import json
from datetime import datetime

CF_DIR = os.path.join(os.path.dirname(__file__), "facturas_consumidor_final")
CREDITO_DIR = os.path.join(os.path.dirname(__file__), "facturas_credito_fiscal")


class FacturacionTab(QWidget):
    """Tab para gestionar facturas y notas."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._setup_ui()
        self.load_invoices()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)

        left_layout = QVBoxLayout()

        filter_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar número o cliente")
        filter_layout.addWidget(self.search_bar)

        self.client_filter = QComboBox()
        self.client_filter.addItem("Todos", None)
        for c in self.manager._clientes:
            self.client_filter.addItem(c.get("nombre", ""), c.get("id"))
        filter_layout.addWidget(self.client_filter)

        self.vendedor_filter = QComboBox()
        self.vendedor_filter.addItem("Todos", None)
        for v in self.manager.db.get_trabajadores(solo_vendedores=True):
            self.vendedor_filter.addItem(v.get("nombre", ""), v.get("id"))
        filter_layout.addWidget(self.vendedor_filter)

        self.tipo_filter = QComboBox()
        self.tipo_filter.addItems(["Todos", "Consumidor final", "Crédito fiscal", "Ticket"])
        filter_layout.addWidget(self.tipo_filter)

        self.date_from = QDateEdit(QDate.currentDate().addYears(-2))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        filter_layout.addWidget(self.date_from)
        filter_layout.addWidget(self.date_to)
        self.update_btn = QPushButton("Actualizar")
        filter_layout.addWidget(self.update_btn)
        filter_layout.addStretch(1)
        left_layout.addLayout(filter_layout)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Fecha", "Cliente", "Total", "Estado"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        left_layout.addWidget(self.table)

        btns = QHBoxLayout()
        self.btn_ticket = QPushButton("Generar ticket virtual")
        self.btn_credito = QPushButton("Nota de crédito")
        self.btn_debito = QPushButton("Nota de débito")
        self.btn_estado = QPushButton("Estado")
        self.btn_eliminar = QPushButton("Eliminar archivos")
        btns.addWidget(self.btn_ticket)
        btns.addWidget(self.btn_credito)
        btns.addWidget(self.btn_debito)
        btns.addWidget(self.btn_estado)
        btns.addWidget(self.btn_eliminar)
        btns.addStretch(1)
        left_layout.addLayout(btns)

        main_layout.addLayout(left_layout, 3)

        preview_layout = QVBoxLayout()
        self.preview_label = QLabel("Previsualización del PDF")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#DDD; padding:20px;")
        preview_layout.addWidget(self.preview_label)
        main_layout.addLayout(preview_layout, 2)

        # Connect signals
        self.update_btn.clicked.connect(self.load_invoices)
        self.search_bar.textChanged.connect(self.load_invoices)
        self.client_filter.currentIndexChanged.connect(self.load_invoices)
        self.vendedor_filter.currentIndexChanged.connect(self.load_invoices)
        self.tipo_filter.currentIndexChanged.connect(self.load_invoices)
        self.date_from.dateChanged.connect(self.load_invoices)
        self.date_to.dateChanged.connect(self.load_invoices)
        self.table.itemSelectionChanged.connect(self.show_invoice)
        
        self.btn_ticket.clicked.connect(self.create_ticket)
        self.btn_credito.clicked.connect(lambda: self.create_nota("credito"))
        self.btn_debito.clicked.connect(lambda: self.create_nota("debito"))
        self.btn_estado.clicked.connect(self.change_estado)
        self.btn_eliminar.clicked.connect(self.delete_files)

    def load_invoices(self):
        ventas = self.manager.db.get_ventas()
        clientes = {c["id"]: c["nombre"] for c in self.manager._clientes}
        search = self.search_bar.text().lower() if hasattr(self, "search_bar") else ""
        d_from = self.date_from.date().toPyDate() if hasattr(self, "date_from") else None
        d_to = self.date_to.date().toPyDate() if hasattr(self, "date_to") else None
        cli_id = self.client_filter.currentData()
        vend_id = self.vendedor_filter.currentData()
        tipo = self.tipo_filter.currentText()

        rows = []
        for v in ventas:
            fecha = v.get("fecha", "")
            try:
                fdate = datetime.strptime(fecha.split()[0], "%Y-%m-%d").date()
            except Exception:
                fdate = None
            if d_from and fdate and fdate < d_from:
                continue
            if d_to and fdate and fdate > d_to:
                continue
            if cli_id and v.get("cliente_id") != cli_id:
                continue
            if vend_id and v.get("vendedor_id") != vend_id:
                continue
            cliente = clientes.get(v.get("cliente_id"), "")
            if search and search not in str(v.get("id", "")).lower() and search not in cliente.lower():
                continue
            credito = self.manager.db.get_venta_credito_fiscal(v["id"])
            has_ticket = bool(self.manager.db.get_ticket_pdf(v["id"]))
            if tipo == "Crédito fiscal" and not credito:
                continue
            if tipo == "Consumidor final" and credito:
                continue
            if tipo == "Ticket" and not has_ticket:
                continue
            # Keep parsed date for later sorting
            v_copy = dict(v)
            v_copy["_parsed_fecha"] = fdate
            rows.append(v_copy)

        # Sort invoices by date descending; fall back to original order if
        # the date is missing
        rows.sort(key=lambda r: r.get("_parsed_fecha"), reverse=True)

        self.table.setRowCount(len(rows))
        for row, v in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(str(v.get("id"))))
            self.table.setItem(row, 1, QTableWidgetItem(v.get("fecha", "")))
            self.table.setItem(row, 2, QTableWidgetItem(clientes.get(v.get("cliente_id"), "")))
            self.table.setItem(row, 3, QTableWidgetItem(f"${v.get('total', 0):.2f}"))
            self.table.setItem(row, 4, QTableWidgetItem(v.get("estado", "")))
        if rows:
            self.table.selectRow(0)

    def _selected_venta(self):
        if self.table.currentRow() < 0:
            return None
        item = self.table.item(self.table.currentRow(), 0)
        if item:
            try:
                return int(item.text())
            except ValueError:
                return None
        return None

    def create_ticket(self):
        venta_id = self._selected_venta()
        if venta_id is None:
            QMessageBox.warning(self, "Ticket", "Seleccione una venta")
            return
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        detalles = self.manager.db.get_detalles_venta(venta_id)
        extra = {}
        raw_extra = venta.get("extra") if venta else None
        if raw_extra:
            try:
                extra = json.loads(raw_extra)
            except Exception:
                extra = {}
        fname, _ = QFileDialog.getSaveFileName(self, "Guardar ticket", "ticket.pdf", "PDF (*.pdf)")
        if not fname:
            return
        generar_ticket_personalizado(venta, detalles, fname, dte_data=extra)
        QMessageBox.information(self, "Ticket", "Ticket generado correctamente")

    def create_nota(self, tipo):
        venta_id = self._selected_venta()
        if venta_id is None:
            QMessageBox.warning(self, "Nota", "Seleccione una venta")
            return
        monto, ok = QInputDialog.getDouble(self, "Monto", "Monto de la nota", 0, decimals=2)
        if not ok:
            return
        motivo, ok2 = QInputDialog.getText(self, "Motivo", "Motivo")
        if not ok2:
            return
        fecha = QDate.currentDate().toString("yyyy-MM-dd")
        nota_id = self.manager.db.add_nota(venta_id, tipo, fecha, monto, motivo)

        if tipo == "debito":
            os.makedirs(NOTAS_DEBITO_DIR, exist_ok=True)
            fname = os.path.join(NOTAS_DEBITO_DIR, f"nota_{nota_id}.txt")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(
                    f"Venta ID: {venta_id}\nFecha: {fecha}\nMonto: {monto}\nMotivo: {motivo}"
                )

        QMessageBox.information(self, "Nota", "Nota registrada")
        self.load_invoices()

    def change_estado(self):
        venta_id = self._selected_venta()
        if venta_id is None:
            QMessageBox.warning(self, "Estado", "Seleccione una venta")
            return
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Estado", "No se encontró la venta seleccionada")
            return
        from dialogs import EstadoVentaDialog
        dialog = EstadoVentaDialog(venta.get("estado", "Pagada"), self)
        if dialog.exec_():
            estado = dialog.get_estado()
            self.manager.db.update_venta_estado(venta_id, estado)
            self.load_invoices()

    def delete_files(self):
        """Elimina PDF y JSON asociados a la venta seleccionada."""
        venta_id = self._selected_venta()
        if venta_id is None:
            QMessageBox.warning(self, "Eliminar", "Seleccione una venta")
            return
        paths = []
        pdf_path = self.manager.db.get_factura_pdf(venta_id)
        if pdf_path:
            paths.append(pdf_path)
            paths.append(os.path.splitext(pdf_path)[0] + ".json")
        ticket_path = self.manager.db.get_ticket_pdf(venta_id)
        if ticket_path:
            paths.append(ticket_path)
            paths.append(os.path.splitext(ticket_path)[0] + ".json")
        paths = [p for p in paths if os.path.exists(p)]
        if not paths:
            QMessageBox.information(self, "Eliminar", "No se encontraron archivos")
            return
        confirm = QMessageBox.question(
            self,
            "Eliminar",
            "¿Eliminar archivos de factura/ticket?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass
        if pdf_path:
            self.manager.db.delete_factura_pdf(venta_id)
        if ticket_path:
            self.manager.db.delete_ticket_pdf(venta_id)
        QMessageBox.information(self, "Eliminar", "Archivos eliminados")

    # ------------------------------------------------------------------
    # Previsualización de facturas
    # ------------------------------------------------------------------
    def show_invoice(self):
        if self.table.currentRow() < 0:
            self.preview_label.setText("Previsualización del PDF")
            self._clear_preview_files()
            return
        venta_id = int(self.table.item(self.table.currentRow(), 0).text())
        self._update_preview(venta_id)

    def _clear_preview_files(self):
        """Remove temporary preview image without deleting stored PDFs."""
        img = getattr(self, "preview_image_file", None)
        if img and os.path.exists(img):
            try:
                os.remove(img)
            except OSError:
                pass
        self.preview_pdf_file = None
        self.preview_image_file = None

    def _update_preview(self, venta_id):
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
        fecha_generacion = venta_data.get("fecha_generacion") or ident.get("fecGeneracion", "")

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
        self.manager.db.add_factura_pdf(venta_id, tipo_doc, file_path)
        return file_path

