import os
import shutil
from appdirs import user_data_dir

APP_NAME = "gestor-de-inventario"


def _get_user_data_dir():
    path = user_data_dir(APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path

DATOS_NEGOCIO_PATH = os.path.join(_get_user_data_dir(), "datos_negocio.json")


def migrate_datos_negocio():
    """Copy existing datos_negocio.json to user data dir if needed."""
    old_path = os.path.join(os.path.dirname(__file__), "datos_negocio.json")
    if os.path.exists(old_path) and not os.path.exists(DATOS_NEGOCIO_PATH):
        try:
            shutil.copyfile(old_path, DATOS_NEGOCIO_PATH)
        except OSError:
            pass
