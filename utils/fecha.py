from datetime import date, datetime
import re
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


def fecha_ddmmaaaa(value: Union[str, datetime, date, None]) -> Optional[str]:
    """Convierte ``value`` al formato ``dd/mm/aaaa`` si es posible."""

    if value is None:
        return None

    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")

    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")

    text = str(value).strip()
    if not text:
        return None

    # Remove time portions such as ``HH:MM:SS`` or ISO ``T`` separators.
    text = text.split("T", 1)[0]
    text = text.split(" ", 1)[0]

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%d/%m/%Y")
        except ValueError:
            continue

    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
        return text

    return None
