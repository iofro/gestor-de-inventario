import sys
import os
import json
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QIcon
from ui_mainwindow import MainWindow

LAST_FILE_PATH = "ultimo_inventario.json"

def cargar_ultimo_archivo():
    if os.path.exists(LAST_FILE_PATH):
        try:
            with open(LAST_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("ultimo", "")
        except Exception:
            return ""
    return ""

if __name__ == "__main__":
    app = QApplication(sys.argv)
    icon_path = os.path.join(os.path.dirname(__file__), "logoinventario.jpg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
    window.show()

    # Cargar automáticamente el último inventario usado
    ultimo_archivo = cargar_ultimo_archivo()
    if ultimo_archivo and os.path.exists(ultimo_archivo):
        try:
            window.manager.importar_inventario_json(ultimo_archivo)
            window.ultimo_archivo_json = ultimo_archivo
            window.compras_tab.refresh_filters()
            window.filter_products()
            window._actualizar_arbol_vendedores()
            window._actualizar_arbol_Distribuidores()   
            window._actualizar_tabla_clientes()    
            window._actualizar_tabla_trabajadores() 
            window._actualizar_historial()
            QMessageBox.information(window, "Inventario", "Inventario cargado exitosamente.")
        except Exception as e:
            QMessageBox.critical(window, "Error", f"No se pudo cargar el inventario:\n{e}")

    sys.exit(app.exec_())
