import json
import os


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
DATOS_NEGOCIO_PATH = os.path.join(ROOT_DIR, "datos_negocio.json")


def get_nombre_comercial(default="FARMACIA SANTA CATALINA"):
    """Return the commercial name stored in ``datos_negocio.json``.

    Parameters
    ----------
    default: str
        Value returned if the file or the key is missing.
    """
    try:
        with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("nombre_comercial", default) or default
    except Exception:
        return default
