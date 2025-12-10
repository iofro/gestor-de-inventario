import sys
import os
import json
import warnings
import sqlite3
import logging
import traceback
from pathlib import Path
import secrets

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
    QVBoxLayout,
    QLabel,
    QProgressBar,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from ui_mainwindow import MainWindow
from login_dialog import LoginDialog
from db import DB
from utils import resource_path
from paths import LAST_INVENTORY_PATH, migrate_datos_negocio, user_data_path
from dte import APP_VERSION
from utils.firmador import firmador_activo, iniciar_firmador

LAST_FILE_PATH = Path(LAST_INVENTORY_PATH)
LAST_USER_PATH = Path(user_data_path("last_user.txt"))
DEFAULT_INVENTORY = resource_path("inventario.json")

logger = logging.getLogger(__name__)
startup_logger = logging.getLogger("startup")


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


def iniciar_servicios(parent=None):
    """Muestra un loader y arranca el firmador antes de abrir la ventana principal."""
    if firmador_activo():
        return

    loader = QDialog(parent)
    loader.setWindowTitle("Iniciando servicios")
    loader.setModal(True)
    loader.setWindowFlags(loader.windowFlags() & ~Qt.WindowCloseButtonHint)
    layout = QVBoxLayout(loader)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)
    lbl = QLabel("Iniciando servicios...")
    lbl.setAlignment(Qt.AlignCenter)
    layout.addWidget(lbl)
    progress = QProgressBar()
    progress.setRange(0, 0)
    layout.addWidget(progress)
    loader.resize(320, 140)
    loader.show()
    QApplication.processEvents()
    try:
        iniciar_firmador()
    except FileNotFoundError as exc:
        loader.accept()
        QMessageBox.critical(parent, "Error", f"No se encontró el firmador:\n{exc}")
    except Exception as exc:
        loader.accept()
        QMessageBox.critical(parent, "Error", f"No se pudo iniciar el firmador:\n{exc}")
    else:
        loader.accept()


def _load_last_user() -> str:
    try:
        if LAST_USER_PATH.is_file():
            return LAST_USER_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def _save_last_user(username: str) -> None:
    try:
        LAST_USER_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAST_USER_PATH.write_text(username.strip(), encoding="utf-8")
    except OSError:
        startup_logger.debug("No se pudo guardar el último usuario utilizado")


def _ensure_admin_recovery(db: DB, parent: QDialog | None = None):
    """Garantiza que exista al menos un administrador, creando uno de recuperación si falta."""
    try:
        has_admin = db.has_any_admin()
    except Exception:
        startup_logger.exception("No se pudo verificar si existen administradores")
        return
    if has_admin:
        return
    # Genera credenciales de recuperación únicas
    base_username = "admin_recuperacion"
    username = base_username
    existing_names = {u["username"].lower() for u in db.get_users()}
    suffix = 1
    while username.lower() in existing_names:
        suffix += 1
        username = f"{base_username}{suffix}"
    password = secrets.token_urlsafe(8)
    try:
        db.add_user(username, password, "admin")
        startup_logger.warning(
            "No se encontraron administradores. Se creó un usuario de recuperación: %s",
            username,
        )
        QMessageBox.information(
            parent,
            "Administrador de recuperación",
            "No se encontró ningún usuario administrador.\n"
            "Se creó un usuario temporal de recuperación:\n\n"
            f"Usuario: {username}\nContraseña: {password}\n\n"
            "Inicia sesión con estas credenciales y crea un administrador permanente.",
        )
    except Exception as exc:
        startup_logger.exception("No se pudo crear el admin de recuperación")
        try:
            QMessageBox.critical(
                parent,
                "Administrador requerido",
                "No se pudo crear un administrador de recuperación.\n"
                f"Error: {exc}",
            )
        except Exception:
            pass

if __name__ == "__main__":
    migrate_datos_negocio()
    if getattr(sys, "frozen", False):
        checks = {
            "schema_NR": resource_path("svfe-json-schemas", "fe-nr-v3.json"),
            "datos_negocio": resource_path("datos_negocio.json"),
            "config_negocio": resource_path("config_negocio.json"),
            "VERSION": resource_path("VERSION"),
        }
        for name, path in checks.items():
            path_obj = Path(path)
            startup_logger.info(
                "resource[%s]=%s exists=%s", name, path_obj, path_obj.exists()
            )

        db_path = user_data_path("inventario.db")
        try:
            size = db_path.stat().st_size
        except OSError:
            size = 0
        startup_logger.info("user_data_dir=%s", user_data_path())
        startup_logger.info("db_path=%s size=%s", db_path, size)
        startup_logger.info("APP_VERSION=%s resources_root=%s", APP_VERSION, resource_path())
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
    _ensure_admin_recovery(db)
    users = db.get_users()
    if not any(u["username"].lower() == "invitado" for u in users):
        db.add_user("invitado", "", "Invitado")
        users = db.get_users()

    # Login centrado y moderno. Usamos el mismo flujo para autenticar o permitir invitado.
    user = None
    last_user = _load_last_user()
    sorted_users = sorted(
        users,
        key=lambda u: (u["username"].lower() != "invitado", u["username"].lower()),
    )
    while True:
        login_dialog = LoginDialog()
        login_dialog.user_combo.clear()
        for u in sorted_users:
            login_dialog.user_combo.addItem(u["username"])
        if last_user:
            idx = login_dialog.user_combo.findText(last_user, Qt.MatchFixedString)
            if idx >= 0:
                login_dialog.user_combo.setCurrentIndex(idx)
        if login_dialog.exec_() != QDialog.Accepted:
            sys.exit(0)

        username = login_dialog.user_combo.currentText().strip()
        password = login_dialog.password_input.text()
        if not username:
            QMessageBox.warning(None, "Error", "Seleccione un usuario.")
            continue

        if username.lower() == "invitado":
            invitado = next((u for u in sorted_users if u["username"].lower() == "invitado"), None)
            if not invitado:
                QMessageBox.warning(None, "Error", "No se encontró el usuario invitado.")
                continue
            user = db.get_user(invitado["id"])
            _save_last_user(username)
            break

        authenticated = db.authenticate(username, password)
        if not authenticated:
            QMessageBox.warning(None, "Error", "Usuario o contraseña incorrectos.")
            continue
        user = db.get_user(authenticated["id"])
        _save_last_user(username)
        break

    if not user:
        sys.exit(0)

    iniciar_servicios()

    window = MainWindow(user, skip_firmador_check=True)
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.showMaximized()

    # Cargar automáticamente el último inventario usadow
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
