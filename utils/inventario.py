from __future__ import annotations

from datetime import date, datetime
from threading import Lock
from typing import Any, Dict, Optional

from db import DB
from utils.fecha import fecha_ddmmaaaa


_DB_SINGLETON: DB | None = None
_DB_LOCK = Lock()


def _get_db() -> DB:
    global _DB_SINGLETON
    with _DB_LOCK:
        if _DB_SINGLETON is None:
            _DB_SINGLETON = DB()
        return _DB_SINGLETON


def _clean_text(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    text = str(value).strip()
    return text or None


def obtener_info_lote(
    *,
    lote_id: Optional[int] = None,
    codigo_lote: Optional[str] = None,
    producto_id: Optional[int] = None,
) -> Dict[str, Optional[str]]:
    """Obtiene información del lote desde ``detalles_compra``."""

    db = _get_db()
    row = None
    with db.lock:
        if lote_id is not None:
            row = db.cursor.execute(
                "SELECT codigo_lote, fecha_vencimiento, registro_sanitario FROM detalles_compra WHERE id=?",
                (lote_id,),
            ).fetchone()
        if row is None and codigo_lote:
            params = [codigo_lote]
            query = (
                "SELECT codigo_lote, fecha_vencimiento, registro_sanitario "
                "FROM detalles_compra WHERE codigo_lote=?"
            )
            if producto_id is not None:
                query += " AND producto_id=?"
                params.append(producto_id)
            query += " ORDER BY id DESC LIMIT 1"
            row = db.cursor.execute(query, tuple(params)).fetchone()
        if row is None and producto_id is not None:
            row = db.cursor.execute(
                "SELECT codigo_lote, fecha_vencimiento, registro_sanitario "
                "FROM detalles_compra WHERE producto_id=? ORDER BY id DESC LIMIT 1",
                (producto_id,),
            ).fetchone()

    if row is None:
        return {"lote": None, "vencimiento": None, "registro": None}

    lote = _clean_text(row["codigo_lote"])
    vencimiento = _clean_text(row["fecha_vencimiento"])
    registro = _clean_text(row["registro_sanitario"])
    return {"lote": lote, "vencimiento": vencimiento, "registro": registro}


def formatear_fecha_vencimiento_ui(value: Any) -> Optional[str]:
    """Aplica el formateo de fecha usado en la UI de Inventario actual."""

    if value in (None, ""):
        return None

    formatted = fecha_ddmmaaaa(value)
    if formatted:
        return formatted

    if isinstance(value, (datetime, date)):
        return fecha_ddmmaaaa(value)

    return _clean_text(value)
