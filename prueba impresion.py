import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QComboBox, QLabel, QMessageBox
)
import win32print

def coordenada_a_texto_raw(x_cm, y_cm, texto, ancho_char_cm=0.25, alto_linea_cm=0.40):
    espacios = int(x_cm / ancho_char_cm)
    saltos = int(y_cm / alto_linea_cm)
    return ("\n" * saltos) + (" " * espacios) + texto + "\n"

class PrinterTestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prueba RAW Epson TM-U950")
        self.setFixedSize(400, 180)

        layout = QVBoxLayout()
        self.label = QLabel("Seleccione una impresora:")
        layout.addWidget(self.label)

        self.printer_combo = QComboBox()
        self.printers = self.get_printers()
        self.printer_combo.addItems(self.printers)
        layout.addWidget(self.printer_combo)

        self.print_button = QPushButton("Imprimir factura RAW")
        self.print_button.clicked.connect(self.print_test)
        layout.addWidget(self.print_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def get_printers(self):
        printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
        return [printer[2] for printer in printers]

    def print_test(self):
        printer_name = self.printer_combo.currentText()
        if not printer_name:
            QMessageBox.warning(self, "Error", "Seleccione una impresora.")
            return

        try:
            factura_raw = ""
            # Encabezado (solo datos, sin etiquetas)
            factura_raw += coordenada_a_texto_raw(4.45, 4.80, "Francisco López")
            factura_raw += coordenada_a_texto_raw(4.45, 5.40, "Col. Escalón, San Salvador")
            factura_raw += coordenada_a_texto_raw(3.81, 6.40, "2025-06-12")
            factura_raw += coordenada_a_texto_raw(3.81, 6.90, "Comercio")
            factura_raw += coordenada_a_texto_raw(3.81, 7.50, "2025-06-10")
            factura_raw += coordenada_a_texto_raw(4.45, 8.00, "30 DÍAS")
            factura_raw += coordenada_a_texto_raw(4.45, 8.50, "María Pérez")
            factura_raw += coordenada_a_texto_raw(7.62, 6.40, "123456-7")
            factura_raw += coordenada_a_texto_raw(7.62, 7.50, "REM-00123")
            factura_raw += coordenada_a_texto_raw(11.43, 6.40, "0614-250786-102-3")
            factura_raw += coordenada_a_texto_raw(12.07, 7.50, "ORD-789")
            factura_raw += coordenada_a_texto_raw(11.43, 8.00, "Distribuidora S.A.")
            factura_raw += coordenada_a_texto_raw(11.75, 8.50, "2025-05-30")

            # Tabla de productos (3 filas de ejemplo)
            productos = [
                ("2", "Paracetamol 500mg", "0.50", "0.00", "0.00", "1.00"),
                ("1", "Ibuprofeno 200mg", "0.75", "0.00", "0.00", "0.75"),
                ("3", "Vitamina C 1000mg", "0.60", "0.00", "0.00", "1.80"),
            ]
            y_base = 10.10
            row_height = 0.6
            for i, (cantidad, descripcion, precio, exentas, no_sujetas, gravadas) in enumerate(productos):
                y = y_base + i * row_height
                factura_raw += coordenada_a_texto_raw(2.22, y, cantidad)
                factura_raw += coordenada_a_texto_raw(3.90, y, descripcion)
                factura_raw += coordenada_a_texto_raw(9.21, y, precio)
                factura_raw += coordenada_a_texto_raw(11.11, y, exentas)
                factura_raw += coordenada_a_texto_raw(12.70, y, no_sujetas)
                factura_raw += coordenada_a_texto_raw(14.10, y, gravadas)

            # Totales y resumen fiscal (solo datos)
            factura_raw += coordenada_a_texto_raw(2.22, 22.23, "Cuatro dólares con cincuenta centavos")
            factura_raw += coordenada_a_texto_raw(14.10, 21.59, "3.55")
            factura_raw += coordenada_a_texto_raw(14.10, 22.23, "0.46")
            factura_raw += coordenada_a_texto_raw(14.10, 22.86, "4.01")
            factura_raw += coordenada_a_texto_raw(14.10, 23.45, "0.00")
            factura_raw += coordenada_a_texto_raw(14.10, 24.00, "0.00")
            factura_raw += coordenada_a_texto_raw(14.10, 24.60, "0.00")
            factura_raw += coordenada_a_texto_raw(14.10, 25.08, "4.01")

            # Enviar a impresora RAW
            SLIP_MODE = b'\x1B\x69'  # ESC i
            hprinter = win32print.OpenPrinter(printer_name)
            hjob = win32print.StartDocPrinter(hprinter, 1, ("Factura RAW", None, "RAW"))
            win32print.StartPagePrinter(hprinter)
            win32print.WritePrinter(hprinter, SLIP_MODE + factura_raw.encode('utf-8'))
            win32print.EndPagePrinter(hprinter)
            win32print.EndDocPrinter(hprinter)
            win32print.ClosePrinter(hprinter)

            QMessageBox.information(self, "Éxito", "Factura RAW enviada a la impresora.")
        except Exception as e:
            QMessageBox.critical(self, "Error de impresión", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PrinterTestWindow()
    window.show()
    sys.exit(app.exec_())
