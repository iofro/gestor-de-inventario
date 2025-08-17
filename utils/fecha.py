from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

TZ_EL_SALVADOR = ZoneInfo("America/El_Salvador")

def fecha_emision_hoy_str(now: Optional[datetime] = None) -> str:
    """Return today's date in El Salvador timezone formatted as YYYY-MM-DD."""
    if now is None:
        now = datetime.now(TZ_EL_SALVADOR)
    else:
        now = now.astimezone(TZ_EL_SALVADOR)
    return now.strftime("%Y-%m-%d")
