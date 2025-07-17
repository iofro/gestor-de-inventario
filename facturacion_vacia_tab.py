from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QDateEdit,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QPushButton,
    QSizePolicy,
    QMessageBox,
)
from PyQt5.QtCore import QDate, Qt

from datetime import datetime

class FacturacionVaciaTab(QWidget):
    """Pestaña de facturación con filtros y acciones básicas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.load_documents()

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------
    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        filter_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText(
            "Buscar por cliente, número de factura o fecha"
        )
        filter_layout.addWidget(self.search_bar)
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        filter_layout.addWidget(QLabel("Desde"))
        filter_layout.addWidget(self.date_from)
        filter_layout.addWidget(QLabel("Hasta"))
        filter_layout.addWidget(self.date_to)
        self.update_btn = QPushButton("Actualizar")
        filter_layout.addWidget(self.update_btn)
        filter_layout.addStretch(1)
        main_layout.addLayout(filter_layout)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                "Tipo",
                "Número",
                "Cliente",
                "Fecha",
                "Total",
                "Estado",
                "Acciones",
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.table)

        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        main_layout.addWidget(self.detail_label)

        self.table.itemSelectionChanged.connect(self.show_details)
        self.update_btn.clicked.connect(self.load_documents)

    # ------------------------------------------------------------------
    # Carga y filtrado de documentos
    # ------------------------------------------------------------------
    def load_documents(self):
        parent = self.parent()
        manager = getattr(parent, "manager", None) if parent else None
        if not manager:
            return

        ventas = manager.db.get_ventas()
        notas = []
        try:
            notas = manager.db.obtener_notas()
        except Exception:
            pass
        clientes = {c["id"]: c["nombre"] for c in manager._clientes}

        search = self.search_bar.text().lower()
        d_from = self.date_from.date().toPyDate()
        d_to = self.date_to.date().toPyDate()

        rows = []

        for v in ventas:
            fecha = v.get("fecha", "")
            try:
                fdate = datetime.strptime(fecha.split()[0], "%Y-%m-%d").date()
            except Exception:
                fdate = None
            if fdate and (fdate < d_from or fdate > d_to):
                continue
            cliente = clientes.get(v.get("cliente_id"), "")
            if search:
                if (
                    search not in str(v.get("id", "")).lower()
                    and search not in cliente.lower()
                    and search not in fecha.lower()
                ):
                    continue
            rows.append(
                {
                    "tipo": "Factura",
                    "numero": v.get("id"),
                    "cliente": cliente,
                    "fecha": fecha,
                    "total": v.get("total", 0),
                    "estado": v.get("estado", ""),
                    "source": ("venta", v),
                    "_parsed_fecha": fdate,
                }
            )

        for n in notas:
            fecha = n.get("fecha", "")
            try:
                fdate = datetime.strptime(fecha.split()[0], "%Y-%m-%d").date()
            except Exception:
                fdate = None
            if fdate and (fdate < d_from or fdate > d_to):
                continue
            venta = next((v for v in ventas if v["id"] == n.get("venta_id")), None)
            cliente = clientes.get(venta.get("cliente_id"), "") if venta else ""
            if search:
                if (
                    search not in str(n.get("id", "")).lower()
                    and search not in cliente.lower()
                    and search not in fecha.lower()
                ):
                    continue
            rows.append(
                {
                    "tipo": "Nota de crédito" if n.get("tipo") == "credito" else "Nota de débito",
                    "numero": n.get("id"),
                    "cliente": cliente,
                    "fecha": fecha,
                    "total": n.get("monto", 0),
                    "estado": "Registrada",
                    "source": ("nota", n),
                    "_parsed_fecha": fdate,
                }
            )

        rows.sort(key=lambda r: r.get("_parsed_fecha"), reverse=True)

        self.table.setRowCount(len(rows))
        for row, doc in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(doc["tipo"]))
            self.table.setItem(row, 1, QTableWidgetItem(str(doc["numero"])))
            self.table.setItem(row, 2, QTableWidgetItem(doc["cliente"]))
            self.table.setItem(row, 3, QTableWidgetItem(doc["fecha"]))
            self.table.setItem(row, 4, QTableWidgetItem(f"${doc['total']:.2f}"))
            self.table.setItem(row, 5, QTableWidgetItem(doc["estado"]))
            actions_widget = QWidget()
            a_layout = QHBoxLayout(actions_widget)
            a_layout.setContentsMargins(0, 0, 0, 0)
            view_btn = QPushButton("Ver")
            pdf_btn = QPushButton("PDF")
            annul_btn = QPushButton("Anular")
            a_layout.addWidget(view_btn)
            a_layout.addWidget(pdf_btn)
            a_layout.addWidget(annul_btn)
            a_layout.addStretch(1)
            self.table.setCellWidget(row, 6, actions_widget)

            for col in range(6):
                item = self.table.item(row, col)
                if item:
                    item.setData(Qt.UserRole, doc)

            view_btn.clicked.connect(lambda _, d=doc: self.view_document(d))
            pdf_btn.clicked.connect(lambda _, d=doc: self.download_pdf(d))
            annul_btn.clicked.connect(lambda _, d=doc: self.annul_document(d))

        if rows:
            self.table.selectRow(0)
        else:
            self.detail_label.clear()

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def view_document(self, doc):
        self._display_details(doc)

    def download_pdf(self, doc):
        QMessageBox.information(self, "PDF", "Descarga no implementada")

    def annul_document(self, doc):
        QMessageBox.information(self, "Anular", "Anulación no implementada")

    def show_details(self):
        if self.table.currentRow() < 0:
            self.detail_label.clear()
            return
        item = self.table.item(self.table.currentRow(), 0)
        doc = item.data(Qt.UserRole) if item else None
        if doc:
            self._display_details(doc)
        else:
            self.detail_label.clear()

    def _display_details(self, doc):
        parent = self.parent()
        manager = getattr(parent, "manager", None) if parent else None
        if not manager:
            return
        tipo, data = doc["source"]
        text = []
        if tipo == "venta":
            detalles = manager.db.get_detalles_venta(data.get("id"))
            text.append(f"Factura Nº {data.get('id')}")
            text.append(f"Fecha: {data.get('fecha', '')}")
            cliente = ""
            if data.get("cliente_id"):
                cli = next((c for c in manager._clientes if c["id"] == data["cliente_id"]), None)
                if cli:
                    cliente = cli.get("nombre", "")
            if cliente:
                text.append(f"Cliente: {cliente}")
            for d in detalles:
                desc = d.get("descripcion", "")
                cant = d.get("cantidad", 0)
                precio = d.get("precio", 0)
                text.append(f"- {desc} x{cant} @ ${precio}")
            text.append(f"Total: ${data.get('total', 0):.2f}")
        else:
            text.append(
                "Nota de crédito" if data.get("tipo") == "credito" else "Nota de débito"
            )
            text.append(f"Número: {data.get('id')}")
            text.append(f"Fecha: {data.get('fecha', '')}")
            text.append(f"Monto: ${data.get('monto', 0):.2f}")
            motivo = data.get("motivo", "")
            if motivo:
                text.append(f"Motivo: {motivo}")
        self.detail_label.setText("\n".join(text))


