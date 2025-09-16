from __future__ import annotations

from typing import Optional

from db import DB
from models.factura import Factura


class FacturasRepo:
    """Repositorio persistente para estados de facturas."""

    def __init__(self, db: DB | None = None) -> None:
        self._db = db or DB()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._db.lock:
            self._db.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS facturas_estado (
                    id INTEGER PRIMARY KEY,
                    modo_transmision TEXT NOT NULL,
                    estado_envio TEXT NOT NULL,
                    tipo_contingencia INTEGER,
                    motivo_contin TEXT
                )
                """
            )
            self._db.conn.commit()

    def add(self, factura: Factura) -> None:
        with self._db.lock:
            self._db.cursor.execute(
                """
                INSERT INTO facturas_estado (
                    id,
                    modo_transmision,
                    estado_envio,
                    tipo_contingencia,
                    motivo_contin
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    modo_transmision=excluded.modo_transmision,
                    estado_envio=excluded.estado_envio,
                    tipo_contingencia=excluded.tipo_contingencia,
                    motivo_contin=excluded.motivo_contin
                """,
                (
                    factura.id,
                    factura.modo_transmision,
                    factura.estado_envio,
                    factura.tipo_contingencia,
                    factura.motivo_contin,
                ),
            )
            self._db.conn.commit()

    def get(self, factura_id: int) -> Optional[Factura]:
        with self._db.lock:
            self._db.cursor.execute(
                """
                SELECT id, modo_transmision, estado_envio, tipo_contingencia, motivo_contin
                FROM facturas_estado
                WHERE id=?
                """,
                (factura_id,),
            )
            row = self._db.cursor.fetchone()
        if not row:
            return None
        return Factura(
            id=row["id"],
            modo_transmision=row["modo_transmision"],
            estado_envio=row["estado_envio"],
            tipo_contingencia=row["tipo_contingencia"],
            motivo_contin=row["motivo_contin"],
        )

    def guardar_en_contingencia(
        self,
        factura_id: int,
        tipo_contingencia: int,
        motivo_contin: str | None = None,
    ) -> Optional[Factura]:
        factura = self.get(factura_id)
        if not factura:
            return None
        factura.modo_transmision = "contingencia"
        factura.estado_envio = "Pendiente"
        factura.tipo_contingencia = tipo_contingencia
        factura.motivo_contin = motivo_contin
        self.add(factura)
        return factura

    def clear(self) -> None:
        with self._db.lock:
            self._db.cursor.execute("DELETE FROM facturas_estado")
            self._db.conn.commit()
