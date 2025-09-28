from datetime import date, datetime
from typing import Optional, Union
from zoneinfo import ZoneInfo

TZ_EL_SALVADOR = ZoneInfo("America/El_Salvador")

def fecha_emision_hoy_str(now: Optional[datetime] = None) -> str:
    """Return today's date in El Salvador timezone formatted as YYYY-MM-DD."""
    if now is None:
        now = datetime.now(TZ_EL_SALVADOR)
    else:
        now = now.astimezone(TZ_EL_SALVADOR)
    return now.strftime("%Y-%m-%d")


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
        try:
            fecha_dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None

    return fecha_dt.date().isoformat()
