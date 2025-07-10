from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

class FacturacionVaciaTab(QWidget):
    """Pestaña vacía de facturación para futuras ampliaciones."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Pestaña de facturación en construcción"))
