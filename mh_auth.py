import json
import logging

from paths import DATOS_NEGOCIO_PATH

log = logging.getLogger(__name__)


def _read_negocio_json():
    with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_manual_token() -> str | None:
    """Lee datos_negocio.json y retorna dte_api.token (string con 'Bearer ...') si existe."""
    try:
        data = _read_negocio_json()
        token = (((data or {}).get("dte_api") or {}).get("token"))
        token = str(token).strip() if token is not None else None
        return token or None
    except Exception as e:  # pragma: no cover - logged for observability
        log.warning("No se pudo leer token manual de datos_negocio.json: %s", e)
        return None


def auth_headers(extra: dict | None = None) -> dict:
    """Construye headers para MH usando EXCLUSIVAMENTE el token manual guardado."""
    token = get_manual_token()
    if not token:
        raise RuntimeError(
            "Token manual no configurado. Use 'Obtener token' en Configuración de Facturación Electrónica."
        )
    headers = {"Authorization": token}
    if extra:
        headers.update(extra)
    log.info("AUTH: USING MANUAL TOKEN (fp=%s)", token[-8:] if len(token) >= 8 else token)
    return headers
