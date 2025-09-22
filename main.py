import sys
import os
import json
import warnings
import sqlite3
import logging
import traceback
from pathlib import Path

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
from paths import LAST_INVENTORY_PATH, migrate_datos_negocio

LAST_FILE_PATH = Path(LAST_INVENTORY_PATH)
DEFAULT_INVENTORY = resource_path("inventario.json")

logger = logging.getLogger(__name__)


def handle_exception(exc_type, exc_value, exc_traceback):
    """Mostrar un mensaje de error sin cerrar la aplicación."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))
    message = "".join(traceback.format_exception_only(exc_type, exc_value)).strip()
    try:
        QMessageBox.critical(
            None,
            "Error inesperado",
            "Ocurrió un error inesperado y la aplicación continuará en ejecución.\n"
            f"{message}",
        )
    except RuntimeError:
        sys.stderr.write(f"Ocurrió un error inesperado: {message}\n")


def cargar_ultimo_archivo():
    """Devuelve la ruta del inventario a cargar al iniciar la aplicación."""
    if LAST_FILE_PATH.exists():
        try:
            with LAST_FILE_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            path = data.get("ultimo", "")
            if path:
                path_obj = Path(path)
                if path_obj.exists():
                    return str(path_obj)
        except (OSError, json.JSONDecodeError):
            pass

    if DEFAULT_INVENTORY.exists():
        return str(DEFAULT_INVENTORY)
    return ""

if __name__ == "__main__":
    migrate_datos_negocio()
    app = QApplication(sys.argv)
    sys.excepthook = handle_exception
    style_path = resource_path("style.qss")
    if style_path.is_file():
        with style_path.open("r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    icon_path = resource_path("logoinventario.jpg")
    if icon_path.is_file():
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
    if icon_path.is_file():
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
            window.sales_tab.load_sales()
            QMessageBox.information(window, "Inventario", "Inventario cargado exitosamente.")
        except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as e:
            QMessageBox.critical(window, "Error", f"No se pudo cargar el inventario:\n{e}")

    sys.exit(app.exec_())
