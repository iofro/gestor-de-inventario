from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Optional, Union
from zoneinfo import ZoneInfo

TZ_EL_SALVADOR = ZoneInfo("America/El_Salvador")

def fecha_emision_hoy_str(now: Optional[datetime] = None) -> str:
    """Return today's date in El Salvador timezone formatted as YYYY-MM-DD."""
    if now is None:
        now = datetime.now(TZ_EL_SALVADOR)
    else:
        now = now.astimezone(TZ_EL_SALVADOR)
    return now.date().isoformat()


def normalizar_fecha_iso(value: Union[str, datetime, date, None]) -> Optional[str]:
    """Convierte distintos formatos de fecha a ``YYYY-MM-DD``."""

    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    if not text:
        return None

    fecha_dt: Optional[datetime] = None
    try:
        fecha_dt = datetime.fromisoformat(text)
    except ValueError:
        fecha_dt = None

    if fecha_dt is None:
        patrones = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
        ]
        for patron in patrones:
            try:
                fecha_dt = datetime.strptime(text[:10], patron)
                break
            except ValueError:
                continue
        else:
            return None

    return fecha_dt.date().isoformat()


def fecha_iso(value: Any) -> str:
    """Return ``value`` formatted as ``YYYY-MM-DD`` when possible.

    ``value`` can be a string in ``DD/MM/AAAA`` format, ISO strings with or without
    time components, :class:`datetime` or :class:`date` instances.  When the value
    cannot be interpreted as a date the original ``value`` is returned so other
    validations can surface the error.
    """

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if value is None:
        return value

    text = str(value).strip()
    if not text:
        return value

    normalized = normalizar_fecha_iso(text)
    if normalized:
        return normalized

    if text.endswith("Z"):
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass

    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        parsed = None

    if parsed is not None:
        return parsed.date().isoformat()

    return value


def fecha_ddmmaaaa(value: Union[str, datetime, date, None]) -> Optional[str]:
    """Convierte ``value`` en una fecha ``DD/MM/AAAA``.

    Acepta cadenas en formato ISO (con o sin hora), ``DD/MM/AAAA`` con o sin
    hora y objetos :class:`datetime`/ :class:`date`.  Si la fecha no puede
    interpretarse retorna ``None``.
    """

    fecha_iso = normalizar_fecha_iso(value)
    if not fecha_iso:
        return None
    try:
        fecha_obj = date.fromisoformat(fecha_iso)
    except ValueError:
        return None
    return fecha_obj.strftime("%d/%m/%Y")
