import json
import logging

from paths import DATOS_NEGOCIO_PATH

log = logging.getLogger(__name__)


_TOKEN_CACHE: dict[str, str | None] = {}


def _normalize_environment(ambiente: str | None) -> str:
    if ambiente is None:
        return "apitest"
    text = str(ambiente).strip().lower()
    if not text:
        return "apitest"
    if text in {"00", "0", "apitest", "pruebas", "test"}:
        return "apitest"
    if text in {"01", "1", "prod", "produccion", "producción", "production"}:
        return "produccion"
    if "prue" in text or "test" in text:
        return "apitest"
    if text.startswith("pro"):
        return "produccion"
    return "apitest"


def _read_negocio_json():
    with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_tokens_from_file() -> dict[str, str]:
    try:
        data = _read_negocio_json()
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - logged for observability
        log.warning("No se pudo leer token manual de datos_negocio.json: %s", exc)
        return {}

    if not isinstance(data, dict):
        return {}

    dte_api = data.get("dte_api")
    if not isinstance(dte_api, dict):
        return {}

    tokens: dict[str, str] = {}
    for field, env in (
        ("token_pruebas", "apitest"),
        ("token_produccion", "produccion"),
    ):
        raw = dte_api.get(field)
        if isinstance(raw, str) and raw:
            tokens[env] = raw

    return tokens


def invalidate_token_cache() -> None:
    _TOKEN_CACHE.clear()


def get_manual_token(ambiente: str | None = None) -> str | None:
    env = _normalize_environment(ambiente)
    if env in _TOKEN_CACHE:
        return _TOKEN_CACHE[env]

    tokens = _load_tokens_from_file()
    for env_key, raw in tokens.items():
        _TOKEN_CACHE[env_key] = raw

    if env not in _TOKEN_CACHE:
        _TOKEN_CACHE[env] = None

    return _TOKEN_CACHE[env]


def auth_headers(extra: dict | None = None, *, ambiente: str | None = None) -> dict:
    """Construye headers para MH usando EXCLUSIVAMENTE el token manual guardado."""

    env = _normalize_environment(ambiente)
    token = get_manual_token(env)
    if not token:
        raise RuntimeError(
            "Token manual no configurado. Use 'Obtener token' en Configuración de Facturación Electrónica."
        )

    headers = {"Authorization": token}
    if extra:
        headers.update(extra)

    fingerprint = token[-8:] if len(token) >= 8 else token
    log.info("AUTH: USING MANUAL TOKEN (amb=%s fp=%s)", env, fingerprint)
    return headers
