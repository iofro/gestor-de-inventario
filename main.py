import sys
import os
import json
import warnings
import sqlite3

# Swig-generated types from external libraries (e.g. PyMuPDF) may emit
# warnings about missing ``__module__`` attributes. Since these wrappers
# live outside this repository, silence the warning to keep the console
# clean until the dependencies are updated upstream.
warnings.filterwarnings(
    "ignore",
    message=r".*(SwigPyObject|SwigPyPacked|swigvarlink).*__module__.*",
)

from PyQt5.QtWidgets import (
    QApplication,
    QMessageBox,
    QDialog,
    QInputDialog,
    QLineEdit,
)
from PyQt5.QtGui import QIcon
from ui_mainwindow import MainWindow
from user_picker_dialog import UserPickerDialog
from db import DB
from utils import resource_path

LAST_FILE_PATH = resource_path("ultimo_inventario.json")
DEFAULT_INVENTORY = resource_path("inventario.json")

def cargar_ultimo_archivo():
    """Devuelve la ruta del inventario a cargar al iniciar la aplicación."""
    if os.path.exists(LAST_FILE_PATH):
        try:
            with open(LAST_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            path = data.get("ultimo", "")
            if path and os.path.exists(path):
                return path
        except (OSError, json.JSONDecodeError):
            pass

    if os.path.exists(DEFAULT_INVENTORY):
        return str(DEFAULT_INVENTORY)
    return ""

if __name__ == "__main__":
    app = QApplication(sys.argv)
    style_path = resource_path("style.qss")
    if style_path.exists():
        with open(style_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    icon_path = resource_path("logoinventario.jpg")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    db = DB()
    users = [
        {"id": u["id"], "name": u["username"], "subtitle": u.get("role", "")}
        for u in db.get_users()
    ]
    dlg = UserPickerDialog(users, multi_select=False, parent=None)
    if dlg.exec_() != QDialog.Accepted:
        sys.exit(0)
    selected = dlg.selected_user_ids()
    if not selected:
        sys.exit(0)
    user_id = selected if not isinstance(selected, list) else selected[0]
    user = db.get_user(user_id)
    if not user:
        sys.exit(0)

    if user["username"] != "invitado":
        while True:
            password, ok = QInputDialog.getText(
                None,
                "Contraseña",
                f"Ingrese la contraseña para {user['username']}:",
                QLineEdit.Password,
            )
            if not ok:
                sys.exit(0)
            if db.authenticate(user["username"], password):
                break
            QMessageBox.warning(None, "Error", "Contraseña incorrecta")

    window = MainWindow(user)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    # Cargar automáticamente el último inventario usado
    ultimo_archivo = cargar_ultimo_archivo()
    if ultimo_archivo and os.path.exists(ultimo_archivo):
        try:
            data = window.manager.importar_inventario_json(ultimo_archivo)
            if isinstance(data, dict) and data.get("tab_order"):
                window.set_tab_order(data["tab_order"])
            window.ultimo_archivo_json = ultimo_archivo
            window.compras_tab.refresh_filters()
            window.filter_products()
            window._actualizar_arbol_vendedores()
            window._actualizar_arbol_Distribuidores()
            window._actualizar_tabla_clientes()
            window._actualizar_tabla_trabajadores()
            window._actualizar_historial()
            window._cargar_personas_estado()
            QMessageBox.information(window, "Inventario", "Inventario cargado exitosamente.")
        except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as e:
            QMessageBox.critical(window, "Error", f"No se pudo cargar el inventario:\n{e}")

    sys.exit(app.exec_())
